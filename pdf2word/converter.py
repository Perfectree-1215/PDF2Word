"""Main pipeline: PDF -> layout analysis (PyMuPDF Layout) -> Markdown with LaTeX equations,
figures copied into an asset folder, Obsidian post-processing."""
from __future__ import annotations

import re
import shutil
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import pymupdf

from .config import (CHAPTER_ASSET_TEMPLATE, CHAPTER_NAME_TEMPLATE, DOC_ASSET_TEMPLATE, DOC_NAME_TEMPLATE,
                     PAPER_ASSET_TEMPLATE, PAPER_NAME_TEMPLATE, Options)
from .lighten import lighten_document
from .inlinemath import inline_text_math
from .mathocr import (LABEL_RE, TEXT_FLAGS, EquationOCR, EquationResult, build_engine, find_labels, hint_usable,
                      label_text, render, tight_crop)
from .metadata import PaperMeta, detect_doc_type, document_meta, resolve_metadata
from .obsidian import block_id, build_frontmatter, ensure_title, image_link, postprocess, yaml_str
from .outline import PageNumbers, Part, page_groups, parse_pages, part_document, read_outline, select_parts, split_children
from .vectormath import doubtful_equation, find_math, inline_latex_ok, reads_as_text
from .symbols import has_pua, map_pua
from .utils import log, safe_name, slugify_title, strip_emphasis, wiki_safe_name

CAPTION_RE = re.compile(r"^\W*(Fig(?:ure)?|Table|Scheme|Algorithm|Chart|Plate)\.?\s*([A-Z]?[0-9]+[A-Za-z]?)", re.I)
# A real caption: bold label ("**Figure 3.** ...") or a label closed by . / : ("Table A1. ...").
# Running text such as "Figure 1 shows ..." or "Figure 6 (right) gives ..." is not one.
_CAPTION_BOLD_RE = re.compile(r"^\s*(?:\*\*|__)\s*(Fig(?:ure)?|Table|Scheme|Algorithm|Chart|Plate)\.?\s*[A-Z]?[0-9]+[A-Za-z]?", re.I)
_CAPTION_PLAIN_RE = re.compile(r"^\s*(Fig(?:ure)?|Table|Scheme|Algorithm|Chart|Plate)\.?\s*[A-Z]?[0-9]+[A-Za-z]?\s*[.:]\s", re.I)


def looks_like_caption(text: str) -> bool:
    s = (text or "").strip()
    if not s or len(s) > 900:
        return False
    if _CAPTION_BOLD_RE.match(s):
        return True
    return bool(_CAPTION_PLAIN_RE.match(strip_emphasis(s)))
GENERATED_RE = re.compile(r"^(fig|table|scheme|algorithm|chart|plate|eq|p\d+-img|inline)[\w.-]*\.(png|jpg|jpeg)$", re.I)
TEXT_CLASSES = {"text", "list-item", "footnote"}


def _version() -> str:
    try:
        from . import __version__
        return __version__
    except Exception:
        return "0.0"


@dataclass
class ConversionResult:
    pdf: Path
    md_path: Optional[Path]
    asset_dir: Optional[Path]
    meta: PaperMeta
    stats: dict = field(default_factory=dict)
    skipped: bool = False
    docx_path: Optional[Path] = None
    part: Optional[Part] = None            # the chapter / page group this file holds (None = whole PDF)
    doc_type: str = "paper"                # "paper" | "document"
    error: str = ""                        # set when a part failed (convert_parts keeps going)

    @property
    def output(self) -> Optional[Path]:
        return self.docx_path or self.md_path


# ----------------------------------------------------------------------------- pymupdf4llm patch

def _patch_pymupdf4llm_pua() -> None:
    """pymupdf4llm drops spans consisting of a single Private-Use-Area character. Those are
    usually Greek letters set in the Symbol font; keep them so we can map them later."""
    try:
        from pymupdf4llm.helpers import document_layout as dl
    except Exception as exc:   # pragma: no cover
        log.debug("PUA patch skipped: %s", exc)
        return
    if getattr(dl, "_pdf2word_pua_patched", False):
        return
    original = dl.omit_if_pua_char

    def keep_symbol_chars(text):
        if len(text) == 1 and has_pua(text):
            return map_pua(text) or ""
        return original(text)

    dl.omit_if_pua_char = keep_symbol_chars
    dl._pdf2word_pua_patched = True


# ----------------------------------------------------------------------------- converter

