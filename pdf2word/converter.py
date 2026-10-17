"""Main pipeline: PDF -> layout analysis (PyMuPDF Layout) -> Markdown with LaTeX equations,
figures copied into an asset folder, Obsidian post-processing."""
from __future__ import annotations

import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pymupdf

from .config import (CHAPTER_ASSET_TEMPLATE, CHAPTER_NAME_TEMPLATE, DOC_ASSET_TEMPLATE, DOC_NAME_TEMPLATE,
                     PAPER_ASSET_TEMPLATE, PAPER_NAME_TEMPLATE, Options)
from .lighten import lighten_document
from .inlinemath import inline_text_math
from .mathocr import TEXT_FLAGS, EquationOCR, EquationResult, build_engine, find_labels, render, tight_crop
from .metadata import PaperMeta, detect_doc_type, document_meta, resolve_metadata
from .obsidian import block_id, build_frontmatter, ensure_title, image_link, postprocess
from .outline import Part, page_groups, part_document, read_outline, select_parts
from .symbols import has_pua, map_pua
from .utils import log, parse_page_range, safe_name, slugify_title, strip_emphasis

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
            pages = parse_page_range(opt.pages, doc.page_count)
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
            asset_name = safe_name(asset_t.format(**fields), 120)
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
                return select_parts(tree, opt.chapters)
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
            log.info("== %s: %d part(s) of %d pages", pdf_path.name, len(parts), doc.page_count)
            for part in parts:
                if stop is not None and stop():
                    log.info("  stopped before part %s", part.num_str)
                    break
                t0 = time.time()
                log.info("== %s  [%s %s] %s  (pages %s)", pdf_path.name, part.kind, part.num_str,
                         part.title, part.pages_label)
                try:
                    title = part.title if part.kind == "chapter" else f"{book.title} (pages {part.pages_label})"
                    meta = PaperMeta(title=title, authors=list(book.authors), first_author=book.first_author,
                                     year=book.year, source="outline", kind=part.kind, container=book.title,
                                     part_pages=part.pages_label, part_id=part.id)
                    fields = self._fields(book, pdf_path)
                    fields.update(part.fields(fields["stem"], doc.page_count))
                    name_t = opt.chapter_template or CHAPTER_NAME_TEMPLATE
                    asset_t = opt.asset_template or CHAPTER_ASSET_TEMPLATE
                    sub = part_document(doc, part, opt.chapter_split)
                    try:
                        results.append(self._run(sub, pdf_path, meta, "document",
                                                 safe_name(name_t.format(**fields), 150),
                                                 safe_name(asset_t.format(**fields), 120), part=part,
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
        pages = None
        fmt = (opt.format or "docx").lower()
        if fmt not in ("docx", "md", "both"):
            raise ValueError(f"unknown output format: {opt.format}")
        out_dir = Path(opt.out_dir).resolve() if opt.out_dir else pdf_path.parent
        md_path = out_dir / (base_name + ".md")
        docx_path = out_dir / (base_name + ".docx")
        asset_dir = out_dir / asset_name
        targets = [p for p, wanted in ((md_path, fmt != "docx"), (docx_path, fmt != "md")) if wanted]
        if not opt.overwrite and any(p.exists() for p in targets):
            log.info("  exists, skipped (use --overwrite): %s", ", ".join(p.name for p in targets if p.exists()))
            return ConversionResult(pdf_path, md_path if fmt != "docx" else None, asset_dir, meta,
                                    docx_path=docx_path if fmt != "md" else None, skipped=True,
                                    part=part, doc_type=doc_type)

        out_dir.mkdir(parents=True, exist_ok=True)
        asset_dir.mkdir(parents=True, exist_ok=True)
        self._remove_generated(asset_dir)

        stats: Counter = Counter()
        layout_doc = doc
        try:
            # 1) layout analysis + markdown per page (pymupdf4llm + PyMuPDF Layout)
            _patch_pymupdf4llm_pua()
            import pymupdf4llm
            if opt.lighten:
                layout_doc, n_light = lighten_document(doc, dpi=opt.dpi)
                stats["pages_lightened"] = n_light
            n_pages = len(pages) if pages else doc.page_count
            log.info("  layout analysis (%d pages) ...", n_pages)
            t_layout = time.time()
            # write_images=False: pictures are rendered from the ORIGINAL document in _picture()
            chunks = pymupdf4llm.to_markdown(
                layout_doc, pages=pages, page_chunks=True, write_images=False,
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
                build_docx(body, meta, out_dir, docx_path, opt, stats)
                written.append(docx_path.name)
        finally:
            if self._ocr is not None:
                self._ocr.cache.save()
            if layout_doc is not doc:
                layout_doc.close()

        if fmt == "docx":                         # images live inside the .docx now
            self._remove_generated(asset_dir)
        if not any(asset_dir.iterdir()):
            asset_dir.rmdir()
            asset_dir_out = None
        else:
            asset_dir_out = asset_dir
        stats["seconds"] = round(time.time() - t0, 1)
        log.info("  -> %s  (%ss; equations %d ok / %d as image; inline text math %d; figures %d%s)",
                 " + ".join(written), stats["seconds"], stats["eq_ok"], stats["eq_fallback"],
                 stats["inline_text_eqs"], stats["figures"],
                 f"; Word equations {stats['docx_eq_native']} native / {stats['docx_eq_text']} text"
                 if fmt != "md" else "")
        return ConversionResult(pdf_path, md_path if fmt != "docx" else None, asset_dir_out, meta,
                                docx_path=docx_path if fmt != "md" else None, stats=dict(stats),
                                part=part, doc_type=doc_type)

    # -- helpers ------------------------------------------------------------
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
        self.doc = doc
        self.asset_dir = asset_dir
        self.stats = stats
        self.conv = conv
        self.opt = conv.opt
        self.page_map = page_map               # sub-document page -> page of the full PDF (0-based)
        self.used_names: Counter = Counter()
        self.picture_names: dict = {}          # base -> [filename, ...] (for sub-figure lettering)
        self.eq_seq = 0
        self.inline_seq = 0
        self.logo_xrefs = self._repeated_images(doc)
        self._page_images_cache: dict = {}

    # ---- document-level helpers ------------------------------------------
    def pdf_page(self, page) -> int:
        """1-based page number in the full PDF (for log messages)."""
        pno = page.number
        if self.page_map and pno < len(self.page_map):
            pno = self.page_map[pno]
        return pno + 1

    @staticmethod
    def _repeated_images(doc) -> set:
        """XObjects shown on many pages (journal logos in headers/footers)."""
        pages_of: dict = {}
        for pno in range(doc.page_count):
            try:
                infos = doc[pno].get_image_info(xrefs=True)
            except Exception:
                continue
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
        # markdown references: tokens first, then the new names (no chained replacements)
        prefix = self.asset_dir.name + "/"
        for i, old in enumerate(renames):
            body = body.replace(prefix + old, f"\x00{i}\x00")
        for i, (old, new) in enumerate(renames.items()):
            body = body.replace(f"\x00{i}\x00", prefix + new)
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
        out = []
        cursor = 0
        for box in boxes:
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
                    if self.opt.inline_image_math:
                        seg = self._inline_math(page, box, seg)
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
            cursor = max(cursor, stop)
        out.append(text[cursor:])
        page_md = "".join(out)
        for label in self._consumed_labels:    # '(3)' lines that belonged to an equation image
            page_md = re.sub(rf"(?m)^[ \t]*\({re.escape(label)}\)[ \t]*\n?", "", page_md, count=1)
        return page_md

    # ---- formulas ----------------------------------------------------------
    def _formula(self, page, box: dict, seg: str) -> str:
        rect = pymupdf.Rect(box["bbox"])
        labels = find_labels(page, rect)
        regions = self._split_regions(rect, labels)
        blocks = []
        for region, label in regions:
            hint = map_pua(page.get_text("text", clip=region) or "").strip()
            self.stats["eq_total"] += 1
            result = self.conv.ocr.recognize_region(page, region, hint)
            if result.cached:
                self.stats["eq_cached"] += 1
            blocks.append(self._format_equation(result, label, hint, page, region))
        return "\n" + "\n".join(blocks) + "\n"

    @staticmethod
    def _split_regions(rect: pymupdf.Rect, labels: list) -> list:
        """A formula box may stack several numbered equations: one region per label."""
        if not labels:
            return [(rect, None)]
        centers = [(lr.y0 + lr.y1) / 2 for _, lr in labels]
        bounds = [rect.y0] + [(centers[i] + centers[i + 1]) / 2 for i in range(len(centers) - 1)] + [rect.y1]
        regions = []
        for i, (label, lr) in enumerate(labels):
            x1 = min(rect.x1, lr.x0 - 2) if lr.x0 - 2 > rect.x0 + 10 else rect.x1
            regions.append((pymupdf.Rect(rect.x0, bounds[i], x1, bounds[i + 1]), label))
        return regions

    def _format_equation(self, result: EquationResult, label: Optional[str], hint: str, page, region) -> str:
        opt = self.opt
        lines = []
        if result.latex and opt.math_mode != "image":
            body = result.latex
            if label:
                body = body + f" \\tag{{{label}}}"
            # the cropped original first, OCR result below it (always when the OCR looks doubtful)
            if opt.math_mode == "both" or result.uncertain:
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
        img = result.image
        if img is None:
            img = tight_crop(render(page, region, 3.0))
        if img is None:
            return None
        self.eq_seq += 1
        base = f"eq-{re.sub(r'[^A-Za-z0-9-]+', '-', label)}" if label else f"eq-u{self.eq_seq:02d}"
        fname = self._unique(base) + ".png"
        dpi = int(round(72 * max(float(self.opt.math_zooms[0]) if self.opt.math_zooms else 2.0, 2.0)))
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
            if label or (h <= 70 and w >= 100 and w / max(h, 1) >= 2.5):
                eq = self._picture_as_equation(page, box, label)
                if eq is not None:
                    return eq
        if not kind and (w < 20 or h < 20 or w * h < 2500 or self._is_logo(page, box)):   # logos, badges, icons
            self.stats["pictures_skipped"] += 1
            return ""
        if kind:
            base = f"{kind}{num}"
        else:
            base = f"p{page.number + 1}-img{box['index'] + 1}"
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
        labels = find_labels(page, pymupdf.Rect(x0, y0 - 3, page.rect.x1, y1 + 3))
        labels = [(lb, r) for lb, r in labels if r.x0 >= x1 - 2]
        return labels[0][0] if labels else None

    def _picture_as_equation(self, page, box: dict, label: Optional[str]) -> Optional[str]:
        region = pymupdf.Rect(box["bbox"])
        result = self.conv.ocr.recognize_region(page, region, "")
        if result.latex is None and not label:
            return None                                   # probably a real picture after all
        self.stats["eq_total"] += 1
        if label:
            self._consumed_labels.append(label)
        return "\n" + self._format_equation(result, label, "", page, region) + "\n"

    @staticmethod
    def _caption_info(box: dict, text: str):
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
            info = self._caption_info(other, text)
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
        info = self._caption_info({}, text)
        if info and self.opt.block_ids:
            kind, num = info
            return f"\n{text} {block_id(kind, num)}\n\n"
        return f"\n{text}\n\n"

    # ---- inline equation images -------------------------------------------
    def _inline_math(self, page, box: dict, seg: str) -> str:
        rect = pymupdf.Rect(box["bbox"])
        infos = self._page_images(page)
        if not infos:
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
            latex = self.conv.ocr.recognize_image(img, "")
            if not latex:
                self.stats["inline_failed"] += 1
                continue
            token = f" ${latex}$ "
            same_line = [w for w in words if min(w[3], ir.y1) - max(w[1], ir.y0) > 0.5 * ir.height]
            before = [w for w in same_line if w[2] <= ir.x0 + 1.5]
            after = [w for w in same_line if w[0] >= ir.x1 - 1.5]
            anchor = max(before, key=lambda w: w[2]) if before else None
            inserted = False
            if anchor:
                pat = self._fuzzy_word(anchor[4])
                mm = pat.search(new, cursor) if pat else None
                if mm:
                    new = new[:mm.end()] + token + new[mm.end():]
                    cursor = mm.end() + len(token)
                    inserted = True
            if not inserted and after:
                nxt = min(after, key=lambda w: w[0])
                pat = self._fuzzy_word(nxt[4])
                mm = pat.search(new, cursor) if pat else None
                if mm:
                    new = new[:mm.start()] + token + new[mm.start():]
                    cursor = mm.start() + len(token)
                    inserted = True
            if not inserted:
                new = new.rstrip("\n") + token.rstrip() + "\n\n"
            self.stats["inline_eqs"] += 1
        return new

    # ---- inline text math (rho_f, u_i set as ordinary text) ---------------
    def _text_math(self, page, box: dict, seg: str) -> str:
        new, found, missed = inline_text_math(page, box["bbox"], seg)
        if found:
            self.stats["inline_text_eqs"] += len(found)
            for src, repl in found:
                log.debug("  page %d: text math %r -> %s", page.number + 1, src, repl)
        if missed:
            self.stats["inline_text_missed"] += len(missed)
            log.debug("  page %d: text math not located in markdown: %s", page.number + 1, "; ".join(missed))
        return new

    @staticmethod
    def _fuzzy_word(word: str):
        w = re.sub(r"^\W+|\W+$", "", word)
        if not w:
            return None
        return re.compile(r"[*_`]*".join(re.escape(ch) for ch in w) + r"[*_`]*")
