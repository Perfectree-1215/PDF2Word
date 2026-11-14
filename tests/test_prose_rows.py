"""Body text that the layout model filed as (part of) a formula box stays body text
(docs/issues/prose-in-formula-box.md): the rows of the text layer tell words set in an upright text
font from math, the box is cut at the body-text rows, and only what is left is read as an equation.
Synthetic pages and a stub engine - no model, no network."""
from __future__ import annotations

import io
import sys
from collections import Counter
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf2word.config import Options  # noqa: E402
from pdf2word.converter import Converter, _DocContext  # noqa: E402
from pdf2word.mathocr import (INK_MAX, EquationOCR, MathEngine, PROSE_SHARE, PROSE_WORDS, holds_body_text,  # noqa: E402
                              ink_share, is_line_art, is_prose_row, split_prose, text_rows_in)

UP, IT, MATH = (False, False), (True, False), (False, True)      # (italic, math font) of a span


def row(*spans):
    return [(text, *style) for text, style in spans]


# ----------------------------------------------------------------------------- one row

def test_rows_of_upright_words_are_body_text():
    # the rows measured on paper-02 p.6 (garbled math font: '~1!' is '(1)', 'r¯*' is rho-bar-star)
    for spans in (
        row(("~1! The Adams–Bashford predictor-step:", UP)),
        row(("~2! The predicted density ", UP), ("r", IT), ("¯* ", UP), ("is obtained by", UP)),
        row(("involves", UP), ("the", UP), ("advective", UP), ("and", UP), ("diffusive", UP), ("fluxes,", UP)),
        row(("(adv.", UP), ("1", MATH), ("diff.)*, obtained with the predictor-step solution", UP)),
        row(("~6! Pressure correction:", UP)),                # two words are enough
    ):
        assert is_prose_row(spans), spans


def test_math_rows_are_not_body_text():
    for spans in (
        row(("u", IT), (" min", UP)),                         # a limit of integration: one word
        row(("Z", MATH), ("u", IT), (" max", UP)),
        row(("G", IT), ("~", UP), ("x", IT), ("2", MATH), ("x", IT), ("8!5", UP), ("H", MATH),
            ("0, 1, otherwise. if u", UP), ("x", IT), ("2", MATH), ("x", IT), ("8 u < D 2 , ~7!", UP)),
        row(("~", UP), ("r", IT), ("¯", UP), ("u", IT), ("˜ i!n115~", UP), ("r", IT), ("u", IT),
            ("i!n2 Dt n 2 @~adv.", UP), ("1", MATH), ("diff.!", UP), ("u", IT), (" n i", IT)),
        row(("~5! ", UP), ("r", IT), ("¯ n11 ", UP), ("is computed by", UP)),   # label + symbol + three short words
        row(("~23!", UP)),                                    # an equation number
        row(("x = y + z", IT)),
        [],
    ):
        assert not is_prose_row(spans), spans


def test_a_row_that_states_a_relation_stays_an_equation():
    # an equation written in words keeps being read; the same words without the relation are body text
    assert not is_prose_row(row(("Nusselt number = hL/k", UP)))
    assert not is_prose_row(row(("fuel + oxidizer → products", UP)))
    assert is_prose_row(row(("Nusselt number", UP)))


def test_italic_and_math_font_words_do_not_count():
    # words set in italics or in a math font are not evidence of body text (a theorem set in italics
    # inside a formula box is left as it was)
    assert not is_prose_row(row(("where the flux is taken at the wall", IT)))
    assert not is_prose_row(row(("where the flux is taken at the wall", MATH)))
    assert is_prose_row(row(("where the flux ", UP), ("q", IT), (" is taken at the wall", UP)))
    assert PROSE_SHARE == 0.6 and PROSE_WORDS == 2            # provisional: one PDF, one page (issue record)


# ----------------------------------------------------------------------------- a formula box

HEAD = "(1) The predictor step of the scheme:"
EQ = "x = y + z"
NOTE = "(2) Pressure correction follows here:"
BOX = pymupdf.Rect(40, 85, 320, 200)


@pytest.fixture
def page():
    """A formula box holding a step heading, an equation, a second heading and a second equation."""
    doc = pymupdf.open()
    pg = doc.new_page(width=595, height=794)
    pg.insert_text((50, 100), HEAD, fontsize=10, fontname="helv")
    pg.insert_text((70, 125), EQ, fontsize=10, fontname="tiit")
    pg.insert_text((50, 150), NOTE, fontsize=10, fontname="helv")
    pg.insert_text((70, 180), EQ, fontsize=10, fontname="tiit")
    return pg


