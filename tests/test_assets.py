"""The asset folder belongs to one output only: a .docx conversion never touches the images of an
earlier .md of the same PDF, and a paper that shares '_asset-{author}-{year}' with another one
gets a folder of its own. A synthetic one-page PDF and a stubbed layout analysis - no paper PDF,
no model, no network.

Run:  python -m pytest tests/test_assets.py -q
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf2word.config import Options  # noqa: E402
from pdf2word.converter import Converter  # noqa: E402
from pdf2word.metadata import PaperMeta  # noqa: E402
from pdf2word.obsidian import image_link  # noqa: E402

ASSET = "_asset-Kim-2024"


def _png(folder: Path, name: str = "fig1.png") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), False).save(str(path))
    return path


# ----------------------------------------------------------------------------- choosing the folder

def test_a_missing_or_empty_folder_is_used(tmp_path):
    own = Converter._own_asset_dir
    assert own(tmp_path, ASSET, tmp_path / "A.md") == tmp_path / ASSET
    (tmp_path / ASSET).mkdir()
    assert own(tmp_path, ASSET, tmp_path / "A.md") == tmp_path / ASSET


def test_another_outputs_folder_is_left_alone(tmp_path):
    own = Converter._own_asset_dir
    _png(tmp_path / ASSET)                                   # paper A's figures, A.md not this run's
    assert own(tmp_path, ASSET, tmp_path / "B.md") == tmp_path / f"{ASSET}-2"
    _png(tmp_path / f"{ASSET}-2")                            # and a third paper's
    assert own(tmp_path, ASSET, tmp_path / "C.md") == tmp_path / f"{ASSET}-3"
    (tmp_path / "D").write_text("x", encoding="utf-8")       # a file of that name is not a folder
    assert own(tmp_path, "D", tmp_path / "D.md") == tmp_path / "D-2"


def test_the_folder_the_md_links_to_is_ours(tmp_path):
    own = Converter._own_asset_dir
    _png(tmp_path / ASSET)
    _png(tmp_path / f"{ASSET}-2")
    a, b = tmp_path / "A.md", tmp_path / "B.md"
    a.write_text("# A\n\n" + image_link(f"{ASSET}/fig1.png") + "\n", encoding="utf-8")
    b.write_text("# B\n\n" + image_link(f"{ASSET}-2/fig1.png", "fig1", "markdown") + "\n", encoding="utf-8")
    assert own(tmp_path, ASSET, a) == tmp_path / ASSET
    assert own(tmp_path, ASSET, b) == tmp_path / f"{ASSET}-2"
    # --image-links markdown URL-quotes a Korean folder name
    _png(tmp_path / "_asset-김-2024")
    k = tmp_path / "K.md"
    k.write_text(image_link("_asset-김-2024/fig1.png", "fig1", "markdown"), encoding="utf-8")
    assert own(tmp_path, "_asset-김-2024", k) == tmp_path / "_asset-김-2024"
    assert own(tmp_path, "_asset-김-2024", a) == tmp_path / "_asset-김-2024-2"


# ----------------------------------------------------------------------------- whole runs

@pytest.fixture
def run(tmp_path, monkeypatch):
    """Converter._run on a one-page PDF with one uncaptioned picture (p1-img1.png); the layout
    analysis is stubbed so that no model is needed. run(fmt, base_name) -> ConversionResult."""
    import pymupdf4llm

    text = "Some text before.\n\n[picture]\n\nSome text after.\n"
    s = text.index("[picture]")
    box = {"class": "picture", "bbox": (100, 100, 300, 250), "pos": (s, s + len("[picture]")), "index": 0}

    def fake_layout(doc, **kw):
        return [{"text": text, "page_boxes": [dict(box)], "metadata": {"page_number": 1}}]
    monkeypatch.setattr(pymupdf4llm, "to_markdown", fake_layout)

    scratch = []
    real_mkdtemp = tempfile.mkdtemp

    def mkdtemp(*a, **kw):
        scratch.append(Path(real_mkdtemp(*a, **dict(kw, dir=tmp_path))))
        return str(scratch[-1])
    monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp)

    out = tmp_path / "out"

    def _run(fmt: str, base_name: str):
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=794)
        page.draw_rect(pymupdf.Rect(100, 100, 300, 250), color=(0, 0, 0), fill=(0.4, 0.6, 0.8))
        opt = Options(format=fmt, out_dir=out, math_engine="none", lighten=False, online=False,
                      vector_math=False, inline_image_math=False, inline_text_math=False)
        meta = PaperMeta(title=f"Paper {base_name}", authors=["J. Kim"], first_author="Kim", year=2024)
        try:
            return Converter(opt)._run(doc, out / f"{base_name}.pdf", meta, "paper", base_name, ASSET)
        finally:
            doc.close()
    _run.out, _run.scratch = out, scratch
    return _run


def test_docx_after_md_keeps_the_md_images(run):
    md = run("md", "Kim-2024-A")
    img = run.out / ASSET / "p1-img1.png"
    assert md.asset_dir == run.out / ASSET and img.exists()
    assert f"{ASSET}/p1-img1.png" in md.md_path.read_text(encoding="utf-8")
    before = img.read_bytes()
    dx = run("docx", "Kim-2024-A")
    assert dx.docx_path.exists() and dx.asset_dir is None
    assert img.exists() and img.read_bytes() == before        # the .md's figure survives
    assert run.scratch and not any(p.exists() for p in run.scratch)   # the private folder is gone
    import docx
    assert len(docx.Document(str(dx.docx_path)).inline_shapes) == 1   # the figure is in the .docx


def test_a_paper_with_the_same_author_and_year_gets_its_own_folder(run):
    a = run("md", "Kim-2024-A")
    img_a = run.out / ASSET / "p1-img1.png"
    before = img_a.read_bytes()
    b = run("md", "Kim-2024-B")
    assert b.asset_dir == run.out / f"{ASSET}-2" and (b.asset_dir / "p1-img1.png").exists()
    body_b = b.md_path.read_text(encoding="utf-8")
    assert f"{ASSET}-2/p1-img1.png" in body_b and f'assets: "{ASSET}-2"' in body_b
    assert img_a.read_bytes() == before
    # converting each one again keeps them apart
    assert run("md", "Kim-2024-A").asset_dir == a.asset_dir
    assert run("md", "Kim-2024-B").asset_dir == b.asset_dir
    assert sorted(p.name for p in run.out.iterdir() if p.is_dir()) == [ASSET, f"{ASSET}-2"]


# ----------------------------------------------------------------------------- #89 / #113

def test_link_breaking_chars_in_the_pdf_name_keep_the_figure(run, tmp_path):
    """'[ ] # ^' in the PDF name: the asset folder goes without them, so that the wiki link stays
    one link (Obsidian) and the .docx finds the picture; the file names keep them."""
    import docx
    pdf = tmp_path / "Manual [2nd ed] #3.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=794)
    page.draw_rect(pymupdf.Rect(100, 100, 300, 250), color=(0, 0, 0), fill=(0.4, 0.6, 0.8))
    doc.set_toc([[1, "Chapter 1", 1]])
    doc.save(str(pdf))
    doc.close()
    opt = dict(format="both", out_dir=run.out, math_engine="none", lighten=False, online=False, doc_type="document",
               vector_math=False, inline_image_math=False, inline_text_math=False)

    whole = Converter(Options(**opt)).convert(pdf)
    conv = Converter(Options(chapters="1", **opt))
    (chapter,) = conv.convert_parts(pdf, conv.plan_parts(pdf))
    assert not chapter.error
    for res, asset in ((whole, "_asset-Manual-2nd-ed-3"), (chapter, "_asset-Manual-2nd-ed-3-01")):
        assert res.asset_dir == run.out / asset and (res.asset_dir / "p1-img1.png").exists()
        body = res.md_path.read_text(encoding="utf-8")
        assert f"![[{asset}/p1-img1.png]]" in body and f'assets: "{asset}"' in body
        assert len(docx.Document(str(res.docx_path)).inline_shapes) == 1      # the figure is in the .docx
    assert whole.md_path.name == "Manual-[2nd-ed]-#3.md"
