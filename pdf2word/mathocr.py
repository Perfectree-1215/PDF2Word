"""Equation OCR: render a page region, split it into lines, recognise LaTeX, validate.

Engines
-------
* ``rapid``  - RapidLaTeXOCR (ONNX port of pix2tex / LaTeX-OCR). Local, CPU, free.
               Single-line model, so multi-line equations are split into rows first.
* ``claude`` - Claude vision (Anthropic API). Much more accurate, handles multi-line
               equations natively. Needs ``pip install anthropic`` and ``ANTHROPIC_API_KEY``.
* ``none``   - no OCR; equations are embedded as cropped images.
"""
from __future__ import annotations

import base64
import difflib
import hashlib
import io
import json
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pymupdf
from PIL import Image

from .symbols import UNICODE_TO_LATEX
from .utils import cache_dir

log = logging.getLogger("pdf2word")

LABEL_RE = re.compile(r"^\s*\(\s*([0-9]{1,3}[a-zA-Z]?(?:[.\-\u2013][0-9]{1,3}[a-z]?)?)\s*\)\s*$")
_SPACE_CMD = r"(?:\\[,;:! ]|\\quad|\\qquad|~)"
# text extraction without decoding embedded images (decoding 100+ bitmaps per page is very slow)
TEXT_FLAGS = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES


# ----------------------------------------------------------------------------- image helpers

def render(page: pymupdf.Page, rect, zoom: float) -> Image.Image:
    clip = pymupdf.Rect(rect) & page.rect
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False)
    mode = "RGB" if pix.n == 3 else ("L" if pix.n == 1 else "RGBA")
    return Image.frombytes(mode, (pix.width, pix.height), pix.samples).convert("L")


def ink_mask(img: Image.Image, thresh: int = 200) -> np.ndarray:
    return np.asarray(img) < thresh


def tight_crop(img: Image.Image, pad: int = 12, thresh: int = 200) -> Optional[Image.Image]:
    """Crop to the ink bounding box (+ white padding). None if the image is blank."""
    mask = ink_mask(img, thresh)
    if not mask.any():
        return None
    ys, xs = np.where(mask)
    crop = img.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    out = Image.new("L", (crop.width + 2 * pad, crop.height + 2 * pad), 255)
    out.paste(crop, (pad, pad))
    return out


def split_rows(img: Image.Image, min_gap: int, thresh: int = 200) -> list:
    """Row bands [(y0, y1), ...] separated by >= min_gap blank pixel rows.

    Very thin bands (fraction bars, dots, accents) are merged into their neighbours.
    """
    rows = ink_mask(img, thresh).sum(axis=1)
    bands = []
    start = last = None
    gap = 0
    for y, v in enumerate(rows):
        if v:
            if start is None:
                start = y
            last = y
            gap = 0
        elif start is not None:
            gap += 1
            if gap >= min_gap:
                bands.append((start, last + 1))
                start = None
                gap = 0
    if start is not None:
        bands.append((start, last + 1))
    if len(bands) > 1:
        med = float(np.median([b - a for a, b in bands]))
        merged = []
        for band in bands:
            tiny = (band[1] - band[0]) < 0.35 * med
            prev_tiny = merged and (merged[-1][1] - merged[-1][0]) < 0.35 * med
            if merged and (tiny or prev_tiny):
                merged[-1] = (merged[-1][0], band[1])
            else:
                merged.append(band)
        bands = merged
    return bands


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def find_labels(page: pymupdf.Page, rect) -> list:
    """Equation numbers '(3)' inside rect, right-aligned: [(label, Rect)] sorted top->bottom."""
    rect = pymupdf.Rect(rect)
    labels = []
    try:
        blocks = page.get_text("dict", clip=rect, flags=TEXT_FLAGS)["blocks"]
    except Exception:
        return labels
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            text = "".join(s["text"] for s in line["spans"])
            m = LABEL_RE.match(text)
            if not m:
                continue
            lb = pymupdf.Rect(line["bbox"])
            if lb.x0 > rect.x0 + 0.45 * rect.width:
                labels.append((m.group(1), lb))
    labels.sort(key=lambda t: t[1].y0)
    return labels


