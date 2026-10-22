"""Garbled text layers (Type 1 fonts with private encodings: '¼' for '=', 'þ' for '+',
'ð' / 'Þ' for parentheses, Latin letters for Greek ones) must not be used to judge or repair
an OCR result, and equation numbers written as 'ð3Þ' must still be found.
See docs/issues/garbled-text-layer.md. Synthetic strings only - no PDF needed."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf2word.mathocr import (LABEL_RE, CONFIDENCE_LOW, hint_fixes, hint_similarity,  # noqa: E402
                              hint_usable, label_text)

# text layer of paper-01.pdf p.2 eq. (1), as PyMuPDF extracts it
GARBLED = "@W\n@t ¼ I \u0002 WhWþ\nh\n\u0002\n\u0003\nFðWÞ þ d\nqv \u0003 Whh \u0003 v\n\u0004\n\u0005\nð1Þ"
GARBLED_LATEX = r"\frac{\partial\Psi}{\partial t}=\left(I-\Psi_{\theta}\Psi_{\theta}^{+}\right)\bigg\{F(\Psi)+\frac{d}{\rho}\chi\circ\Psi_{\theta\theta}\circ\chi\bigg\}"
# a healthy text layer (MDPI-style) and its correct / wrong OCR results
HEALTHY = "Fz = ρP VP v2 φ,P r (1)"
HEALTHY_LATEX = r"F_{z}=\rho_{P}V_{P}\frac{v_{\varphi,P}^{2}}{r}"
HEALTHY_WRONG = r"F_{z}\underline{{{\bf\Psi}}}_{\mu\nu}\frac{\upsilon}{r}"


def test_hint_usable():
    assert hint_usable(HEALTHY)
    assert not hint_usable(GARBLED)                 # ð Þ þ: 4 occurrences
    assert not hint_usable("")                      # empty is not usable either
    assert hint_usable("x = a ð b")                 # a single stray character is tolerated
    assert not hint_usable("ðxÞ")                   # two is the threshold


def test_label_text_normalises_garbled_parentheses():
    assert label_text("ð3Þ") == "(3)"
    assert label_text("(3)") == "(3)"
    assert LABEL_RE.match(label_text(" ð12aÞ ")).group(1) == "12a"
    assert LABEL_RE.match(label_text("ð5.95Þ")).group(1) == "5.95"
    assert LABEL_RE.match(label_text("ðWÞ")) is None  # not a number


def test_garbled_layer_is_not_used_to_judge_or_repair():
    # before the fix this correct result scored 0.18 and was flagged "⚠ OCR 신뢰도 낮음"
    assert hint_similarity(GARBLED_LATEX, GARBLED) == 1.0
    assert hint_fixes(GARBLED_LATEX, GARBLED) == GARBLED_LATEX
    # a healthy layer still separates right from wrong (no regression)
    assert hint_similarity(HEALTHY_LATEX, HEALTHY) > 0.85
    assert hint_similarity(HEALTHY_WRONG, HEALTHY) < CONFIDENCE_LOW
