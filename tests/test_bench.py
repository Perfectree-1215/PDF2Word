"""tools/bench_mathocr.py: the pure parts (summary, LaTeX normalisation, golden-set scoring),
the reports and the engine / golden-skeleton plumbing of main(). Synthetic PDFs and stub engines
only: no paper PDF, no model."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import bench_mathocr as bench  # noqa: E402
from bench_mathocr import normalize_latex, score_against_golden, summarize  # noqa: E402
from pdf2word import mathocr  # noqa: E402
from pdf2word.mathocr import AGREE_LOW, CONFIDENCE_LOW, agreement  # noqa: E402

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
    golden = {(2, "1", 0): {"latex": EQ1_GOLD, "verified": True},
              (2, "4", 0): {"latex": EQ4_GOLD, "verified": True}}
    g = score_against_golden(rows, golden)["rapid"]
    assert g["compared"] == 2 and g["exact"] == 1 and g["exact_rate"] == 0.5
    assert 0.85 < g["mean_sim"] < 1.0                               # eq (4) is close, not exact
    assert rows[0]["engines"]["rapid"]["golden_exact"] is True
    assert rows[1]["engines"]["rapid"]["golden_exact"] is False
    # the similarity is the converter's own measure (mathocr.agreement), not a copy of it
    assert rows[1]["engines"]["rapid"]["golden_sim"] == round(agreement(EQ4_GOLD, EQ4_OCR), 3)
    assert [r["golden_status"] for r in rows] == ["verified", "verified", "missing"]
    assert "golden_sim" not in rows[2]["engines"]["rapid"]       # no golden entry for that one

    rows = _rows()
    golden[(2, "4", 0)]["verified"] = False                       # an entry the person has not checked yet
    g = score_against_golden(rows, golden)["rapid"]
    assert g["compared"] == 1 and g["exact"] == 1
    assert rows[1]["golden_status"] == "unverified" and "golden_sim" not in rows[1]["engines"]["rapid"]


def test_normalize_latex_knows_the_p2t_spellings():
    assert normalize_latex(r"\cfrac{a}{b}") == normalize_latex(r"\frac{a}{b}")
    assert normalize_latex(r"\operatorname*{min}") == normalize_latex("min")
    assert normalize_latex(r"\sf x \mathsf{y} \pmb{z}") == "xyz"
    assert normalize_latex(r"\Biggl[ x \Biggr]") == normalize_latex("[x]")
    assert normalize_latex(r"\iota") != normalize_latex(r"\it ota")        # \it must not eat \iota


def test_row_breaks_before_groups_are_not_escaped_braces():
    # "\\\\{" is a row break followed by a group, which str.replace("\\{") used to misread
    from pdf2word.mathocr import braces_balanced, looks_garbage
    two_rows = r"\begin{aligned}{a=b}\\{=c+d}\end{aligned}"
    assert braces_balanced(two_rows) and not looks_garbage(two_rows)
    assert normalize_latex(two_rows) == normalize_latex("a=b =c+d")
    assert normalize_latex(r"\{x\}") == normalize_latex(r"\lbrace x\rbrace")


def test_summary_reads_the_uncertain_key(tmp_path):
    # rows of a current results.json carry EquationResult.uncertain: an agreement of 0.85 is flagged
    # (AGREE_LOW) although the old text-layer rule (confidence < CONFIDENCE_LOW) would not flag it;
    # rows of an older results.json have no such key and still use the old rule
    rows = [{"index": 1, "page": 2, "label": "1", "hint": "", "text_layer_garbled": True, "crop": None,
             "engines": {"rapid": {"latex": "x", "confidence": 0.85, "uncertain": True, "seconds": 1.0,
                                   "lines": 1}}},
            {"index": 2, "page": 2, "label": "2", "hint": "", "text_layer_garbled": False, "crop": None,
             "engines": {"rapid": {"latex": "y", "confidence": 0.4, "seconds": 1.0, "lines": 1}}}]
    summary = summarize(rows)
    assert summary["rapid"]["uncertain"] == 2           # one by the key, one by the old rule
    scores = score_against_golden(rows, {})
    bench.write_markdown(tmp_path / "report.md", tmp_path / "x.pdf", rows, summary, scores)
    bench.write_html(tmp_path / "report.html", tmp_path / "x.pdf", rows, summary, scores)
    md = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "| rapid | 0.85 \u26a0 |" in md and "| rapid | 0.40 \u26a0 |" in md
    assert (tmp_path / "report.html").read_text(encoding="utf-8").count("<td class='low'>") == 2


# ----------------------------------------------------------------------------- golden keys

def _unnumbered_rows():
    """One page with two unnumbered display equations and a numbered one; the engine is right."""
    def row(i, label, latex):
        return {"index": i, "page": 3, "label": label, "hint": "", "text_layer_garbled": False, "crop": None,
                "engines": {"stub": {"latex": latex, "confidence": 1.0, "seconds": 1.0, "lines": 1}}}
    return [row(1, None, "a=b"), row(2, None, "c=d"), row(3, "7", "e=f")]


def test_golden_keeps_unnumbered_equations_of_one_page_apart(tmp_path):
    rows = _unnumbered_rows()
    path = tmp_path / "golden.json"
    bench.write_golden_skeleton(path, tmp_path / "x.pdf", rows, "stub")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert [(e["page"], e["label"], e["k"]) for e in data["equations"]] == [(3, None, 0), (3, None, 1), (3, "7", 0)]
    for e in data["equations"]:                          # the person checked every entry
        e["verified"] = True
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    golden = bench.load_golden(path)
    assert len(golden) == 3
    g = score_against_golden(rows, golden)["stub"]
    assert g["compared"] == 3 and g["exact"] == 3 and g["mean_sim"] == 1.0
    assert 'label "", k 0' in bench._golden_note(rows[0])
    assert 'label "", k 1' in bench._golden_note(rows[1])
    assert bench._golden_note(rows[2]).endswith('label "7")')          # a numbered one is named by its label


def test_load_golden_rejects_duplicate_keys(tmp_path):
    path = tmp_path / "golden.json"
    path.write_text(json.dumps({"equations": [
        {"page": 3, "label": "", "verified": True, "latex": "a=b"},
        {"page": 3, "label": None, "verified": True, "latex": "c=d"},
        {"page": 3, "label": "7", "verified": True, "latex": "e=f"}]}), encoding="utf-8")
    with pytest.raises(SystemExit, match=r"\(3, '', 0\)"):
        bench.load_golden(path)


def test_load_golden_reads_entries_without_k(tmp_path):
    # golden.json written before the ordinal existed (bench/paper-01): no "k", unique labels -> k = 0,
    # and the scores are the ones of the 3-tuple keys above
    path = tmp_path / "golden.json"
    path.write_text(json.dumps({"pdf": "x.pdf", "equations": [
        {"page": 2, "label": "1", "verified": True, "latex": EQ1_GOLD},
        {"page": 2, "label": "4", "verified": True, "latex": EQ4_GOLD}]}), encoding="utf-8")
    golden = bench.load_golden(path)
    assert set(golden) == {(2, "1", 0), (2, "4", 0)}
    g = score_against_golden(_rows(), golden)["rapid"]
    assert g["compared"] == 2 and g["exact"] == 1 and 0.85 < g["mean_sim"] < 1.0


# ----------------------------------------------------------------------------- reports

def test_html_report_escapes_latex(tmp_path):
    rows = [{"index": 1, "page": 1, "label": None, "hint": "", "text_layer_garbled": False, "crop": None,
             "engines": {"p2t": {"latex": "0<x<1", "confidence": 1.0, "uncertain": False, "seconds": 1.0,
                                 "lines": 1}}}]
    path = tmp_path / "report.html"
    bench.write_html(path, tmp_path / "x.pdf", rows, summarize(rows), score_against_golden(rows, {}))
    text = path.read_text(encoding="utf-8")
    assert "$$0&lt;x&lt;1$$" in text and "<x<1" not in text


def test_report_legend_names_both_thresholds(tmp_path):
    rows = _rows()
    summary, scores = summarize(rows), score_against_golden(rows, {})
    bench.write_markdown(tmp_path / "report.md", tmp_path / "x.pdf", rows, summary, scores)
    bench.write_html(tmp_path / "report.html", tmp_path / "x.pdf", rows, summary, scores)
    for name in ("report.md", "report.html"):
        text = (tmp_path / name).read_text(encoding="utf-8").replace("&lt;", "<")
        assert f"< {CONFIDENCE_LOW}" in text and f"< {AGREE_LOW}" in text, name
        assert "garbled or missing" in text, name
    # a region without any text layer is judged by the agreement of the render scales too
    assert "agreement between render scales" in bench._layer_note(rows[2])


# ----------------------------------------------------------------------------- running

class _StubEngine(mathocr.MathEngine):
    """Returns its readings in turn (one per render scale); multi-scale like p2t. No model."""
    multiline = True
    multi_zoom = True
    default_zooms = (2.0, 3.0)

    def __init__(self, *readings, name="stub"):
        self.readings = readings or ("a=b+c",)
        self.name = name
        self.calls = 0

    def recognize(self, img, hint=""):
        self.calls += 1
        return self.readings[(self.calls - 1) % len(self.readings)]


def _engine_args():
    return argparse.Namespace(math_max_tokens=320, claude_model="claude-opus-5-5", claude_effort="low")


def _drawn_and_garbled_page():
    """An equation drawn as graphics (no text layer at all) and one with a garbled Type 1 layer."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    for x in range(200, 300, 7):
        page.draw_rect(pymupdf.Rect(x, 150, x + 5, 160), color=(0, 0, 0), fill=(0, 0, 0), width=0)
    page.insert_text((200, 260), "\u00f0x \u00fe y \u00de", fontsize=14)
    drawn, garbled = pymupdf.Rect(195, 145, 305, 165), pymupdf.Rect(195, 240, 320, 268)
    return doc, drawn, garbled, page.get_text("text", clip=garbled).strip()