# ----------------------------------------------------------------------------- LaTeX hygiene

def clean_latex(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\\label\{[^}]*\}", "", s)
    s = re.sub(r"\\tag\*?\{[^}]*\}", "", s)
    s = re.sub(r"\\[vh]phantom\{[^{}]*\}", "", s)
    s = re.sub(r"\\(mathrm|mathbf|mathit|mathcal|operatorname|text|mathsf)\{\{([^{}]*)\}\}", r"\\\1{\2}", s)
    s = re.sub(r"\{\\cal\s+([A-Za-z])\}", r"\\mathcal{\1}", s)
    s = re.sub(r"\\cal\s+([A-Za-z])", r"\\mathcal{\1}", s)
    # \stackrel{\rightarrow}{v} -> \vec{v},  \stackrel{\sim}{x} -> \tilde{x}
    s = re.sub(r"\\stackrel\{\\rightarrow\}\{([^{}]*)\}", r"\\vec{\1}", s)
    s = re.sub(r"\\stackrel\{\\rightarrow\}(\\[A-Za-z]+\{[^{}]*\}|\\?[A-Za-z0-9])", r"\\vec{\1}", s)
    s = re.sub(r"\\stackrel\{\\sim\}\{([^{}]*)\}", r"\\tilde{\1}", s)
    s = re.sub(r"\\stackrel\{\\wedge\}\{([^{}]*)\}", r"\\hat{\1}", s)
    s = re.sub(r"\\mathrm\{exp\}", r"\\exp", s)
    # pix2tex spells words letter by letter: 'r a d' -> 'rad' (runs of >= 3 single letters)
    s = re.sub(r"(?<![A-Za-z\\])([A-Za-z](?: [A-Za-z]){2,})(?![A-Za-z])",
               lambda m: m.group(1).replace(" ", ""), s)
    s = re.sub(rf"(?:\s*{_SPACE_CMD}){{3,}}", r" \\quad ", s)
    s = re.sub(rf"^(?:{_SPACE_CMD}\s*)+", "", s)
    s = re.sub(rf"(?:\s*{_SPACE_CMD})+\s*$", "", s)
    # an equation number that slipped into the crop: '... \quad (12)' at the very end
    s = re.sub(rf"(?:(?:\s|{_SPACE_CMD})+|(?<![A-Za-z0-9_}}\]]))\(\s*\d{{1,3}}[a-z]?\s*\)\s*$", "", s)
    s = re.sub(rf"(?:\s*{_SPACE_CMD})+\s*$", "", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def _brace_counts(s: str):
    s = s.replace("\\{", "").replace("\\}", "")
    return s.count("{"), s.count("}")


def braces_balanced(s: str) -> bool:
    depth = 0
    for ch in s.replace("\\{", "").replace("\\}", ""):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def fix_braces(s: str) -> str:
    opened, closed = _brace_counts(s)
    if 0 < opened - closed <= 2:
        s += "}" * (opened - closed)
    # unmatched \left / \right make MathJax refuse the whole block: drop the sizing commands
    if s.count(r"\left") != s.count(r"\right"):
        s = re.sub(r"\\(left|right)(?=[\s(\[|.{\\)\]])", "", s)
    return s


def environments_balanced(s: str) -> bool:
    begins = re.findall(r"\\begin\{([a-zA-Z*]+)\}", s)
    ends = re.findall(r"\\end\{([a-zA-Z*]+)\}", s)
    return sorted(begins) == sorted(ends)


def looks_garbage(s: str, max_len: int = 600) -> bool:
    if not s or len(s) > max_len:
        return True
    if re.search(r"(.{4,30}?)(?:\1){4,}", s):            # runaway repetition
        return True
    if s.count(r"\qquad") >= 4 or s.count(r"\quad") >= 8:
        return True
    if len(re.findall(r"\\(?:hat|widehat|tilde|widetilde|dot|bar|overline)\{", s)) > 14:
        return True
    if not braces_balanced(s) or not environments_balanced(s):
        return True
    if not re.search(r"[A-Za-z0-9]", s):
        return True
    return False


def hint_fixes(latex: str, hint: str) -> str:
    """Use the PDF text layer of the region to repair typical OCR confusions."""
    if not hint:
        return latex
    out = latex
    if "\u2202" in hint and r"\partial" not in out:            # ∂ -> \hat{C}, \tilde{\phi} ...
        n = hint.count("\u2202")
        cands = Counter(re.findall(r"\\(?:hat|widehat|tilde|widetilde|dot|ddot|bar|mathcal)\{\\?[A-Za-z]{1,10}\}", out))
        for tok, c in cands.most_common(3):
            if abs(c - n) <= max(1, n // 2):
                out = out.replace(tok, r"\partial ")
                break
    if "\u2202" in hint:
        # \frac{<accent>{..}..}{<accent>{..}t} is the \u2202/\u2202t pattern: both accents are \u2202
        acc = r"\\(?:hat|widehat|tilde|widetilde|dot|ddot|bar|mathcal)\{((?:[^{}]|\{[^{}]*\})*)\}"
        inner = r"(?:[^{}]|\{[^{}]*\})*"

        def _partial(arg: str) -> str:
            # keep a variable swallowed by the accent: \hat{\sqrt{t}} -> \partial t
            m = re.fullmatch(r"\\[a-zA-Z]+\{([a-zA-Z])\}", arg.strip())
            return r"\partial " + (m.group(1) if m else "")

        out = re.sub(rf"(\\frac\{{){acc}({inner}\}}\{{){acc}",
                     lambda m: m.group(1) + _partial(m.group(2)) + m.group(3) + _partial(m.group(4)), out)
        out = re.sub(rf"(\\frac\{{)\\partial ({inner}\}}\{{){acc}",
                     lambda m: m.group(1) + r"\partial " + m.group(2) + _partial(m.group(3)), out)
        out = re.sub(rf"(\\frac\{{){acc}({inner}\}}\{{)\\partial ",
                     lambda m: m.group(1) + _partial(m.group(2)) + m.group(3) + r"\partial ", out)
    # d/dt misread as Q/dt
    out = re.sub(r"(\\frac\{)\\mathrm\{Q\}((?:[^{}]|\{[^{}]*\})*\}\{\\mathrm\{d\})", r"\1\\mathrm{d}\2", out)
    out = re.sub(r"(\\frac\{)Q((?:[^{}]|\{[^{}]*\})*\}\{d[ \\a-zA-Z])", r"\1d\2", out)
    if "\u2211" in hint and r"\sum" not in out:
        out = out.replace(r"\Sigma", r"\sum")
    if "\u2207" in hint and r"\nabla" not in out:
        out = re.sub(r"\\rlap\{?/\}?\\nabla|\\triangledown|\\bigtriangledown", r"\\nabla", out)
    if "\u222b" in hint and r"\int" not in out:
        out = out.replace(r"\smallint", r"\int")
    return re.sub(r"\s{2,}", " ", out).strip()


# ----------------------------------------------------------------------------- confidence

_SYMBOL_NAMES = {cmd.strip("\\ ") for cmd in UNICODE_TO_LATEX.values() if cmd.startswith("\\")}
_HINT_MAP = {ch: cmd.strip("\\ ") for ch, cmd in UNICODE_TO_LATEX.items() if cmd.startswith("\\")}
CONFIDENCE_OK = 0.75          # stop trying other render scales above this similarity
CONFIDENCE_LOW = 0.6          # below this the result is flagged for the reader


def _hint_letters(hint: str) -> str:
    hint = re.sub(r"\(\s*\d{1,3}[a-z]?\s*\)\s*$", "", (hint or "").strip())
    out = []
    for ch in hint:
        if ch in _HINT_MAP:
            out.append(_HINT_MAP[ch])
        elif ch.isascii() and ch.isalnum():
            out.append(ch)
    return "".join(out)


def _latex_letters(latex: str) -> str:
    s = re.sub(r"\\tag\*?\{[^}]*\}", "", latex or "")
    s = re.sub(r"\\(?:begin|end)\{[a-zA-Z*]+\}", " ", s)
    s = re.sub(r"\\([A-Za-z]+)", lambda m: m.group(1) if m.group(1) in _SYMBOL_NAMES else " ", s)
    return "".join(ch for ch in s if ch.isascii() and ch.isalnum())


def hint_similarity(latex: str, hint: str) -> float:
    """How well the OCR result matches the PDF text layer of the same region (0..1).

    Compares the sequences of letters/digits/Greek names; 1.0 when the region has no usable
    text layer (equations set as images), so image-only PDFs are never penalised."""
    a, b = _hint_letters(hint), _latex_letters(latex)
    if len(a) < 3:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


# ----------------------------------------------------------------------------- cache

class OCRCache:
    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.path = cache_dir() / "mathocr-cache.json"
        self.data: dict = {}
        self.dirty = False
        if enabled and self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                self.data = {}

    VERSION = "2"           # bump when clean-up rules change (invalidates old entries)

    @classmethod
    def key(cls, engine: str, png: bytes) -> str:
        return hashlib.sha1(f"{engine}:{cls.VERSION}".encode("utf-8") + b"\0" + png).hexdigest()

    def get(self, key: str):
        return self.data.get(key) if self.enabled else None

    def set(self, key: str, value: str) -> None:
        if self.enabled:
            self.data[key] = value
            self.dirty = True

    def save(self) -> None:
        if not (self.enabled and self.dirty):
            return
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
            self.dirty = False
        except Exception as exc:
            log.debug("cache save failed: %s", exc)


# ----------------------------------------------------------------------------- engines

class MathEngine:
    name = "base"
    multiline = False           # True: engine accepts whole multi-line equation images

    def recognize(self, img: Image.Image, hint: str = "") -> Optional[str]:
        raise NotImplementedError


class RapidEngine(MathEngine):
    """RapidLaTeXOCR (ONNX, CPU). First call downloads ~170 MB of weights."""
    name = "rapid"

    def __init__(self, max_tokens: int = 320):
        self.max_tokens = max_tokens
        self._model = None

    def _load(self):
        if self._model is None:
            from rapid_latex_ocr import LaTeXOCR
            log.info("  loading RapidLaTeXOCR model ...")
            self._model = LaTeXOCR()
            try:
                self._model.encoder_decoder.max_seq_len = int(self.max_tokens)
            except Exception:
                pass
        return self._model

    def recognize(self, img: Image.Image, hint: str = "") -> Optional[str]:
        model = self._load()
        res, _elapsed = model(png_bytes(img.convert("RGB")))
        return res or None


class ClaudeEngine(MathEngine):
    """Claude vision via the Anthropic SDK (server-side refusal fallbacks enabled)."""
    name = "claude"
    multiline = True
    PROMPT = (
        "Transcribe the mathematical expression in this image into LaTeX.\n"
        "Rules: output ONLY the LaTeX code - no $ delimiters, no \\tag, no explanations, no code fences. "
        "For multi-line equations use \\begin{aligned} ... \\end{aligned} with \\\\ line breaks and & before = signs. "
        "Keep bold/vector notation (\\mathbf) and subscripts exactly as printed. "
        "If the image does not contain a formula, output exactly EMPTY."
    )

    def __init__(self, model: str = "claude-opus-5-5", effort: str = "low"):
        import anthropic  # optional dependency
        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self._use_fallbacks = True
        self._use_effort = True

    def _create(self, kwargs: dict):
        a = self._anthropic
        if self._use_effort:
            kwargs = dict(kwargs, output_config={"effort": self.effort})
        if self._use_fallbacks:
            try:
                return self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
            except TypeError:                      # SDK too old for `fallbacks`/`output_config`
                self._use_fallbacks = False
            except a.BadRequestError as exc:
                log.debug("fallback form rejected (%s); retrying plain request", exc)
                self._use_fallbacks = False
        try:
            return self.client.messages.create(**kwargs)
        except TypeError:
            self._use_effort = False
            kwargs.pop("output_config", None)
            return self.client.messages.create(**kwargs)

    def recognize(self, img: Image.Image, hint: str = "") -> Optional[str]:
        a = self._anthropic
        data = base64.standard_b64encode(png_bytes(img.convert("RGB"))).decode("utf-8")
        text = self.PROMPT
        if hint:
            text += ("\n\nText layer extracted from the PDF for this region (may be garbled or "
                     "out of order; use only as a hint for symbols):\n" + hint[:800])
        kwargs = dict(
            model=self.model, max_tokens=2048,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
                {"type": "text", "text": text},
            ]}],
        )
        for attempt in range(3):
            try:
                resp = self._create(kwargs)
                break
            except a.RateLimitError as exc:
                wait = min(int(exc.response.headers.get("retry-after", "15") or 15), 60)
                log.warning("  Claude rate limited; waiting %ss", wait)
                time.sleep(wait)
            except a.APIStatusError as exc:
                log.warning("  Claude API error %s: %s", exc.status_code, getattr(exc, "message", exc))
                return None
            except a.APIConnectionError as exc:
                log.warning("  Claude connection error: %s", exc)
                return None
        else:
            return None
        if getattr(resp, "stop_reason", None) == "refusal":
            return None
        out = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
        return self._strip(out)

    @staticmethod
    def _strip(text: str) -> Optional[str]:
        text = text.strip()
        text = re.sub(r"^```(?:latex|tex)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
        if text.upper() in ("EMPTY", "NONE", ""):
            return None
        text = re.sub(r"^\$\$?", "", text)
        text = re.sub(r"\$\$?$", "", text).strip()
        text = re.sub(r"^\\\[", "", text)
        text = re.sub(r"\\\]$", "", text).strip()
        return text or None


def build_engine(name: str, **kw) -> Optional[MathEngine]:
    name = (name or "rapid").lower()
    if name in ("none", "off", "image"):
        return None
    if name == "rapid":
        return RapidEngine(max_tokens=kw.get("max_tokens", 320))
    if name == "claude":
        try:
            return ClaudeEngine(model=kw.get("model", "claude-opus-5-5"), effort=kw.get("effort", "low"))
        except ImportError as exc:
            raise SystemExit("math engine 'claude' needs the Anthropic SDK: pip install anthropic") from exc
    raise SystemExit(f"unknown math engine: {name}")


# ----------------------------------------------------------------------------- orchestration

@dataclass
class EquationResult:
    latex: Optional[str]
    image: Optional[Image.Image]
    lines: int = 1
    cached: bool = False
    seconds: float = 0.0
    confidence: float = 1.0      # similarity to the PDF text layer (1.0 = no text layer to compare)

    @property
    def uncertain(self) -> bool:
        return self.latex is not None and self.confidence < CONFIDENCE_LOW


class EquationOCR:
    def __init__(self, engine: Optional[MathEngine], zooms=(2.0, 3.0, 4.0),
                 cache: bool = True, min_gap_pt: float = 3.0):
        self.engine = engine
        self.zooms = tuple(zooms) or (2.0,)
        self.cache = OCRCache(cache)
        self.min_gap_pt = min_gap_pt
        self.calls = 0
        self.cache_hits = 0

    # -- single image -------------------------------------------------------
    def recognize_image(self, img: Image.Image, hint: str = "") -> Optional[str]:
        """OCR one (already tight-cropped) image; returns validated LaTeX or None."""
        if self.engine is None:
            return None
        png = png_bytes(img)
        key = self.cache.key(self.engine.name, png)
        cached = self.cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            return hint_fixes(clean_latex(cached), hint) or None
        self.calls += 1
        t0 = time.time()
        try:
            raw = self.engine.recognize(img, hint)
        except Exception as exc:
            log.warning("  OCR failed: %s", exc)
            raw = None
        latex = hint_fixes(clean_latex(raw or ""), hint)
        latex = fix_braces(latex)
        if looks_garbage(latex):
            log.debug("  OCR rejected (%.1fs): %r", time.time() - t0, latex[:120])
            latex = ""
        else:
            log.debug("  OCR ok (%.1fs): %s", time.time() - t0, latex[:120])
        self.cache.set(key, latex)
        return latex or None

    # -- page region --------------------------------------------------------
    def recognize_region(self, page: pymupdf.Page, rect, hint: str = "") -> EquationResult:
        t0 = time.time()
        rect = pymupdf.Rect(rect)
        base_zoom = self.zooms[0]
        base = tight_crop(render(page, rect, max(base_zoom, 2.0)))
        if base is None:
            return EquationResult(None, None, 0)
        if self.engine is None:
            return EquationResult(None, base, 1, seconds=time.time() - t0)

        if self.engine.multiline:
            latex = self.recognize_image(base, hint)
            if latex is None and len(self.zooms) > 1:
                alt = tight_crop(render(page, rect, self.zooms[1]))
                latex = self.recognize_image(alt, hint) if alt is not None else None
            conf = hint_similarity(latex, hint) if latex else 0.0
            return EquationResult(latex, base, 1, seconds=time.time() - t0, confidence=conf)

        # line-based engine: split the region into text rows, OCR each row. The result is
        # checked against the PDF text layer; a poor match is retried at the other render
        # scales and the best-matching candidate wins.
        best_latex, best_conf, best_lines = None, -1.0, 0
        for zoom in self.zooms:
            latex, n_lines = self._recognize_lines(page, rect, zoom, hint)
            if not latex:
                continue
            conf = hint_similarity(latex, hint)
            if conf > best_conf:
                best_latex, best_conf, best_lines = latex, conf, n_lines
            if conf >= CONFIDENCE_OK:
                break
        if best_latex is None:
            return EquationResult(None, base, 0, seconds=time.time() - t0)
        return EquationResult(best_latex, base, best_lines, seconds=time.time() - t0, confidence=best_conf)

    def _recognize_lines(self, page: pymupdf.Page, rect: pymupdf.Rect, zoom: float, hint: str):
        """Split the region into rows at `zoom`, OCR each (other scales as fallback per row)."""
        full = render(page, rect, zoom)
        bands = split_rows(full, min_gap=max(3, int(round(self.min_gap_pt * zoom))))
        if not bands:
            return None, 0
        line_rects = [pymupdf.Rect(rect.x0, rect.y0 + a / zoom - 1, rect.x1, rect.y0 + b / zoom + 1)
                      for a, b in bands]
        order = [zoom] + [z for z in self.zooms if z != zoom]
        pieces = []
        for lr in line_rects:
            latex = None
            for z in order:
                img = tight_crop(render(page, lr, z))
                if img is None:
                    continue
                latex = self.recognize_image(img, hint)
                if latex:
                    break
            if not latex:
                return None, len(line_rects)
            pieces.append(latex)
        if len(pieces) == 1:
            return pieces[0], 1
        return "\\begin{gathered}\n" + " \\\\\n".join(pieces) + "\n\\end{gathered}", len(pieces)
