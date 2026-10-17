"""Word output: build a .docx from a small Markdown sample and read it back.

Run:  python -m pytest tests/test_docx.py -q      (or)      python tests/test_docx.py
Needs python-docx; native equations additionally need latex2mathml + Microsoft Office's
MML2OMML.XSL (the test accepts the LaTeX-text fallback when they are missing).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf2word.config import Options  # noqa: E402
from pdf2word.docx_out import OmmlConverter, build_docx  # noqa: E402
from pdf2word.metadata import PaperMeta  # noqa: E402

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"

SAMPLE_MD = """# Inline Equation Images in Word Documents

Kwang Hee Kim, Jane Doe

> [!abstract] Abstract
> This note tests the Word writer with **bold**, _italic_ and $\\rho_{f}$ inline math.

## 1 Introduction

The particle _i_<sup>th</sup> velocity $u_i$ and the density ρ<sub>f</sub> are used [^1].

### <u>2.3.1 Steady Flamelet (SF) Model</u>

Some <u>underlined words</u> and a <mark>highlighted</mark> phrase in running text.

![[_asset-Kim-2024/fig1.png]]

**Figure 1.** A tiny test picture. ^fig-1

![[_asset-Kim-2024/eq-1.png]]
$$
m_{\\mathrm{p}}\\frac{\\mathrm{d}v}{\\mathrm{d}t}=\\sum F_{\\mathrm{c}}+m_{\\mathrm{p}}g \\tag{1}
$$
^eq-1

$$
\\begin{gathered}
a = b \\\\
c = d
\\end{gathered} \\tag{2}
$$
^eq-2

| Quantity | Value |
|---|---|
| Density | 1000 kg/m<sup>3</sup> |
| Viscosity | 0.001 Pa s |

- first item
- second item

%% equation text: hidden comment %%

## References

[^1]: A. Author, "A paper," *Journal*, 2024.
"""


def _make_png(path: Path, size=(120, 40), dpi=144):
    from PIL import Image
    img = Image.new("L", size, 255)
    for x in range(10, size[0] - 10):
        img.putpixel((x, size[1] // 2), 0)
    img.save(path, dpi=(dpi, dpi))


def test_build_docx():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        assets = base / "_asset-Kim-2024"
        assets.mkdir()
        _make_png(assets / "fig1.png", size=(400, 200), dpi=200)
        _make_png(assets / "eq-1.png", size=(240, 60), dpi=144)
        meta = PaperMeta(title="Inline Equation Images in Word Documents",
                         authors=["Kwang Hee Kim", "Jane Doe"], first_author="Kim", year=2024,
                         journal="Test Journal", doi="10.1000/test", keywords=["a", "b"])
        stats = {}
        out = build_docx(SAMPLE_MD, meta, base, base / "out.docx", Options(), stats)
        assert out.exists() and out.stat().st_size > 5000

        import docx
        d = docx.Document(str(out))
        texts = [p.text for p in d.paragraphs]
        headings = [p.text for p in d.paragraphs if p.style.name.startswith("Heading") or p.style.name == "Title"]
        assert headings[0] == meta.title                       # title once, from metadata
        assert texts.count(meta.title) == 1                    # the '# Title' line is not repeated
        assert "Abstract" in headings and "1 Introduction" in headings and "References" in headings
        assert any("Keywords:" in t for t in texts)
        assert len(d.inline_shapes) == 2                       # figure + equation image
        assert len(d.tables) == 1 and len(d.tables[0].rows) == 3
        assert any(p.style.name == "Caption" for p in d.paragraphs)
        assert any(p.style.name == "List Bullet" for p in d.paragraphs)
        assert not any("hidden comment" in t for t in texts)   # %% comments are dropped
        xml = d.element.xml
        n_native = xml.count(f'<m:oMath ') + xml.count("<m:oMath>")
        if OmmlConverter().available:
            assert stats.get("docx_eq_native", 0) >= 3 and n_native >= 3   # 2 blocks + inline math
            assert "(1)" in "".join(texts) and "(2)" in "".join(texts)
        else:
            assert stats.get("docx_eq_text", 0) >= 2
            assert any("\\frac{\\mathrm{d}v}" in t for t in texts)
        # superscript/subscript runs survive
        sup = [r for p in d.paragraphs for r in p.runs if r.font.superscript]
        sub = [r for p in d.paragraphs for r in p.runs if r.font.subscript]
        assert sup and sub
        # <u>/<mark> become formatting, never literal tags; headings lose the tags entirely
        assert "<u>" not in xml and "&lt;u&gt;" not in xml
        assert "2.3.1 Steady Flamelet (SF) Model" in headings
        underlined = [r for p in d.paragraphs for r in p.runs if r.underline and "underlined words" in r.text]
        assert underlined


def test_prepare_latex():
    prep = OmmlConverter.prepare
    assert prep(r"\Bigl(a\Bigr) \tag{3}") == r"\left(a\right)"
    assert prep(r"\Big(x\Big)") == "(x)"
    assert prep(r"\begin{gathered}a\\b\end{gathered}") == r"\begin{matrix}a\\b\end{matrix}"
    assert prep(r"\stackrel{\rightarrow}{v}_f") == r"\vec{v}_f"
    assert prep(r"\left(a") == "(a"                         # unbalanced sizing commands dropped


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
