"""Choosing between the readings of one equation at several render scales when there is no
usable text layer (docs/issues/garbled-text-layer.md, cause 7). Pure functions, no model."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf2word.mathocr import AGREE_OK, CONFIDENCE_LOW, agreement, pick_by_agreement  # noqa: E402

# paper-01 eq. (1) as read at two scales: the second mis-read \chi\circ ... \circ\chi
GOOD = r"\frac{\partial\Psi}{\partial t}=\left(I-\Psi_{\theta}\Psi_{\theta}^{+}\right)\bigg\{F(\Psi)+\frac{d}{\rho}\chi\circ\Psi_{\theta\theta}\circ\chi\bigg\}"
BAD = r"\frac{\partial\Psi}{\partial t}=\left(I-\Psi_{\theta}\Psi_{\theta}^{+}\right)\bigg\{F(\Psi)+\frac{d}{\rho}\gamma\circ\Psi_{\theta\theta}\propto\gamma\bigg\}"
GOOD2 = r"\frac{\partial\boldsymbol{\Psi}}{\partial t}=(I-\Psi_{\theta}\Psi_{\theta}^{+})\left\{F(\Psi)+\frac{d}{\rho}\chi\circ\Psi_{\theta\theta}\circ\chi\right\}"


def test_agreement_ignores_style():
    assert agreement(GOOD, GOOD2) == 1.0
    assert CONFIDENCE_LOW < agreement(GOOD, BAD) < AGREE_OK      # close, but not "the same reading"
    assert agreement(GOOD, "") == 0.0


def test_pick_majority_and_confidence():
    i, conf = pick_by_agreement([BAD, GOOD, GOOD2])
    assert i in (1, 2) and conf == 1.0                            # the two agreeing readings win
    i, conf = pick_by_agreement([GOOD, GOOD2, BAD])
    assert i == 1 and conf == 1.0                                 # tie between 0 and 1 -> later scale
    i, conf = pick_by_agreement([GOOD, BAD])                      # two readings, no majority
    assert i == 1 and conf == pytest.approx(agreement(GOOD, BAD))
    i, conf = pick_by_agreement([r"a=b", r"\int x\,dx"])          # unrelated readings -> flagged
    assert conf < CONFIDENCE_LOW


def test_pick_edge_cases():
    assert pick_by_agreement([]) == (-1, 0.0)
    assert pick_by_agreement([GOOD]) == (0, 1.0)                  # one reading: cannot judge
