"""Inline *text* mathematics -> ``$...$``.

The text layer of a PDF keeps inline formulas such as ``ρ_f`` or ``u_i`` as ordinary
characters: a Greek letter from a math/Symbol font, an italic one-letter variable, and a
smaller span shifted below (subscript) or above (superscript) the baseline.  pymupdf4llm
turns those into ``_ρ_ f`` / ``_u_ i`` / ``_d_<sup>2</sup>`` which neither reads nor renders
well.  This module

1. groups the spans of a text box into visual lines (:func:`group_lines`),
2. classifies the spans (math symbol, italic variable, sub-/superscript, operator glue) and
   joins neighbouring ones into *runs* (:func:`collect_runs`),
3. renders a run as LaTeX (:func:`run_to_latex`), and
4. locates the run inside the Markdown produced by pymupdf4llm with an emphasis-tolerant
   regular expression and replaces it by ``$...$`` (:func:`replace_runs`).  A run that cannot
   be located leaves the Markdown untouched: the body text is never damaged.

The heuristics are deliberately conservative: a run must contain a Greek letter / math
symbol or a sub-/superscript attached to a variable; lone italic words are never touched
(``_et al._``, ``_Re_``), and a symbol glued to ordinary letters (``µm``) is left alone.
Everything except :func:`extract_spans` / :func:`inline_text_math` is pure and testable
without a PDF.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Optional

import pymupdf

from .symbols import UNICODE_TO_LATEX, map_pua

# ----------------------------------------------------------------------------- tunables

SMALL_RATIO = 0.86        # span size below this fraction of the body size -> script candidate
SHIFT_RATIO = 0.05        # ...whose baseline is shifted by at least this fraction of the body size
LINE_TOL = 3.0            # pt: spans whose line top or bottom differ by less share a visual line
GLUE_GAP = 0.3            # fraction of the font size: a smaller gap to a word means "glued" (µm)
MAX_SCRIPT_LEN = 14       # longest sub-/superscript text we accept

TEXT_FLAGS = pymupdf.TEXTFLAGS_RAWDICT & ~pymupdf.TEXT_PRESERVE_IMAGES & ~pymupdf.TEXT_PRESERVE_LIGATURES

MATH_FONT_RE = re.compile(
    r"CM[A-Z]+\d|Symbol|Math|Pazo|EU[RSF]M\d|MSAM|MSBM|RSFS|MTMI|MTSY|MTEX|STIX|Euclid", re.I)

_GREEK_LOWER = "αβγδεζηθικλμνξοπρστυφχψω" + "ϑϕϖϱςϵ"
_GREEK_UPPER = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
#: characters that behave like letters in a formula (a run needs one of these or a script)
LETTER_SYMBOLS = frozenset(_GREEK_LOWER + _GREEK_UPPER + "∂∇∞ℓħ")
#: characters that may glue two parts of a run together but never make a run on their own
OPERATORS = frozenset("=+−-×·⋅∙/<>≤≥≠≈≡∝±∓∼≃→←↔⇒⇔∈∉⊂⊃⊆⊇∪∩∧∨⊥∥∘∗′″∑∏∫√⊗⊕∣∀∃∅…⋯≪≫")
#: Greek capitals that look like Latin letters have no LaTeX command
_GREEK_CAPS_LOOKALIKE = dict(zip("ΑΒΕΖΗΙΚΜΝΟΡΤΧ", "ABEZHIKMNOPTX"))
_GREEK_LOWER_LOOKALIKE = {"ο": "o"}

_SCRIPT_RE = re.compile(r"^(?=.*[\w∞⊥∥′*+\-−])[\w,.;:()+\-−*/′'∞⊥∥∗∘·⋅ ]{1,%d}$" % MAX_SCRIPT_LEN)
_SHORT_SUP_RE = re.compile(r"^(?=.*\w)[\w′*−-]{1,2}$")       # body-size span flagged superscript
#: glyphs that pdfTeX places above a letter for \vec, \bar, \hat, \tilde, \dot ...
_ACCENT_GLYPHS = {"→": "vec", "⃗": "vec", "¯": "bar", "ˉ": "bar", "‾": "bar",
                  "ˆ": "hat", "˜": "tilde", "˙": "dot", "¨": "ddot", "ˇ": "check",
                  "˘": "breve"}
ACCENT_RAISE = 0.25       # accent glyph baseline must sit this fraction of the body size above the line
_TWO_LETTER_VAR = re.compile(r"^(?:[A-Z][a-z]|[A-Z]{2}|d[A-Za-z])$")   # Re, Pr, Da, CD, dt, dx
_TRAIL_PUNCT = re.compile(r"[,.;:]+$")
_OP_CHARS = "".join(sorted(OPERATORS))

ATOM_KINDS = frozenset({"var", "sym", "op", "sub", "sup", "accent"})


# ----------------------------------------------------------------------------- spans

@dataclass
class Span:
    """The subset of a PyMuPDF ``dict`` span that the heuristics need.

    ``y0``/``y1`` are the top/bottom of the *MuPDF line* the span belongs to (as pymupdf4llm
    uses them), ``baseline`` is the y of the glyph origin.  ``kind`` is filled by
    :func:`classify_spans`: ``text`` | ``space`` | ``var`` | ``sym`` | ``op`` | ``sub`` | ``sup``.
    """
    text: str
    font: str = ""
    size: float = 10.0
    flags: int = 0
    x0: float = 0.0
    x1: float = 0.0
    y0: float = 0.0
    y1: float = 0.0
    baseline: float = 0.0
    kind: str = field(default="", compare=False)
    attach: int = field(default=0, compare=False)      # accent: id() of the span it decorates

    @property
    def italic(self) -> bool:
        return bool(self.flags & 2)

    @property
    def sup_flag(self) -> bool:
        return bool(self.flags & 1)

    @property
    def bold(self) -> bool:
        return bool(self.flags & 16)

    @property
    def math_font(self) -> bool:
        return bool(MATH_FONT_RE.search(self.font or ""))

    @property
    def clean(self) -> str:
        """Text with Symbol-font PUA code points mapped and math alphanumerics folded to ASCII."""
        return normalize(self.text).strip()


def normalize(text: str) -> str:
    """map_pua + fold Mathematical Alphanumeric Symbols (𝑍 -> Z), ligatures and the micro sign.

    (A blanket NFKC would also turn ϕ into φ and ϑ into θ, which changes the LaTeX command.)
    """
    out = []
    for ch in map_pua(text or ""):
        o = ord(ch)
        if 0x1D400 <= o <= 0x1D7FF or ch in "ﬀﬁﬂﬃﬄ":
            ch = unicodedata.normalize("NFKC", ch) or ch
        elif ch == "µ":            # micro sign -> mu
            ch = "μ"
        elif ch == "Ω":            # ohm sign -> Omega
            ch = "Ω"
        out.append(ch)
    return "".join(out)


def extract_spans(page, rect) -> list[Span]:
    """All horizontal text spans of ``page`` inside ``rect`` (a layout box), unmerged.

    Uses ``rawdict`` so the baseline can be taken from the span's non-blank characters: a
    subscript span often starts with a synthetic space that MuPDF places on the body baseline,
    which would hide the shift if the span origin were used.
    """
    clip = pymupdf.Rect(rect)
    clip = pymupdf.Rect(clip.x0 - 1, clip.y0 - 1, clip.x1 + 1, clip.y1 + 1) & page.rect
    if clip.is_empty:
        return []
    try:
        blocks = page.get_text("rawdict", clip=clip, flags=TEXT_FLAGS)["blocks"]
    except Exception:
        return []
    spans: list[Span] = []
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            direction = line.get("dir", (1, 0))
            if abs(direction[0] - 1) > 1e-3:          # rotated text
                continue
            ly0, ly1 = line["bbox"][1], line["bbox"][3]
            for sp in line.get("spans", []):
                chars = sp.get("chars") or []
                text = "".join(c["c"] for c in chars)
                if not text:
                    continue
                ys = sorted(c["origin"][1] for c in chars if not c["c"].isspace())
                baseline = ys[len(ys) // 2] if ys else chars[0]["origin"][1]
                x0 = min(c["bbox"][0] for c in chars)
                x1 = max(c["bbox"][2] for c in chars)
                spans.append(Span(text, sp.get("font", ""), float(sp["size"]), int(sp["flags"]),
                                  float(x0), float(x1), float(ly0), float(ly1), float(baseline)))
    return spans


# ----------------------------------------------------------------------------- lines & classification

def _weighted_median(values: list) -> float:
    """values: [(value, weight)] -> weighted median."""
    items = sorted(values)
    half = sum(w for _, w in items) / 2.0
    acc = 0.0
    for v, w in items:
        acc += w
        if acc >= half:
            return v
    return items[-1][0]


def body_size(spans: Iterable[Span]) -> float:
    """Dominant font size of a text box (character-weighted median, superscripts excluded)."""
    vals = [(s.size, len(s.text.strip())) for s in spans if s.text.strip() and not s.sup_flag]
    return _weighted_median(vals) if vals else 10.0


def group_lines(spans: Iterable[Span], tol: float = LINE_TOL) -> list[list[Span]]:
    """Group spans into visual lines the way pymupdf4llm does (top or bottom within ``tol``),
    additionally accepting spans that vertically overlap the line by more than half their
    height (sub-/superscripts MuPDF put into a line of their own).  Spans are left-to-right."""
    ordered = sorted(spans, key=lambda s: (s.y1, s.x0))
    lines: list[list[Span]] = []
    for s in ordered:
        if lines:
            last = lines[-1][-1]
            same = abs(s.y1 - last.y1) <= tol or abs(s.y0 - last.y0) <= tol
            if not same:
                overlap = min(s.y1, last.y1) - max(s.y0, last.y0)
                h = min(s.y1 - s.y0, last.y1 - last.y0)
                same = h > 0 and overlap > 0.5 * h
            if same:
                lines[-1].append(s)
                continue
        lines.append([s])
    for line in lines:
        line.sort(key=lambda s: s.x0)
    return lines


def _var_like(core: str) -> bool:
    """A single variable: 1-2 Latin letters or one Greek letter, optionally wrapped in operators."""
    core = core.strip(" \xa0" + _OP_CHARS)
    if not core:
        return False
    if len(core) == 1:
        return core.isalpha() or core in LETTER_SYMBOLS
    if len(core) == 2 and core.isascii() and core.isalpha():
        return bool(_TWO_LETTER_VAR.match(core))
    return False


def _symbolish(core: str) -> bool:
    """Only math characters (symbols, operators, digits, brackets) and at least one symbol."""
    found = False
    for ch in core:
        if ch in LETTER_SYMBOLS or ch in OPERATORS:
            found = True
        elif not (ch.isspace() or ch.isdigit() or ch in "()[],."):
            return False
    return found


def _classify(s: Span, body: float, baseline: Optional[float]) -> str:
    if not s.text.strip():
        return "space"
    clean = s.clean
    small = s.size < SMALL_RATIO * body
    down = up = False
    if small and baseline is not None:
        dy = s.baseline - baseline
        down = dy > SHIFT_RATIO * body
        up = dy < -SHIFT_RATIO * body
    # MuPDF also flags body-size spans as superscript now and then ("<sup>),which</sup>");
    # accept those only when they are as short as a real exponent.
    script_ok = bool(_SCRIPT_RE.match(clean)) and (small or (s.sup_flag and _SHORT_SUP_RE.match(clean)))
    if (s.sup_flag or up) and script_ok:
        return "sup"
    if down and script_ok:
        return "sub"
    if clean in _ACCENT_GLYPHS and baseline is not None and s.baseline < baseline - ACCENT_RAISE * body:
        return "accent"                    # attached to a neighbour (or demoted) by _attach_accents
    if small:
        return "text"                      # small but on the baseline: footnote-size text etc.
    core = _TRAIL_PUNCT.sub("", clean)
    if core and all(ch in OPERATORS or ch.isspace() for ch in core):
        return "op"                        # "=", "−", "×" in any font: glue only
    if s.math_font:
        if _var_like(core):
            return "var"
        return "sym" if _symbolish(core) else "text"
    if s.italic:
        return "var" if _var_like(core) else "text"
    if len(core) == 1 and core in LETTER_SYMBOLS:
        return "sym"                       # Greek letter set in the text font (Word documents)
    return "text"


def _attach_accents(line: list[Span]) -> None:
    """An accent glyph decorates the neighbouring variable it overlaps horizontally; without
    such a neighbour it is an ordinary operator (an arrow) or text."""
    for k, s in enumerate(line):
        if s.kind != "accent":
            continue
        best, best_overlap = None, 0.0
        for side in (line[k - 1::-1] if k else [], line[k + 1:]):
            for t in side:
                if t.kind == "space":
                    continue
                if t.kind in ("var", "sym"):
                    overlap = min(s.x1, t.x1) - max(s.x0, t.x0)
                    if overlap > best_overlap:
                        best, best_overlap = t, overlap
                break
        if best is None:
            s.kind = "op" if s.clean in OPERATORS else "text"
        else:
            s.attach = id(best)


def classify_spans(line: list[Span], body: float) -> None:
    """Fill ``kind`` for every span of one visual line."""
    base = [s for s in line if s.text.strip() and not s.sup_flag and s.size >= SMALL_RATIO * body]
    baseline = _weighted_median([(s.baseline, len(s.text.strip())) for s in base]) if base else None
    for s in line:
        s.kind = _classify(s, body, baseline)
    _attach_accents(line)


# ----------------------------------------------------------------------------- runs

def _has_letter_symbol(s: Span) -> bool:
    return any(ch in LETTER_SYMBOLS for ch in s.clean)


def _segment(atoms: list[Span]) -> list[list[Span]]:
    """Split a stretch of atom spans into runs: a script needs a base (variable, symbol or
    another script) right before it, operators cannot start or end a run."""
    out: list[list[Span]] = []
    cur: list[Span] = []
    for s in atoms:
        if s.kind in ("sub", "sup"):
            prev = next((t for t in reversed(cur) if t.kind != "accent"), None)
            if prev is not None and prev.kind in ("var", "sym", "sub", "sup"):
                cur.append(s)
            else:                              # script without a base: breaks the run
                if cur:
                    out.append(cur)
                cur = []
        else:
            cur.append(s)
    if cur:
        out.append(cur)
    runs = []
    for run in out:
        while run and run[0].kind == "op":
            run = run[1:]
        while run and run[-1].kind == "op":
            run = run[:-1]
        if run:
            runs.append(run)
    return runs


def _qualifies(run: list[Span]) -> bool:
    kinds = [s.kind for s in run]
    if not any(k in ("var", "sym") for k in kinds):
        return False
    has_script = any(k in ("sub", "sup", "accent") for k in kinds)
    has_symbol = any(_has_letter_symbol(s) for s in run if s.kind in ("var", "sym"))
    return has_script or has_symbol


def _glued(line: list[Span], run: list[Span]) -> bool:
    """True when the run touches ordinary letters without a space ("µm", "α-phase")."""
    first, last = run[0], run[-1]
    idx = {id(s): i for i, s in enumerate(line)}
    i0, i1 = idx[id(first)], idx[id(last)]
    if i0 > 0:
        prev = line[i0 - 1]
        if (prev.kind != "space" and not prev.text[-1:].isspace() and not first.text[:1].isspace()
                and prev.text[-1:].isalnum() and first.x0 - prev.x1 < GLUE_GAP * first.size):
            return True
    if i1 + 1 < len(line):
        nxt = line[i1 + 1]
        ch = nxt.text[:1]
        if (nxt.kind != "space" and not ch.isspace() and not last.text[-1:].isspace()
                and (ch.isalnum() or ch in "-–") and nxt.x0 - last.x1 < GLUE_GAP * last.size):
            return True
    return False


def collect_runs(spans: Iterable[Span], body: Optional[float] = None) -> list[list[Span]]:
    """Inline-math runs (lists of consecutive spans, whitespace spans dropped) in reading order."""
    spans = [s for s in spans if s.text]
    if not spans:
        return []
    if body is None:
        body = body_size(spans)
    runs: list[list[Span]] = []
    for line in group_lines(spans):
        classify_spans(line, body)
        i, n = 0, len(line)
        while i < n:
            if line[i].kind not in ATOM_KINDS:
                i += 1
                continue
            j = i
            while j < n and (line[j].kind in ATOM_KINDS or line[j].kind == "space"):
                j += 1
            atoms = [s for s in line[i:j] if s.kind != "space"]
            for run in _segment(atoms):
                if _qualifies(run) and not _glued(line, run):
                    runs.append(run)
            i = j
    return runs


# ----------------------------------------------------------------------------- LaTeX

_ACCENTS = {"̂": "hat", "̃": "tilde", "̄": "bar", "̅": "bar", "̇": "dot",
            "̈": "ddot", "̌": "check", "̆": "breve", "⃗": "vec"}


def char_to_latex(ch: str) -> str:
    if ch in UNICODE_TO_LATEX:
        return UNICODE_TO_LATEX[ch].strip()
    if ch in _GREEK_CAPS_LOOKALIKE or ch in _GREEK_LOWER_LOOKALIKE:
        return _GREEK_CAPS_LOOKALIKE.get(ch) or _GREEK_LOWER_LOOKALIKE[ch]
    decomposed = unicodedata.normalize("NFD", ch)
    if len(decomposed) == 2 and decomposed[1] in _ACCENTS and decomposed[0].isalpha():
        return "\\%s{%s}" % (_ACCENTS[decomposed[1]], char_to_latex(decomposed[0]))   # Î -> \hat{I}
    return ch


def _tokens(text: str) -> list[str]:
    """Split clean span text into LaTeX tokens: words/numbers, commands (\\rho), operators."""
    toks: list[str] = []
    buf = ""
    for ch in text:
        if ch.isspace():
            if buf:
                toks.append(buf)
                buf = ""
            continue
        lat = char_to_latex(ch)
        if ch in OPERATORS or lat != ch or ch in LETTER_SYMBOLS:
            if buf:
                toks.append(buf)
                buf = ""
            toks.append(lat)
        else:
            buf += ch
    if buf:
        toks.append(buf)
    return toks


def _smart_join(parts: list[str]) -> str:
    """Concatenate, inserting a space only where a command would swallow the next letter."""
    out = ""
    for p in parts:
        if not p:
            continue
        if out and re.search(r"\\[A-Za-z]+$", out) and p[0].isalnum():
            out += " "
        out += p
    return out


def _upright(tok: str) -> str:
    if tok.startswith("\\"):
        return tok
    return re.sub(r"[A-Za-z]{2,}", lambda m: r"\mathrm{" + m.group(0) + "}", tok)


def _embolden(tok: str) -> str:
    """Bold variables are vectors/tensors: u -> \\mathbf{u}, \\tau -> \\boldsymbol{\\tau}."""
    if re.fullmatch(r"\\[A-Za-z]+", tok) and tok not in _OP_LATEX:
        return r"\boldsymbol{" + tok + "}"
    if re.fullmatch(r"[A-Za-z]+", tok):
        return r"\mathbf{" + tok + "}"
    return tok


def _script_text(spans: list[Span], texts: dict) -> str:
    parts = []
    for s in spans:
        toks = _tokens(texts[id(s)])
        if not s.italic and not s.math_font:
            toks = [_upright(t) for t in toks]
        parts.append(_smart_join(toks))
    return _smart_join(parts)


_LEAD_OPS = re.compile(r"^[\s%s]+" % re.escape(_OP_CHARS))
_TRAIL_OPS = re.compile(r"[\s%s]+$" % re.escape(_OP_CHARS))
_OP_LATEX = frozenset(char_to_latex(c) for c in OPERATORS)


def run_to_latex(run: list[Span]) -> tuple[str, str, str]:
    """-> (latex, text to put before the formula, text to put after it).

    Operators at the very start/end of the run ("ψ=" set in one Symbol-font span) and trailing
    punctuation ("P,") are moved outside of ``$...$``.
    """
    atoms = [s for s in run if s.kind != "space"]
    if not atoms:
        return "", "", ""
    texts = {id(s): s.clean for s in atoms}
    first_id, last_id = id(atoms[0]), id(atoms[-1])
    trail = ""
    m = _TRAIL_PUNCT.search(texts[last_id])
    if m and m.start() > 0:
        trail = m.group(0)
        texts[last_id] = texts[last_id][:m.start()]
    m = _TRAIL_OPS.search(texts[last_id])
    if m and m.start() > 0:
        trail = " " + m.group(0).strip() + trail
        texts[last_id] = texts[last_id][:m.start()]
    lead = ""
    m = _LEAD_OPS.match(texts[first_id])
    if m and m.end() < len(texts[first_id]):
        lead = m.group(0).strip() + " "
        texts[first_id] = texts[first_id][m.end():]
    tokens: list[str] = []
    i = 0
    while i < len(atoms):
        s = atoms[i]
        if s.kind in ("sub", "sup", "accent"):     # scripts/accents are consumed by their base
            i += 1
            continue
        toks = _tokens(texts[id(s)])
        if s.bold:
            toks = [_embolden(t) for t in toks]
        accents = [a for a in atoms if a.kind == "accent" and a.attach == id(s)]
        if accents and (not toks or toks[-1] in _OP_LATEX):
            toks.append("{}")
        for a in accents:                          # \vec{v}
            toks[-1] = "\\%s{%s}" % (_ACCENT_GLYPHS[a.clean], toks[-1])
        j = i + 1
        groups: list[tuple[str, list[Span]]] = []
        while j < len(atoms) and atoms[j].kind in ("sub", "sup", "accent"):
            if atoms[j].kind != "accent":
                if groups and groups[-1][0] == atoms[j].kind:
                    groups[-1][1].append(atoms[j])
                else:
                    groups.append((atoms[j].kind, [atoms[j]]))
            j += 1
        if groups:
            if not toks or toks[-1] in _OP_LATEX:
                toks.append("{}")
            base = toks[-1]
            plain = re.fullmatch(r"[A-Za-z]+|\\mathbf\{[A-Za-z]+\}", base) is not None
            tail = ""
            for kind, group in groups:
                content = _script_text(group, texts)
                if not content:
                    continue
                if kind == "sup" and re.fullmatch(r"'+", content):
                    tail += content
                    continue
                wrap = not (len(content) == 1 and content.isascii() and content.isalnum() and plain)
                tail += ("_" if kind == "sub" else "^") + ("{" + content + "}" if wrap else content)
            toks[-1] = base + tail
        tokens += toks
        i = j
    latex = " ".join(t for t in tokens if t)
    if "$" in latex or not latex.strip():
        return "", "", ""
    return latex, lead, trail


# ----------------------------------------------------------------------------- locate & replace

_GLUE = r"(?:[*_`\s]|<sup>|</sup>){0,8}"


def _char_pattern(ch: str) -> str:
    if ch.isspace():
        return r"\s*"
    alts = {ch}
    for alt in (map_pua(ch), normalize(ch)):
        if alt and alt != ch:
            alts.add(alt)
    if len(alts) == 1:
        return re.escape(ch)
    return "(?:" + "|".join(re.escape(a) for a in sorted(alts, key=len, reverse=True)) + ")"


def run_pattern(run: list[Span]) -> re.Pattern:
    """Regex that finds the run's text inside pymupdf4llm Markdown, ignoring emphasis markers,
    ``<sup>`` tags and whitespace between spans (``_ρ_ f``, ``_ui_``, ``_d_<sup>2</sup>``)."""
    parts = []
    for s in run:
        text = s.text.strip()
        if not text:
            continue
        parts.append(r"[*_`]*".join(_char_pattern(ch) for ch in text))
    body = _GLUE.join(parts)
    return re.compile(r"(?<![A-Za-z0-9\\])(?:[*_`]|<sup>)*" + body + r"(?:[*_`]|</sup>)*(?![A-Za-z0-9])")


def _search_outside_math(pat: re.Pattern, text: str, pos: int):
    while True:
        m = pat.search(text, pos)
        if m is None or text.count("$", 0, m.start()) % 2 == 0:
            return m
        pos = m.end()


def replace_runs(seg: str, runs: list[list[Span]]) -> tuple[str, list[tuple[str, str]], list[str]]:
    """Replace each run inside ``seg`` by ``$latex$``.

    -> (new text, [(matched markdown, replacement)], [runs not found]).  Runs are searched in
    reading order starting after the previous replacement; an unlocated run is skipped.
    """
    found: list[tuple[str, str]] = []
    missed: list[str] = []
    pos = 0
    for run in runs:
        source = " ".join(s.text.strip() for s in run if s.text.strip())
        latex, lead, trail = run_to_latex(run)
        if not latex:
            missed.append(source)
            continue
        m = _search_outside_math(run_pattern(run), seg, pos)
        if m is None or m.group(0).count("<sup>") != m.group(0).count("</sup>"):
            missed.append(source)              # not found, or would tear a <sup>...</sup> pair apart
            continue
        repl = f"{lead}${latex}${trail}"
        tail = seg[m.end():]
        mm = re.match(r"[ \t]+(?=[,.;:)])", tail)    # "_h_ i , is" -> "$h_i$, is"
        if mm:
            tail = tail[mm.end():]
        seg = seg[:m.start()] + repl + tail
        pos = m.start() + len(repl)
        found.append((m.group(0), repl))
    return seg, found, missed


def inline_text_math(page, bbox, seg: str) -> tuple[str, list[tuple[str, str]], list[str]]:
    """Convert the text-layer inline math of one layout box: -> (markdown, found, missed)."""
    runs = collect_runs(extract_spans(page, bbox))
    if not runs:
        return seg, [], []
    return replace_runs(seg, runs)
