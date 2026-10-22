"""Paper metadata: DOI/arXiv detection, CrossRef & arXiv lookup, first-page heuristics."""
from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET

import pymupdf
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Optional
from urllib.parse import quote

from . import __version__

log = logging.getLogger("pdf2word")

# ')' is allowed inside a DOI (10.1016/0021-9991(81)90145-5); clean_doi drops an unbalanced trailing one
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>\]]+)", re.I)
_DOI_ANNOUNCED_RE = re.compile(r"(?:doi\.org/|doi:\s*|\bDOI\b\s*:?\s*)(10\.\d{4,9}/[^\s\"'<>\]]+)", re.I)
ARXIV_RE = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
_USER_AGENT = f"pdf2word/{__version__} (https://github.com/Perfectree-1215/PDF2Word)"
_BAD_TITLES = re.compile(r"^(untitled.*|microsoft (word|powerpoint).*|powerpoint.*|.*프레젠테이션|presentation\d*|"
                         r"slide ?\d+|슬라이드 ?\d+|doc(ument)?\d*|제목 없음.*|무제.*|\d[\w-]*|.*\.(docx?|pptx?|tex|pdf|indd))$"
                         r"|^\s*$", re.I)
_BAD_AUTHORS = re.compile(r"^(user|admin|administrator|owner|author|confit|unknown|windows|\s*)$", re.I)
_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "phd", "md", "dr"}
_PARTICLES = {"van", "von", "de", "der", "den", "del", "della", "di", "da", "le", "la", "du",
              "dos", "das", "do", "al", "bin", "ibn", "mac", "ten", "ter", "el"}
_AFFILIATION_RE = re.compile(
    r"(university|institute|department|school|laboratory|@|received|abstract|college|faculty|"
    r"center|centre|academy|corporation|ltd|inc\b|co\.,|research|division|hospital|"
    r"www\.|https?://|homepage)", re.I)
# journal masthead block on top of page 1 (Elsevier): the journal name there is not the title
_MASTHEAD_RE = re.compile(r"journal homepage|contents lists available", re.I)
# inline markup CrossRef keeps in titles (JATS / HTML); a whitelist, so a literal 'a < b > c' survives
_MARKUP_TAG_RE = re.compile(r"</?(?:i|b|em|strong|u|sub|sup|inf|scp|sc|span|tt|mml:[a-z]+|math)\b[^>]*>", re.I)
_GLUED_TAG_RE = re.compile(r"(?<=[^\W\d_])<(?:i|em|b)>(?=\w)|(?<=\w)</(?:i|em|b)>(?=[^\W\d_])", re.I)


@dataclass
class PaperMeta:
    title: str = ""
    authors: list = field(default_factory=list)
    first_author: str = ""          # surname of the first author
    year: Optional[int] = None
    journal: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    arxiv: str = ""
    url: str = ""
    keywords: list = field(default_factory=list)
    source: str = ""                # crossref | arxiv | heuristic | document | outline (+override)
    kind: str = "paper"             # paper | document | chapter | pages
    container: str = ""             # title of the whole document when this is one chapter / page group
    part_pages: str = ""            # human form: "p. 201-205 (PDF 249-253)" / "PDF 249-253"
    part_pages_pdf: str = ""        # "249-253": pages of the part in the PDF (1-based)
    part_pages_printed: str = ""    # "201-205": printed page numbers (page labels), "" if unknown
    part_id: str = ""               # bookmark id of the chapter ("3.2")

    def merge_missing(self, other: "PaperMeta") -> "PaperMeta":
        """Fill empty fields of self from other (self wins)."""
        for key, value in asdict(other).items():
            if key == "source":
                continue
            if not getattr(self, key) and value:
                setattr(self, key, value)
        return self


# ----------------------------------------------------------------------------- identifiers

def clean_doi(doi: str) -> str:
    doi = doi.strip()
    # trailing punctuation; ')' only when unbalanced, so '...(81)90145-5)' keeps its own parentheses
    while doi and doi[-1] in ".,;:)]}>\"'":
        if doi[-1] == ")" and doi.count(")") <= doi.count("("):
            break
        doi = doi[:-1]
    # DOIs glued to the following word in extracted text, e.g. 10.1000/abc.Received
    doi = re.sub(r"\.(Received|Accepted|Published|Available|Copyright|Keywords?|Abstract)$", "", doi, flags=re.I)
    return doi


