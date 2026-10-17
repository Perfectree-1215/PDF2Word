"""Math that is not in the text layer: equations and symbols drawn as vector paths (manuals
produced from DocBook / FrameMaker / MathML renderers) or as small loose images.

Glyph outlines are clustered into *atoms* (one symbol or term each). An atom that sits inside a
text row is an inline symbol (OCR -> $...$, or a small image when the OCR looks doubtful); the
others are grouped into display equations that the layout model did not see.
"""
from __future__ import annotations

import re
from typing import Optional

import pymupdf

from .mathocr import LABEL_RE, TEXT_FLAGS
from .utils import log

MAX_PATHS = 2500                 # pages with more vector paths (dense plots) are skipped
GLYPH_GAP = (3.0, 2.0)           # pt: outlines closer than this form one symbol / term
EQUATION_GAP = (14.0, 7.0)       # pt: terms closer than this form one display equation
ROW_REACH = 40.0                 # pt: an atom this close to a text line (horizontally) is inline
SKIP_CLASSES = ("picture", "table", "formula", "page-header", "page-footer")
_DOUBTFUL = re.compile(r"\\(mathcal|mathscr|mathfrak|S\b|boldmath|textstyle|scriptstyle|quad|qquad|stackrel|"
                       r"xrightarrow|xleftarrow|underline|overline\{\{|operatorname\{\s*\}|mathrm\{\s*\})|\{\s*\}|"
                       r"\\[,;!:]|\\ |\\\\|&")
_SIMPLE = re.compile(r"(?:\\(?:vec|hat|bar|dot|ddot|tilde|mathbf|boldsymbol)\{[A-Za-z]\}|\\[A-Za-z]+|[A-Za-z])"
                     r"(?:_\{[^{}]{1,10}\}|_[A-Za-z0-9])?(?:\^\{[^{}]{1,6}\}|\^[A-Za-z0-9])?"
                     r"(?:_\{[^{}]{1,10}\}|_[A-Za-z0-9])?")


# ----------------------------------------------------------------------------- geometry

def cluster(rects, gx: float, gy: float) -> list:
    """Union-find over rects whose gap-expanded boxes touch; a sweep over x keeps it fast."""
    items = sorted((pymupdf.Rect(r) for r in rects), key=lambda r: r.x0)
    n = len(items)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        a = items[i]
        for j in range(i + 1, n):
            b = items[j]
            if b.x0 > a.x1 + gx:
                break
            if a.y0 - gy <= b.y1 and b.y0 - gy <= a.y1:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
    groups: dict = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(items[i])
    out = []
    for members in groups.values():
        u = pymupdf.Rect(members[0])
        for r in members[1:]:
            u |= r
        out.append(u)
    return sorted(out, key=lambda r: (round(r.y0), r.x0))


def _covered(r: pymupdf.Rect, s: pymupdf.Rect, frac: float = 0.5) -> bool:
    inter = r & s
    return (not inter.is_empty) and inter.get_area() >= frac * max(r.get_area(), 1e-6)


def page_atoms(page, boxes: list, images=(), use_vector: bool = True) -> list:
    """Rects of glyph clusters (vector paths) and loose small images outside figures/tables."""
    pr = page.rect
    skip = [pymupdf.Rect(b["bbox"]) for b in boxes if b.get("class") in SKIP_CLASSES]
    all_boxes = [pymupdf.Rect(b["bbox"]) for b in boxes]
    rects = []
    if use_vector:
        try:
            paths = page.get_drawings()
        except Exception as exc:
            log.debug("get_drawings failed: %s", exc)
            paths = []
        if len(paths) > MAX_PATHS:
            log.debug("page %d: %d vector paths, vector math skipped", page.number + 1, len(paths))
            paths = []
        for p in paths:
            r = pymupdf.Rect(p["rect"])
            if r.width > 0.45 * pr.width or r.height > 0.5 * pr.height:
                continue                                   # rules, frames, backgrounds
            if r.width > 120 and r.height < 1.5:
                continue                                   # horizontal rules
            if r.width < 0.3 and r.height < 0.3:
                continue
            if r.y1 < 0.04 * pr.height or r.y0 > 0.96 * pr.height:
                continue                                   # header / footer bands
            if any(_covered(r, s) for s in skip):
                continue
            rects.append(r)
    atoms = cluster(rects, *GLYPH_GAP) if rects else []
    for info in images:                                    # small images the layout did not box
        r = pymupdf.Rect(info["bbox"])
        if r.is_empty or r.get_area() > 0.2 * pr.get_area():
            continue
        if any(_covered(r, s) for s in all_boxes):
            continue
        atoms.append(r)
    out = []
    for a in atoms:
        if a.width < 2 or a.height < 2:
            continue
        try:                                               # underlines / strike-throughs sit on text
            words = page.get_text("words", clip=a)
        except Exception:
            words = []
        if any(_covered(a, pymupdf.Rect(w[:4]), 0.4) for w in words):
            continue
        out.append(a)
    return out


