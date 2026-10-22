"""Pix2Text MFR 1.5 formula recogniser on onnxruntime alone - no torch, no transformers.

The model (https://huggingface.co/breezedeus/pix2text-mfr-1.5, MIT) is a TrOCR: a DeiT encoder
that takes a 384x384 image and a 6-layer text decoder without a key-value cache, so every
decoding step re-runs the decoder over the whole prefix. Its three files (120 MB) are fetched on
first use into the models folder and verified by size and sha256 (docs/decisions/math-engine-pix2text.md).
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

log = logging.getLogger("pdf2word")

MODEL_NAME = "pix2text-mfr-1.5"
MODEL_FILES = {                                   # name: (bytes, sha256) of the 2026-10-22 files
    "encoder_model.onnx": (87510770, "080a3f660f08bc9ebcacdd96e34be6b6400f8c7e62d7cd0dd8251badc37f610b"),
    "decoder_model.onnx": (32026253, "917deb98e91a0453c5f234f58a0f32f9fb037de8527c7eb4ed394daf9e692f2a"),
    "tokenizer.json": (113168, "4ffbeb2143e6a38324bb6111b7a8109530d38a076a8439aa5777535f0a32758a"),
}
MODEL_REVISION = "1cef9f0bdcd6a4c63df7de1311fb0894593340cc"   # the commit the hashes above belong to
MODEL_URLS = (f"https://huggingface.co/breezedeus/pix2text-mfr-1.5/resolve/{MODEL_REVISION}/",
              f"https://hf-mirror.com/breezedeus/pix2text-mfr-1.5/resolve/{MODEL_REVISION}/")
MODELS_ENV = "PDF2WORD_MODELS"

IMAGE_SIZE = 384                                  # preprocessor_config.json: resize, bicubic, (x/255 - 0.5) / 0.5
BOS, EOS = 1, 2                                   # generation_config.json: decoder_start_token_id, eos_token_id
MAX_TOKENS = 640                                  # a two-line equation needs ~330; decoding is quadratic in length
TIME_BUDGET = 60.0                                # seconds per image; EquationOCR also caps the whole equation
THREADS = 4                                       # intra-op threads: as fast as the default 12 at a third of the CPU time


class ModelError(RuntimeError):
    """The model files are missing and could not be fetched (offline, firewall, Hugging Face down)."""


# ----------------------------------------------------------------------------- model files

def models_dir() -> Path:
    """Where downloaded models live: $PDF2WORD_MODELS, else %LOCALAPPDATA%/pdf2word/models on
    Windows and ~/.cache/pdf2word/models elsewhere. Never the project folder (it may be a synced
    cloud folder with a non-ASCII path) and never site-packages (shared between projects)."""
    env = os.environ.get(MODELS_ENV)
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / "pdf2word" / "models"


def model_dir() -> Path:
    return models_dir() / MODEL_NAME


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def file_ok(path: Path, size: int, sha256: str) -> bool:
    return path.is_file() and path.stat().st_size == size and _sha256(path) == sha256


def _open_url(url: str, timeout: float = 60.0):
    """(iterator of byte chunks, Content-Length or None). Replaced by the tests."""
    import requests
    r = requests.get(url, stream=True, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    length = r.headers.get("Content-Length")
    return r.iter_content(chunk_size=1 << 20), (int(length) if length else None)


def download_file(name: str, dest: Path, size: int, sha256: str) -> None:
    """Fetch one model file through a .part file; keep it only when size and hash match."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    errors = []
    for base in MODEL_URLS:
        url = base + name
        try:
            chunks, length = _open_url(url)
            if length is not None and length != size:
                raise ModelError(f"unexpected size {length} (want {size})")
            done = 0
            with open(part, "wb") as f:
                for chunk in chunks:
                    f.write(chunk)
                    done += len(chunk)
            if not file_ok(part, size, sha256):
                raise ModelError(f"size or sha256 mismatch after download ({done} bytes)")
            part.replace(dest)
            log.info("  downloaded %s (%.0f MB)", name, size / 1e6)
            return
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            try:
                part.unlink()
            except OSError:
                pass
    raise ModelError("; ".join(errors))


