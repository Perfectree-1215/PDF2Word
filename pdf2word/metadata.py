"""Paper metadata: DOI/arXiv detection, CrossRef & arXiv lookup, first-page heuristics."""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

import pymupdf
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Optional
from urllib.parse import quote

log = logging.getLogger("pdf2word")

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>)\]]+)", re.I)
ARXIV_RE = re.compile(r"arXiv:\s*(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
_USER_AGENT = "pdf2word/0.1 (https://github.com/pdf2word)"
_BAD_TITLES = re.compile(r"^(untitled|microsoft word.*|doc\d*|\d[\w-]*|.*\.(docx?|tex|pdf|indd))$|^\s*$", re.I)
_BAD_AUTHORS = re.compile(r"^(user|admin|administrator|owner|author|confit|unknown|windows|\s*)$", re.I)
_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "phd", "md", "dr"}
_PARTICLES = {"van", "von", "de", "der", "den", "del", "della", "di", "da", "le", "la", "du",
              "dos", "das", "do", "al", "bin", "ibn", "mac", "ten", "ter", "el"}
_AFFILIATION_RE = re.compile(
    r"(university|institute|department|school|laboratory|@|received|abstract|college|faculty|"
    r"center|centre|academy|corporation|ltd|inc\b|co\.,|research|division|hospital)", re.I)


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
    source: str = ""                # crossref | arxiv | heuristic (+override)

    def as_dict(self) -> dict:
        return asdict(self)

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
    doi = doi.strip().rstrip(".,;:)]}>\"'")
    # DOIs glued to the following word in extracted text, e.g. 10.1000/abc.Received
    doi = re.sub(r"\.(Received|Accepted|Published|Available|Copyright|Keywords?|Abstract)$", "", doi, flags=re.I)
    return doi


def find_doi(text: str) -> str:
    """First DOI of the text; one announced as 'doi:' / 'doi.org/' is preferred."""
    m = re.search(r"(?:doi\.org/|doi:\s*|\bDOI\b\s*:?\s*)(10\.\d{4,9}/[^\s\"'<>)\]]+)", text, re.I)
    if m:
        return clean_doi(m.group(1))
    m = DOI_RE.search(text)
    return clean_doi(m.group(1)) if m else ""


def find_arxiv(text: str) -> str:
    m = ARXIV_RE.search(text) or ARXIV_URL_RE.search(text)
    return m.group(1) if m else ""


# ----------------------------------------------------------------------------- names

def clean_author(name: str) -> str:
    name = re.sub(r"[\*†‡§¶#∗✉✝\d]+", "", name)          # affiliation markers
    name = re.sub(r"\s+", " ", name).strip(" ,;")
    return name


def surname(name: str) -> str:
    """'Kwang Hee Kim' -> 'Kim', 'Weers, M.' -> 'Weers', 'Ludwig van Beethoven' -> 'van Beethoven'."""
    name = clean_author(name)
    if not name:
        return ""
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
    line = re.sub(r"\b(and|&)\b", ",", line, flags=re.I)
    parts = [clean_author(p) for p in re.split(r"[,;]", line)]
    return [p for p in parts
            if p and len(p) > 1 and re.search(r"[A-Za-zÀ-ɏ가-힣一-鿿]", p)]


# ----------------------------------------------------------------------------- online lookups