class Stub(MathEngine):
    """Reads every image as `reading`."""
    name = "stub"
    multiline = True
    multi_zoom = True
    default_zooms = (3.0, 4.0, 2.0)

    def __init__(self, reading):
        self.reading, self.calls = reading, 0

    def recognize(self, img, hint=""):
        self.calls += 1
        return self.reading


def context(doc, tmp_path, monkeypatch, reading="x=y+z"):
    """-> (_DocContext, engine, the regions handed to the OCR)."""
    conv = Converter(Options())
    eng = Stub(reading)
    conv._engine, conv._engine_built, conv._ocr = eng, True, EquationOCR(eng, cache=False)
    seen = []
    read = conv._ocr.recognize_region

    def spy(page, rect, hint="", mask=None, **kw):
        seen.append((pymupdf.Rect(rect), hint))
        return read(page, rect, hint, mask, **kw)
    monkeypatch.setattr(conv._ocr, "recognize_region", spy)
    ctx = _DocContext(doc, tmp_path, Counter(), conv)
    ctx._consumed_labels = []
    return ctx, eng, seen


def test_text_rows_in_groups_lines_and_marks_body_text(page):
    rows = text_rows_in(page, BOX)
    assert [r["prose"] for r in rows] == [True, False, True, False]
    assert [r["text"] for r in rows] == [HEAD, EQ, NOTE, EQ]
    assert all(a["rect"].y1 <= b["rect"].y0 + 3 for a, b in zip(rows, rows[1:]))    # top to bottom


def test_words_justified_into_separate_lines_form_one_row():
    # justified body text: MuPDF returns every word as a line of its own (paper-02 p.6 '#33')
    doc = pymupdf.open()
    pg = doc.new_page(width=595, height=794)
    for x, word in ((50, "involves"), (110, "the"), (150, "advective"), (220, "and"), (260, "diffusive")):
        pg.insert_text((x, 100), word, fontsize=10, fontname="helv")
    rows = text_rows_in(pg, pymupdf.Rect(40, 85, 320, 110))
    assert len(rows) == 1 and rows[0]["prose"]
    assert rows[0]["text"] == "involves the advective and diffusive"


def test_spaces_that_are_spans_of_their_own_keep_the_words_apart():
    # paper-02 p.6: every word is a span and so is every space between two words; the row's text
    # keeps those spaces ('The predicted density', not 'Thepredicteddensity')
    doc = pymupdf.open()
    pg = doc.new_page(width=595, height=794)
    x = 50.0
    for piece in ("The", " ", "predicted", " ", "density", " ", "is", " ", "obtained"):
        font = "tiro" if piece == " " else "helv"             # a space in another font is a span of its own
        pg.insert_text((x, 100), piece, fontsize=10, fontname=font)
        x += pymupdf.get_text_length(piece, fontname=font, fontsize=10)
    spans = [s["text"] for b in pg.get_text("dict")["blocks"] for ln in b["lines"] for s in ln["spans"]]
    assert " " in spans                                       # the page really has such spans
    rows = text_rows_in(pg, pymupdf.Rect(40, 85, 320, 110))
    assert len(rows) == 1 and rows[0]["prose"]
    assert rows[0]["text"] == "The predicted density is obtained"


def test_a_box_without_body_text_is_left_whole(page):
    # nothing changes for an ordinary equation: the very box, no cut
    rect = pymupdf.Rect(60, 112, 320, 130)
    assert split_prose(page, rect) == [("math", rect)]
    empty = pymupdf.Rect(400, 400, 500, 430)                    # no text layer at all (a pictured equation)
    assert split_prose(page, empty) == [("math", empty)]


def test_the_box_is_cut_at_its_body_text_rows(page):
    rows = text_rows_in(page, BOX)
    parts = split_prose(page, BOX)
    assert [k for k, _ in parts] == ["text", "math", "text", "math"]
    assert parts[0][1] == HEAD and parts[2][1] == NOTE
    first, second = parts[1][1], parts[3][1]
    assert (first.x0, first.x1) == (second.x0, second.x1) == (BOX.x0, BOX.x1)       # the box's own width
    assert first.y0 == rows[0]["rect"].y1 and first.y1 == rows[2]["rect"].y0        # between the two headings
    assert second.y0 == rows[2]["rect"].y1 and second.y1 == BOX.y1                  # down to the end of the box
    assert first.contains(rows[1]["rect"]) and second.contains(rows[3]["rect"])