def ensure_model(directory: Optional[Path] = None, download: bool = True) -> Path:
    """The folder holding verified model files, downloading what is missing or damaged.
    Raises ModelError with the folder and the URLs in the message when that fails."""
    directory = Path(directory) if directory else model_dir()
    missing = [n for n, (size, sha) in MODEL_FILES.items() if not file_ok(directory / n, size, sha)]
    if not missing:
        return directory
    if not download:
        raise ModelError(f"model files missing in {directory}: {', '.join(missing)}")
    log.info("  fetching the %s model (%d file(s), %.0f MB) into %s ...", MODEL_NAME, len(missing),
             sum(MODEL_FILES[n][0] for n in missing) / 1e6, directory)
    try:
        for n in missing:
            download_file(n, directory / n, *MODEL_FILES[n])
    except ModelError as exc:
        raise ModelError(
            f"could not fetch {MODEL_NAME} ({exc}). Put {', '.join(MODEL_FILES)} from {MODEL_URLS[0]} "
            f"into {directory} by hand, or set {MODELS_ENV} to a folder that has {MODEL_NAME}/") from exc
    return directory


# ----------------------------------------------------------------------------- pre / post processing

def preprocess(img: Image.Image) -> np.ndarray:
    """PIL image -> float32 [1, 3, 384, 384] exactly as TrOCRProcessor / DeiTImageProcessor does
    (RGB, bicubic resize to a square, 1/255 in float64, then (x - 0.5) / 0.5)."""
    rgb = img.convert("RGB").resize((IMAGE_SIZE, IMAGE_SIZE), Image.BICUBIC)
    x = (np.asarray(rgb).astype(np.float64) * (1.0 / 255.0)).astype(np.float32)
    x = (x - np.float32(0.5)) / np.float32(0.5)
    return np.ascontiguousarray(x.transpose(2, 0, 1)[None])


_TOKEN_RE = re.compile(r"\\[A-Za-z]+\*?|\\.|\S")
#: commands that take an argument: with an empty one ('\hat{}', '\mathrm{}') they draw nothing
_ARG_CMDS = frozenset((
    "hat widehat tilde widetilde bar vec dot ddot check breve acute grave overline underline "
    "overrightarrow overleftarrow mathrm mathbf mathit mathcal mathbb mathsf mathtt mathfrak mathscr "
    "boldsymbol bm text textrm textbf textit operatorname sqrt underbrace overbrace").split())
_EMPTY_GROUP_RE = re.compile(r"(\\[A-Za-z]+|[_^])?\{\}(?=([_^])?)")
_FONT_SWITCH_RE = re.compile(r"\\(?:sf|tt|it)(?![A-Za-z])\s*")


def _drop_empty(m: re.Match) -> str:
    """Replacement for an empty group found by _EMPTY_GROUP_RE."""
    head = m.group(1) or ""
    if head in ("_", "^") or head[1:] in _ARG_CMDS:
        return ""                              # an empty script, an accent / font command on nothing
    if head:
        return m.group(0)                      # '\to{}': the {} only ends the command word - keep it
    return m.group(0) if m.group(2) else ""    # '{}^{14}': the empty base of a pre-script stays


def postprocess(text: str) -> str:
    """The tokenizer's output has a space between every token ('\\frac { a } { b }'): join the
    tokens (a space stays only between a control word or a row break and a letter), drop the
    empty groups that draw nothing (an empty script, accent or font command; the {} after an
    argument-less command and the empty base of a pre-script '{}^{14}' stay) and the leading
    '^{..}' / '_{..}' the model sometimes emits, and spell what pdf2word's renderers
    expect (\\frac for \\cfrac, \\operatorname without the star, no \\sf / \\tt / \\it)."""
    tokens = _TOKEN_RE.findall(text or "")
    out = []
    for tok in tokens:
        if out and (re.fullmatch(r"\\[A-Za-z]+", out[-1]) or out[-1] == "\\\\") and tok[0].isalpha():
            out.append(" ")
        out.append(tok)
    s = "".join(out)
    s = _FONT_SWITCH_RE.sub("", s)
    s = re.sub(r"\\mathsf\{", r"\\mathrm{", s)
    s = re.sub(r"\\pmb\{", r"\\boldsymbol{", s)
    s = re.sub(r"\\[cdt]frac(?![A-Za-z])", r"\\frac", s)
    s = s.replace("\\operatorname*", "\\operatorname")
    for _ in range(10):
        new = _EMPTY_GROUP_RE.sub(_drop_empty, s)
        if new == s:
            break
        s = new
    s = re.sub(r"^(?:[_^]\{[^{}]*\})+", "", s)                        # a script with nothing to attach to
    s = re.sub(r"(?:\\\\\s*)+(?=\\end\{)", "", s)                      # trailing line break in an environment
    return s.strip()


