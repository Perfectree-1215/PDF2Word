"""Bookmark (outline) handling: chapter tree, page ranges, selection syntax, page groups and
the cut of shared pages. Uses a small PDF generated on the fly (no model, no network).

Run:  python -m pytest tests -q      (or)      python tests/test_outline.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf2word.metadata import detect_doc_type  # noqa: E402
from pdf2word.outline import (Part, end_y, find_heading_y, flatten, format_tree, page_groups,  # noqa: E402
                              part_document, read_outline, select_parts, start_y, title_for_name)

W, H = 500, 700


def _book() -> pymupdf.Document:
    """8 pages. Chapter 1 = p1-3 (Chapter 2 starts at the top of p4); Chapter 2 = p4-6 where
    section 2.1 starts mid-page 5 and Chapter 3 starts in the middle of page 6; Chapter 3 = p6-8."""
    doc = pymupdf.open()
    for i in range(8):
        page = doc.new_page(width=W, height=H)
        page.insert_text((50, 40), f"Running header page {i + 1}", fontsize=8)
        for k in range(12):
            page.insert_text((50, 80 + 45 * k), f"Body text line {k + 1} of page {i + 1}", fontsize=11)
    doc[0].insert_text((50, 120), "Chapter 1 Alpha", fontsize=20)
    doc[3].insert_text((50, 60), "Chapter 2 Beta", fontsize=20)
    doc[4].insert_text((50, 300), "2.1 Gamma section", fontsize=14)
    doc[5].insert_text((50, 350), "Chapter 3 Delta", fontsize=20)
    # destinations a little above each heading, as PDF producers usually place them
    # (set_toc takes top-left page coordinates)
    toc = [
        [1, "Chapter 1 Alpha", 1, {"kind": pymupdf.LINK_GOTO, "to": pymupdf.Point(50, 95), "page": 0}],
        [1, "Chapter 2 Beta", 4, {"kind": pymupdf.LINK_GOTO, "to": pymupdf.Point(50, 30), "page": 3}],
        [2, "2.1 Gamma section", 5, {"kind": pymupdf.LINK_GOTO, "to": pymupdf.Point(50, 270), "page": 4}],
        [1, "Chapter 3 Delta", 6, {"kind": pymupdf.LINK_GOTO, "to": pymupdf.Point(50, 300), "page": 5}],
    ]
    doc.set_toc(toc)
    return doc


def test_tree_and_ranges():
    doc = _book()
    tree = read_outline(doc)
    assert [n.title for n in tree] == ["Chapter 1 Alpha", "Chapter 2 Beta", "Chapter 3 Delta"]
    c1, c2, c3 = tree
    assert (c1.page_from, c1.page_to) == (0, 2)          # chapter 2 starts a new page
    assert (c2.page_from, c2.page_to) == (3, 5)          # chapter 3 starts mid-page 6 -> page 6 shared
    assert c2.end_hint and c2.end_hint[0] == "Chapter 3 Delta"
    assert (c3.page_from, c3.page_to) == (5, 7)
    assert c2.children[0].title == "2.1 Gamma section"
    assert c2.children[0].id == "2.1" and c2.children[0].level == 2
    assert [n.id for n in flatten(tree)] == ["1", "2", "2.1", "3"]
    assert [n.num_str for n in tree] == ["01", "02", "03"]
    assert c2.children[0].num_str == "01"
    listing = format_tree(tree, depth=1)
    assert "Chapter 2 Beta" in listing and "2.1 Gamma" not in listing and "[+1 below]" in listing
    assert "2.1 Gamma" in format_tree(tree, depth=2)


def test_selection_syntax():
    tree = read_outline(_book())
    assert [p.id for p in select_parts(tree, "3,1")] == ["1", "3"]            # document order, no dupes
    assert [p.id for p in select_parts(tree, "1-2")] == ["1", "2"]
    assert [p.id for p in select_parts(tree, "2.1-2.1")] == ["2.1"]
    assert [p.id for p in select_parts(tree, "all")] == ["1", "2", "3"]
    assert [p.id for p in select_parts(tree, "all:2")] == ["2.1"]
    for bad in ("9", "2.5", "1-2.1"):
        try:
            select_parts(tree, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(bad)


def test_cut_positions_and_subdocument():
    doc = _book()
    tree = read_outline(doc)
    c1, c2, c3 = tree
    # heading line found just below the hint (y0 of a 20 pt line with baseline 120 is ~98)
    assert start_y(doc, c1) is not None and 90 < start_y(doc, c1) < 105
    assert start_y(doc, c2) is None                                          # top of the page
    y_end = end_y(doc, c2)                                                   # "Chapter 3" baseline 350
    assert y_end is not None and 318 < y_end < 335
    assert find_heading_y(doc[5], "Chapter 3 Delta", 300) is not None

    sub = part_document(doc, c2, cut="exact")
    assert sub.page_count == 3
    first, last = sub[0].get_text(), sub[2].get_text()
    assert "Chapter 2 Beta" in first
    assert "Chapter 3 Delta" not in last and "Body text line 12 of page 6" not in last
    assert "Body text line 1 of page 6" in last                               # text above the cut survives

    whole = part_document(doc, c2, cut="page")
    assert "Chapter 3 Delta" in whole[2].get_text()

    sub3 = part_document(doc, c3, cut="exact")
    t = sub3[0].get_text()
    assert "Chapter 3 Delta" in t and "Body text line 1 of page 6" not in t


def test_page_groups_and_fields():
    groups = page_groups(23, 10)
    assert [(g.page_from, g.page_to) for g in groups] == [(0, 9), (10, 19), (20, 22)]
    assert groups[0].title == "p01-10" and groups[2].title == "p21-23"
    assert groups[0].num_str == "01" and groups[0].kind == "pages"
    f = Part(title="Chapter 4: Starting & Executing", page_from=184, page_to=217, num=4, width=2,
             id="3.4").fields("Guide", 6056)
    assert f == {"stem": "Guide", "num": "04", "title": "Chapter-4-Starting-&-Executing", "id": "3.4",
                 "p0": "0185", "p1": "0218"}
    assert "{stem}-{num}-{title}".format(**f) == "Guide-04-Chapter-4-Starting-&-Executing"
    assert title_for_name("1.2. Program Capabilities") == "1.2-Program-Capabilities"
    long = title_for_name("Chapter 3: Guide to a Successful Simulation Using Ansys Fluent Software")
    assert long == "Chapter-3-Guide-to-a-Successful-Simulation-Using-Ansys" and len(long) <= 60
    assert title_for_name("") == "untitled"


def test_doc_type_detection():
    doc = _book()
    assert detect_doc_type(doc, "Some report without identifiers")[0] == "document"
    assert detect_doc_type(doc, "https://doi.org/10.3390/min12040480")[0] == "paper"
    assert detect_doc_type(doc, "Abstract\nWe study ...")[0] == "paper"
    big = pymupdf.open()
    for _ in range(100):
        big.new_page()
    assert detect_doc_type(big, "Abstract of a thesis")[0] == "document"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
