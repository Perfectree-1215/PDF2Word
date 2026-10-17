"""Math drawn as vector graphics (manuals): glyph clustering, inline vs display classification,
OCR plausibility; printed page numbers; sub-chapter splitting. No OCR model needed.

Run:  python -m pytest tests -q      (or)      python tests/test_vectormath.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf2word.outline import PageNumbers, parse_pages, read_outline, split_children  # noqa: E402
from pdf2word.vectormath import (classify, cluster, doubtful_equation, find_math, inline_latex_ok,  # noqa: E402
                                 page_atoms, text_rows)

W, H = 500, 700


def _glyph(page, x, y, w=5, h=8):
    """A tiny filled rectangle standing in for one glyph outline."""
    page.draw_rect(pymupdf.Rect(x, y, x + w, y + h), color=(0, 0, 0), fill=(0, 0, 0), width=0)


def _manual_page():
    """One text row with a drawn symbol in a gap, one drawn display equation with a '(5.1)'
    label at the right margin, a horizontal rule, and a figure area full of line art."""
    doc = pymupdf.open()
    page = doc.new_page(width=W, height=H)
    page.insert_text((50, 100), "where", fontsize=11)             # ... symbol gap ...
    page.insert_text((110, 100), "is the solid angle of the ray", fontsize=11)
    for x in (84, 90):                                              # symbol: two glyph outlines
        _glyph(page, x, 91)
    for x in range(200, 300, 7):                                    # display equation glyphs
        _glyph(page, x, 150, 5, 10)
    page.insert_text((450, 158), "(5.1)", fontsize=11)              # its number
    page.draw_line((50, 40), (450, 40), width=0.5)                  # header rule: ignored
    for k in range(20):                                             # figure line art: ignored
        page.draw_line((60 + 10 * k, 400), (65 + 10 * k, 480), width=0.5)
    page.insert_text((50, 520), "plain text with nothing drawn", fontsize=11)
    boxes = [
        {"class": "text", "bbox": (50, 88, 450, 104), "pos": (0, 10)},
        {"class": "picture", "bbox": (50, 390, 300, 490), "pos": (10, 12)},
        {"class": "text", "bbox": (50, 508, 450, 524), "pos": (12, 20)},
    ]
    return doc, page, boxes


def test_cluster_and_atoms():
    rects = [pymupdf.Rect(0, 0, 5, 8), pymupdf.Rect(6, 0, 11, 8), pymupdf.Rect(40, 0, 45, 8)]
    merged = cluster(rects, 3, 2)
    assert len(merged) == 2 and merged[0].x1 == 11
    doc, page, boxes = _manual_page()
    atoms = page_atoms(page, boxes)
    xs = sorted(round(a.x0) for a in atoms)
    assert 84 in xs and 200 in xs                                  # symbol and equation found
    assert all(a.width < 150 for a in atoms)                       # rule and figure art excluded
    assert len(atoms) == 2


def test_classify_and_find_math():
    doc, page, boxes = _manual_page()
    atoms = page_atoms(page, boxes)
    inline, display = classify(atoms, text_rows(page))
    assert len(inline) == 1 and round(inline[0].x0) == 84
    assert len(display) == 1 and round(display[0].x0) == 200      # the (5.1) label row does not count
    inline2, eqs = find_math(page, boxes)
    assert len(inline2) == 1 and len(eqs) == 1
    assert eqs[0].width > 90


def test_inline_latex_plausibility():
    tiny = pymupdf.Rect(0, 0, 9, 10)
    assert inline_latex_ok(r"\Omega", tiny)
    assert inline_latex_ok(r"T_{w}", tiny)
    assert inline_latex_ok(r"\vec{s}", tiny)
    assert inline_latex_ok(r"q_{in}", pymupdf.Rect(0, 0, 14, 10))
    assert not inline_latex_ok(r"{\mathcal Q}", tiny)
    assert not inline_latex_ok(r"\overline{{\S}}", tiny)
    assert not inline_latex_ok(r"D \quad /", tiny)
    assert not inline_latex_ok(r"\textstyle{\mathcal{f}}", tiny)
    assert not inline_latex_ok("", tiny)
    wide = pymupdf.Rect(0, 0, 80, 12)
    assert inline_latex_ok(r"\alpha + \beta_{1} x", wide)
    assert doubtful_equation(r"q_{in}=\bigoplus_{\vec{s}} l_{in} d\Omega")       # misread integral
    assert doubtful_equation(r"Q_{out}=(1-{\mathcal{E}}_{w})Q_{in}")
    assert not doubtful_equation(r"q_{out}=(1-\varepsilon_{w})q_{in}+\varepsilon_{w}\sigma T_{w}^{4}")


def _labelled_doc():
    doc = pymupdf.open()
    for i in range(8):
        page = doc.new_page(width=W, height=H)
        page.insert_text((50, 300), f"content of pdf page {i + 1}", fontsize=11)
    doc.set_page_labels([{"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},
                         {"startpage": 3, "prefix": "", "style": "D", "firstpagenum": 1}])
    return doc


def test_page_labels_and_parse_pages():
    doc = _labelled_doc()
    nums = PageNumbers(doc)
    assert nums.source == "labels"
    assert [nums.label(i) for i in range(5)] == ["i", "ii", "iii", "1", "2"]
    assert nums.describe(3, 4) == "p. 1-2 (PDF 4-5)"
    assert nums.describe(0, 0) == "p. i (PDF 1)"
    assert nums.printed_range(3, 7) == "1-5"
    assert nums.index_of("2") == 4 and nums.index_of("ii") == 1 and nums.index_of("99") is None
    assert parse_pages("p2-3", doc, nums) == [4, 5]
    assert parse_pages("1,p2", doc, nums) == [0, 4]
    assert parse_pages("2-3", doc, nums) == [1, 2]                 # plain = PDF order
    try:
        parse_pages("p77", doc, nums)
    except ValueError:
        pass
    else:
        raise AssertionError("unknown printed page must fail")


def test_printed_number_guess():
    doc = pymupdf.open()
    for i in range(12):
        page = doc.new_page(width=W, height=H)
        page.insert_text((50, 300), "body text", fontsize=11)
        if i >= 2:                                                  # printed numbers start at 11
            page.insert_text((240, 680), str(i + 1 + 10), fontsize=9)
    nums = PageNumbers(doc)
    assert nums.source == "printed" and nums.offset == 10
    assert nums.label(5) == "16" and nums.describe(5, 6) == "p. 16-17 (PDF 6-7)"
    plain = pymupdf.open()
    for _ in range(5):
        plain.new_page()
    assert PageNumbers(plain).source == "none" and PageNumbers(plain).describe(1, 2) == "PDF 2-3"


def test_split_children():
    from tests.test_outline import _book
    doc = _book()
    c1, c2, c3 = read_outline(doc)
    assert split_children(doc, c3) == [c3]                          # no sub-entries: unchanged
    parts = split_children(doc, c2)
    assert [p.title for p in parts] == ["Chapter 2 Beta", "2.1 Gamma section"]
    intro = parts[0]
    assert (intro.page_from, intro.page_to) == (3, 4) and intro.end_hint[0] == "2.1 Gamma section"
    assert intro.num_str == c2.num_str and intro.id == c2.id


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