class Converter:
    def __init__(self, options: Optional[Options] = None):
        self.opt = options or Options()
        self._engine = None
        self._engine_built = False
        self._ocr: Optional[EquationOCR] = None

    # -- lazy OCR -----------------------------------------------------------
    @property
    def ocr(self) -> EquationOCR:
        if self._ocr is None:
            if not self._engine_built:
                self._engine = build_engine(self.opt.math_engine, max_tokens=self.opt.math_max_tokens,
                                            model=self.opt.claude_model, effort=self.opt.claude_effort)
                self._engine_built = True
            self._ocr = EquationOCR(self._engine, zooms=self.opt.math_zooms, cache=self.opt.cache)
        return self._ocr

    @property
    def engine_name(self) -> str:
        """The engine in use: the one actually built (p2t may have fallen back to rapid), else
        the one asked for."""
        if self._engine_built:
            return self._engine.name if self._engine else "none"
        return "none" if self.opt.math_engine in ("none", "off", "image") else self.opt.math_engine

    # -- public -------------------------------------------------------------
    def convert(self, pdf_path) -> ConversionResult:
        """The whole document (or the --pages range) -> one Word / Markdown file."""
        opt = self.opt
        t0 = time.time()
        pdf_path = Path(pdf_path).resolve()
        log.info("== %s", pdf_path.name)
        doc = self._open(pdf_path)
        try:
            pages = parse_pages(opt.pages, doc) if opt.pages else None
            first_text = map_pua("\n".join(doc[i].get_text("text") for i in range(min(2, doc.page_count))))
            doc_type = self._doc_type(doc, first_text)
            if doc_type == "paper":
                meta = resolve_metadata(doc, first_text, online=opt.online,
                                        author=opt.author, year=opt.year, title=opt.title)
            else:
                meta = document_meta(doc, pdf_path)
                self._apply_overrides(meta)
            fields = self._fields(meta, pdf_path)
            name_t = opt.name_template or (PAPER_NAME_TEMPLATE if doc_type == "paper" else DOC_NAME_TEMPLATE)
            asset_t = opt.asset_template or (PAPER_ASSET_TEMPLATE if doc_type == "paper" else DOC_ASSET_TEMPLATE)
            log.info("  title : %s", meta.title or "(unknown)")
            if doc_type == "paper":
                log.info("  author: %s (%d authors)  year: %s", meta.first_author or "?", len(meta.authors),
                         meta.year or "nd")
            base_name = safe_name(name_t.format(**fields), 150)
            asset_name = wiki_safe_name(asset_t.format(**fields), 120)
            if pages is None:
                return self._run(doc, pdf_path, meta, doc_type, base_name, asset_name, t0=t0)
            # a page range: work on a sub-document so that nothing scans the other pages
            sub = self._subdoc(doc, pages)
            try:
                return self._run(sub, pdf_path, meta, doc_type, base_name, asset_name,
                                 page_map=list(pages), total_pages=doc.page_count, t0=t0)
            finally:
                sub.close()
        finally:
            doc.close()

    @staticmethod
    def _subdoc(doc, pages: list) -> pymupdf.Document:
        """A new document with just these pages (0-based, in the given order)."""
        sub = pymupdf.open()
        runs: list = []
        for p in pages:
            if runs and p == runs[-1][1] + 1:
                runs[-1][1] = p
            else:
                runs.append([p, p])
        for a, b in runs:
            sub.insert_pdf(doc, from_page=a, to_page=b)
        return sub

    def plan_parts(self, pdf_path) -> list:
        """Parts requested by the options (--chapters / --split-pages); [] = convert as a whole."""
        opt = self.opt
        if not opt.chapters and not opt.split_pages:
            return []
        doc = self._open(pdf_path)
        try:
            if opt.chapters:
                tree = read_outline(doc)
                if not tree:
                    raise RuntimeError("the PDF has no bookmarks; use --split-pages N or --pages")
                parts = select_parts(tree, opt.chapters)
                if opt.subchapters:
                    parts = [p for sel in parts for p in split_children(doc, sel)]
                return parts
            return page_groups(doc.page_count, opt.split_pages)
        finally:
            doc.close()

    def convert_parts(self, pdf_path, parts: list, stop=None) -> list:
        """Every part (bookmark chapter or page group) -> its own file. A failing part is logged
        and returned with .error set; the remaining parts still run. `stop()` returning True
        between parts ends the loop early."""
        opt = self.opt
        pdf_path = Path(pdf_path).resolve()
        doc = self._open(pdf_path)
        results = []
        try:
            book = document_meta(doc, pdf_path)
            numbers = PageNumbers(doc)
            log.info("== %s: %d part(s) of %d pages (page numbers: %s)", pdf_path.name, len(parts),
                     doc.page_count, numbers.source)
            for part in parts:
                if stop is not None and stop():
                    log.info("  stopped before part %s", part.num_str)
                    break
                t0 = time.time()
                where = numbers.describe(part.page_from, part.page_to)
                log.info("== %s  [%s %s] %s  (%s)", pdf_path.name, part.kind, part.num_str, part.title, where)
                try:
                    title = part.title if part.kind == "chapter" else f"{book.title} ({where})"
                    meta = PaperMeta(title=title, authors=list(book.authors), first_author=book.first_author,
                                     year=book.year, source="outline", kind=part.kind, container=book.title,
                                     part_pages=where, part_pages_pdf=part.pages_label,
                                     part_pages_printed=numbers.printed_range(part.page_from, part.page_to),
                                     part_id=part.id)
                    fields = self._fields(book, pdf_path)
                    fields.update(part.fields(fields["stem"], doc.page_count))
                    name_t = opt.chapter_template or CHAPTER_NAME_TEMPLATE
                    asset_t = opt.asset_template or CHAPTER_ASSET_TEMPLATE
                    sub = part_document(doc, part, opt.chapter_split)
                    try:
                        results.append(self._run(sub, pdf_path, meta, "document",
                                                 safe_name(name_t.format(**fields), 150),
                                                 wiki_safe_name(asset_t.format(**fields), 120), part=part,
                                                 page_map=list(range(part.page_from, part.page_to + 1)),
                                                 total_pages=doc.page_count, t0=t0))
                    finally:
                        sub.close()
                except Exception as exc:
                    log.error("  FAILED part %s (%s): %s", part.num_str, part.title, exc)
                    if opt.verbose:
                        log.exception("part failure")
                    results.append(ConversionResult(pdf_path, None, None, PaperMeta(title=part.title),
                                                    part=part, doc_type="document", error=str(exc)))
        finally:
            doc.close()
        return results

    # -- pipeline -----------------------------------------------------------
    def _run(self, doc, pdf_path: Path, meta: PaperMeta, doc_type: str, base_name: str, asset_name: str,
             part: Optional[Part] = None, page_map: Optional[list] = None, total_pages: int = 0,
             t0: Optional[float] = None) -> ConversionResult:
        """Layout analysis -> Markdown assembly -> post-processing -> files, for `doc`: the whole
        document, or a sub-document (page range / one part) whose page i is page page_map[i] of
        the PDF. The caller closes `doc`."""
        opt = self.opt
        t0 = t0 or time.time()
        total_pages = total_pages or doc.page_count
        fmt = (opt.format or "docx").lower()
        if fmt not in ("docx", "md", "both"):
            raise ValueError(f"unknown output format: {opt.format}")
        out_dir = Path(opt.out_dir).resolve() if opt.out_dir else pdf_path.parent
        md_path = out_dir / (base_name + ".md")
        docx_path = out_dir / (base_name + ".docx")
        asset_dir = out_dir / asset_name
        targets = [p for p, wanted in ((md_path, fmt != "docx"), (docx_path, fmt != "md")) if wanted]
        if not opt.overwrite and any(p.exists() for p in targets):
            log.info("  exists, skipped (--no-overwrite is set): %s", ", ".join(p.name for p in targets if p.exists()))
            return ConversionResult(pdf_path, md_path if fmt != "docx" else None, asset_dir, meta,
                                    docx_path=docx_path if fmt != "md" else None, skipped=True,
                                    part=part, doc_type=doc_type)

        out_dir.mkdir(parents=True, exist_ok=True)
        scratch: Optional[Path] = None
        if fmt == "docx":
            # the images only feed the .docx: build them in a private folder so that an asset
            # folder of the same name in out_dir (an earlier .md's) is never touched
            scratch = Path(tempfile.mkdtemp(prefix="pdf2word-"))
            asset_dir = scratch / asset_name
        else:
            asset_dir = self._own_asset_dir(out_dir, asset_name, md_path)
        asset_dir.mkdir(parents=True, exist_ok=True)
        self._remove_generated(asset_dir)

        stats: Counter = Counter()
        layout_doc = doc
        try:
            # 1) layout analysis + markdown per page (pymupdf4llm + PyMuPDF Layout)
            _patch_pymupdf4llm_pua()
            import pymupdf4llm
            layout_doc = self._layout_doc(doc, stats)
            n_pages = doc.page_count
            log.info("  layout analysis (%d pages) ...", n_pages)
            t_layout = time.time()
            # write_images=False: pictures are rendered from the ORIGINAL document in _picture()
            chunks = pymupdf4llm.to_markdown(
                layout_doc, page_chunks=True, write_images=False,
                header=opt.keep_headers, footer=opt.keep_headers,
                use_ocr=opt.ocr_pages, force_text=True, show_progress=n_pages > 30,
            )
            log.info("  layout analysis done (%.0fs)", time.time() - t_layout)
            if isinstance(chunks, str):           # layout module unavailable -> plain string
                chunks = [{"text": chunks, "page_boxes": [], "metadata": {"page_number": 1}}]

            # 2) per-page assembly
            ctx = _DocContext(doc, asset_dir, stats, self, page_map=page_map)
            md_parts = []
            for i, chunk in enumerate(chunks, 1):
                pno = int(chunk["metadata"].get("page_number", i)) - 1
                page = doc[pno]
                n_formula = sum(1 for b in chunk.get("page_boxes") or [] if b.get("class") == "formula")
                if n_formula:
                    log.info("  page %d/%d: %d equation block(s)", ctx.pdf_page(page), total_pages, n_formula)
                md_parts.append(ctx.render_page(page, chunk))
                stats["pages"] += 1
            body = ctx.finalize_subfigures("\n".join(md_parts))

            # 3) post-processing + frontmatter
            body = ensure_title(postprocess(body, opt, paper=doc_type == "paper"), meta.title)
            front = build_frontmatter(meta, pdf_path, asset_dir.name, _version(), self.engine_name, stats)
            written = []
            if fmt in ("md", "both"):
                md_path.write_text(front + body, encoding="utf-8")
                written.append(md_path.name)
            if fmt in ("docx", "both"):
                from .docx_out import build_docx
                log.info("  writing Word document ...")
                build_docx(body, meta, asset_dir.parent, docx_path, opt, stats)
                written.append(docx_path.name)
        finally:
            if self._ocr is not None:
                self._ocr.cache.save()
            if layout_doc is not doc:
                layout_doc.close()
            if scratch is not None:               # images live inside the .docx now
                shutil.rmtree(scratch, ignore_errors=True)

        asset_dir_out = None
        if scratch is None:
            if any(asset_dir.iterdir()):
                asset_dir_out = asset_dir
            else:
                asset_dir.rmdir()
        stats["seconds"] = round(time.time() - t0, 1)
        log.info("  -> %s  (%ss; equations %d ok / %d as image%s; inline text math %d; figures %d%s)",
                 " + ".join(written), stats["seconds"], stats["eq_ok"], stats["eq_fallback"],
                 f" / {stats['eq_unverified']} unverified (garbled text layer)" if stats["eq_unverified"] else "",
                 stats["inline_text_eqs"], stats["figures"],
                 f"; Word equations {stats['docx_eq_native']} native / {stats['docx_eq_text']} text"
                 if fmt != "md" else "")
        return ConversionResult(pdf_path, md_path if fmt != "docx" else None, asset_dir_out, meta,
                                docx_path=docx_path if fmt != "md" else None, stats=dict(stats),
                                part=part, doc_type=doc_type)

    # -- helpers ------------------------------------------------------------
    def _layout_doc(self, doc, stats: Counter):
        """The document the layout analysis reads: `doc`, or a lightened copy (image clusters merged,
        big bitmaps swapped for a blank stand-in). Not with --ocr-pages: the OCR decision and the OCR
        itself need the page pixels. The caller closes a copy."""
        opt = self.opt
        if not opt.lighten:
            return doc
        if opt.ocr_pages:
            log.info("  lighten skipped: --ocr-pages needs the original page pixels")
            return doc
        layout_doc, n_light = lighten_document(doc, dpi=opt.dpi)
        stats["pages_lightened"] = n_light
        return layout_doc

    @staticmethod
    def _open(pdf_path) -> pymupdf.Document:
        doc = pymupdf.open(pdf_path)
        if doc.needs_pass:
            doc.close()
            raise RuntimeError("PDF is password protected")
        if doc.page_count == 0:
            doc.close()
            raise RuntimeError("PDF has no pages")
        return doc

    def _doc_type(self, doc, first_text: str) -> str:
        wanted = (self.opt.doc_type or "auto").lower()
        if wanted in ("paper", "document"):
            kind, why = wanted, "option"
        else:
            kind, why = detect_doc_type(doc, first_text)
        log.info("  document type: %s (%s)", kind, why)
        return kind

    def _apply_overrides(self, meta: PaperMeta) -> None:
        opt = self.opt
        if opt.title:
            meta.title = opt.title
        if opt.year:
            meta.year = int(opt.year)
        if opt.author:
            meta.first_author = opt.author
            meta.authors = meta.authors or [opt.author]

    @staticmethod
    def _fields(meta: PaperMeta, pdf_path: Path) -> dict:
        """Template fields shared by file and asset-folder names."""
        author = safe_name(meta.first_author or "Unknown", 40)
        year = str(meta.year or "nd")
        title_slug = slugify_title(meta.title) if meta.title else safe_name(pdf_path.stem, 60)
        return dict(author=author, year=year, title=title_slug, stem=safe_name(pdf_path.stem, 80))

    @staticmethod
    def _own_asset_dir(out_dir: Path, asset_name: str, md_path: Path) -> Path:
        """The asset folder of a Markdown output: `asset_name`, unless a folder of that name holds
        another output's images (the default '_asset-{author}-{year}' is shared by every paper of
        that author and year). Then asset_name-2, -3 ...: the first one that is missing, empty or
        ours - linked from the .md this run rewrites, or named in its frontmatter."""
        try:
            own = md_path.read_text(encoding="utf-8") if md_path.is_file() else ""
        except (OSError, UnicodeDecodeError):
            own = ""
        n = 1
        while True:
            name = asset_name if n == 1 else f"{asset_name}-{n}"
            cand = out_dir / name
            if not cand.exists():
                break
            if cand.is_dir() and (not any(cand.iterdir()) or f"assets: {yaml_str(name)}\n" in own
                                  or f"[[{name}/" in own or f"]({quote(name + '/')}" in own):
                break
            n += 1
        if n > 1:
            log.info("  %s holds another output's images; using %s", asset_name, name)
        return cand

    @staticmethod
    def _remove_generated(asset_dir: Path) -> None:
        for f in asset_dir.iterdir():
            if f.is_file() and GENERATED_RE.match(f.name):
                try:
                    f.unlink()
                except OSError:
                    pass