# ----------------------------------------------------------------------------- runner

def _repeating(ids: list, span: int = 32, min_repeats: int = 4, max_period: int = 8) -> bool:
    """True when the tail of `ids` is a cycle of 1-8 tokens repeated over at least `span` tokens
    (and at least min_repeats times): the model is looping and the rest would be garbage anyway.
    A short run of one id is ordinary LaTeX - four closing braces, '{cccc}', '10000' - so
    period 1 needs 32 equal ids and period 8 four repeats."""
    for period in range(1, max_period + 1):
        reps = max(min_repeats, -(-span // period))
        n = period * reps
        if len(ids) < n:
            continue                           # (not break: n is not monotonic in period)
        tail = ids[-n:]
        if tail == tail[-period:] * reps:
            return True
    return False


class MFRRunner:
    """Encoder + decoder sessions and the greedy decoding loop. `sessions` / `tokenizer` can be
    injected (the tests use fakes); otherwise they are created from the models folder on first use."""

    def __init__(self, max_tokens: int = MAX_TOKENS, time_budget: float = TIME_BUDGET,
                 sessions=None, tokenizer=None):
        self.max_tokens = int(max_tokens)
        self.time_budget = float(time_budget)
        self._enc, self._dec = sessions if sessions else (None, None)
        self._tok = tokenizer

    def load(self) -> "MFRRunner":
        if self._enc is None or self._dec is None:
            import onnxruntime as ort
            directory = ensure_model()
            opts = ort.SessionOptions()
            opts.log_severity_level = 3
            opts.intra_op_num_threads = max(1, min(THREADS, os.cpu_count() or THREADS))
            opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
            providers = ["CPUExecutionProvider"]
            self._enc = ort.InferenceSession(str(directory / "encoder_model.onnx"), opts, providers=providers)
            self._dec = ort.InferenceSession(str(directory / "decoder_model.onnx"), opts, providers=providers)
        if self._tok is None:
            from tokenizers import Tokenizer
            directory = ensure_model()
            self._tok = Tokenizer.from_file(str(directory / "tokenizer.json"))
        return self

    def decode_ids(self, hidden: np.ndarray, deadline: Optional[float] = None) -> Optional[list]:
        """Greedy token ids for one encoded image; None when the decoder loops or runs out of time
        (the per-image budget, or the caller's `deadline` in time.time() terms, whichever is first)."""
        names = [i.name for i in self._dec.get_inputs()]
        id_name = next((n for n in names if "ids" in n), names[0])
        hid_name = next((n for n in names if "hidden" in n), names[-1])
        ids = [BOS]
        t0 = time.time()
        stop_at = t0 + self.time_budget if deadline is None else min(t0 + self.time_budget, deadline)
        while len(ids) - 1 < self.max_tokens:
            logits = self._dec.run(None, {id_name: np.asarray([ids], dtype=np.int64), hid_name: hidden})[0]
            nxt = int(np.argmax(logits[0, -1]))
            if nxt == EOS:
                break
            ids.append(nxt)
            if _repeating(ids):
                log.debug("  p2t: decoder loops after %d tokens", len(ids) - 1)
                return None
            if time.time() > stop_at:
                log.warning("  p2t: time budget exhausted after %d tokens (%.0fs)", len(ids) - 1, time.time() - t0)
                return None
        return ids[1:]

    def recognize(self, img: Image.Image, deadline: Optional[float] = None) -> Optional[str]:
        self.load()
        pixel = preprocess(img)
        hidden = self._enc.run(None, {self._enc.get_inputs()[0].name: pixel})[0]
        ids = self.decode_ids(hidden, deadline)
        if not ids:
            return None
        text = postprocess(self._tok.decode(ids, skip_special_tokens=True))
        return text or None
