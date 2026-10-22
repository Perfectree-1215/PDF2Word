"""The p2t engine's place in the pipeline (docs/decisions/math-engine-pix2text.md): the fallback to
rapid when its model cannot be loaded, the per-engine render scales, and how EquationOCR reads a
region with an engine that takes whole multi-line images. Stub engines on a synthetic page - no
model, no network."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf2word import mathocr  # noqa: E402
from pdf2word.mathocr import (AGREE_LOW, CONFIDENCE_OK, EquationOCR, MathEngine, Pix2TextEngine,  # noqa: E402
                              RapidEngine, agreement, build_engine, pick_by_agreement)
from pdf2word.mfr_onnx import ModelError  # noqa: E402

GARBLED = "@W\n@t ¼ I \u0002 WhWþ\nh\n\u0002\n\u0003\nFðWÞ þ d\nð1Þ"


class Stub(MathEngine):
    """Returns its readings in order, whatever the image."""
    name = "stub"
    multiline = True
    multi_zoom = True
    default_zooms = (3.0, 4.0, 2.0)

    def __init__(self, readings):
        self.readings, self.calls = list(readings), 0

    def recognize(self, img, hint=""):
        self.calls += 1
        return self.readings[self.calls - 1]


class OneShot(Stub):
    """An engine that must not be called often (the Claude engine)."""
    name = "oneshot"
    multi_zoom = False
    default_zooms = None


@pytest.fixture
def page():
    doc = pymupdf.open()
    pg = doc.new_page(width=595, height=794)
    pg.insert_text((50, 460), "x = y + z", fontsize=12)
    return pg


RECT = pymupdf.Rect(40, 445, 200, 470)
A = r"x=y+z"
A2 = r"x = \mathrm{y} + z"            # the same reading, spelt differently
B = r"a=b"


# ----------------------------------------------------------------------------- build_engine

def test_p2t_falls_back_to_rapid_when_the_model_cannot_load(monkeypatch, caplog):
    def fail(self):
        raise ModelError("offline")
    monkeypatch.setattr(Pix2TextEngine, "load", fail)
    with caplog.at_level(logging.WARNING, logger="pdf2word"):
        engine = build_engine("p2t", max_tokens=99)
    assert isinstance(engine, RapidEngine) and engine.max_tokens == 99
    assert "rapid" in caplog.text and "offline" in caplog.text


def test_p2t_is_the_default_and_loads_eagerly(monkeypatch):
    loaded = []
    monkeypatch.setattr(Pix2TextEngine, "load", lambda self: loaded.append(self) or self)
    assert isinstance(build_engine("p2t"), Pix2TextEngine)
    assert isinstance(build_engine(None), Pix2TextEngine)
    assert len(loaded) == 2
    assert build_engine("none") is None and isinstance(build_engine("rapid"), RapidEngine)


# ----------------------------------------------------------------------------- render scales

def test_zooms_come_from_the_engine_unless_given():
    assert EquationOCR(Stub([]), cache=False).zooms == (3.0, 4.0, 2.0)
    assert EquationOCR(Stub([]), zooms=(2, 3), cache=False).zooms == (2.0, 3.0)
    assert EquationOCR(RapidEngine(), cache=False).zooms == (2.0, 3.0, 4.0)
    assert EquationOCR(None, cache=False).zooms == (2.0, 3.0, 4.0)
    assert Pix2TextEngine.default_zooms == (4.0, 3.0, 2.0) and Pix2TextEngine.multiline


# ----------------------------------------------------------------------------- reading a region

def test_without_a_text_layer_the_scales_must_agree(page):
    eng = Stub([A, A2, B])
    r = EquationOCR(eng, cache=False).recognize_region(page, RECT, "")
    assert eng.calls == 2 and r.latex == A2 and r.confidence == 1.0        # 3x and 4x agree: stop
    assert r.lines == 1 and r.image is not None

    eng = Stub([A, B, A2])
    r = EquationOCR(eng, cache=False).recognize_region(page, RECT, GARBLED)
    assert eng.calls == 3 and r.latex == A and r.confidence == 1.0         # majority of three; tie -> 3x over 2x

    eng = Stub([A, B, None])
    r = EquationOCR(eng, cache=False).recognize_region(page, RECT, "")
    assert eng.calls == 3 and r.latex == B and r.confidence < CONFIDENCE_OK  # no majority: flagged


def test_with_a_text_layer_a_good_match_stops_early(page):
    eng = Stub([A, B])
    r = EquationOCR(eng, cache=False).recognize_region(page, RECT, "x = y + z")
    assert eng.calls == 1 and r.latex == A and r.confidence >= CONFIDENCE_OK

    eng = Stub([B, A])
    r = EquationOCR(eng, cache=False).recognize_region(page, RECT, "x = y + z")
    assert eng.calls == 2 and r.latex == A                                 # poor match retried, best wins

    eng = Stub([None, None, None])
    r = EquationOCR(eng, cache=False).recognize_region(page, RECT, "x = y + z")
    assert eng.calls == 3 and r.latex is None and r.lines == 0


def test_multi_line_readings_count_their_lines(page):
    two = "\\begin{aligned} a &= b \\\\ &+ c \\end{aligned}"
    eng = Stub([two, two])
    r = EquationOCR(eng, cache=False).recognize_region(page, RECT, "")
    assert r.lines == 2 and r.latex == two


def test_a_one_shot_engine_reads_once(page):
    eng = OneShot([A, B])
    r = EquationOCR(eng, zooms=(2, 3, 4), cache=False).recognize_region(page, RECT, GARBLED)
    assert eng.calls == 1 and r.latex == A and r.confidence == 1.0         # garbled layer: not judged
    eng = OneShot([None, A])
    r = EquationOCR(eng, zooms=(2, 3), cache=False).recognize_region(page, RECT, "x = y + z")
    assert eng.calls == 2 and r.latex == A                                 # one retry when nothing came back


def test_results_are_cached_per_engine(page, tmp_path, monkeypatch):
    monkeypatch.setattr(mathocr, "cache_dir", lambda: tmp_path)
    eng = Stub([A, A])
    ocr = EquationOCR(eng, zooms=(3,), cache=True)
    ocr.recognize_region(page, RECT, "")
    ocr.recognize_region(page, RECT, "")
    assert eng.calls == 1 and ocr.cache_hits == 1
    other = Stub([B, B])
    other.name = "other"
    ocr.engine = other                                      # same cache, another engine: not its entries
    assert ocr.recognize_region(page, RECT, "").latex == B and other.calls == 1


def test_disabled_cache_touches_no_profile_folder(page, tmp_path, monkeypatch):
    # cache=False (--no-cache, most tests here) must not create %LOCALAPPDATA%\pdf2word nor copy
    # the old pdf2obsidian caches into it
    for var in ("LOCALAPPDATA", "XDG_CACHE_HOME"):
        monkeypatch.setenv(var, str(tmp_path))
    (tmp_path / "pdf2obsidian").mkdir()
    (tmp_path / "pdf2obsidian" / "mathocr-cache.json").write_text("{}", encoding="utf-8")
    ocr = EquationOCR(Stub([A, A]), cache=False)
    assert ocr.recognize_region(page, RECT, "").latex == A
    ocr.cache.save()
    assert [p.name for p in tmp_path.iterdir()] == ["pdf2obsidian"]


# ----------------------------------------------------------------------------- round 2 (decision workflow lenses)

def test_ties_between_readings_go_to_the_largest_scale():
    # two readings that agree equally with the third: without scales the later one wins, with
    # scales the larger one does (p2t reads 4x first, so the later reading is the smaller scale)
    assert pick_by_agreement([A, A2, B]) == (1, 1.0)
    assert pick_by_agreement([A, A2, B], zooms=[4.0, 3.0, 2.0]) == (0, 1.0)
    assert pick_by_agreement([B, A, A2], zooms=[4.0, 3.0, 2.0])[0] == 1


def test_scale_disagreement_flags_the_equation(page):
    bad = r"x=y+w"                                           # a plausible but different reading
    conf = agreement(A, bad)
    assert 0.6 < conf < AGREE_LOW                           # the text-layer threshold would let it pass
    r = EquationOCR(Stub([A, bad, A2]), zooms=(4, 3), cache=False).recognize_region(page, RECT, "")
    assert r.by_agreement and r.confidence == pytest.approx(conf) and r.uncertain
    r = EquationOCR(Stub([A, A2]), cache=False).recognize_region(page, RECT, "")
    assert r.by_agreement and not r.uncertain
    r = EquationOCR(Stub([A]), zooms=(4,), cache=False).recognize_region(page, RECT, "x = y + z")
    assert not r.by_agreement                              # a text-layer match keeps the old threshold


class Watched(Stub):
    """Records the deadline each reading was given."""

    def __init__(self, readings):
        super().__init__(readings)
        self.seen = []

    def recognize(self, img, hint=""):
        self.seen.append(self.deadline)
        return super().recognize(img, hint)


def test_region_time_budget_stops_further_scales(page, monkeypatch):
    eng = Watched([A, B, A2])
    ocr = EquationOCR(eng, cache=False)
    monkeypatch.setattr(ocr, "REGION_BUDGET", -1.0)         # the deadline has already passed
    r = ocr.recognize_region(page, RECT, "")
    assert eng.calls == 1 and r.latex == A                  # one reading, no retry at other scales
    assert eng.seen[0] is not None and eng.deadline is None  # set while reading, cleared afterwards


def test_the_region_deadline_does_not_reach_later_images(page):
    # converter._inline_math reads inline symbols with recognize_image after the display equations:
    # they must not inherit an equation's deadline, which may long have passed
    eng = Watched([A, A2, B])
    ocr = EquationOCR(eng, cache=False)
    ocr.recognize_region(page, RECT, "")
    img = mathocr.tight_crop(mathocr.render(page, RECT, 3.0))
    assert ocr.recognize_image(img, "") == B
    assert eng.seen[0] is not None and eng.seen[-1] is None


def test_long_multi_row_readings_are_not_garbage():
    # p2t reads a whole multi-row equation at once (three rows of paper-01 come to 666-814
    # characters): the 600-character cap, made for rapid's one-row readings, holds per row
    rows = ["+".join(r"\frac{a_{%d%d}}{b_{%d}}" % (k, i, i) for i in range(12)) for k in range(3)]
    three = r"\begin{aligned}" + "\\\\".join(rows) + r"\end{aligned}"
    assert all(len(r) == 255 for r in rows) and 600 < len(three) < 1200
    assert not mathocr.looks_garbage(three)
    assert mathocr.looks_garbage("".join(rows))             # as many characters on one row: too long


def test_a_region_can_be_cropped_without_reading(page):
    # --math-mode image drops the LaTeX anyway: the crop alone, no reading at any scale
    eng = Stub([A, A2, B])
    r = EquationOCR(eng, cache=False).recognize_region(page, RECT, "x = y + z", read=False)
    assert eng.calls == 0 and r.latex is None and r.lines == 1 and r.image is not None


def test_math_mode_image_does_not_read_display_equations(page, tmp_path):
    from collections import Counter
    from pdf2word.config import Options
    from pdf2word.converter import Converter, _DocContext
    for mode, reads in (("image", False), ("both", True)):
        conv = Converter(Options(math_mode=mode))
        eng = Stub([A, A2, B, A, A2, B])
        conv._engine, conv._engine_built, conv._ocr = eng, True, EquationOCR(eng, cache=False)
        ctx = _DocContext(page.parent, tmp_path, Counter(), conv)
        ctx._consumed_labels = []
        md = ctx._orphan_equation(page, RECT) + ctx._formula(page, {"bbox": tuple(RECT)}, "")
        assert (eng.calls > 0) == reads, mode
        assert "eq-u01" in md and "eq-u02" in md and ("$$" in md) == reads


def test_the_saved_crop_is_rendered_at_the_display_scale(page, tmp_path):
    # Markdown viewers draw the equation PNG at pixel size: 144 dpi whatever scales the engine reads
    from collections import Counter
    from PIL import Image
    from pdf2word.config import Options
    from pdf2word.converter import Converter, _DocContext
    eng = Stub([A, A2])
    ocr = EquationOCR(eng, cache=False)
    r = ocr.recognize_region(page, RECT, "")
    want = mathocr.tight_crop(mathocr.render(page, RECT, 2.0))
    assert r.image.size == want.size and EquationOCR.DISPLAY_ZOOM == 2.0
    conv = Converter(Options())
    conv._engine, conv._engine_built, conv._ocr = eng, True, ocr
    ctx = _DocContext(page.parent, tmp_path, Counter(), conv)
    with Image.open(tmp_path / ctx._save_equation_image(r, None, page, RECT)) as im:
        assert im.size == want.size and round(im.info["dpi"][0]) == 144
    # nothing at the display scale (masked or faint): the 3x unmasked fallback says 216 dpi
    with Image.open(tmp_path / ctx._save_equation_image(mathocr.EquationResult(None, None, 0), None,
                                                        page, RECT)) as im:
        assert im.size == mathocr.tight_crop(mathocr.render(page, RECT, 3.0)).size
        assert round(im.info["dpi"][0]) == 216


def _converter_reading(reading):
    """A Converter whose engine reads every image as `reading` at every scale."""
    from pdf2word.config import Options
    from pdf2word.converter import Converter
    conv = Converter(Options())
    eng = Stub([reading] * 6)
    conv._engine, conv._engine_built, conv._ocr = eng, True, EquationOCR(eng, cache=False)
    return conv


def test_a_word_badge_is_not_an_equation(tmp_path):
    # a publisher badge (CrossMark, Check for updates) that reads as a word is not a display
    # equation: drawn as vector outlines it is dropped, set as a picture it stays a picture
    import io
    from collections import Counter
    from PIL import Image, ImageDraw
    from pdf2word.converter import _DocContext
    doc = pymupdf.open()
    pg = doc.new_page(width=595, height=794)
    pg.insert_text((60, 400), "Body text far away from the badges.", fontsize=10)
    sh = pg.new_shape()                                       # an outlined word: nine glyph bars, 7 pt high
    for i in range(9):
        sh.draw_rect(pymupdf.Rect(480 + 4 * i, 186, 483 + 4 * i, 193))
    sh.finish(fill=(0, 0, 0), color=None)
    sh.commit()
    img = Image.new("RGB", (480, 120), "white")              # a word badge set as a picture, no caption
    ImageDraw.Draw(img).rectangle((1, 1, 478, 118), outline="black")
    ImageDraw.Draw(img).text((10, 40), "Check for updates", fill="black")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    pic = pymupdf.Rect(400, 100, 520, 130)
    pg.insert_image(pic, stream=buf.getvalue())
    drawn = pymupdf.Rect(478, 184, 518, 195)
    box = {"class": "picture", "bbox": tuple(pic), "pos": (0, 0), "index": 0, "_text": ""}
    boxes = [box, {"class": "text", "bbox": (55, 388, 300, 404), "pos": (0, 0), "_text": "Body text."}]
    for reading, word in ((A, False), (r"\mathrm{CrossMark}", True), (r"\mathrm{Check~for~updates}", True)):
        ctx = _DocContext(doc, tmp_path / str(word), Counter(), _converter_reading(reading))
        ctx.asset_dir.mkdir(exist_ok=True)
        ctx._consumed_labels = []
        md = ctx._orphan_equation(pg, drawn)
        assert (md == "") == word and ctx.stats["eq_total"] == ctx.stats["eq_drawn"] == (0 if word else 1), reading
        md = ctx._picture(pg, box, "", boxes)
        assert ("$$" in md) != word and ("p1-img1.png" in md) == word, reading
        assert ctx.stats["figures"] == (1 if word else 0)


def test_failed_calls_are_not_cached(page, tmp_path, monkeypatch):
    monkeypatch.setattr(mathocr, "cache_dir", lambda: tmp_path)

    class Flaky(Stub):
        def recognize(self, img, hint=""):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("model busy")
            return A
    eng = Flaky([])
    ocr = EquationOCR(eng, zooms=(4,), cache=True)
    assert ocr.recognize_region(page, RECT, "").latex is None
    assert ocr.recognize_region(page, RECT, "").latex == A   # the failure was not remembered
    assert eng.calls == 2