def convert(pdf_path, options: Optional[Options] = None, **kwargs) -> ConversionResult:
    """Convenience API: convert('paper.pdf', out_dir='vault/papers', math_engine='rapid')."""
    opt = options or Options()
    for k, v in kwargs.items():
        if not hasattr(opt, k):
            raise TypeError(f"unknown option: {k}")
        setattr(opt, k, v)
    return Converter(opt).convert(pdf_path)


# ----------------------------------------------------------------------------- per-document context

class _DocContext:
    def __init__(self, doc, asset_dir: Path, stats: Counter, conv: Converter, page_map: Optional[list] = None):
        self.asset_dir = asset_dir
        self.stats = stats
        self.conv = conv
        self.opt = conv.opt
        self.page_map = page_map               # sub-document page -> page of the full PDF (0-based)
        self.used_names: Counter = Counter()
        self.picture_names: dict = {}          # base -> [filename, ...] (for sub-figure lettering)
        self.eq_seq = 0
        self.inline_seq = 0
        self._page_images_cache: dict = {}
        self.logo_xrefs = self._repeated_images(doc, self._page_images_cache)

    # ---- document-level helpers ------------------------------------------
    def pdf_page(self, page) -> int:
        """1-based page number in the full PDF (log messages, picture file names)."""
        pno = page.number
        if self.page_map and pno < len(self.page_map):
            pno = self.page_map[pno]
        return pno + 1

    @staticmethod
    def _repeated_images(doc, infos_by_page: Optional[dict] = None) -> set:
        """XObjects shown on many pages (journal logos in headers/footers). The per-page lists are
        kept in `infos_by_page` (the _page_images cache: same document, same page numbers)."""
        pages_of: dict = {}
        for pno in range(doc.page_count):
            try:
                infos = doc[pno].get_image_info(xrefs=True)
            except Exception:
                continue
            if infos_by_page is not None:
                infos_by_page[pno] = infos
            for info in infos:
                xref = info.get("xref") or 0
                if xref:
                    pages_of.setdefault(xref, set()).add(pno)
        limit = 3 if doc.page_count >= 6 else 2
        return {x for x, p in pages_of.items() if len(p) >= limit}

    def _page_images(self, page) -> list:
        if page.number not in self._page_images_cache:
            try:
                self._page_images_cache[page.number] = page.get_image_info(xrefs=True)
            except Exception:
                self._page_images_cache[page.number] = []
        return self._page_images_cache[page.number]

    def _embed(self, filename: str, alt: str = "") -> str:
        return image_link(f"{self.asset_dir.name}/{filename}", alt or Path(filename).stem, self.opt.image_links)

    def _unique(self, base: str) -> str:
        self.used_names[base] += 1
        n = self.used_names[base]
        if n == 1:
            return base
        return f"{base}{chr(ord('a') + n - 2)}" if n <= 27 else f"{base}-{n}"

    def finalize_subfigures(self, body: str) -> str:
        """fig3.png + fig3a.png (panels of one figure) -> fig3a.png + fig3b.png."""
        renames = {}
        for base, names in self.picture_names.items():
            if len(names) < 2:
                continue
            for i, old in enumerate(names):
                ext = Path(old).suffix
                new = f"{base}{chr(ord('a') + i)}{ext}" if i < 26 else f"{base}-{i + 1}{ext}"
                if new != old:
                    renames[old] = new
        if not renames:
            return body
        # files: go through temporary names to avoid clashes
        tmp_names = {}
        for old in renames:
            tmp = self.asset_dir / (old + ".tmp")
            (self.asset_dir / old).replace(tmp)
            tmp_names[old] = tmp
        for old, new in renames.items():
            tmp_names[old].replace(self.asset_dir / new)
        # markdown references, spelled as _embed() wrote them (obsidian.image_link URL-quotes the
        # path for image_links="markdown"); tokens first, then the new names (no chained replacements)
        def ref(name: str) -> str:
            rel = f"{self.asset_dir.name}/{name}"
            return quote(rel) if self.opt.image_links == "markdown" else rel

        for i, old in enumerate(renames):
            body = body.replace(ref(old), f"\x00{i}\x00")
        for i, (old, new) in enumerate(renames.items()):
            body = body.replace(f"\x00{i}\x00", ref(new))
        return body

    # ---- page --------------------------------------------------------------
    def render_page(self, page, chunk: dict) -> str:
        text = chunk.get("text") or ""
        boxes = chunk.get("page_boxes") or []
        if not boxes:
            return text
        for box in boxes:                      # captions/text need their text for figure naming
            s, e = box["pos"]
            box["_text"] = text[s:e]
        self._consumed_labels = []
        # equations / symbols drawn as vector paths or loose images (manuals): found once per page
        inline_atoms, orphan_eqs = [], []
        if self.opt.vector_math or self.opt.inline_image_math:
            try:
                inline_atoms, orphan_eqs = find_math(page, boxes, self._page_images(page), self.opt.vector_math)
            except Exception as exc:
                log.debug("  page %d: graphics math scan failed: %s", self.pdf_page(page), exc)
        pre: list = []
        pending: dict = {}
        for eq in orphan_eqs:
            try:
                md = self._orphan_equation(page, eq)
            except Exception as exc:
                log.warning("  page %d: drawn equation failed (%s)", self.pdf_page(page), exc)
                continue
            if md:
                idx = self._box_above(boxes, eq)
                (pre if idx is None else pending.setdefault(idx, [])).append(md)
        if inline_atoms:
            self.stats["inline_graphics"] += len(inline_atoms)

        out = list(pre)
        cursor = 0
        for i, box in enumerate(boxes):
            start, stop = box["pos"]
            cls = box.get("class", "text")
            seg = text[start:stop]
            if start > cursor:
                out.append(text[cursor:start])
            try:
                if cls == "formula":
                    seg = self._formula(page, box, seg)
                elif cls == "picture":
                    seg = self._picture(page, box, seg, boxes)
                elif cls == "text" and looks_like_caption(seg):
                    seg = self._caption(seg)           # caption the layout model filed as text
                elif cls in TEXT_CLASSES:
                    extra = [a for a in inline_atoms if self._inside(a, box)]
                    if self.opt.inline_image_math or extra:
                        seg = self._inline_math(page, box, seg, extra)
                    if self.opt.inline_text_math and cls != "footnote":
                        seg = self._text_math(page, box, seg)
                elif cls == "section-header":
                    seg = self._heading(seg)
                elif cls == "title":
                    seg = self._title(seg)
                elif cls == "caption":
                    seg = self._caption(seg)
            except Exception as exc:   # never lose a page because of one box
                log.warning("  page %d: %s box failed (%s); kept raw text", self.pdf_page(page), cls, exc)
                if self.opt.verbose:
                    log.exception("box failure")
            out.append(seg)
            out.extend(pending.get(i, []))
            cursor = max(cursor, stop)
        out.append(text[cursor:])
        page_md = "".join(out)
        for label in dict.fromkeys(self._consumed_labels):   # '(3)' lines that belonged to an equation image
            page_md = re.sub(rf"(?m)^[ \t]*\({re.escape(label)}\)[ \t]*\n?", "", page_md, count=1)
        return page_md

    @staticmethod
    def _inside(rect: pymupdf.Rect, box: dict, frac: float = 0.6) -> bool:
        inter = rect & pymupdf.Rect(box["bbox"])
        return (not inter.is_empty) and inter.get_area() >= frac * max(rect.get_area(), 1e-6)

    @staticmethod
    def _box_above(boxes: list, eq: pymupdf.Rect) -> Optional[int]:
        """Index of the box after which a drawn equation belongs: the nearest box ending above
        it in the same column (any column if none); None = top of the page."""
        cands = []
        for i, b in enumerate(boxes):
            x0, y0, x1, y1 = b["bbox"]
            if y1 <= eq.y0 + 3:
                cands.append((min(x1, eq.x1) - max(x0, eq.x0) > 0, y1, i))
        if not cands:
            return None
        same_col = [c for c in cands if c[0]]
        pool = same_col or cands
        return max(pool, key=lambda c: (c[1], c[2]))[2]

    def _orphan_equation(self, page, eq: pymupdf.Rect) -> str:
        """A display equation drawn as graphics (no text layer, no layout box): OCR of the
        rendered region, numbered by a '(5.95)' label found to its right."""
        strip = pymupdf.Rect(eq.x1, eq.y0 - 3, page.rect.x1, eq.y1 + 3)
        # `box` keeps find_labels from taking the other column's numbers on two-column pages
        labels = find_labels(page, strip, box=eq) if strip.width > 10 else []
        label = labels[0][0] if labels else None
        region = (eq + (-2, -2, 2, 2)) & page.rect
        result = self.conv.ocr.recognize_region(page, region, "", read=self.opt.math_mode != "image")
        if reads_as_text(result.latex):          # a word drawn as graphics (badge, wordmark), not an equation
            log.debug("  page %d: drawn cluster reads as text (%s), dropped", self.pdf_page(page), result.latex)
            return ""
        self.stats["eq_total"] += 1
        self.stats["eq_drawn"] += 1
        if label:
            self._consumed_labels.append(label)
        return "\n" + self._format_equation(result, label, "", page, region) + "\n"

    # ---- formulas ----------------------------------------------------------
    def _formula(self, page, box: dict, seg: str) -> str:
        rect = pymupdf.Rect(box["bbox"])
        inside = (page.get_text("text", clip=rect) or "").strip()
        m = LABEL_RE.match(label_text(inside))
        if m and rect.width < 60:
            # only an equation number: the equation itself is drawn as graphics (handled per page)
            self._consumed_labels.append(m.group(1))
            return ""
        # the number may sit outside the box, at the right margin (the strip reaches the page edge;
        # `box` keeps find_labels from taking the other column's numbers on two-column pages)
        labels = find_labels(page, pymupdf.Rect(rect.x0, rect.y0 - 3, page.rect.x1, rect.y1 + 3), box=rect)
        regions = self._split_regions(rect, labels, page)
        blocks = []
        for region, label, mask in regions:
            hint = map_pua(page.get_text("text", clip=region) or "").strip()
            unverified = bool(hint) and not hint_usable(hint)
            if unverified:
                # garbled Type 1 text layer (docs/issues/garbled-text-layer.md): the OCR compares its
                # render scales with each other instead, and the output is formatted like an
                # equation without a text layer
                self.stats["eq_unverified"] += 1
            self.stats["eq_total"] += 1
            result = self.conv.ocr.recognize_region(page, region, hint, mask, read=self.opt.math_mode != "image")
            blocks.append(self._format_equation(result, label, "" if unverified else hint, page, region,
                                                unverified=unverified))
        return "\n" + "\n".join(blocks) + "\n"

    @staticmethod
    def _split_regions(rect: pymupdf.Rect, labels: list, page) -> list:
        """A formula box may stack several numbered equations: one region per label,
        [(region, label, mask)]. A number on the equation's own text row is cut off at its left
        edge. A number on a row of its own (under the end of a tall equation - paper-01 eq. (3))
        keeps the region's full width, because cutting there removed the end of the equation,
        and is painted out through `mask` instead."""
        if not labels:
            return [(rect, None, [])]
        rows = []                                        # text rows that are not a number
        try:
            blocks = page.get_text("dict", clip=rect, flags=TEXT_FLAGS)["blocks"]
        except Exception:
            blocks = []
        for block in blocks:
            for line in block.get("lines", []):
                text = "".join(s["text"] for s in line["spans"])
                if text.strip() and not LABEL_RE.match(label_text(text)):
                    rows.append(pymupdf.Rect(line["bbox"]))
        centers = [(lr.y0 + lr.y1) / 2 for _, lr in labels]
        bounds = [rect.y0] + [(centers[i] + centers[i + 1]) / 2 for i in range(len(centers) - 1)] + [rect.y1]
        regions = []
        for i, (label, lr) in enumerate(labels):
            region = pymupdf.Rect(rect.x0, bounds[i], rect.x1, bounds[i + 1])
            own_row = any(
                r.x0 < lr.x0 and min(r.y1, lr.y1) - max(r.y0, lr.y0) > 0.5 * lr.height for r in rows)
            if own_row and lr.x0 - 2 > rect.x0 + 10:
                region.x1 = min(rect.x1, lr.x0 - 2)
            regions.append((region, label, [lr] if lr.intersects(region) else []))
        return regions

    def _format_equation(self, result: EquationResult, label: Optional[str], hint: str, page, region,
                         unverified: bool = False) -> str:
        opt = self.opt
        lines = []
        if not hint and not unverified and doubtful_equation(result.latex):
            # no text layer to verify against (drawn / pictured equation) and the LaTeX looks garbled.
            # Not for a garbled *text* layer: that is an ordinary typeset equation, and the heuristic
            # (tuned for vector-drawn glyph clusters) flags legitimate line breaks and spacing.
            result.confidence = min(result.confidence, 0.5)
        if result.latex and opt.math_mode != "image":
            body = result.latex
            if label:
                body = body + f" \\tag{{{label}}}"
            # the cropped original first, OCR result below it (always when the OCR looks doubtful or
            # could not be checked against a text layer)
            if opt.math_mode == "both" or result.uncertain or unverified:
                fname = self._save_equation_image(result, label, page, region)
                if fname:
                    lines.append(self._embed(fname))
            lines += ["$$", body, "$$"]
            if label and opt.block_ids:
                lines.append(block_id("eq", label))
            if result.uncertain:
                lines.append(f"*⚠ OCR 신뢰도 낮음 ({int(result.confidence * 100)}%) · 위 수식 이미지를 확인하세요*")
                self.stats["eq_uncertain"] += 1
            self.stats["eq_ok"] += 1
        else:
            fname = self._save_equation_image(result, label, page, region)
            if fname:
                lines.append(self._embed(fname))
            if label:
                lines.append(f"*Eq. ({label})*" + (" " + block_id("eq", label) if opt.block_ids else ""))
            if hint:
                snippet = re.sub(r"\s+", " ", hint)[:300]
                lines.append(f"%% equation text: {snippet} %%")
            self.stats["eq_fallback"] += 1
        return "\n".join(lines) + "\n"

    def _save_equation_image(self, result: EquationResult, label: Optional[str], page, region) -> Optional[str]:
        img, zoom = result.image, EquationOCR.DISPLAY_ZOOM
        if img is None:                     # nothing at the display scale (masked or faint): 3x, unmasked
            img, zoom = tight_crop(render(page, region, 3.0)), 3.0
        if img is None:
            return None
        self.eq_seq += 1
        base = f"eq-{re.sub(r'[^A-Za-z0-9-]+', '-', label)}" if label else f"eq-u{self.eq_seq:02d}"
        fname = self._unique(base) + ".png"
        dpi = int(round(72 * zoom))
        img.save(self.asset_dir / fname, dpi=(dpi, dpi))   # physical size survives into Word
        return fname

    # ---- pictures ----------------------------------------------------------
    def _picture(self, page, box: dict, seg: str, boxes: list) -> str:
        rect = pymupdf.Rect(box["bbox"]) & page.rect
        if rect.is_empty:
            return ""
        kind, num = self._nearest_caption(box, boxes)
        w, h = rect.width, rect.height
        # Equations set as images (Word/MathType): a '(n)' label to the right, or a short wide strip
        if not kind and self.opt.math_engine not in ("none", "off", "image") and not self._is_logo(page, box):
            label = self._label_right_of(page, box)
            if label:                      # numbered equation(s) set as a picture: one region per number
                return self._formula(page, box, seg)
            if h <= 70 and w >= 100 and w / max(h, 1) >= 2.5:
                eq = self._picture_as_equation(page, box)
                if eq is not None:
                    return eq
        if not kind and (w < 20 or h < 20 or w * h < 2500 or self._is_logo(page, box)):   # logos, badges, icons
            self.stats["pictures_skipped"] += 1
            return ""
        if kind:
            base = f"{kind}{num}"
        else:
            base = f"p{self.pdf_page(page)}-img{box['index'] + 1}"
        fname = self._unique(base) + ".png"
        pix = page.get_pixmap(clip=rect, dpi=self.opt.dpi)      # rendered from the original PDF
        try:
            pix.set_dpi(self.opt.dpi, self.opt.dpi)
        except Exception:
            pass
        pix.save(self.asset_dir / fname)
        self.picture_names.setdefault(base, []).append(fname)
        self.stats["figures"] += 1
        out = "\n" + self._embed(fname) + "\n\n"
        rest = re.sub(r"<!--.*?-->", "", seg, flags=re.S).strip()   # text found inside the picture
        if self.opt.keep_picture_text and rest:
            out += rest + "\n\n"
        return out

    def _is_logo(self, page, box: dict) -> bool:
        """True when the box is (mostly) an image that repeats on many pages (journal logo)."""
        if not self.logo_xrefs:
            return False
        br = pymupdf.Rect(box["bbox"])
        for info in self._page_images(page):
            if (info.get("xref") or 0) not in self.logo_xrefs:
                continue
            ir = pymupdf.Rect(info["bbox"])
            inter = ir & br
            if not inter.is_empty and inter.get_area() >= 0.6 * br.get_area():
                return True
        return False

    def _label_right_of(self, page, box: dict) -> Optional[str]:
        x0, y0, x1, y1 = box["bbox"]
        strip = pymupdf.Rect(x1, y0 - 3, page.rect.x1, y1 + 3)
        if strip.is_empty or strip.width < 10:
            return None
        # `box` keeps find_labels from taking the other column's numbers on two-column pages
        labels = find_labels(page, pymupdf.Rect(x0, y0 - 3, page.rect.x1, y1 + 3), box=pymupdf.Rect(box["bbox"]))
        labels = [(lb, r) for lb, r in labels if r.x0 >= x1 - 2]
        return labels[0][0] if labels else None

    def _picture_as_equation(self, page, box: dict) -> Optional[str]:
        region = pymupdf.Rect(box["bbox"])
        result = self.conv.ocr.recognize_region(page, region, "")
        if result.latex is None or reads_as_text(result.latex):
            return None                                   # probably a real picture after all
        self.stats["eq_total"] += 1
        return "\n" + self._format_equation(result, None, "", page, region) + "\n"

    @staticmethod
    def _caption_info(text: str):
        m = CAPTION_RE.match(strip_emphasis(text.strip()))
        if not m:
            return None
        kind = m.group(1).lower()
        kind = "fig" if kind.startswith("fig") else kind
        return kind, m.group(2)

    def _nearest_caption(self, box: dict, boxes: list):
        """Caption below (figures) or above (tables) the picture, horizontally overlapping."""
        px0, py0, px1, py1 = box["bbox"]
        best = None
        for other in boxes:
            cls = other.get("class")
            text = other.get("_text")
            if text is None or cls not in ("caption", "text"):
                continue
            if cls == "text" and not looks_like_caption(text):
                continue                       # plain paragraph, not a mis-classified caption
            cx0, cy0, cx1, cy1 = other["bbox"]
            if min(px1, cx1) - max(px0, cx0) <= 0:
                continue
            info = self._caption_info(text)
            if not info:
                continue
            if cy0 >= py1 - 5:
                dist = cy0 - py1
            elif cy1 <= py0 + 5:
                dist = (py0 - cy1) + 40        # captions above are less likely (tables)
            else:
                dist = 1000
            if dist < 160 and (best is None or dist < best[0]):
                best = (dist, info)
        return best[1] if best else (None, None)

    # ---- headings / title / captions --------------------------------------
    @staticmethod
    def _heading(seg: str) -> str:
        text = strip_emphasis(re.sub(r"^\s*#+\s*", "", seg.strip()))
        if not text:
            return ""
        m = re.match(r"^(\d+(?:\.\d+)*)\.?\s+(.*)", text)
        if m:
            depth = m.group(1).count(".") + 1
            level = min(1 + depth, 6)
        elif re.match(r"^(appendix|supplement)", text, re.I):
            level = 2
        else:
            level = 2
        return f"\n{'#' * level} {text}\n\n"

    @staticmethod
    def _title(seg: str) -> str:
        text = strip_emphasis(re.sub(r"^\s*#+\s*", "", seg.strip()))
        return f"\n# {text}\n\n" if text else ""

    def _caption(self, seg: str) -> str:
        text = seg.strip()
        if not text:
            return ""
        info = self._caption_info(text)
        if info and self.opt.block_ids:
            kind, num = info
            return f"\n{text} {block_id(kind, num)}\n\n"
        return f"\n{text}\n\n"

    # ---- inline equation images -------------------------------------------
    def _inline_math(self, page, box: dict, seg: str, extra: Optional[list] = None) -> str:
        """Small images (and, via `extra`, vector-drawn symbols) inside a text box -> $...$ at
        the right spot of the text; a doubtful OCR result becomes a small inline image."""
        rect = pymupdf.Rect(box["bbox"])
        infos = self._page_images(page) if self.opt.inline_image_math else []
        extra = extra or []
        if not infos and not extra:
            return seg
        sizes = []
        try:
            for blk in page.get_text("dict", clip=rect, flags=TEXT_FLAGS)["blocks"]:
                for ln in blk.get("lines", []):
                    sizes += [s["size"] for s in ln["spans"] if s["text"].strip()]
        except Exception:
            pass
        body = sorted(sizes)[len(sizes) // 2] if sizes else 10.0
        max_h = max(14.0, 2.4 * body)
        cands = []
        for info in infos:
            if (info.get("xref") or 0) in self.logo_xrefs:
                continue
            ir = pymupdf.Rect(info["bbox"])
            if ir.is_empty or ir.height > max_h or ir.width < 4 or ir.width > rect.width * 0.9:
                continue
            inter = ir & rect
            if inter.is_empty or inter.get_area() < 0.8 * ir.get_area():
                continue
            cands.append(ir)
        for a in extra:
            a = pymupdf.Rect(a)
            if not any((a & c).get_area() > 0.5 * a.get_area() for c in cands):
                cands.append(a)
        if not cands:
            return seg
        words = page.get_text("words", clip=rect)
        cands.sort(key=lambda r: (round(r.y1 / 4), r.x0))
        new = seg
        cursor = 0
        for ir in cands:
            img = tight_crop(render(page, ir, 3.0), pad=10)
            if img is None:
                continue
            latex = self.conv.ocr.recognize_image(img, "") if self.conv.engine_name != "none" else None
            if latex and not inline_latex_ok(latex, ir):
                log.debug("  page %d: inline OCR doubtful (%s) -> image", self.pdf_page(page), latex)
                latex = None
            if latex:
                token = f" ${latex}$ "
            else:
                fname = self._save_inline_image(tight_crop(render(page, ir, 3.0), pad=2) or img)
                if not fname:
                    self.stats["inline_failed"] += 1
                    continue
                token = " " + self._embed(fname, "symbol") + " "
                self.stats["inline_as_image"] += 1
            new, cursor, inserted = self._place_token(new, cursor, token, words, ir)
            if not inserted:
                self.stats["inline_unplaced"] += 1
            if latex:
                self.stats["inline_eqs"] += 1
        return re.sub(r"(?<=\S)  +(?=\S)", " ", new)

    def _place_token(self, text: str, cursor: int, token: str, words: list, ir: pymupdf.Rect):
        """Insert `token` where the symbol sits in reading order: after the two words preceding it
        (one word is ambiguous: 'of', 'the'), else after one word whose follower matches, else
        before the following word, else at the end of the paragraph. -> (text, cursor, placed)"""
        order = sorted(words, key=lambda w: (round(((w[1] + w[3]) / 2) / 5), w[0]))
        cy = (ir.y0 + ir.y1) / 2
        pos = 0
        for i, w in enumerate(order):
            wy = (w[1] + w[3]) / 2
            if wy < ir.y0 - 0.3 * ir.height:                                   # lines above
                pos = i + 1
            elif abs(wy - cy) <= 0.7 * max(ir.height, w[3] - w[1]) and w[2] <= ir.x0 + 1.5:
                pos = i + 1                                                      # same line, left of it
        before = [w[4] for w in order[max(0, pos - 2):pos]]
        after = order[pos][4] if pos < len(order) else None
        tries = ([before[-2:]] if len(before) == 2 else []) + ([before[-1:]] if before else [])
        for anchor in tries:
            pats = [self._fuzzy_word(w) for w in anchor]
            if not all(pats):
                continue
            pat = re.compile(r"\s+".join(p.pattern for p in pats))
            for mm in pat.finditer(text, cursor):
                end = mm.end()
                trail = re.search(r"[^\w\s]+$", anchor[-1])          # 'flux,' stays together
                if trail and text.startswith(trail.group(0), end):
                    end += len(trail.group(0))
                if len(anchor) == 1 and after:                         # one word: check what follows
                    apat = self._fuzzy_word(after)
                    if apat and not apat.match(text[end:].lstrip(" ,.;:()[]")):
                        continue
                tok = token.rstrip() if text[end:end + 1] in ",.;:)]" else token   # 'q_in, as'
                return text[:end] + tok + text[end:], end + len(tok), True
        if after:
            apat = self._fuzzy_word(after)
            mm = apat.search(text, cursor) if apat else None
            if mm:
                return text[:mm.start()] + token + text[mm.start():], mm.start() + len(token), True
        return text.rstrip("\n") + token.rstrip() + "\n\n", len(text), False

    def _save_inline_image(self, img) -> Optional[str]:
        """A symbol crop (rendered at zoom 3 = 216 dpi) saved at its physical size."""
        try:
            self.inline_seq += 1
            fname = f"inline-{self.inline_seq:02d}.png"
            img.save(self.asset_dir / fname, dpi=(216, 216))
            return fname
        except Exception as exc:
            log.debug("inline image not saved: %s", exc)
            return None

    # ---- inline text math (rho_f, u_i set as ordinary text) ---------------
    def _text_math(self, page, box: dict, seg: str) -> str:
        new, found, missed = inline_text_math(page, box["bbox"], seg)
        if found:
            self.stats["inline_text_eqs"] += len(found)
            for src, repl in found:
                log.debug("  page %d: text math %r -> %s", self.pdf_page(page), src, repl)
        if missed:
            self.stats["inline_text_missed"] += len(missed)
            log.debug("  page %d: text math not located in markdown: %s", self.pdf_page(page), "; ".join(missed))
        return new

    @staticmethod
    def _fuzzy_word(word: str):
        w = re.sub(r"^\W+|\W+$", "", word)
        if not w:
            return None
        return re.compile(r"[*_`]*".join(re.escape(ch) for ch in w) + r"[*_`]*")
