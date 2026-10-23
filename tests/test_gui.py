"""GUI logic that runs without a window: the 추가 옵션 box, the settings file, the parts each PDF
is cut into, the worker loop and the status line. No Tk window, model or network; the PDF is
generated on the fly and the settings file lives in tmp_path.

Run:  python -m pytest tests/test_gui.py -q
"""
from __future__ import annotations

import json
import queue
import sys
import threading
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main_gui  # noqa: E402  (module level only: no window, no command line)
from pdf2word.cli import build_parser  # noqa: E402
from pdf2word.config import Options  # noqa: E402
from pdf2word.converter import ConversionResult, Converter  # noqa: E402
from pdf2word.metadata import PaperMeta  # noqa: E402


def _book(path: Path) -> str:
    """6 pages: 1 Intro (p1-2), 2 Method (p3-4: 2.1 Setup, 2.2 Runs), 3 Results (p5-6)."""
    doc = pymupdf.open()
    for i in range(6):
        doc.new_page(width=400, height=600).insert_text((50, 80), f"Body text of page {i + 1}", fontsize=11)
    doc.set_toc([[1, "Intro", 1], [1, "Method", 3], [2, "Setup", 3], [2, "Runs", 4], [1, "Results", 5]])
    doc.save(str(path))
    doc.close()
    return str(path)


def _drain(q: "queue.Queue") -> list:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def _fake_converter(monkeypatch, calls: list, fail_with: BaseException | None = None):
    """Real planning (plan_parts); conversion only records the call."""
    class Fake(Converter):
        def convert(self, pdf_path):
            calls.append(("convert", Path(pdf_path).name))
            if fail_with is not None:
                raise fail_with
            return ConversionResult(Path(pdf_path), Path(pdf_path).with_suffix(".md"), None, PaperMeta(title="x"))

        def convert_parts(self, pdf_path, parts, stop=None):
            calls.append(("convert_parts", [p.title for p in parts]))
            return [ConversionResult(Path(pdf_path), None, None, PaperMeta(title=p.title), part=p,
                                     error="boom" if p.title == "Method" else "") for p in parts]

    monkeypatch.setattr("pdf2word.converter.Converter", Fake)


# ----------------------------------------------------------------------------- #8 chapters

def test_extra_chapter_options_split_the_pdf(tmp_path):
    pdf = _book(tmp_path / "book.pdf")

    def titles(options, sel=None):
        return [p.title for p in main_gui.plan_for(Converter(options), pdf, sel)]

    assert titles(Options(chapters="1,2")) == ["Intro", "Method"]
    assert titles(Options(split_pages=2)) == ["p1-2", "p3-4", "p5-6"]
    assert titles(Options(chapters="2", subchapters=True))[-2:] == ["Setup", "Runs"]
    assert titles(Options()) == []                                   # whole PDF in one file
    # the chapter picker's choice for this PDF wins over the typed options
    assert titles(Options(chapters="1,2"), {"kind": "pages", "size": 4}) == ["p1-4", "p5-6"]
    assert titles(Options(split_pages=2), {"kind": "chapters", "ids": ["3"]}) == ["Results"]


def test_worker_converts_each_planned_part(tmp_path, monkeypatch):
    pdf = _book(tmp_path / "book.pdf")
    calls: list = []
    _fake_converter(monkeypatch, calls)
    q: "queue.Queue" = queue.Queue()
    assert main_gui.run_jobs(q, threading.Event(), [pdf], Options(chapters="1,2")) == (1, 1)
    msgs = _drain(q)
    assert calls == [("convert_parts", ["Intro", "Method"])]         # never one whole-PDF convert()
    assert [p.part.title for k, p in msgs if k == "result"] == ["Intro"]
    assert [p for k, p in msgs if k == "error"] == ["실패: book.pdf [Method]: boom"]
    assert msgs[-1] == ("finished", (1, 1))                          # one count per output file, as the CLI


def test_bad_chapter_id_fails_that_file_only(tmp_path, monkeypatch):
    pdf = _book(tmp_path / "book.pdf")
    calls: list = []
    _fake_converter(monkeypatch, calls)
    q: "queue.Queue" = queue.Queue()
    main_gui.run_jobs(q, threading.Event(), [pdf], Options(chapters="9"))
    msgs = _drain(q)
    assert calls == []
    assert [p for k, p in msgs if k == "error"][0].startswith("실패: book.pdf: unknown chapter id: 9")
    assert msgs[-1] == ("finished", (0, 1))


def test_list_chapters_is_refused_in_gui():
    msg = main_gui.refused_in_gui(build_parser().parse_args(["x.pdf", "--list-chapters"]))
    assert "--list-chapters" in msg and "챕터 선택" in msg
    assert main_gui.refused_in_gui(build_parser().parse_args(["x.pdf", "--chapters", "1"])) == ""


# ----------------------------------------------------------------------------- #9 SystemExit

