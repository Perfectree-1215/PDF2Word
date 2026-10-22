"""Equation numbers on a synthetic two-column page (built with PyMuPDF, no fixture file):
the left column's '(1)' must be found although the search strip reaches into the right column,
the right column's text must not be mistaken for the left equation's number, and a garbled
number 'ð2Þ' must still count. See docs/issues/garbled-text-layer.md ("추가 원인")."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf2word.config import Options  # noqa: E402
from pdf2word.converter import Converter, _DocContext  # noqa: E402
from pdf2word.mathocr import find_labels, ink_mask, render  # noqa: E402

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


def test_picture_equation_takes_its_own_columns_number():
    pic = {"bbox": (42, 445, 270, 466)}           # an equation set as a picture in the left column
    assert _DocContext._label_right_of(None, _two_column_page(), pic) == "1"
    assert _DocContext._label_right_of(None, _two_column_page(left_label=""), pic) is None


def test_drawn_equation_takes_its_own_columns_number(tmp_path):
    eq = pymupdf.Rect(45, 448, 140, 466)           # a vector-drawn equation in the left column
    for left_label, want in (("(1)", ["1"]), ("", [])):
        page = _two_column_page(left_label=left_label)
        ctx = _DocContext(page.parent, tmp_path, Counter(), Converter(Options(math_engine="none")))
        ctx._consumed_labels = []
        md = ctx._orphan_equation(page, eq)
        assert ctx._consumed_labels == want and ("*Eq. (1)*" in md) == bool(want) and "(7)" not in md


# ----------------------------------------------------------------------------- where the number sits

def _numbered_page(label_y: float):
    """A tall equation (two text rows) in a box; its number '(3)' at `label_y`."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=794)
    page.insert_text((50, 460), "dW/dt = F(W) + G(W)", fontsize=10)
    page.insert_text((50, 476), "+ H(W)", fontsize=10)
    page.insert_text((270, label_y), "(3)", fontsize=10)
    return page


BOX = pymupdf.Rect(42, 445, 294, 490)


def test_number_on_the_equations_row_is_cut_off():
    page = _numbered_page(label_y=476)                     # same row as the equation's last line
    labels = find_labels(page, BOX)
    (region, label, mask), = _DocContext._split_regions(BOX, labels, page)
    assert label == "3" and region.x1 == pytest.approx(labels[0][1].x0 - 2) and mask == []


def test_number_on_its_own_row_keeps_the_width_and_is_masked():
    # paper-01 eq. (3): the number sits below the end of a tall equation; cutting the region at
    # its left edge removed the equation's closing ')^2 ]'
    page = _numbered_page(label_y=488)
    labels = find_labels(page, BOX)
    lr = labels[0][1]
    (region, label, mask), = _DocContext._split_regions(BOX, labels, page)
    assert label == "3" and region.x1 == BOX.x1 and mask == [lr]
    # the number is painted out of the render, the equation is not
    plain, masked = render(page, region, 2.0), render(page, region, 2.0, mask)
    x0, y0 = int((lr.x0 - region.x0) * 2), int((lr.y0 - region.y0) * 2)
    x1, y1 = int((lr.x1 - region.x0) * 2) + 1, int((lr.y1 - region.y0) * 2) + 1
    assert ink_mask(plain)[y0:y1, x0:x1].any() and not ink_mask(masked)[y0:y1, x0:x1].any()
    assert ink_mask(masked)[:, :x0 - 4].any()
    assert _DocContext._split_regions(BOX, [], page) == [(BOX, None, [])]
