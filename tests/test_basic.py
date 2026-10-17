"""Unit tests for the pure helpers (no PDF, no network, no OCR model needed).

Run:  python -m pytest tests -q      (or)      python tests/test_basic.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf2word.inlinemath import Span, collect_runs, replace_runs, run_to_latex  # noqa: E402
from pdf2word.mathocr import clean_latex, fix_braces, hint_fixes, looks_garbage  # noqa: E402
from pdf2word.metadata import find_arxiv, find_doi, split_author_line, surname  # noqa: E402
from pdf2word.obsidian import (_abstract_callout, _fix_math_delimiters,  # noqa: E402
                                   _merge_title_lines, citations_to_footnotes, image_link)
from pdf2word.symbols import map_pua  # noqa: E402
from pdf2word.utils import parse_page_range, safe_name, slugify_title, strip_emphasis  # noqa: E402


def test_surname():
    assert surname("Kwang Hee Kim") == "Kim"
    assert surname("Weers, M.") == "Weers"
    assert surname("Ludwig van Beethoven") == "van Beethoven"
    assert surname("Huaqing Ma1,§") == "Ma"
    assert surname("김광희") == "김광희"


def test_identifiers():
    assert find_doi("https://doi.org/10.3390/min12040480 Academic") == "10.3390/min12040480"
    assert find_doi("doi:10.1016/j.powtec.2020.01.001.") == "10.1016/j.powtec.2020.01.001"
    assert find_arxiv("arXiv:2301.12345v2 [cs.LG]") == "2301.12345"
    assert split_author_line("Huaqing Ma1,§, Changhua Xie2 and Yongzhi Zhao2,✉") == \
        ["Huaqing Ma", "Changhua Xie", "Yongzhi Zhao"]


def test_symbol_font_pua():
    assert map_pua("In the above,  is ") == "In the above, ρ is ∂"
    assert map_pua("x") == "x"


def test_latex_hygiene():
    assert clean_latex(r"\mu_{\mathrm{{eff}}}=\mu\qquad\qquad\qquad") == r"\mu_{\mathrm{eff}}=\mu"
    assert looks_garbage(r"\qquad\qquad\qquad\qquad\qquad")
    assert not looks_garbage(r"a+b")
    assert not looks_garbage(r"\begin{array}{c c c}{{1}}&{{0}}&{{0}}\\ {{0}}&{{1}}&{{0}}\end{array}")
    assert fix_braces(r"\frac{a}{b") == r"\frac{a}{b}"
    out = hint_fixes(r"\frac{\hat{Q}\rho}{\hat{Q}t}=0", "∂ρ ∂t = 0")
    assert r"\partial" in out and r"\hat{Q}" not in out


def test_names():
    assert safe_name("_asset-Ma-2025") == "_asset-Ma-2025"
    assert safe_name('a<b>:"c"') == "a-b-c"
    assert slugify_title("Numerical modeling of wet milling by an improved CFD-DEM-VOF model") \
        == "Numerical-modeling-wet-milling-improved-CFD-DEM-VOF"
    assert strip_emphasis("**_2.3 VOF method_**") == "2.3 VOF method"
    assert parse_page_range("1-3,7", 10) == [0, 1, 2, 6]
    assert image_link("_asset-A-2020/fig1.png") == "![[_asset-A-2020/fig1.png]]"
    assert image_link("_asset-A 2020/fig1.png", "fig1", "markdown") == "![fig1](_asset-A%202020/fig1.png)"


def test_math_block_spacing():
    md = "Intro\n$$\na=b\n$$\n^eq-1\ntext after\n"
    assert _fix_math_delimiters(md) == "Intro\n\n$$\na=b\n$$\n^eq-1\n\ntext after\n"


def test_abstract_title_footnotes():
    md = ("# Development of a Model\n# for the Separation\n\nAbstract: " + "x" * 100 +
          "\n\nBody [1] and [2,3] and [4-6].\n\n## References\n\n1. First.\n2. Second.\n3. Third.\n"
          "4. Fourth.\n5. Fifth.\n6. Sixth.\n")
    out = citations_to_footnotes(_abstract_callout(_merge_title_lines(md)))
    assert out.startswith("# Development of a Model for the Separation\n")
    assert "> [!abstract] Abstract\n> xxx" in out
    assert "Body [^1] and [^2][^3] and [^4][^5][^6]." in out
    assert "[^6]: Sixth." in out


# ----------------------------------------------------------------------------- inline text math

PAL, PALI, BOLDI = "PalatinoLinotype-Roman", "PalatinoLinotype-Italic", "PalatinoLinotype-BoldIta"
TNR, TNRI, SYM, PAZO, CMSY = "TimesNewRomanPSMT", "TimesNewRomanPS-ItalicMT", "SymbolMT", "PazoMath", "CMSY10"


def _line(*items, body=10.0, y=100.0):
    """(text, font, size, flags[, dy[, dx]]) -> spans of one line, left to right.
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
    out = []
    for run in collect_runs(spans):
        latex, lead, trail = run_to_latex(run)
        out.append(lead + latex + trail)
    return out