def find_doi(text: str) -> str:
    """First DOI of the text; one announced as 'doi:' / 'doi.org/' is preferred."""
    m = _DOI_ANNOUNCED_RE.search(text)
    if m:
        return clean_doi(m.group(1))
    m = DOI_RE.search(text)
    return clean_doi(m.group(1)) if m else ""


def find_dois(text: str, limit: int = 3) -> list:
    """Candidate DOIs of the paper: announced ones ('doi:' / 'doi.org/') first, then bare ones,
    without duplicates. The first one is find_doi(text)."""
    found = [clean_doi(m.group(1)) for m in _DOI_ANNOUNCED_RE.finditer(text)]
    found += [clean_doi(m.group(1)) for m in DOI_RE.finditer(text)]
    out, seen = [], set()
    for doi in found:
        if doi and doi.lower() not in seen:
            seen.add(doi.lower())
            out.append(doi)
    return out[:limit]


def find_arxiv(text: str) -> str:
    m = ARXIV_RE.search(text) or ARXIV_URL_RE.search(text)
    return m.group(1) if m else ""


# ----------------------------------------------------------------------------- names

def clean_author(name: str) -> str:
    name = re.sub(r"[\*†‡§¶#∗✉✝⇑⁎\d]+", "", name)          # affiliation markers
    name = re.sub(r"\s+", " ", name).strip(" ,;")
    return name


def surname(name: str) -> str:
    """'Kwang Hee Kim' -> 'Kim', 'Weers, M.' -> 'Weers', 'Ludwig van Beethoven' -> 'van Beethoven'."""
    name = clean_author(name)
    if not name:
        return ""
    if re.fullmatch(r"[가-힣]{1,2}\s+[가-힣]{1,3}", name):      # '신 지원': Korean order, surname first
        return name.split()[0]
    if "," in name:
        return name.split(",", 1)[0].strip()
    parts = name.split(" ")
    while len(parts) > 1 and parts[-1].lower().strip(".") in _NAME_SUFFIXES:
        parts.pop()
    i = len(parts) - 1
    while i - 1 >= 0 and parts[i - 1].lower().strip(".") in _PARTICLES:
        i -= 1
    return " ".join(parts[i:])


def split_author_line(line: str) -> list:
    line = re.sub(r"[(（].*?[)）]", "", line)          # (corresponding author), （affiliation）
    line = re.sub(r"\s*&\s*|\band\b", ",", line, flags=re.I)
    parts = [clean_author(p) for p in re.split(r"[,;]", line)]
    return [p for p in parts
            if p and len(p) > 1 and re.search(r"[A-Za-zÀ-ɏ가-힣一-鿿]", p)]


# ----------------------------------------------------------------------------- online lookups

def _strip_markup(text: str) -> str:
    """'Effect of <i>in situ</i> H<sub>2</sub>O' -> 'Effect of in situ H2O'; entities decoded.
    <i>/<em>/<b> glued between letters (APS: 'in<i>p</i>-wave') become a space."""
    text = _GLUED_TAG_RE.sub(" ", text or "")
    text = _MARKUP_TAG_RE.sub("", text)
    return " ".join(html.unescape(text).split())


def _get(session, url: str, **kw):
    """GET through the shared session of one conversion, or a one-off requests.get."""
    if session is None:
        import requests
        return requests.get(url, **kw)
    return session.get(url, **kw)