def test_doubtful_latex_without_text_layer_is_capped(tmp_path):
    # the converter caps a doubtful reading it cannot check against a text layer at 0.5
    # (_DocContext._format_equation, vectormath.doubtful_equation); the bench must flag it the same way
    doc, drawn, garbled, garbled_hint = _drawn_and_garbled_page()
    assert garbled_hint and not mathocr.hint_usable(garbled_hint)
    eng = _StubEngine(r"\mathcal{F}=ma")
    rows = bench.run(doc, [(1, drawn, "", None, False, []), (1, garbled, garbled_hint, None, True, [])],
                     {"stub": eng}, None, tmp_path, warmup=False)
    e = rows[0]["engines"]["stub"]
    assert e["latex"] == r"\mathcal{F}=ma" and e["confidence"] == 0.5 and e["uncertain"] is True
    e = rows[1]["engines"]["stub"]                       # garbled text layer: not capped, as in the converter
    assert e["confidence"] == 1.0 and e["uncertain"] is False
    rows = bench.run(doc, [(1, drawn, "", None, False, [])], {"stub": _StubEngine("F=ma")}, None, tmp_path,
                     warmup=False)
    assert rows[0]["engines"]["stub"]["confidence"] == 1.0                # a plausible reading is not capped


def test_equation_regions_never_runs_page_ocr(monkeypatch):
    # the converter passes use_ocr=opt.ocr_pages (False by default); without it pymupdf4llm probes
    # for Tesseract (subprocesses) and OCRs pages that look scanned
    import pymupdf4llm
    seen = {}

    def fake_to_markdown(doc, **kw):
        seen.update(kw)
        return []
    monkeypatch.setattr(pymupdf4llm, "to_markdown", fake_to_markdown)
    doc = pymupdf.open()
    doc.new_page()
    assert bench.equation_regions(doc, None, lighten=False) == []
    assert seen["use_ocr"] is False


