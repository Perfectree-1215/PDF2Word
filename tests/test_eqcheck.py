"""Equation check page (pdf2word/eqcheck.py): the HTML that shows PDF crop, LaTeX and rendering side by
side and writes corrections back into the note. Synthetic data, no model."""
from __future__ import annotations

import json
import re
from collections import Counter

import pymupdf
from PIL import Image

from pdf2word.config import Options
from pdf2word.converter import Converter, _DocContext
from pdf2word.eqcheck import equation_block, image_data_uri, write_equation_check
from pdf2word.mathocr import EquationResult


def test_equation_block_matches_what_the_converter_writes():
    assert equation_block("a+b", "3") == "$$\na+b \\tag{3}\n$$"
    assert equation_block("x", None) == "$$\nx\n$$"


def test_page_embeds_data_and_escapes(tmp_path):
    img = Image.new("RGB", (40, 20), "white")
    eqs = [{"page": 2, "label": "3", "uid": "3", "anchored": True, "latex": "a+b", "in_md": True, "uncertain": True,
            "unverified": False, "confidence": 0.55, "image": img},
           {"page": 3, "label": "4", "uid": "4", "anchored": True, "latex": "", "in_md": False, "uncertain": False,
            "unverified": True, "confidence": 1.0, "image": None},
           {"page": 5, "label": None, "uid": "u01", "anchored": False, "latex": "</script><b>x</b>", "in_md": True,
            "uncertain": False, "unverified": False, "confidence": 1.0, "image": None}]
    out = write_equation_check(tmp_path / "x.equations.html", eqs, title="T </script>", pdf_name="x.pdf", md_name="x.md")
    text = out.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>") and "T &lt;/script&gt;" in text
    assert text.count("</script>") == 3                        # KaTeX loader, the JSON and the code block: payload is escaped
    payload = re.search(r'<script type="application/json" id="data">(.*?)</script>', text, re.S).group(1)
    data = json.loads(payload.replace("<\\/", "</"))
    assert data["md"] == "x.md" and len(data["equations"]) == 3
    e0, e1, e2 = data["equations"]
    assert e0["block"] == "$$\na+b \\tag{3}\n$$" and e0["image"].startswith("data:image/png;base64,")
    assert e0["anchor_id"] == "eq-3"                                                     # found by its ^eq-3 line after edits
    assert e1["block"] == "" and e1["anchor"] == "*Eq. (4)*" and e1["image"] == ""     # image-only: insert after its line
    assert e2["latex"] == "</script><b>x</b>" and e2["label"] is None and e2["uid"] == "u01" and e2["anchor_id"] == ""
    assert image_data_uri(None) == ""


def test_converter_records_every_display_equation(tmp_path):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=794)
    page.insert_text((100, 300), "E = m c^2", fontsize=12)
    ctx = _DocContext(doc, tmp_path, Counter(), Converter(Options(math_engine="none", math_mode="latex")))
    region = pymupdf.Rect(90, 280, 300, 320)
    md = ctx._format_equation(EquationResult(latex="E = m c^{2}", image=None, confidence=0.9), "7", "hint", page, region)
    assert "$$\nE = m c^{2} \\tag{7}\n$$\n^eq-7\n" in md
    md2 = ctx._format_equation(EquationResult(latex=None, image=None), None, "", page, region)   # OCR failed: image only
    assert "![[" in md2 and "\n^eq-u01\n" in md2                                # anchor even without LaTeX
    md3 = ctx._format_equation(EquationResult(latex="x = y", image=None), None, "", page, region)
    assert "$$\nx = y\n$$\n^eq-u02\n" in md3                                      # unnumbered: u02 anchor after the block
    assert len(ctx.equations) == 3
    first, second, third = ctx.equations
    assert first["page"] == 1 and first["label"] == "7" and first["uid"] == "7" and first["latex"] == "E = m c^{2}" and first["in_md"]
    assert first["image"] is not None and first["image"].width > 0           # rendered from the page region
    assert second["latex"] == "" and not second["in_md"] and second["uid"] == "u01" and second["anchored"]
    assert third["uid"] == "u02"
    out = write_equation_check(tmp_path / "n.equations.html", ctx.equations, title="n", pdf_name="n.pdf", md_name="n.md")
    assert out.stat().st_size > 1000
    doc.close()
