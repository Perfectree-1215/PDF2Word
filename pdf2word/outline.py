"""Bookmarks (the PDF outline) -> chapter tree with page ranges, chapter sub-documents cut at
the bookmark positions, fixed-size page groups, and the selection syntax of the command line.

A *part* is one piece of a document that becomes its own output file: a chapter chosen from the
bookmarks, or a group of N pages when the PDF has no bookmarks.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

import pymupdf

from .utils import log, safe_name

TOP_FRACTION = 0.12          # a start position this close to the page top means "starts the page"
HEADING_WINDOW = 240.0       # pt below the bookmark position in which the heading text is searched
_NORM_RE = re.compile(r"[^0-9a-z가-힣぀-ヿ一-鿿]+")


@dataclass
class Part:
    title: str
    page_from: int                      # 0-based, inclusive
    page_to: int                        # 0-based, inclusive
    num: int = 1                        # ordinal used in file names (document-wide, per level)
    width: int = 2                      # zero padding of num
    id: str = ""                        # position in the outline tree: "3", "3.2" ("" for page groups)
    level: int = 1                      # depth in the tree (1 = top)
    kind: str = "chapter"               # "chapter" | "pages"
    y_hint: Optional[float] = None      # bookmark position on page_from (top-left y), None = unknown
    end_hint: Optional[tuple] = None    # (title, y) of the entry that starts on page_to, None = page end
    children: list = field(default_factory=list)

    # ---- derived ---------------------------------------------------------------
    @property
    def num_str(self) -> str:
        return f"{self.num:0{self.width}d}"

    @property
    def page_count(self) -> int:
        return self.page_to - self.page_from + 1

    @property
    def pages_label(self) -> str:
        return f"{self.page_from + 1}-{self.page_to + 1}" if self.page_to > self.page_from else str(self.page_from + 1)

    def fields(self, stem: str, page_count: int) -> dict:
        """Template fields for file names: {stem} {num} {title} {id} {p0} {p1}."""
        w = len(str(page_count))
        return dict(stem=stem, num=self.num_str, title=title_for_name(self.title), id=self.id,
                    p0=f"{self.page_from + 1:0{w}d}", p1=f"{self.page_to + 1:0{w}d}")

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


def title_for_name(title: str, maxlen: int = 60) -> str:
    """'1.2. Program Capabilities' -> '1.2-Program-Capabilities'; long titles are cut at a word
    boundary, never in the middle of a word."""
    title = re.sub(r"^(\d+(?:\.\d+)*)\.(?=\s)", r"\1", (title or "").strip())   # '1.2.' -> '1.2'
    name = safe_name(title, maxlen + 40)
    if len(name) > maxlen:
        cut = name.rfind("-", 0, maxlen + 1)
        name = name[:cut] if cut >= maxlen // 2 else name[:maxlen]
    return name.rstrip("-.") or "untitled"


# ----------------------------------------------------------------------------- outline -> tree

def _clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").replace("\x00", "")).strip() or "untitled"


def _page_height(doc, pno: int) -> float:
    try:
        return float(doc.page_cropbox(pno).height)
    except Exception:
        return float(doc[pno].rect.height)


def _outline_entries(doc) -> list:
    """[(level, title, page0, y_top)] in document order. Walks the raw outline objects: that
    is ~200x faster than get_toc(simple=False) on big manuals (no named-destination lookups
    per item) and their x/y are already page (top-left) coordinates."""
    entries: list = []
    try:
        ol = doc.outline
    except Exception as exc:
        log.debug("outline unavailable: %s", exc)
        ol = None
    if ol is not None:
        stack = [(ol, 1)]
        while stack:
            item, lvl = stack.pop()
            while item:
                try:
                    page = int(item.page)
                    y = float(item.y) if item.y is not None else None
                    if 0 <= page < doc.page_count:
                        entries.append((lvl, _clean_title(item.title), page, y if y and y > 0 else None))
                    down = item.down
                except Exception:
                    down = None
                if down:
                    # children must come right after their parent, before the next sibling
                    stack.append((item.next, lvl))
                    item, lvl = down, lvl + 1
                    continue
                item = item.next
        return entries
    try:                                               # fallback: page numbers only
        for item in doc.get_toc(simple=True):
            lvl, title, page = int(item[0]), item[1], int(item[2])
            if 1 <= page <= doc.page_count:
                entries.append((max(1, lvl), _clean_title(title), page - 1, None))
    except Exception as exc:
        log.debug("outline unavailable: %s", exc)
    return entries


def read_outline(doc) -> list:
    """The bookmark tree as a list of top-level Parts (children nested). Empty if none."""
    entries = _outline_entries(doc)
    if not entries:
        return []

    roots: list = []
    stack: list = []                     # (raw level, node)
    for lvl, title, pno, y in entries:
        node = Part(title=title, page_from=pno, page_to=pno, y_hint=y)
        while stack and stack[-1][0] >= lvl:
            stack.pop()
        if stack:
            stack[-1][1].children.append(node)
        else:
            roots.append(node)
        stack.append((lvl, node))

    order: list = []                     # document order with tree depth

    def visit(nodes, prefix, depth):
        for i, node in enumerate(nodes, 1):
            node.id = f"{prefix}{i}"
            node.level = depth
            order.append(node)
            visit(node.children, node.id + ".", depth + 1)

    visit(roots, "", 1)

    # ordinals: position among all entries of the same depth, zero-padded to that count
    per_level = Counter(n.level for n in order)
    seen: Counter = Counter()
    for node in order:
        seen[node.level] += 1
        node.num = seen[node.level]
        node.width = max(2, len(str(per_level[node.level])))

    # page ranges: up to the next entry that is not deeper than this one
    for i, node in enumerate(order):
        nxt = next((m for m in order[i + 1:] if m.level <= node.level), None)
        if nxt is None:
            node.page_to = doc.page_count - 1
            continue
        if nxt.page_from <= node.page_from:
            node.page_to = node.page_from
            node.end_hint = (nxt.title, nxt.y_hint) if nxt.page_from == node.page_from and nxt.y_hint else None
            continue
        if _starts_at_top(doc, nxt):
            node.page_to = nxt.page_from - 1
        else:                            # the next chapter begins mid-page: that page is shared
            node.page_to = nxt.page_from
            node.end_hint = (nxt.title, nxt.y_hint)
    return roots


def _starts_at_top(doc, node: Part) -> bool:
    if node.y_hint is None:
        return True
    return node.y_hint <= TOP_FRACTION * _page_height(doc, node.page_from)


def flatten(tree: list) -> list:
    out = []
    for node in tree:
        out.extend(node.walk())
    return out


# ----------------------------------------------------------------------------- listing / selection

def format_tree(tree: list, depth: int = 2, numbers=None) -> str:
    """Listing for --list-chapters; with `numbers` (PageNumbers) the printed page numbers are
    shown first and the PDF page order second."""
    show_printed = numbers is not None and getattr(numbers, "source", "none") != "none"
    rows = []
    for node in flatten(tree):
        if node.level > depth:
            continue
        hidden = len(list(node.walk())) - 1 if node.level == depth else 0
        indent = "  " * (node.level - 1)
        more = f"  [+{hidden} below]" if hidden else ""
        if show_printed:
            printed = numbers.printed_range(node.page_from, node.page_to) or "-"
            rows.append(f"{node.id:>9}  {printed:>11}  {node.pages_label:>11}  {indent}{node.title}"
                        f"  ({node.page_count} p){more}")
        else:
            rows.append(f"{node.id:>9}  {node.pages_label:>11}  {indent}{node.title}  ({node.page_count} p){more}")
    head = (f"{'id':>9}  {'printed':>11}  {'PDF pages':>11}  title" if show_printed
            else f"{'id':>9}  {'pages':>11}  title")
    return "\n".join([head] + rows)


def select_parts(tree: list, spec: str) -> list:
    """'3,4.2,5.1-5.4', 'all' (top level), 'all:2' (every entry of depth 2) -> parts in document order."""
    nodes = flatten(tree)
    by_id = {n.id: n for n in nodes}
    wanted: list = []
    for token in re.split(r"[,\s]+", (spec or "").strip()):
        if not token:
            continue
        m = re.fullmatch(r"all(?::(\d+))?", token, re.I)
        if m:
            depth = int(m.group(1) or 1)
            wanted += [n for n in nodes if n.level == depth]
            continue
        m = re.fullmatch(r"([\d.]+)-([\d.]+)", token)
        if m:
            a, b = m.group(1), m.group(2)
            pa, pb = a.rsplit(".", 1), b.rsplit(".", 1)
            if len(pa) != len(pb) or (len(pa) == 2 and pa[0] != pb[0]):
                raise ValueError(f"chapter range must stay within one parent: {token}")
            prefix = (pa[0] + ".") if len(pa) == 2 else ""
            lo, hi = int(pa[-1]), int(pb[-1])
            for i in range(lo, hi + 1):
                node = by_id.get(f"{prefix}{i}")
                if node is None:
                    raise ValueError(f"unknown chapter id: {prefix}{i}")
                wanted.append(node)
            continue
        node = by_id.get(token)
        if node is None:
            raise ValueError(f"unknown chapter id: {token} (use --list-chapters)")
        wanted.append(node)
    order = {id(n): i for i, n in enumerate(nodes)}
    uniq = {id(n): n for n in wanted}
    return sorted(uniq.values(), key=lambda n: order[id(n)])


def split_children(doc, part: Part) -> list:
    """One entry -> its direct sub-entries, each as a part of its own. Text between the entry's
    heading and its first sub-entry (the chapter introduction) becomes a small part of its own,
    titled like the entry; an entry without sub-entries is returned unchanged."""
    if not part.children:
        return [part]
    first = part.children[0]
    out = []
    intro = Part(title=part.title, page_from=part.page_from, page_to=part.page_from, num=part.num,
                 width=part.width, id=part.id, level=part.level, kind="chapter", y_hint=part.y_hint)
    if first.page_from > part.page_from:
        if _starts_at_top(doc, first):
            intro.page_to = first.page_from - 1
        else:
            intro.page_to = first.page_from
            intro.end_hint = (first.title, first.y_hint)
        out.append(intro)
    elif first.y_hint is not None and (part.y_hint or 0.0) + 60 < first.y_hint:
        intro.end_hint = (first.title, first.y_hint)       # same page, some text in between
        out.append(intro)
    out += list(part.children)
    return out


class PageNumbers:
    """Printed page numbers: the PDF's page labels when it has them ('xii', '201'), else a
    constant offset guessed from numbers printed in the headers/footers, else nothing."""

    def __init__(self, doc):
        self.doc = doc
        self.count = doc.page_count
        self._cache: dict = {}
        self.source = "none"
        self.offset = 0
        try:
            self.has_labels = bool(doc.get_page_labels())
        except Exception:
            self.has_labels = False
        if self.has_labels:
            self.source = "labels"
        else:
            self.offset = self._guess_offset()
            if self.offset is not None:
                self.source = "printed"
        self._index: Optional[dict] = None

    # ---- lookup ---------------------------------------------------------------
    def label(self, pno: int) -> str:
        """Printed number of a 0-based page; '' when unknown."""
        if pno in self._cache:
            return self._cache[pno]
        value = ""
        if self.source == "labels":
            try:
                value = (self.doc[pno].get_label() or "").strip()
            except Exception:
                value = ""
        elif self.source == "printed":
            n = pno + 1 + (self.offset or 0)
            value = str(n) if n >= 1 else ""
        self._cache[pno] = value
        return value

    def describe(self, page_from: int, page_to: int) -> str:
        """'p. 201-205 (PDF 249-253)', 'p. 6-10' when printed == PDF numbering, 'PDF 249-253' without."""
        pdf = f"{page_from + 1}-{page_to + 1}" if page_to > page_from else str(page_from + 1)
        a, b = self.label(page_from), self.label(page_to)
        if not a or not b:
            return f"PDF {pdf}"
        printed = f"{a}-{b}" if page_to > page_from else a
        if printed == pdf:
            return f"p. {printed}"
        return f"p. {printed} (PDF {pdf})"

    def printed_range(self, page_from: int, page_to: int) -> str:
        a, b = self.label(page_from), self.label(page_to)
        if not a or not b:
            return ""
        return f"{a}-{b}" if page_to > page_from else a

    def index_of(self, printed: str) -> Optional[int]:
        """0-based page of a printed number ('201', 'xii'); the first page carrying it."""
        if self._index is None:
            self._index = {}
            for pno in range(self.count):
                lab = self.label(pno)
                if lab and lab not in self._index:
                    self._index[lab] = pno
        return self._index.get(printed.strip().lower()) if printed else None

    # ---- heuristics --------------------------------------------------------------
    def _guess_offset(self) -> Optional[int]:
        n = self.count
        if n < 3:
            return None
        sample = sorted({int(round(n * k / 12)) for k in range(1, 12)} | {2, n - 2})
        offsets: Counter = Counter()
        seen = 0
        for pno in sample:
            if not 0 <= pno < n:
                continue
            printed = self._edge_number(self.doc[pno])
            if printed is None:
                continue
            seen += 1
            offsets[printed - (pno + 1)] += 1
        if seen < 3 or not offsets:
            return None
        offset, votes = offsets.most_common(1)[0]
        return offset if votes >= max(3, 0.6 * seen) else None

    @staticmethod
    def _edge_number(page) -> Optional[int]:
        """A page number printed in the header/footer band ('201', '6 of 23', 'Page 12')."""
        try:
            lines = _text_lines(page)
        except Exception:
            return None
        h = page.rect.height
        for y0, y1, text in lines:
            if not (y1 < 0.09 * h or y0 > 0.9 * h):
                continue
            t = text.strip()
            m = re.fullmatch(r"(?:page\s*)?(\d{1,4})(?:\s*(?:of|/)\s*\d{1,4})?", t, re.I) or \
                re.fullmatch(r"[-–—]\s*(\d{1,4})\s*[-–—]", t)
            if m:
                return int(m.group(1))
        return None


def parse_pages(spec: Optional[str], doc, numbers: Optional[PageNumbers] = None) -> Optional[list]:
    """'1-5,8' (PDF order, 1-based) and 'p201-205' / 'pxii' (printed numbers) -> 0-based pages."""
    from .utils import parse_page_range
    if not spec:
        return None
    plain, pages = [], []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        m = re.fullmatch(r"p\s*([A-Za-z0-9]+)(?:\s*-\s*p?\s*([A-Za-z0-9]+))?", token, re.I)
        if not m:
            plain.append(token)
            continue
        numbers = numbers or PageNumbers(doc)
        a = numbers.index_of(m.group(1))
        b = numbers.index_of(m.group(2)) if m.group(2) else a
        if a is None or b is None:
            raise ValueError(f"printed page not found: {token}")
        pages += [p for p in range(min(a, b), max(a, b) + 1) if p not in pages]
    if plain:
        pages += [p for p in (parse_page_range(",".join(plain), doc.page_count) or []) if p not in pages]
    return sorted(pages) or None


def page_groups(page_count: int, size: int) -> list:
    """Fixed-size page groups for PDFs without bookmarks: 'p0001-0050', 'p0051-0100', ..."""
    size = max(1, int(size))
    groups = []
    n_groups = (page_count + size - 1) // size
    w = len(str(page_count))
    for i in range(n_groups):
        a, b = i * size, min(page_count, (i + 1) * size) - 1
        groups.append(Part(title=f"p{a + 1:0{w}d}-{b + 1:0{w}d}", page_from=a, page_to=b, num=i + 1,
                           width=max(2, len(str(n_groups))), kind="pages"))
    return groups


# ----------------------------------------------------------------------------- cutting

def _norm(s: str) -> str:
    return _NORM_RE.sub("", (s or "").lower())


def _text_lines(page) -> list:
    flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    lines = []
    try:
        blocks = page.get_text("dict", flags=flags)["blocks"]
    except Exception:
        return lines
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            text = "".join(s["text"] for s in line["spans"]).strip()
            if text:
                lines.append((line["bbox"][1], line["bbox"][3], text))
    lines.sort()
    return lines


def find_heading_y(page, title: str, hint_y: Optional[float]) -> Optional[float]:
    """Top of the text line that shows `title`, searched a little above and well below the
    bookmark position (generators often point slightly above the heading)."""
    key = _norm(title)
    if len(key) < 3:
        return None
    best = None
    for y0, y1, text in _text_lines(page):
        if hint_y is not None and (y0 < hint_y - 12 or y0 > hint_y + HEADING_WINDOW):
            continue
        t = _norm(text)
        if not t:
            continue
        if t.startswith(key[:24]) or (len(t) >= 6 and key.startswith(t)):
            if best is None or y0 < best:
                best = y0
    return best


def start_y(doc, part: Part) -> Optional[float]:
    """Where the part begins on its first page (top-left y), None when it owns the whole page."""
    if part.y_hint is None:
        return None
    page = doc[part.page_from]
    if part.y_hint <= TOP_FRACTION * page.rect.height:
        return None
    y = find_heading_y(page, part.title, part.y_hint)
    return max(0.0, (y if y is not None else part.y_hint) - 2)


def end_y(doc, part: Part) -> Optional[float]:
    """Where the next entry begins on the part's last page, None when the page is all ours."""
    if not part.end_hint:
        return None
    title, hint = part.end_hint
    page = doc[part.page_to]
    y = find_heading_y(page, title, hint)
    y = (y if y is not None else hint)
    if y is None or y <= TOP_FRACTION * page.rect.height:
        return None
    return max(0.0, y - 2)


def _redact(page, rect: pymupdf.Rect) -> None:
    rect = rect & page.rect
    if rect.is_empty or rect.height < 2:
        return
    page.add_redact_annot(rect)
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                          graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED)


def part_document(doc, part: Part, cut: str = "exact") -> pymupdf.Document:
    """A new document holding only the part's pages; with cut='exact' the text of neighbouring
    chapters on the first/last page is removed (redacted) at the bookmark positions."""
    sub = pymupdf.open()
    sub.insert_pdf(doc, from_page=part.page_from, to_page=part.page_to)
    if cut != "exact" or part.kind != "chapter":
        return sub
    y0 = start_y(doc, part)
    y1 = end_y(doc, part)
    if y0 is not None:
        first = sub[0]
        _redact(first, pymupdf.Rect(0, 0, first.rect.width, y0))
    if y1 is not None:
        last = sub[sub.page_count - 1]
        _redact(last, pymupdf.Rect(0, y1, last.rect.width, last.rect.height))
    if y0 is not None or y1 is not None:
        log.debug("  cut: start y=%s on p%d, end y=%s on p%d", y0, part.page_from + 1, y1, part.page_to + 1)
    return sub
