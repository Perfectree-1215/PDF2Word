"""Equation numbers on a synthetic two-column page (built with PyMuPDF, no fixture file):
the left column's '(1)' must be found although the search strip reaches into the right column,
the right column's text must not be mistaken for the left equation's number, and a garbled
number 'ð2Þ' must still count. See docs/issues/garbled-text-layer.md ("추가 원인")."""
from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf2word.mathocr import find_labels  # noqa: E402

LEFT_BOX = pymupdf.Rect(42, 445, 294, 466)        # paper-01 p.2 eq. (1): spans the left column
RIGHT_BOX = pymupdf.Rect(311, 445, 563, 466)      # a right-column equation at the same height


def _two_column_page(right_label: str = "(7)", left_label: str = "(1)"):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=794)
    page.insert_text((50, 460), "dW/dt = F(W)", fontsize=10)          # left equation body
    page.insert_text((282, 460), left_label, fontsize=10)             # left number at the column edge
    page.insert_text((311, 460), "right column body text here", fontsize=10)
    page.insert_text((551, 460), right_label, fontsize=10)            # right column's number
    return page


def _strip(box, page):
    return pymupdf.Rect(box.x0, box.y0 - 3, page.rect.x1, box.y1 + 3)


def test_left_column_number_is_found_with_box():
    page = _two_column_page()
    assert [l for l, _ in find_labels(page, _strip(LEFT_BOX, page), box=LEFT_BOX)] == ["1"]
    assert [l for l, _ in find_labels(page, _strip(RIGHT_BOX, page), box=RIGHT_BOX)] == ["7"]


def test_without_box_the_wide_strip_hid_the_left_number():
    # the behaviour before the fix, kept for callers that pass a strip that is the box itself
    page = _two_column_page()
    assert [l for l, _ in find_labels(page, _strip(LEFT_BOX, page))] == ["7"]   # wrong column!
    assert [l for l, _ in find_labels(page, LEFT_BOX)] == ["1"]


def test_other_columns_number_is_not_taken():
    page = _two_column_page(left_label="")        # left equation has no number
    assert find_labels(page, _strip(LEFT_BOX, page), box=LEFT_BOX) == []


def test_garbled_number_counts():
    page = _two_column_page(left_label="ð2Þ")    # 'ð2Þ'
    assert [l for l, _ in find_labels(page, _strip(LEFT_BOX, page), box=LEFT_BOX)] == ["2"]