def test_consecutive_body_text_rows_make_one_paragraph():
    doc = pymupdf.open()
    pg = doc.new_page(width=595, height=794)
    pg.insert_text((50, 100), "involves the advective and diffusive fluxes,", fontsize=10, fontname="helv")
    pg.insert_text((50, 112), "obtained with the predictor step solution", fontsize=10, fontname="helv")
    pg.insert_text((70, 140), EQ, fontsize=10, fontname="tiit")
    parts = split_prose(pg, pymupdf.Rect(40, 85, 320, 150))
    assert [k for k, _ in parts] == ["text", "math"]
    assert parts[0][1] == "involves the advective and diffusive fluxes, obtained with the predictor step solution"


def test_a_drawn_equation_under_body_text_is_kept_and_blank_strips_are_not():
    # the equation has no text layer (vector outlines): the strip under the heading is still an
    # equation because it is inked; the blank strip above the heading is nothing
    doc = pymupdf.open()
    pg = doc.new_page(width=595, height=794)
    pg.insert_text((50, 100), HEAD, fontsize=10, fontname="helv")
    sh = pg.new_shape()
    for i in range(6):
        sh.draw_rect(pymupdf.Rect(70 + 8 * i, 120, 75 + 8 * i, 130))
    sh.finish(fill=(0, 0, 0), color=None)
    sh.commit()
    box = pymupdf.Rect(40, 60, 320, 140)
    parts = split_prose(pg, box)
    assert [k for k, _ in parts] == ["text", "math"]
    assert parts[1][1].y1 == box.y1 and parts[1][1].y0 > 100
    assert [k for k, _ in split_prose(pg, pymupdf.Rect(40, 60, 320, 112))] == ["text"]   # nothing drawn in it


# ----------------------------------------------------------------------------- the converter

def test_a_formula_box_of_body_text_is_not_read(tmp_path, monkeypatch):
    # paper-02 p.6 '#25': the whole box is one sentence - the text layer as it is, no OCR, no equation
    doc = pymupdf.open()
    pg = doc.new_page(width=595, height=794)
    pg.insert_text((50, 100), "(2) The predicted density is obtained by", fontsize=10, fontname="helv")
    ctx, eng, seen = context(doc, tmp_path, monkeypatch, r"\mathrm{(2)\quad The~predicted~density}")
    md = ctx._formula(pg, {"class": "formula", "bbox": (45, 88, 300, 104)}, "\n\n")
    assert md.strip() == "(2) The predicted density is obtained by"
    assert eng.calls == 0 and not seen and "$$" not in md
    assert ctx.stats["eq_total"] == 0 and not ctx.equations


def test_body_text_rows_stay_text_and_the_equations_between_them_are_read(page, tmp_path, monkeypatch):
    ctx, eng, seen = context(page.parent, tmp_path, monkeypatch)
    md = ctx._formula(page, {"class": "formula", "bbox": tuple(BOX)}, "\n\n")
    rows = text_rows_in(page, BOX)
    assert md.count("$$") == 4 and ctx.stats["eq_total"] == 2 and len(ctx.equations) == 2
    # reading order: heading, equation, heading, equation - each a block of its own
    order = [md.index(HEAD), md.index("$$"), md.index(NOTE), md.rindex("$$")]
    assert order == sorted(order)
    assert f"\n{HEAD}\n\n" in md and f"\n{NOTE}\n\n" in md
    assert "predictor" not in "".join(md.split("$$")[1::2])       # no body text inside an equation block
    # the OCR saw the equation rows only, with the equation's own text layer as the hint
    assert len(seen) == 2 and all(hint == EQ for _, hint in seen)
    for region, _ in seen:
        assert not any(region.intersects(r["rect"]) for r in rows if r["prose"])


# ----------------------------------------------------------------------------- drawn / pictured equations
# docs/issues/watermark-as-equation.md: an equation drawn as graphics or set as a picture has no text
# layer where it stands, so a region that holds body text is none

def _paragraph_page():
    """Four lines of body text, a caption of two lines, and an equation drawn as glyph outlines."""
    doc = pymupdf.open()
    pg = doc.new_page(width=595, height=794)
    for k in range(4):
        pg.insert_text((50, 100 + 14 * k), "body text of the paragraph that a watermark runs across", fontsize=10,
                       fontname="helv")
    pg.insert_text((50, 300), "(b) Temperature along the tube", fontsize=10, fontname="helv")
    pg.insert_text((50, 314), "Fig. 8 Results of the design condition", fontsize=10, fontname="helv")
    sh = pg.new_shape()
    for i in range(10):                                   # glyph strokes: 1.5 pt of ink per 8 pt
        sh.draw_rect(pymupdf.Rect(200 + 8 * i, 500, 201.5 + 8 * i, 510))
    sh.finish(fill=(0, 0, 0), color=None)
    sh.commit()
    grey = Image.new("L", (240, 160))                     # a photo the layout model did not box
    grey.putdata([40 + (x * 7 + y * 13) % 120 for y in range(160) for x in range(240)])
    buf = io.BytesIO()
    grey.save(buf, "PNG")
    pg.insert_image(PHOTO, stream=buf.getvalue())
    return pg