def crossref_lookup(doi: str, timeout: float = 10.0, *, session=None,
                    errors: Optional[list] = None) -> Optional[PaperMeta]:
    """CrossRef record of the DOI, or None. Failure reasons are appended to `errors`."""
    try:
        r = _get(session, f"https://api.crossref.org/works/{quote(doi, safe='')}",
                 headers={"User-Agent": _USER_AGENT}, timeout=timeout)
        if r.status_code != 200:
            log.debug("CrossRef %s -> HTTP %s", doi, r.status_code)
            if errors is not None:
                errors.append(f"CrossRef {doi}: HTTP {r.status_code}")
            return None
        m = r.json().get("message", {})
    except Exception as exc:  # network errors, bad JSON ...
        log.debug("CrossRef lookup failed: %s", exc)
        if errors is not None:
            errors.append(f"CrossRef {doi}: {exc}")
        return None

    meta = PaperMeta(source="crossref")
    titles = m.get("title") or []
    meta.title = _strip_markup(titles[0]) if titles else ""
    first = None                    # the record's first author (with a family name or a full name)
    for a in m.get("author", []) or []:
        if a.get("family"):
            meta.authors.append(clean_author(f"{a.get('given', '')} {a['family']}"))
        elif a.get("name"):
            meta.authors.append(clean_author(a["name"]))
        else:
            continue
        if first is None:
            first = a
    for key in ("published-print", "published-online", "issued", "created"):
        parts = (m.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            meta.year = int(parts[0][0])
            break
    ct = m.get("container-title") or []
    meta.journal = _strip_markup(ct[0]) if ct else ""
    meta.volume = str(m.get("volume") or "")
    meta.issue = str(m.get("issue") or "")
    meta.pages = str(m.get("page") or "")
    meta.doi = m.get("DOI") or doi
    meta.url = m.get("URL") or f"https://doi.org/{meta.doi}"
    # surname = CrossRef's own family field ('García Márquez', 'Abu Bakar'), plus any particle it
    # left at the end of 'given' ('Ludwig van' + 'Beethoven' -> 'van Beethoven')
    fam = clean_author(first["family"]) if first and first.get("family") else ""
    if fam:
        given = (first.get("given") or "").split()
        while given and given[-1].lower().strip(".") in _PARTICLES:
            fam = f"{given.pop()} {fam}"
        meta.first_author = fam
    elif meta.authors:
        meta.first_author = surname(meta.authors[0])
    return meta


def arxiv_lookup(arxiv_id: str, timeout: float = 10.0, *, session=None,
                 errors: Optional[list] = None) -> Optional[PaperMeta]:
    """arXiv record of the id, or None. Failure reasons are appended to `errors`."""
    def fail(reason: str) -> None:
        if errors is not None:
            errors.append(f"arXiv {arxiv_id}: {reason}")

    try:
        r = _get(session, "https://export.arxiv.org/api/query", params={"id_list": arxiv_id},
                 headers={"User-Agent": _USER_AGENT}, timeout=timeout)
        if r.status_code != 200:
            log.debug("arXiv %s -> HTTP %s", arxiv_id, r.status_code)
            fail(f"HTTP {r.status_code}")
            return None
        root = ET.fromstring(r.text)
    except Exception as exc:
        log.debug("arXiv lookup failed: %s", exc)
        fail(str(exc))
        return None
    ns = {"a": "http://www.w3.org/2005/Atom", "ar": "http://arxiv.org/schemas/atom"}
    entry = root.find("a:entry", ns)
    if entry is None:
        fail("no entry")
        return None
    title = " ".join((entry.findtext("a:title", default="", namespaces=ns) or "").split())
    if not title or title == "Error":
        fail("no entry")
        return None
    meta = PaperMeta(source="arxiv", title=title)
    meta.authors = [clean_author(e.findtext("a:name", default="", namespaces=ns) or "")
                    for e in entry.findall("a:author", ns)]
    meta.authors = [a for a in meta.authors if a]
    published = entry.findtext("a:published", default="", namespaces=ns) or ""
    if published[:4].isdigit():
        meta.year = int(published[:4])
    meta.arxiv = arxiv_id
    meta.doi = (entry.findtext("ar:doi", default="", namespaces=ns) or "").strip()
    meta.url = (entry.findtext("a:id", default="", namespaces=ns) or "").strip() or f"https://arxiv.org/abs/{arxiv_id}"
    meta.journal = "arXiv"
    if meta.authors:
        meta.first_author = surname(meta.authors[0])
    return meta


# ----------------------------------------------------------------------------- heuristics

def _page_lines(page) -> list:
    """[(size, y0, text, bbox, text_nosup)] for every text line of the page, in extraction order.

    text joins every span, including the space-only spans MuPDF makes from glyph gaps.
    text_nosup also drops raised small spans (affiliation letters, corresponding-author marks),
    keeping any ',' ';' they held; it is meant for author lines only - titles keep 'Ca2+'."""
    lines = []
    flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    for block in page.get_text("dict", flags=flags)["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            inked = [s for s in line["spans"] if s["text"].strip()]
            if not inked:
                continue
            size = max(s["size"] for s in inked)
            text = "".join(s["text"] for s in line["spans"]).strip()
            nosup = "".join(
                re.sub(r"[^,;]", "", s["text"])
                if s["text"].strip() and s["flags"] & 1 and s["size"] < 0.85 * size else s["text"]
                for s in line["spans"]).strip()
            lines.append((round(size, 1), line["bbox"][1], text, line["bbox"], nosup))
    return lines


def heuristic_meta(doc, first_pages_text: str) -> PaperMeta:
    meta = PaperMeta(source="heuristic")
    pdfmeta = doc.metadata or {}
    page = doc[0]
    lines = _page_lines(page)
    page_h = page.rect.height

    # --- title: PDF metadata unless it looks like junk, else the biggest text on page 1
    title = " ".join((pdfmeta.get("title") or "").split())
    title_lines = []
    if lines:
        # skip a journal masthead block on top ('Contents lists available at ...', 'journal homepage: ...')
        top = max((bbox[3] for _, y0, text, bbox, _ in lines
                   if y0 < page_h * 0.3 and _MASTHEAD_RE.search(text)), default=float("-inf"))
        size_chars: Counter = Counter()
        for size, y0, text, _, _ in lines:
            if top <= y0 < page_h * 0.6:
                size_chars[size] += len(text)
        candidates = sorted((s for s, n in size_chars.items() if n >= 12), reverse=True)
        if candidates:
            big = candidates[0]
            title_lines = sorted(((y0, text, bbox) for size, y0, text, bbox, _ in lines
                                  if size == big and top <= y0 < page_h * 0.6
                                  and not re.fullmatch(r"[\[\(].{1,12}[\]\)]|\S{1,3}", text.strip())),
                                 key=lambda x: x[0])
            # keep the largest vertically contiguous run (drops stray labels in the same font)
            runs, run = [], []
            for item in title_lines:
                if run and item[0] - run[-1][2][3] > 1.6 * big:
                    runs.append(run)
                    run = []
                run.append(item)
            if run:
                runs.append(run)
            title_lines = max(runs, key=lambda r: sum(len(t) for _, t, _ in r)) if runs else []
    heuristic_title = " ".join(t for _, t, _ in title_lines).strip()
    if not title or len(title) < 8 or _BAD_TITLES.match(title):
        title = heuristic_title
    meta.title = re.sub(r"\s+", " ", title).strip()

    # --- authors: PDF metadata, else the lines right below the title
    author_field = (pdfmeta.get("author") or "").strip()
    if (author_field and not _BAD_AUTHORS.match(author_field)
            and re.search(r"[A-Za-zÀ-ɏ가-힣]", author_field)):
        meta.authors = split_author_line(author_field.replace(";", ","))
    if not meta.authors and title_lines:
        bottom = max(b[3] for _, _, b in title_lines)
        below = [(y0, text, nosup) for size, y0, text, bbox, nosup in lines if bottom - 2 < y0 < bottom + 90]
        for _, text, nosup in sorted(below):
            bare = re.sub(r"[(（].*?[)）]", "", text)       # affiliations in parentheses are fine
            if _AFFILIATION_RE.search(bare):
                break
            names = split_author_line(nosup)              # without superscript affiliation letters
            if names and all(len(n.split()) <= 5 for n in names):
                meta.authors.extend(names)
            if len(meta.authors) >= 2 and not text.rstrip().endswith(","):
                break
    if meta.authors:
        meta.first_author = surname(meta.authors[0])

    # --- year: the journal's citation line on top of page 1 ('70 (2014) 123-135'), else the latest
    # date keyword (the history runs Received -> Accepted -> Published), else the commonest year
    head = first_pages_text[:6000]
    kw_years = [int(k.group(1)) for k in re.finditer(
        r"(?:©|\(c\)|copyright|published|accepted|received|available online|revised)"
        r"[^\n]{0,60}?(19[5-9]\d|20[0-4]\d)", head, re.I)]
    kw_year = max(kw_years) if kw_years else None
    cite = re.search(r"\b\d+\s*\((19[5-9]\d|20[0-4]\d)\)\s*\d+\s*[–-]\s*\d+", page.get_text("text")[:1500])
    cite_year = int(cite.group(1)) if cite else None
    if cite_year and (kw_year is None or cite_year >= kw_year):
        meta.year = cite_year
    elif kw_year:
        meta.year = kw_year
    else:
        years = [int(y) for y in YEAR_RE.findall(head)]
        if years:
            meta.year = Counter(years).most_common(1)[0][0]
        else:
            m2 = re.search(r"D:(\d{4})", pdfmeta.get("creationDate") or "")
            if m2:
                meta.year = int(m2.group(1))

    # --- keywords (the text right after 'Keywords:' up to a blank line / next section)
    m = re.search(r"Keywords?\s*[:：][ \t]*(.{0,400})", first_pages_text, re.I | re.S)
    if m:
        chunk = m.group(1).lstrip("\n")             # the list may start on the next line
        cut = re.search(r"\n\s*\n|\n\s*\d+\.?\s+[A-Z]|\bIntroduction\b|\n\s*1\s*\n"
                        r"|(?i:\n\s*a\s?b\s?s\s?t\s?r\s?a\s?c\s?t\b)", chunk)
        if cut:
            chunk = chunk[:cut.start()]
        if re.search(r"[;,·•]", chunk.split("\n", 1)[0]):     # separated list, maybe wrapped
            kw = [k.strip(" .") for k in re.split(r"[;,·•]\s*|\s{2,}", chunk.replace("\n", " "))
                  if _keyword_ok(k)]
        else:                                       # one keyword per line: stop at the first non-keyword
            kw = []
            for line in chunk.split("\n"):
                parts = [p for p in re.split(r"\s{2,}", line.strip()) if p]
                if not parts or not all(_keyword_ok(p) for p in parts):
                    break
                if line.rstrip().endswith("."):     # a sentence ends the list (kept only as the sole line)
                    if not kw:
                        kw = [p.strip(" .") for p in parts]
                    break
                kw += [p.strip(" .") for p in parts]
        meta.keywords = kw[:12]
    return _normalize_meta(meta)


def _keyword_ok(k: str) -> bool:
    return (2 < len(k.strip()) < 60 and len(k.split()) <= 6
            and not re.search(r"[\[\]©@]|https?:|^\d+$|\d{1,2}:\d{2}|\bauthors?\b", k, re.I))


_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
              "ﬅ": "st", "ﬆ": "st"}


def _fix_text(s: str) -> str:
    for lig, rep in _LIGATURES.items():
        s = s.replace(lig, rep)
    return re.sub(r"\s+", " ", s).strip()


def _normalize_meta(meta: PaperMeta) -> PaperMeta:
    meta.title = _fix_text(meta.title)
    meta.journal = _fix_text(meta.journal)
    meta.authors = [_fix_text(a) for a in meta.authors if _fix_text(a)]
    meta.keywords = [_fix_text(k) for k in meta.keywords if _fix_text(k)]
    meta.first_author = _fix_text(meta.first_author)
    return meta


# ----------------------------------------------------------------------------- document type

def detect_doc_type(doc, first_pages_text: str) -> tuple:
    """('paper' | 'document', reason). Papers carry a DOI / arXiv id or an abstract on the first
    pages; everything else (books, manuals, reports, slides) is a plain document."""
    if find_doi(first_pages_text):
        return "paper", "DOI found"
    if find_arxiv(first_pages_text):
        return "paper", "arXiv id found"
    if doc.page_count <= 80 and re.search(r"\babstract\b", first_pages_text, re.I):
        return "paper", "abstract on the first pages"
    return "document", f"{doc.page_count} pages, no DOI / abstract"


def document_meta(doc, pdf_path) -> PaperMeta:
    """Metadata of a non-paper document: the PDF's own title/author fields, else the file name."""
    meta = PaperMeta(source="document", kind="document")
    pdfmeta = doc.metadata or {}
    title = " ".join((pdfmeta.get("title") or "").split())
    if not title or len(title) < 3 or _BAD_TITLES.match(title):
        title = re.sub(r"[_]+", " ", getattr(pdf_path, "stem", str(pdf_path))).strip()
    meta.title = title
    author_field = (pdfmeta.get("author") or "").strip()
    if author_field and not _BAD_AUTHORS.match(author_field) and re.search(r"[A-Za-zÀ-ɏ가-힣]", author_field):
        meta.authors = split_author_line(author_field.replace(";", ","))
        if meta.authors:
            meta.first_author = surname(meta.authors[0])
    m = re.search(r"D:(\d{4})", pdfmeta.get("creationDate") or pdfmeta.get("modDate") or "")
    if m:
        meta.year = int(m.group(1))
    return _normalize_meta(meta)


# ----------------------------------------------------------------------------- orchestration

def _title_key(text: str) -> str:
    """Letters and digits only (any script), lower case, ligatures and markup removed."""
    text = (text or "").lower()
    for lig, rep in _LIGATURES.items():
        text = text.replace(lig, rep)
    return re.sub(r"[\W_]+", "", _strip_markup(text))


def _crossref_for_paper(dois: list, first_pages_text: str, session, errors: list) -> Optional[PaperMeta]:
    """The CrossRef record of the paper itself: the first candidate DOI whose title is printed on the
    first pages (page 1 may also cite a dataset or another paper by DOI). When none matches, the
    record of the first DOI is used as before, with a warning (non-English page 1, math in the title)."""
    page_key = _title_key(first_pages_text)
    first_rec = None
    for i, doi in enumerate(dois):
        rec = crossref_lookup(doi, session=session, errors=errors)
        if rec is None:
            continue
        key = _title_key(rec.title)
        if len(key) >= 8 and key in page_key:
            log.info("  metadata: CrossRef (%s)", doi)
            return rec
        errors.append(f"CrossRef {doi}: title not found on the first pages")
        if i == 0:
            first_rec = rec
    if first_rec is not None:
        log.warning("  metadata: CrossRef title not found on page 1 - using the record of %s anyway", dois[0])
        log.info("  metadata: CrossRef (%s)", dois[0])
    return first_rec


def resolve_metadata(doc, first_pages_text: str, *, online: bool = True,
                     author: Optional[str] = None, year: Optional[int] = None,
                     title: Optional[str] = None) -> PaperMeta:
    heur = heuristic_meta(doc, first_pages_text)
    dois = find_dois(first_pages_text)
    doi = dois[0] if dois else ""
    arxiv_id = find_arxiv(first_pages_text)
    meta: Optional[PaperMeta] = None
    errors: list = []
    lookup = online and bool(dois or arxiv_id)
    if lookup:
        session = None
        try:
            import requests
            session = requests.Session()            # one connection pool for every lookup below
        except Exception as exc:
            errors.append(f"requests: {exc}")
        if session is not None:
            try:
                if dois:
                    meta = _crossref_for_paper(dois, first_pages_text, session, errors)
                if meta is None and arxiv_id:
                    meta = arxiv_lookup(arxiv_id, session=session, errors=errors)
                    if meta:
                        log.info("  metadata: arXiv (%s)", arxiv_id)
                        if errors:                  # e.g. a DataCite DOI CrossRef does not know
                            log.debug("  metadata: %s", "; ".join(errors))
            finally:
                session.close()
    if meta is None:
        meta = heur
        if lookup:
            log.warning("  metadata: online lookup failed (%s) - using page-1 heuristics",
                        "; ".join(errors) or "no record")
        else:
            log.info("  metadata: heuristics%s", "" if online else " (offline)")
    else:
        meta.merge_missing(heur)
    if doi and not meta.doi:
        meta.doi = doi
    if arxiv_id and not meta.arxiv:
        meta.arxiv = arxiv_id
    if meta.doi and not meta.url:
        meta.url = f"https://doi.org/{meta.doi}"

    # manual overrides
    if title:
        meta.title = title
    if year:
        meta.year = int(year)
    if author:
        meta.first_author = author
        if not meta.authors:
            meta.authors = [author]
    if title or year or author:
        meta.source = (meta.source + "+override").strip("+")
    if not meta.first_author and meta.authors:
        meta.first_author = surname(meta.authors[0])
    return _normalize_meta(meta)
