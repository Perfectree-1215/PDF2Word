"""pdf2word/inlinemath.py - placing text-layer runs in the pymupdf4llm Markdown without touching the
prose around them. Synthetic spans and Markdown strings only (no PDF, no model).

Run:  python -m pytest tests/test_inlinemath.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf2word.inlinemath import Span, collect_runs, replace_runs, run_to_latex  # noqa: E402

PAL, PALI, BOLDI = "PalatinoLinotype-Roman", "PalatinoLinotype-Italic", "PalatinoLinotype-BoldIta"
CMMI, CMR, CMSY7 = "CMMI10", "CMR7", "CMSY7"


def _line(*items, body=10.0, y=100.0):
    """(text, font, size, flags[, dy[, dx]]) -> spans of one line, left to right (as in test_basic).
    dy shifts the baseline (down is positive), dx shifts the *next* span (negative = overlap)."""
    spans, x = [], 50.0
    for it in items:
        text, font, size, flags = it[:4]
        dy = it[4] if len(it) > 4 else 0.0
        dx = it[5] if len(it) > 5 else 0.0
        w = 0.5 * size * len(text)
        spans.append(Span(text, font, size, flags, x, x + w, y - body, y + 0.3 * body, y + dy))
        x += w + dx
    return spans


def _latex(spans):
    return [lead + latex + trail for latex, lead, trail in (run_to_latex(r) for r in collect_runs(spans))]


def _prose(md: str) -> str:
    """The Markdown with every $...$ taken out: what is left must keep its emphasis markers paired."""
    return re.sub(r"\$[^$]*\$", "", md)


# ----------------------------------------------------------------------------- prose words (#52)

#: (variable, script, Markdown of the box - the prose word comes first -, expected Markdown)
PROSE_WORDS = [
    ("u", "p", "the particles move up as the slip velocity _u_ p grows",
     "the particles move up as the slip velocity $u_p$ grows"),
    ("a", "s", "taken as the sound speed _a_ s of the gas",
     "taken as the sound speed $a_s$ of the gas"),
    ("a", "t", "measured at the wall, where _a_ t is the acceleration",
     "measured at the wall, where $a_t$ is the acceleration"),
    ("m", "s", "a pulse of 5 ms where _m_ s is the solid mass",
     "a pulse of 5 ms where $m_s$ is the solid mass"),
    ("m", "in", "after 10 min the inlet mass _m_ in drops",
     r"after 10 min the inlet mass $m_{\mathrm{in}}$ drops"),
    ("a", "1", "a 1 mm gap is set and _a_ 1 is the first coefficient",
     "a 1 mm gap is set and $a_1$ is the first coefficient"),
]


def test_inline_text_math_skips_prose_words():
    for var, script, md, want in PROSE_WORDS:
        sp = _line(("x ", PAL, 10, 4), (var, PALI, 10, 6), (script, PAL, 6.7, 4, 1.4), (" y", PAL, 10, 4))
        new, found, missed = replace_runs(md, collect_runs(sp))
        assert new == want and len(found) == 1 and not missed, md
        word = md.split(" _")[0]
        assert new.startswith(word), md                       # the prose before the run is untouched
    # the italic run is not in the Markdown at all: the prose word that spells it stays
    sp = _line(("x ", PAL, 10, 4), ("u", PALI, 10, 6), ("p", PAL, 6.7, 4, 1.4), (" y", PAL, 10, 4))
    md = "the particles move up as the gas slows down"
    assert replace_runs(md, collect_runs(sp)) == (md, [], ["u p"])


def test_unmarked_ascii_run_is_placed_only_when_unambiguous():
    # math-font variable without the italic flag + roman subscript: the Markdown has no marker around it
    sp = _line(("x ", PAL, 10, 4), ("u", CMMI, 10, 4), ("p", CMR, 6.7, 4, 1.4), (" y", PAL, 10, 4))
    runs = collect_runs(sp)
    md = "the particles move up as the slip velocity up grows"
    assert replace_runs(md, runs) == (md, [], ["u p"])         # which 'up' is the variable? leave both
    assert replace_runs("the slip velocity up grows", runs)[0] == "the slip velocity $u_p$ grows"
    # two such runs and exactly two stretches that spell them: placed in reading order
    sp = _line(("x ", PAL, 10, 4), ("u", CMMI, 10, 4), ("p", CMR, 6.7, 4, 1.4), (" and ", PAL, 10, 4),
               ("u", CMMI, 10, 4), ("p", CMR, 6.7, 4, 1.4), (" y", PAL, 10, 4))
    runs = collect_runs(sp)
    assert len(runs) == 2
    new, found, missed = replace_runs("the velocity u p grows and u p decays", runs)
    assert new == "the velocity $u_p$ grows and $u_p$ decays" and len(found) == 2 and not missed
    md = "we move up as the velocity u p grows and u p decays"  # one stretch too many: nothing is placed
    assert replace_runs(md, runs) == (md, [], ["u p", "u p"])


def test_marked_run_inside_a_longer_emphasis_group():
    # an all-italic sentence: pymupdf4llm writes one _..._ group, so no marker touches the variable
    sp = _line(("In this regime the slip velocity ", PALI, 10, 6), ("u", PALI, 10, 6), ("p", PALI, 6.7, 6, 1.4),
               (" is small", PALI, 10, 6))
    runs = collect_runs(sp)
    md = "_In this regime the slip velocity u p is small compared to the gas speed._"
    assert replace_runs(md, runs)[0] == "_In this regime the slip velocity $u_p$ is small compared to the gas speed._"
    md = "_The particles move up as the slip velocity u p grows._"      # a look-alike word: leave both
    assert replace_runs(md, runs) == (md, [], ["u p"])
    # no English word spells a Greek run: the first stretch is the run
    sp = _line(("the density ", PALI, 10, 6), ("ρ", PALI, 10, 6), ("f", PALI, 6.7, 6, 1.4), (" of", PALI, 10, 6))
    new, found, missed = replace_runs("_the density ρ f of the fluid_", collect_runs(sp))
    assert new == r"_the density $\rho_{f}$ of the fluid_" and not missed


# ----------------------------------------------------------------------------- emphasis groups (#53)

def test_inline_text_math_keeps_emphasis_groups_closed():
    # pymupdf4llm merges an italic prose word and an italic variable into one _..._ group
    sp = _line(("so-called ", PAL, 10, 4), ("in situ ", PALI, 10, 6), ("u", CMMI, 10, 6), ("p", PAL, 6.7, 4, 1.4),
               (" denotes", PAL, 10, 4))
    md = "The so-called _in situ u_ p denotes the slip velocity."
    new, found, missed = replace_runs(md, collect_runs(sp))
    assert new == "The so-called _in situ $u_p$_ denotes the slip velocity." and len(found) == 1 and not missed
    assert _prose(new).count("_") % 2 == 0
    sp = _line(("value ", PAL, 10, 4), ("u", CMMI, 10, 6), ("p", CMMI, 6.7, 6, 1.4), (" in situ", PALI, 10, 6),
               (" denotes", PAL, 10, 4))
    new, _, _ = replace_runs("The value _up in situ_ denotes the slip velocity.", collect_runs(sp))
    assert new == "The value _$u_p$ in situ_ denotes the slip velocity."
    assert _prose(new).count("_") % 2 == 0
    # a bold-italic group: both markers go back outside, in the order that closes the group
    sp = _line(("the ", PAL, 10, 4), ("velocity ", BOLDI, 10, 22), ("u", BOLDI, 10, 22), ("i", PAL, 7, 4, 1.5),
               (" is", PAL, 10, 4))
    new, _, missed = replace_runs("the **_velocity u_** i is constant", collect_runs(sp))
    assert new == r"the **_velocity $\mathbf{u}_i$_** is constant" and not missed
    assert _prose(new).count("_") % 2 == 0 and _prose(new).count("**") % 2 == 0
    # a run whose markers are all inside the match is unchanged by this
    sp = _line(("x ", PAL, 10, 4), ("u", PALI, 10, 6), ("p", PAL, 6.7, 4, 1.4), (" y", PAL, 10, 4))
    assert replace_runs("so _u_ p is", collect_runs(sp))[0] == "so $u_p$ is"


# ----------------------------------------------------------------------------- asterisk operator (#55)

def test_inline_text_math_asterisk_operator_superscript():
    for star in ("*", "\u2217"):                            # ASCII asterisk and the math asterisk operator
        sp = _line(("where ", PAL, 10, 4), ("u", CMMI, 10, 6), (star, CMSY7, 7, 6, -4.0), (" is", PAL, 10, 4))
        assert len(_latex(sp)) == 1, star
    sp = _line(("where ", PAL, 10, 4), ("u", CMMI, 10, 6), ("\u2217", CMSY7, 7, 6, -4.0), (" is", PAL, 10, 4))
    assert _latex(sp) == [r"u^{\ast}"]
    assert replace_runs("where _u_<sup>\u2217</sup> is the", collect_runs(sp))[0] == r"where $u^{\ast}$ is the"