def test_build_engines_skips_p2t_that_fell_back_to_rapid(monkeypatch, capsys):
    def no_model(self):
        raise RuntimeError("model files not available (offline)")
    monkeypatch.setattr(mathocr.Pix2TextEngine, "load", no_model)
    assert bench.build_engines(["p2t"], _engine_args()) == {}
    assert "fell back to rapid" in capsys.readouterr().out
    engines = bench.build_engines(["rapid"], _engine_args())
    assert isinstance(engines["rapid"], mathocr.RapidEngine)              # lazy: no model is loaded here
    monkeypatch.setattr(mathocr.Pix2TextEngine, "load", lambda self: self)
    engines = bench.build_engines(["P2T"], _engine_args())
    assert isinstance(engines["P2T"], mathocr.Pix2TextEngine)             # names are compared in lower case


def _stub_main(monkeypatch, region):
    """main() without the layout analysis, the console set-up and the real engines (except the
    names that build_engine rejects)."""
    monkeypatch.setattr(bench, "setup_console", lambda: None, raising=False)
    monkeypatch.setattr(bench, "setup_logging", lambda verbose=False: None)
    monkeypatch.setattr(bench, "equation_regions", lambda d, pages=None, lighten=True: [
        (1, region, "a = b + c", "1", False, []), (1, region, "a = b + c", "2\u20133", False, [])])
    real = bench.build_engine
    monkeypatch.setattr(bench, "build_engine",
                        lambda name, **kw: _StubEngine("a=b+c") if name == "stub" else real(name, **kw))


def test_golden_skeleton_comes_from_a_built_engine(tmp_path, monkeypatch):
    pdf = tmp_path / "x.pdf"
    doc = pymupdf.open()
    doc.new_page(width=595, height=842).insert_text((100, 200), "a = b + c", fontsize=20)
    doc.save(str(pdf))
    _stub_main(monkeypatch, pymupdf.Rect(90, 178, 320, 208))
    out = tmp_path / "out"
    rc = bench.main([str(pdf), "--engines", "rapdi,stub", "-o", str(out), "--no-warmup", "--no-lighten"])
    assert rc == 0
    golden = json.loads((out / "golden.json").read_text(encoding="utf-8"))
    assert [e["latex"] for e in golden["equations"]] == ["a=b+c", "a=b+c"]


def test_main_sets_up_console_first(monkeypatch):
    # a label like (2-3) with an en dash is printed while the equations are read; on a stdout
    # redirected in cp949 that print crashed before results.json was written, so the console is
    # set up before anything else
    class Sentinel(Exception):
        pass

    def boom():
        raise Sentinel
    monkeypatch.setattr(bench, "setup_console", boom, raising=False)
    monkeypatch.setattr(bench, "setup_logging", lambda verbose=False: None)
    with pytest.raises(Sentinel):
        bench.main(["x.pdf"])