def crossref_lookup(doi: str, timeout: float = 10.0) -> Optional[PaperMeta]:
    try:
        import requests
        r = requests.get(f"https://api.crossref.org/works/{quote(doi, safe='')}",
                         headers={"User-Agent": _USER_AGENT}, timeout=timeout)
        if r.status_code != 200:
            log.debug("CrossRef %s -> HTTP %s", doi, r.status_code)
            return None
        m = r.json().get("message", {})
    except Exception as exc:  # network errors, bad JSON ...
        log.debug("CrossRef lookup failed: %s", exc)
        return None

    meta = PaperMeta(source="crossref")
    titles = m.get("title") or []
    meta.title = " ".join(titles[0].split()) if titles else ""
    for a in m.get("author", []) or []:
        if a.get("family"):
            meta.authors.append(clean_author(f"{a.get('given', '')} {a['family']}"))
        elif a.get("name"):
            meta.authors.append(clean_author(a["name"]))
    for key in ("published-print", "published-online", "issued", "created"):
        parts = (m.get(key) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            meta.year = int(parts[0][0])
            break
    ct = m.get("container-title") or []
    meta.journal = ct[0] if ct else ""
    meta.volume = str(m.get("volume") or "")
    meta.issue = str(m.get("issue") or "")
    meta.pages = str(m.get("page") or "")
    meta.doi = m.get("DOI") or doi
    meta.url = m.get("URL") or f"https://doi.org/{meta.doi}"
    if meta.authors:
        meta.first_author = surname(meta.authors[0])
    return meta


def arxiv_lookup(arxiv_id: str, timeout: float = 10.0) -> Optional[PaperMeta]:
    try:
        import requests
        r = requests.get("https://export.arxiv.org/api/query", params={"id_list": arxiv_id},
                         headers={"User-Agent": _USER_AGENT}, timeout=timeout)
        if r.status_code != 200:
            return None
        root = ET.fromstring(r.text)
    except Exception as exc:
        log.debug("arXiv lookup failed: %s", exc)
        return None
    ns = {"a": "http://www.w3.org/2005/Atom", "ar": "http://arxiv.org/schemas/atom"}
    entry = root.find("a:entry", ns)
    if entry is None:
        return None
    title = " ".join((entry.findtext("a:title", default="", namespaces=ns) or "").split())
    if not title or title == "Error":
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
    """[(size, y0, text, bbox)] for every text line of the page, in extraction order."""
    lines = []
    flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    for block in page.get_text("dict", flags=flags)["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            size = max(s["size"] for s in spans)
            text = "".join(s["text"] for s in spans).strip()
            lines.append((round(size, 1), line["bbox"][1], text, line["bbox"]))
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
        size_chars: Counter = Counter()
        for size, y0, text, _ in lines:
            if y0 < page_h * 0.6:
                size_chars[size] += len(text)
        candidates = sorted((s for s, n in size_chars.items() if n >= 12), reverse=True)
        if candidates:
            big = candidates[0]
            title_lines = sorted(((y0, text, bbox) for size, y0, text, bbox in lines
                                  if size == big and y0 < page_h * 0.6
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
        below = [(y0, text) for size, y0, text, bbox in lines if bottom - 2 < y0 < bottom + 90]
        for _, text in sorted(below):
            bare = re.sub(r"[(（].*?[)）]", "", text)       # affiliations in parentheses are fine
            if _AFFILIATION_RE.search(bare):
                break
            names = split_author_line(text)
            if names and all(len(n.split()) <= 5 for n in names):
                meta.authors.extend(names)
            if len(meta.authors) >= 2 and not text.rstrip().endswith(","):
                break
    if meta.authors:
        meta.first_author = surname(meta.authors[0])

    # --- year
    head = first_pages_text[:6000]
    m = re.search(r"(?:©|\(c\)|copyright|published|accepted|received|available online|revised)"
                  r"[^\n]{0,60}?(19[5-9]\d|20[0-4]\d)", head, re.I)
    if m:
        meta.year = int(m.group(1))
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
        chunk = m.group(1)
        if chunk.startswith("\n"):                   # nothing on the 'Keywords:' line itself
            chunk = chunk.lstrip("\n").split("\n", 1)[0]
        cut = re.search(r"\n\s*\n|\n\s*\d+\.?\s+[A-Z]|\bIntroduction\b|\n\s*1\s*\n", chunk)
        if cut:
            chunk = chunk[:cut.start()]
        kw = re.split(r"[;,·•]\s*|\s{2,}", chunk.replace("\n", " "))
        meta.keywords = [k.strip(" .") for k in kw
                         if 2 < len(k.strip()) < 60 and len(k.split()) <= 6
                         and not re.search(r"[\[\]©@]|https?:|^\d+$|\d{1,2}:\d{2}|\bauthors?\b", k, re.I)][:12]
    return _normalize_meta(meta)


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


# ----------------------------------------------------------------------------- orchestration

def resolve_metadata(doc, first_pages_text: str, *, online: bool = True,
                     author: Optional[str] = None, year: Optional[int] = None,
                     title: Optional[str] = None) -> PaperMeta:
    heur = heuristic_meta(doc, first_pages_text)
    doi = find_doi(first_pages_text)
    arxiv_id = find_arxiv(first_pages_text)
    meta: Optional[PaperMeta] = None
    if online and doi:
        meta = crossref_lookup(doi)
        if meta:
            log.info("  metadata: CrossRef (%s)", doi)
    if meta is None and online and arxiv_id:
        meta = arxiv_lookup(arxiv_id)
        if meta:
            log.info("  metadata: arXiv (%s)", arxiv_id)
    if meta is None:
        meta = heur
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