PHOTO = pymupdf.Rect(300, 560, 540, 720)             # a dense grey image
PARAGRAPH = pymupdf.Rect(45, 85, 400, 150)           # the four lines
CAPTION = pymupdf.Rect(45, 288, 300, 318)            # the two caption lines: a short wide strip
DRAWN = pymupdf.Rect(198, 498, 282, 512)             # the glyph outlines


def test_an_equation_is_line_art_and_a_photo_is_not():
    # paper-04 p.20: a photo the layout model did not box came out as an equation. Of an equation's
    # ink box at most a quarter is ink (106 equations of four papers); of that photo's, 0.57-0.66
    pg = _paragraph_page()
    assert ink_share(Image.new("L", (40, 40), 255)) == 0.0                       # blank
    assert ink_share(Image.new("L", (40, 40), 0)) == 1.0
    strokes = Image.new("L", (80, 20), 255)
    for x in range(0, 80, 8):
        strokes.paste(0, (x, 0, x + 2, 20))
    assert ink_share(strokes) < 0.3
    assert is_line_art(pg, DRAWN) and is_line_art(pg, PARAGRAPH) and INK_MAX == 0.5
    assert not is_line_art(pg, PHOTO)


def test_a_photo_is_not_an_equation(tmp_path, monkeypatch):
    pg = _paragraph_page()
    ctx, eng, seen = context(pg.parent, tmp_path, monkeypatch)
    assert ctx._orphan_equation(pg, PHOTO) == ""                      # a loose image among the page's atoms
    assert ctx._picture_as_equation(pg, {"class": "picture", "bbox": tuple(PHOTO)}) is None
    assert eng.calls == 0 and not seen and ctx.stats["eq_total"] == 0


def test_holds_body_text_wants_half_a_row_inside():
    pg = _paragraph_page()
    rows = text_rows_in(pg, PARAGRAPH)
    assert len(rows) == 4 and all(r["prose"] for r in rows)
    assert holds_body_text(pg, PARAGRAPH) and holds_body_text(pg, CAPTION)
    assert not holds_body_text(pg, DRAWN)
    last = rows[-1]["rect"]
    # an equation right under a paragraph: its region brushes the last line, which does not count
    assert not holds_body_text(pg, pymupdf.Rect(45, last.y1 - 3, 400, last.y1 + 40))
    assert holds_body_text(pg, pymupdf.Rect(45, last.y0 + 2, 400, last.y1 + 40))
    # a narrow region inside the paragraph sees clipped fragments of its lines, no whole row of words
    assert not holds_body_text(pg, pymupdf.Rect(120, 85, 150, 150))


def test_a_drawn_cluster_over_body_text_is_not_an_equation(tmp_path, monkeypatch):
    pg = _paragraph_page()
    ctx, eng, seen = context(pg.parent, tmp_path, monkeypatch)
    assert ctx._orphan_equation(pg, PARAGRAPH) == ""                  # paper-03: the watermark's bounding box
    assert eng.calls == 0 and not seen and ctx.stats["eq_total"] == 0 and not ctx.equations
    md = ctx._orphan_equation(pg, DRAWN)                              # a drawn equation, no text layer: as before
    assert "$$" in md and eng.calls > 0 and ctx.stats["eq_total"] == ctx.stats["eq_drawn"] == 1


def test_a_picture_strip_of_body_text_is_not_an_equation(tmp_path, monkeypatch):
    pg = _paragraph_page()
    ctx, eng, seen = context(pg.parent, tmp_path, monkeypatch)
    # paper-03 p.14: two caption lines the layout model boxed as a picture, a short wide strip
    assert ctx._picture_as_equation(pg, {"class": "picture", "bbox": tuple(CAPTION)}) is None
    assert eng.calls == 0 and ctx.stats["eq_total"] == 0
    md = ctx._picture_as_equation(pg, {"class": "picture", "bbox": tuple(DRAWN)})
    assert md is not None and "$$" in md and ctx.stats["eq_total"] == 1


def test_an_ordinary_formula_box_is_read_as_before(page, tmp_path, monkeypatch):
    ctx, eng, seen = context(page.parent, tmp_path, monkeypatch)
    rect = pymupdf.Rect(60, 112, 320, 130)
    md = ctx._formula(page, {"class": "formula", "bbox": tuple(rect)}, "\n\n")
    assert [r for r, _ in seen] == [rect] and md == "\n$$\nx=y+z\n$$\n^eq-u01\n\n"
