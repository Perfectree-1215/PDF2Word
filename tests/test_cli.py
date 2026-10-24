"""pdf2word.cli: option values the parser refuses up front (exit code 2, a usage message)
instead of a traceback, a silently dropped value or a whole-PDF conversion. The GUI's 추가 옵션
goes through the same parser. No PDF, no network, no model.

Run:  python -m pytest tests/test_cli.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf2word.cli import build_parser, options_from_args  # noqa: E402


def _parse(*argv):
    return build_parser().parse_args(["x.pdf", *argv])


def _refused(capsys, *argv) -> str:
    with pytest.raises(SystemExit) as exc:
        _parse(*argv)
    assert exc.value.code == 2
    return capsys.readouterr().err


# ----------------------------------------------------------------------------- #118

def test_math_zooms_are_checked_by_argparse(capsys):
    assert _parse("--math-zooms", "4,3").math_zooms == (4.0, 3.0)
    assert _parse("--math-zooms", " 2.5 , 3 ,").math_zooms == (2.5, 3.0)
    assert _parse("--math-zooms", " ").math_zooms is None              # blank: the engine's own order
    assert _parse().math_zooms is None
    for bad in ("4x,3x", "4;3", "0,2", "-1", "3,-3", "nan", "inf"):
        assert "--math-zooms" in _refused(capsys, "--math-zooms", bad), bad


def test_math_zooms_reach_the_options():
    assert options_from_args(_parse("--math-zooms", "4,3,2")).math_zooms == (4.0, 3.0, 2.0)
    assert options_from_args(_parse()).math_zooms is None


# ----------------------------------------------------------------------------- --figure-panels

def test_figure_panels_default_and_choice(capsys):
    assert _parse().figure_panels == "merge"
    assert options_from_args(_parse()).figure_panels == "merge"
    assert options_from_args(_parse("--figure-panels", "split")).figure_panels == "split"
    assert "--figure-panels" in _refused(capsys, "--figure-panels", "both")


# ----------------------------------------------------------------------------- blank --chapters

def test_blank_chapters_are_refused(capsys):
    for bad in (" ", "", "\t"):
        assert "--chapters" in _refused(capsys, "--chapters", bad), repr(bad)
    assert _parse("--chapters", "3,4.2").chapters == "3,4.2"
    assert _parse().chapters is None


# ----------------------------------------------------------------------------- --figure-sheet / --sheet-dpi

def test_figure_sheet_and_sheet_dpi_default_choice_and_refusal(capsys):
    assert (_parse().figure_sheet, _parse().sheet_dpi) == ("replace", 120)         # sheets by default (2026-10-24)
    opt = options_from_args(_parse())
    assert (opt.figure_sheet, opt.sheet_dpi) == ("replace", 120)
    assert options_from_args(_parse("--figure-sheet", "none")).figure_sheet == "none"
    opt = options_from_args(_parse("--figure-sheet", "replace", "--sheet-dpi", "200"))
    assert (opt.figure_sheet, opt.sheet_dpi) == ("replace", 200)
    assert "--figure-sheet" in _refused(capsys, "--figure-sheet", "both")
    assert "--sheet-dpi" in _refused(capsys, "--sheet-dpi", "high")


# ----------------------------------------------------------------------------- --math-mode / --no-equation-check

def test_math_mode_default_is_latex_and_both_stays_available(capsys):
    assert _parse().math_mode == "latex"                                   # the check page replaces the image above every equation
    assert options_from_args(_parse()).math_mode == "latex"
    assert options_from_args(_parse("--math-mode", "both")).math_mode == "both"
    assert "--math-mode" in _refused(capsys, "--math-mode", "text")


def test_no_equation_check_reaches_the_options():
    assert _parse().no_equation_check is False
    assert options_from_args(_parse()).equation_check is True
    assert options_from_args(_parse("--no-equation-check")).equation_check is False
