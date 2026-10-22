"""pdf2word/mfr_onnx.py - the Pix2Text MFR runner without the model: fake onnxruntime sessions,
a fake tokenizer and a fake downloader. No network, no model files, no torch."""
from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf2word import mfr_onnx  # noqa: E402
from pdf2word.mfr_onnx import (BOS, EOS, IMAGE_SIZE, MFRRunner, ModelError, _repeating,  # noqa: E402
                               ensure_model, models_dir, postprocess, preprocess)


# ----------------------------------------------------------------------------- fakes

class _Input:
    def __init__(self, name):
        self.name = name


class FakeEncoder:
    def get_inputs(self):
        return [_Input("pixel_values")]

    def run(self, _, feeds):
        x = feeds["pixel_values"]
        assert x.shape == (1, 3, IMAGE_SIZE, IMAGE_SIZE) and x.dtype == np.float32
        return [np.zeros((1, 578, 384), np.float32)]


class FakeDecoder:
    """Emits the ids of `script` one per step, then EOS. `delay` slows every step down."""

    def __init__(self, script, delay: float = 0.0, vocab: int = 1868):
        self.script, self.delay, self.vocab = list(script), delay, vocab
        self.steps = 0

    def get_inputs(self):
        return [_Input("input_ids"), _Input("encoder_hidden_states")]

    def run(self, _, feeds):
        ids = feeds["input_ids"]
        assert ids.dtype == np.int64 and ids[0, 0] == BOS and feeds["encoder_hidden_states"].shape == (1, 578, 384)
        step = ids.shape[1] - 1
        self.steps += 1
        nxt = self.script[step] if step < len(self.script) else EOS
        logits = np.zeros((1, ids.shape[1], self.vocab), np.float32)
        logits[0, -1, nxt] = 1.0
        if self.delay:
            time.sleep(self.delay)
        return [logits]


class FakeTokenizer:
    VOCAB = {3: "\\frac", 4: "{", 5: "}", 6: "a", 7: "b", 8: "x", 9: "^", 10: "_", 11: "2", 12: "\\alpha"}

    def decode(self, ids, skip_special_tokens=True):
        return " ".join(self.VOCAB[i] for i in ids if not (skip_special_tokens and i in (0, BOS, EOS)))


def _runner(script, **kw) -> MFRRunner:
    return MFRRunner(sessions=(FakeEncoder(), FakeDecoder(script, delay=kw.pop("delay", 0.0))),
                     tokenizer=FakeTokenizer(), **kw)


IMG = Image.new("L", (120, 40), 255)


# ----------------------------------------------------------------------------- decoding

def test_greedy_decoding_joins_the_tokens():
    assert _runner([3, 4, 6, 5, 4, 7, 5]).recognize(IMG) == r"\frac{a}{b}"
    assert _runner([12, 8, 9, 4, 11, 5]).recognize(IMG) == r"\alpha x^{2}"     # a space only before a letter
    assert _runner([]).recognize(IMG) is None                                   # EOS at once: nothing read


def test_max_tokens_cap_and_time_budget():
    r = _runner([3, 4, 6, 5, 4, 7, 5], max_tokens=4)
    assert r.recognize(IMG) == r"\frac{a}"                                      # cut after 4 tokens
    assert r._dec.steps == 4
    assert _runner([6, 7, 8, 11, 6, 8], delay=0.01, time_budget=0.0).recognize(IMG) is None


def test_decoder_loops_are_cut_short():
    r = _runner([6, 7, 11] * 40)
    assert r.recognize(IMG) is None
    assert r._dec.steps < 40                                                    # stopped long before the cap
    assert _repeating([1, 2, 3] * 6) and _repeating([5] * 8)
    assert not _repeating(list(range(40))) and not _repeating([1, 2])


# ----------------------------------------------------------------------------- pre / post processing

def test_preprocess_matches_the_processor_config():
    img = Image.new("RGB", (300, 50), (255, 255, 255))
    img.paste((0, 0, 0), (0, 0, 150, 50))                                       # left half black
    x = preprocess(img)
    assert x.shape == (1, 3, IMAGE_SIZE, IMAGE_SIZE) and x.dtype == np.float32
    assert x.min() == pytest.approx(-1.0) and x.max() == pytest.approx(1.0)
    assert x[0, :, :, :100].mean() < -0.9 and x[0, :, :, -100:].mean() > 0.9    # squashed, not cropped
    assert preprocess(Image.new("L", (10, 10), 255)).shape == (1, 3, IMAGE_SIZE, IMAGE_SIZE)


