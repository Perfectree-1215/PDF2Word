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
    assert EquationOCR(other, zooms=(3,), cache=True).recognize_region(page, RECT, "").latex == B


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


def test_region_time_budget_stops_further_scales(page, monkeypatch):
    eng = Stub([A, B, A2])
    ocr = EquationOCR(eng, cache=False)
    monkeypatch.setattr(ocr, "REGION_BUDGET", -1.0)         # the deadline has already passed
    r = ocr.recognize_region(page, RECT, "")
    assert eng.calls == 1 and r.latex == A                  # one reading, no retry at other scales
    assert eng.deadline is not None


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