# ----------------------------------------------------------------------------- classification

def text_rows(page) -> list:
    """Visual text rows: [{'rect', 'lines': [(Rect, text)], 'height', 'label_only'}]."""
    lines = []
    try:
        blocks = page.get_text("dict", flags=TEXT_FLAGS)["blocks"]
    except Exception:
        return []
    for b in blocks:
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []):
            text = "".join(s["text"] for s in ln["spans"]).strip()
            if text:
                lines.append((pymupdf.Rect(ln["bbox"]), text))
    lines.sort(key=lambda t: (t[0].y0, t[0].x0))
    rows: list = []
    for r, text in lines:
        if rows:
            row = rows[-1]
            rr = row["rect"]
            overlap = min(rr.y1, r.y1) - max(rr.y0, r.y0)
            if overlap >= 0.5 * min(rr.height, r.height):
                row["rect"] = rr | r
                row["lines"].append((r, text))
                continue
        rows.append({"rect": pymupdf.Rect(r), "lines": [(r, text)]})
    for row in rows:
        hs = sorted(lr.height for lr, _ in row["lines"])
        row["height"] = hs[len(hs) // 2]
        row["label_only"] = all(LABEL_RE.match(t) for _, t in row["lines"])
    return rows


def classify(atoms: list, rows: list):
    """-> (inline atoms, display atoms). Inline = inside a text row, next to real text."""
    inline, display = [], []
    for a in atoms:
        cy = (a.y0 + a.y1) / 2
        hit = False
        for row in rows:
            rr = row["rect"]
            if not (rr.y0 - 1 <= cy <= rr.y1 + 1) or row["label_only"]:
                continue
            if a.height > 1.9 * row["height"]:
                continue
            for lr, text in row["lines"]:
                if LABEL_RE.match(text):
                    continue
                if lr.x0 - ROW_REACH <= a.x1 and a.x0 <= lr.x1 + ROW_REACH:
                    hit = True
                    break
            if hit:
                break
        (inline if hit else display).append(a)
    return inline, display


def find_math(page, boxes: list, images=(), use_vector: bool = True):
    """-> (inline symbol rects, display equation rects) drawn as graphics on this page."""
    atoms = page_atoms(page, boxes, images, use_vector)
    if not atoms:
        return [], []
    inline, display = classify(atoms, text_rows(page))
    eqs = cluster(display, *EQUATION_GAP) if display else []
    eqs = [e for e in eqs if e.width >= 8 and e.height >= 6 and not (e.width < 14 and e.height < 14)]
    return inline, eqs


# ----------------------------------------------------------------------------- OCR plausibility

_DOUBTFUL_EQ = re.compile(r"\\(mathcal|mathscr|mathfrak|textstyle|scriptstyle|boldmath|overline\{\{|underline\{\{|S\b"
                          r"|bigoplus|bigotimes|bigodot|biguplus|bigsqcup)|\{\s*\}")   # big operators: misread integrals


def doubtful_equation(latex: Optional[str]) -> bool:
    """Signs that pix2tex misread a display equation it had no text layer to be checked against."""
    return bool(latex) and bool(_DOUBTFUL_EQ.search(latex))


def inline_latex_ok(latex: Optional[str], rect) -> bool:
    """Is this OCR result believable for a symbol of this size? Single glyphs must come back
    as one letter / Greek command with at most a sub- and superscript; anything with
    `\\mathcal`, stray spacing commands or empty groups is treated as garbage."""
    s = (latex or "").strip()
    if not s or _DOUBTFUL.search(s):
        return False
    rect = pymupdf.Rect(rect)
    if rect.width < 1.7 * max(rect.height, 1):          # one glyph, maybe with a subscript
        return bool(_SIMPLE.fullmatch(s))
    return len(s) <= 80