def test_inline_text_math_runs():
    # InDesign: italic variable + small roman subscript on a lower baseline; a lone italic v is prose
    sp = _line(("in which ", PAL, 10, 4), ("m", PALI, 10, 6), ("p", PAL, 6.7, 4, 1.4), (", ", PAL, 10, 4),
               ("v", PALI, 10, 6), (" and ", PAL, 10, 4), ("ρ", PALI, 10, 6), ("f", PAL, 6.7, 4, 1.4), (" is", PAL, 10, 4))
    assert _latex(sp) == ["m_p", r"\rho_{f}"]
    # Word: Symbol-font PUA rho, italic u + small italic i, i-th with the superscript flag, tau_ij
    sp = _line(("In the above, ", TNR, 11, 4), ("", SYM, 11, 0), (" is the density, ", TNR, 11, 4),
               ("u", TNRI, 11, 6), ("i", TNRI, 7, 6, 1.0), (" is the ", TNR, 11, 4), ("i", TNRI, 11, 6),
               ("th", TNR, 7, 5, -4.9), (" component, ", TNR, 11, 4), ("", SYM, 11, 0), ("ij", TNRI, 7, 6, 1.0),
               (" stress", TNR, 11, 4), body=11)
    assert _latex(sp) == [r"\rho", "u_i", r"i^{\mathrm{th}}", r"\tau_{ij}"]
    # pdfTeX: math-font Psi with mixed subscripts and a relation chain, \vec accent glyph, bold vector
    sp = _line(("find", PAL, 10, 4), (" Ψ", PAZO, 10, 4), ("3", PAL, 7.6, 4, 1.8), ("D", PALI, 7.6, 6, 1.8),
               (" ", PAL, 10, 4), ("=", PAL, 10, 4), (" Ψ", PAZO, 10, 4), ("⊥", CMSY, 7.9, 6, 2.1), (". Then ", PAL, 10, 4),
               ("→", CMSY, 10.4, 6, -6.0, -4.5), ("v", PALI, 10, 6), ("f", PALI, 7.6, 6, 1.8), (" and ", PAL, 10, 4),
               ("u", BOLDI, 10, 22), ("j", PALI, 7, 6, 1.5), (" end", PAL, 10, 4))
    assert _latex(sp) == [r"\Psi_{3D} = \Psi_{\perp}", r"\vec{v}_{f}", r"\mathbf{u}_j"]
    # not math: µm glued to a word, italic words, lone two-letter variable, units, citation marks, p < 0.05
    sp = _line(("10", PAL, 10, 4), (" µ", "EURM10", 10, 4), ("m and ", PAL, 10, 4), ("et al.", PALI, 10, 6),
               (" [19] (", PAL, 10, 4), ("Re", PALI, 10, 6), (") kg/m", PAL, 10, 4), ("3", PAL, 7.6, 5, -5.4),
               (" ", PAL, 10, 4), ("as", PALI, 10, 6), ("12", PAL, 7, 5, -5), (" ", PAL, 10, 4), ("p", PALI, 10, 6),
               (" < 0.05", PAL, 10, 4))
    assert _latex(sp) == []