def test_engine_systemexit_is_reported_and_stops(monkeypatch):
    calls: list = []
    _fake_converter(monkeypatch, calls, SystemExit("math engine 'claude' needs the Anthropic SDK"))
    q: "queue.Queue" = queue.Queue()
    assert main_gui.run_jobs(q, threading.Event(), ["a.pdf", "b.pdf"], Options(math_engine="claude")) == (0, 1)
    msgs = _drain(q)
    assert calls == [("convert", "a.pdf")]                           # the engine fails the same way for b.pdf
    assert [p for k, p in msgs if k == "error"] == ["실패: a.pdf: math engine 'claude' needs the Anthropic SDK"]
    assert any(k == "log" and "1개" in p for k, p in msgs)           # says the rest is skipped
    assert msgs[-1] == ("finished", (0, 1))


# ----------------------------------------------------------------------------- #10 quoting

@pytest.mark.parametrize("text, tokens", [
    ('--title "My Report"', ["--title", "My Report"]),
    ('--title="A B"', ["--title=A B"]),
    ('-o "D:\\My Vault\\papers"', ["-o", "D:\\My Vault\\papers"]),
    ("-o D:\\out\\papers", ["-o", "D:\\out\\papers"]),
    ("--author O'Brien", ["--author", "O'Brien"]),
    ("--chapter-template {stem}#{num} -v", ["--chapter-template", "{stem}#{num}", "-v"]),
    ("--author Kim --year 2024 --citations footnotes -v",
     ["--author", "Kim", "--year", "2024", "--citations", "footnotes", "-v"]),
    ("   ", []),
])
def test_extra_options_keep_quoted_values_and_backslashes(text, tokens):
    assert main_gui.split_extra(text) == tokens


def test_quoted_extra_values_reach_the_options():
    args = build_parser().parse_args(["x.pdf"] + main_gui.split_extra("--title \"My Report\" --author O'Brien"))
    assert (args.title, args.author) == ("My Report", "O'Brien")


def test_figure_panels_split_from_the_gui_and_from_extra_options():
    # the App class lives inside launch_gui (needs a window), so check the argv it emits with the unchecked box
    # (["--figure-panels", "split"]) and the same option typed into the "extra options" box
    for tokens in (["--figure-panels", "split"], main_gui.split_extra("--figure-panels split")):
        assert build_parser().parse_args(["x.pdf"] + tokens).figure_panels == "split"
    assert build_parser().parse_args(["x.pdf"]).figure_panels == "merge"      # box checked: nothing is added


def test_unbalanced_quote_raises_value_error():
    with pytest.raises(ValueError):
        main_gui.split_extra('--title "unbalanced')


# ----------------------------------------------------------------------------- #11 settings

def test_v13_settings_move_from_rapid_to_p2t_once(tmp_path, monkeypatch):
    path = tmp_path / "gui.json"
    monkeypatch.setattr(main_gui, "_settings_path", lambda: path)
    assert main_gui.load_settings() == {} and not path.exists()     # no file: defaults

    path.write_text(json.dumps({"format": "md", "engine": "rapid"}), encoding="utf-8")   # v1.3 file
    data = main_gui.load_settings()
    assert data["engine"] == "p2t" and data["format"] == "md"

    main_gui.save_settings(dict(data, engine="rapid"))              # the user picks rapid again
    assert json.loads(path.read_text(encoding="utf-8"))["v"] == main_gui.SETTINGS_VERSION
    assert main_gui.load_settings()["engine"] == "rapid"            # ... and keeps it

    assert main_gui.settings_engine({"engine": "claude"}) == "claude"   # only rapid moves
    assert main_gui.settings_engine({"format": "md"}) == "p2t"
    assert main_gui.settings_engine({"v": 2, "engine": "rapid"}) == "rapid"


# ----------------------------------------------------------------------------- #12 status line

def test_status_text_names_the_engines_model():
    from pdf2word.mfr_onnx import MODEL_FILES
    p2t_mb = round(sum(size for size, _ in MODEL_FILES.values()) / 1e6, -1)
    assert f"약 {p2t_mb:.0f} MB" in main_gui.status_text("p2t")
    assert "약 170 MB" in main_gui.status_text("rapid")
    assert main_gui.status_text("claude") == main_gui.status_text("none") == "변환 중 …"


def test_figure_sheet_combo_values_reach_the_parser():
    # the combo lives inside launch_gui; _argv adds ["--figure-sheet", value] only when the value is not "none"
    assert dict(main_gui.SHEETS)["개별 파일 (기본)"] == "none"
    for _text, value in main_gui.SHEETS:
        tokens = [] if value == "none" else ["--figure-sheet", value]
        assert build_parser().parse_args(["x.pdf"] + tokens).figure_sheet == value
    assert [v for _t, v in main_gui.SHEETS] == ["none", "add", "replace"]
    assert main_gui.split_extra("--sheet-dpi 200") == ["--sheet-dpi", "200"]
    assert build_parser().parse_args(["x.pdf"] + main_gui.split_extra("--sheet-dpi 200")).sheet_dpi == 200
