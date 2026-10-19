"""tools/bench_mathocr.py: the pure parts (summary, LaTeX normalisation, golden-set scoring).
No PDF, no model."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from bench_mathocr import normalize_latex, score_against_golden, summarize  # noqa: E402

# paper-01 eq. (1): what rapid read, and what a person wrote (bold, \left\{ ... \right\})
EQ1_OCR = (r"\frac{\partial\Psi}{\partial t}=\left(I-\Psi_{\theta}\Psi_{\theta}^{+}\right)"
           r"\bigg\{F(\Psi)+\frac{d}{\rho}\chi\circ\Psi_{\theta\theta}\circ\chi\bigg\}")
EQ1_GOLD = (r"\frac{\partial\boldsymbol{\Psi}}{\partial t}=\left(I-\boldsymbol{\Psi}_{\theta}"
            r"\boldsymbol{\Psi}_{\theta}^{+}\right)\left\{F(\boldsymbol{\Psi})+\frac{d}{\rho}"
            r"\boldsymbol{\chi}\circ\boldsymbol{\Psi}_{\theta\theta}\circ\boldsymbol{\chi}\right\}")
# paper-01 eq. (4): rapid read the tildes as bars and the double prime as \varphi_2
EQ4_OCR = (r"\bar{f}=\int_{\varphi_{\mathrm{min}}}^{\varphi_{\mathrm{max}}}f(\varphi)\bar{p}"
           r"(\varphi;\tilde{Y}_{\mathrm{CO}_{2}},\tilde{Y}_{\mathrm{CO}_{2}}^{\varphi_{2}})d\varphi,")
EQ4_GOLD = (r"\tilde{f}=\int_{\varphi_{\min}}^{\varphi_{\max}}f(\varphi)\tilde{p}"
            r"(\varphi;\tilde{Y}_{CO_{2}},\tilde{Y}_{CO_{2}}^{\prime\prime2})d\varphi")


def test_normalize_latex_ignores_style_but_keeps_accents():
    assert normalize_latex(EQ1_OCR) == normalize_latex(EQ1_GOLD)
    assert normalize_latex(EQ4_OCR) != normalize_latex(EQ4_GOLD)
    # the things that are ignored
    assert normalize_latex(r"\mathrm{CO}_{2}") == normalize_latex(r"CO_2")
    assert normalize_latex(r"\varphi_{\mathrm{min}}") == normalize_latex(r"\varphi_{\min}")
    assert normalize_latex(r"a \, b \quad c") == normalize_latex("ab c")
    assert normalize_latex(r"\begin{gathered} a \\ b \end{gathered}") == normalize_latex("a b")
    assert normalize_latex(r"\left( x \right)") == normalize_latex("(x)")
    assert normalize_latex(r"x''") == normalize_latex(r"x\prime\prime")
    assert normalize_latex(r"\tag{3} x = y,") == normalize_latex("x=y")
    assert normalize_latex(r"\widetilde{Y}_{\mathrm{CO}_2}") == normalize_latex(r"\tilde{Y}_{CO_{2}}")
    assert normalize_latex(r"\overline{\rho u}") == normalize_latex(r"\bar{\rho u}")
    assert normalize_latex(r"\begin{aligned} a &= b \\ &+ c \end{aligned}") == normalize_latex("a=b+c")
    # the things that are kept
    assert normalize_latex(r"\tilde{f}") != normalize_latex(r"\bar{f}")
    assert normalize_latex(r"x_{i}") != normalize_latex(r"x^{i}")
    assert normalize_latex(r"\{x\}") != normalize_latex("(x)")


def _rows():
    return [
        {"index": 1, "page": 2, "label": "1", "hint": "", "text_layer_garbled": True, "crop": None,
         "engines": {"rapid": {"latex": EQ1_OCR, "confidence": 1.0, "seconds": 4.0, "lines": 1}}},
        {"index": 2, "page": 2, "label": "4", "hint": "", "text_layer_garbled": True, "crop": None,
         "engines": {"rapid": {"latex": EQ4_OCR, "confidence": 0.4, "seconds": 6.0, "lines": 1}}},
        {"index": 3, "page": 3, "label": None, "hint": "", "text_layer_garbled": False, "crop": None,
         "engines": {"rapid": {"latex": None, "confidence": 0.0, "seconds": 2.0, "lines": 0}}},
    ]


def test_summary_counts_garbled_and_uncertain():
    s = summarize(_rows())["rapid"]
    assert s["equations"] == 3 and s["recognized"] == 2 and s["failed"] == 1
    assert s["uncertain"] == 1 and s["text_layer_garbled"] == 2
    assert s["median_seconds"] == 4.0 and s["total_seconds"] == 12.0
    assert s["mean_confidence"] == pytest.approx(0.7)


def test_golden_scoring_uses_verified_entries_only():
    rows = _rows()
    golden = {(2, "1"): {"latex": EQ1_GOLD, "verified": True},
              (2, "4"): {"latex": EQ4_GOLD, "verified": True}}
    g = score_against_golden(rows, golden)["rapid"]
    assert g["compared"] == 2 and g["exact"] == 1 and g["exact_rate"] == 0.5
    assert 0.85 < g["mean_sim"] < 1.0                               # eq (4) is close, not exact
    assert rows[0]["engines"]["rapid"]["golden_exact"] is True
    assert rows[1]["engines"]["rapid"]["golden_exact"] is False
    assert [r["golden_status"] for r in rows] == ["verified", "verified", "missing"]
    assert "golden_sim" not in rows[2]["engines"]["rapid"]       # no golden entry for that one

    rows = _rows()
    golden[(2, "4")]["verified"] = False                          # an entry the person has not checked yet
    g = score_against_golden(rows, golden)["rapid"]
    assert g["compared"] == 1 and g["exact"] == 1
    assert rows[1]["golden_status"] == "unverified" and "golden_sim" not in rows[1]["engines"]["rapid"]