def test_inline_text_math_replace():
    sp = _line(("in which ", PAL, 10, 4), ("m", PALI, 10, 6), ("p", PAL, 6.7, 4, 1.4), (", ", PAL, 10, 4),
               ("ρ", PALI, 10, 6), ("f", PAL, 6.7, 4, 1.4), (" and ", PAL, 10, 4), ("h", TNRI, 10, 6),
               ("i", TNRI, 7, 6, 1.0), (", the", PAL, 10, 4))
    runs = collect_runs(sp)
    new, found, missed = replace_runs("in a simple case _m_ p, _ρ_ f and _hi_ , the", runs)
    assert new == "in a simple case $m_p$, $\\rho_{f}$ and $h_i$, the" and not missed
    new, found, missed = replace_runs("unrelated text", runs)            # never damage the body text
    assert new == "unrelated text" and len(missed) == 3
    new, _, _ = replace_runs("see $m_p$ then _m_ p", runs[:1])              # not inside existing math
    assert new == "see $m_p$ then $m_p$"
    sp = _line(("where ", PAL, 10, 4), ("d", PALI, 10, 6), ("2", PAL, 7, 5, -4), ("→", CMSY, 10.4, 6, -6.0, -4.5),
               ("x", PALI, 10, 6), ("i", PALI, 7, 6, 1.5), ("/", PAL, 10, 4), ("dt", PALI, 10, 6), ("2", PAL, 7, 5, -4),
               (" is", PAL, 10, 4))
    new, _, _ = replace_runs("where _d_<sup>2</sup><sup>_→_</sup> _x i_ / _dt_<sup>2</sup> is", collect_runs(sp))
    assert new == "where $d^2 \\vec{x}_{i} / dt^2$ is"
    sp = _line(("( ", PAL, 10, 4), ("F", PALI, 10, 6), ("i", PALI, 7.6, 6, 1.8), (")", PAL, 10, 5),
               (", centrifugal-", PAL, 10, 5))
    new, _, _ = replace_runs("( _F i_<sup>), centrifugal-</sup> force", collect_runs(sp))
    assert new == "( $F_i$<sup>), centrifugal-</sup> force"            # a <sup> pair is never torn apart


def test_caption_detection():
    from pdf2word.converter import looks_like_caption
    assert looks_like_caption("**Figure 2.** Particle size distributions of the used materials.")
    assert looks_like_caption("**Figure 3** Sketch diagram of the single particle sedimentation.")
    assert looks_like_caption("Table A1. Additional parameters set in the DEM simulations.")
    assert not looks_like_caption("Figure 1 shows Scanning Electron Microscope (SEM) micrographs of particles.")
    assert not looks_like_caption("Figure 6 (right) shows the measured initial particle velocity.")
    assert not looks_like_caption("Figure 13b shows the experimental and predicted separation curves.")


def test_ocr_confidence_and_cleanups():
    from pdf2word.mathocr import hint_similarity
    from pdf2word.obsidian import _clean_front_matter, _fix_tables, _split_merged_references
    good = r"F_{z}=\rho_{P}V_{P}\frac{v_{\varphi,P}^{2}}{r}"
    bad = r"F_{z}\underline{{{\bf\Psi}}}_{\mu\nu}\frac{\upsilon}{r}"
    hint = "Fz = ρP VP v2 φ,P r (1)"
    assert hint_similarity(good, hint) > 0.85 > hint_similarity(bad, hint)
    assert hint_similarity(bad, "") == 1.0                      # no text layer: cannot judge
    assert _fix_tables("|a|b|\n|---|---|\n|i\nStiffness k|0.86|\n") == "|a|b|\n|---|---|\n|i Stiffness k|0.86|\n"
    refs = _split_merged_references("## References\n\n2. Galk, J. Köln, 1995. 3. Bauer, U. Aachen, 2002.\n")
    assert "\n2. Galk, J. Köln, 1995.\n\n3. Bauer, U. Aachen, 2002.\n" in refs
    md = "_Article_\n\n## Title\n\n**Martin Weers**<sup>**1,**</sup> **and Alfred Weber**<sup>**1**</sup>\n\n## 1. Intro\n"
    out = _clean_front_matter(md)                               # title may still be '##' at this stage
    assert "_Article_" not in out and "Martin Weers<sup>1,</sup> and Alfred Weber<sup>1</sup>" in out


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except AssertionError as exc:
                failures += 1
                print("FAIL", name, exc)
    raise SystemExit(1 if failures else 0)