def test_postprocess_compacts_and_repairs():
    assert postprocess(r"\frac { a } { b }") == r"\frac{a}{b}"
    assert postprocess(r"\mathrm { C O } _ { 2 } d \varphi") == r"\mathrm{CO}_{2}d\varphi"
    assert postprocess(r"\partial t \alpha \beta") == r"\partial t\alpha\beta"
    assert postprocess(r"\operatorname* { m i n } \cfrac { 1 } { 2 } \sf x") == r"\operatorname{min}\frac{1}{2}x"
    assert postprocess(r"^ { 2 } x _ { i }") == r"x_{i}"                        # nothing to attach the script to
    assert postprocess(r"\hat { } x _ { } ^ { }") == "x"                        # empty groups
    assert postprocess(r"\begin{aligned} { } & { { } a } \\ { } & { { } = b } \\ \end{aligned}") \
        == r"\begin{aligned}&{a}\\&{=b}\end{aligned}"
    assert postprocess(r"\pmb { x } \mathsf { y }") == r"\boldsymbol{x}\mathrm{y}"
    assert postprocess("") == ""


# ----------------------------------------------------------------------------- model files

def test_models_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(mfr_onnx.MODELS_ENV, str(tmp_path / "m"))
    assert models_dir() == tmp_path / "m"
    monkeypatch.delenv(mfr_onnx.MODELS_ENV)
    assert models_dir().parts[-2:] == ("pdf2word", "models")


def _fake_files(monkeypatch, served: dict):
    """MODEL_FILES / _open_url replaced by tiny in-memory files; returns the download counter."""
    files = {n: (len(b), hashlib.sha256(b).hexdigest()) for n, b in served.items()}
    monkeypatch.setattr(mfr_onnx, "MODEL_FILES", files)
    calls = []

    def _open_url(url, timeout=60.0):
        calls.append(url)
        name = url.rsplit("/", 1)[1]
        data = served[name] if "mirror" not in url else served[name]
        return iter([data[:3], data[3:]]), len(data)
    monkeypatch.setattr(mfr_onnx, "_open_url", _open_url)
    return calls


def test_ensure_model_downloads_verifies_and_reuses(monkeypatch, tmp_path):
    calls = _fake_files(monkeypatch, {"enc.onnx": b"encoder-bytes", "tok.json": b"{}"})
    d = ensure_model(tmp_path)
    assert d == tmp_path and (tmp_path / "enc.onnx").read_bytes() == b"encoder-bytes"
    assert len(calls) == 2 and not list(tmp_path.glob("*.part"))
    ensure_model(tmp_path)
    assert len(calls) == 2                                                      # verified files: no download
    (tmp_path / "tok.json").write_bytes(b"damaged")                             # wrong size -> fetched again
    ensure_model(tmp_path)
    assert len(calls) == 3 and (tmp_path / "tok.json").read_bytes() == b"{}"


def test_ensure_model_rejects_a_bad_download(monkeypatch, tmp_path):
    _fake_files(monkeypatch, {"enc.onnx": b"good"})
    monkeypatch.setattr(mfr_onnx, "_open_url", lambda url, timeout=60.0: (iter([b"evil"]), 4))
    with pytest.raises(ModelError) as info:
        ensure_model(tmp_path)
    assert "sha256" in str(info.value) and str(tmp_path) in str(info.value)
    assert not (tmp_path / "enc.onnx").exists() and not list(tmp_path.glob("*.part"))
    with pytest.raises(ModelError):
        ensure_model(tmp_path, download=False)


def test_callers_deadline_cuts_decoding_short():
    r = _runner([6, 7, 8, 11, 6, 8], delay=0.01)
    assert r.recognize(IMG, deadline=time.time() - 1) is None       # already past
    assert r.recognize(IMG, deadline=time.time() + 60) == "abx2ax"  # far away: untouched
