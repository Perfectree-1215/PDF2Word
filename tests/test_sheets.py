"""Figure sheets (pdf2word/sheets.py): the images a note embeds, tiled onto a few labelled
PNGs that stay within Claude's native-resolution limit. Synthetic PNGs and Markdown, no model."""
from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from pdf2word import sheets
from pdf2word.config import Options
from pdf2word.sheets import MAX_EDGE, MAX_PATCHES, Tile, apply_sheets, label_for, pack, patches

ASSET = "_asset-X"


def _png(path: Path, w: int, h: int, dpi: int = 200, shade: int = 128):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), False)
    pix.clear_with(shade)
    pix.set_dpi(dpi, dpi)
    pix.save(str(path))


def _size(path: Path):
    pix = pymupdf.Pixmap(str(path))
    return pix.width, pix.height


def _tile(name: str, w: int, h: int) -> Tile:
    return Tile(name, pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 4, 4), False), w, h, label_for(name))


def _sheet_size(placed):
    return (max(p.x + p.w for p in placed) + sheets.GUTTER,
            max(p.y + sheets.LABEL_H + p.h for p in placed) + sheets.GUTTER)


def test_default_is_off():
    assert Options().figure_sheet == "none" and Options().sheet_dpi == 120
    assert sheets.SHEET_EDGE <= sheets.MAX_EDGE


def test_labels():
    assert label_for("fig3.png") == "Fig. 3"
    assert label_for("fig3a.png") == "Fig. 3a"
    assert label_for("table2.png") == "Table 2"
    assert label_for("eq-12.png") == "Eq. (12)"
    assert label_for("p4-img10.png") == "p4-img10"


def test_pack_keeps_order_within_native_limits():
    tiles = [_tile(f"fig{i}.png", 900, 700) for i in range(1, 13)]
    packed = pack(tiles)
    assert len(packed) == 3                               # 2 x 2 big tiles per sheet
    assert [p.tile.name for s in packed for p in s] == [t.name for t in tiles]
    for placed in packed:
        w, h = _sheet_size(placed)
        assert max(w, h) <= MAX_EDGE and patches(w, h) <= MAX_PATCHES
    first = packed[0]
    assert first[0].y == first[1].y and first[2].y > first[0].y and first[2].x == first[0].x


def test_narrow_tiles_stack_into_a_tall_sheet():
    tiles = [_tile(f"eq-{i}.png", 300, 60) for i in range(1, 41)]
    (placed,) = pack(tiles)                               # 40 small crops fit on one sheet
    w, h = _sheet_size(placed)
    assert max(w, h) <= MAX_EDGE and patches(w, h) <= MAX_PATCHES


def test_height_sorted_packing_wastes_less_than_document_order():
    # a mixed set: four big figures, a few mid-size ones and small equation crops, in document order
    tiles = [_tile("fig1.png", 505, 382), _tile("eq-1.png", 240, 45), _tile("fig2.png", 507, 179),
             _tile("eq-2.png", 290, 95), _tile("fig3.png", 917, 344), _tile("fig4.png", 950, 636),
             _tile("p4-img10.png", 951, 703), _tile("p5-img12.png", 951, 703), _tile("fig9.png", 476, 690),
             _tile("p6-img10.png", 951, 703), _tile("fig11.png", 359, 532), _tile("fig12.png", 507, 928)]

    def cost(packed):
        return sum(patches(*_sheet_size(s)) for s in packed)
    ordered, sorted_ = pack(tiles, by_height=False), pack(tiles)
    assert len(sorted_) <= len(ordered) and cost(sorted_) < cost(ordered)
    assert sorted({p.tile.name for s in sorted_ for p in s}) == sorted(t.name for t in tiles)   # nothing lost
    assert sorted_[0][0].tile.name == "fig12.png"                                               # tallest first


def test_oversized_tiles_are_shrunk_to_fit():
    (placed,) = pack([_tile("fig1.png", 4000, 500)])
    p = placed[0]
    assert p.w <= MAX_EDGE - 2 * sheets.GUTTER and p.h < 500
    (placed,) = pack([_tile("fig2.png", 3000, 3000)])
    p = placed[0]
    assert patches(p.w + 2 * sheets.GUTTER, p.h + sheets.LABEL_H + 2 * sheets.GUTTER) <= MAX_PATCHES


BODY = """# Title

![[_asset-X/fig1.png]]

**Figure 1.** Caption one. ^fig-1

Text with an inline symbol ![[_asset-X/inline-1.png]] in the sentence.

![[_asset-X/eq-1.png]]
$$
x = 1 \\tag{1}
$$
^eq-1

![[_asset-X/fig2.png]]

![[_asset-X/missing.png]]

## References
"""


@pytest.fixture
def assets(tmp_path):
    d = tmp_path / ASSET
    d.mkdir()
    _png(d / "fig1.png", 1200, 900, dpi=200)
    _png(d / "fig2.png", 600, 400, dpi=200, shade=90)
    _png(d / "eq-1.png", 300, 60, dpi=216)
    _png(d / "inline-1.png", 40, 30, dpi=216)
    return d


def test_replace_mode_rewrites_embeds_and_appends_the_sheet_section(assets):
    res = apply_sheets(BODY, assets, style="wiki", dpi=150, fallback_dpi=200, mode="replace")
    assert res.sheets == ["sheet-1.png"] and (assets / "sheet-1.png").is_file()
    assert res.tiled == ["fig1.png", "eq-1.png", "fig2.png"] and res.stale == res.tiled
    assert "*[Fig. 1 → sheet-1.png]*" in res.body and "*[Fig. 2 → sheet-1.png]*" in res.body
    assert "*[Eq. (1) → sheet-1.png]*" in res.body
    assert "![[_asset-X/fig1.png]]" not in res.body
    assert "![[_asset-X/inline-1.png]] in the sentence" in res.body      # inline symbol: untouched
    assert "![[_asset-X/missing.png]]" in res.body                         # unknown file: untouched
    assert "**Figure 1.** Caption one. ^fig-1" in res.body and "x = 1" in res.body
    assert "## 그림 모음" in res.body and "sheet-1.png: Fig. 1 · Fig. 2 · Eq. (1)" in res.body   # tallest first
    assert res.body.rstrip().endswith("![[_asset-X/sheet-1.png]]")
    for name in res.tiled:                                                 # nothing deleted here
        assert (assets / name).is_file()
    w, h = _size(assets / "sheet-1.png")
    assert max(w, h) <= MAX_EDGE and patches(w, h) <= MAX_PATCHES
    assert w >= 900 + 2 * sheets.GUTTER                 # fig1 at 150 dpi: 1200 px * 150/200 = 900 px wide


def test_add_mode_keeps_the_embeds(assets):
    res = apply_sheets(BODY, assets, mode="add")
    assert res.stale == [] and res.sheets == ["sheet-1.png"]
    assert "![[_asset-X/fig1.png]]" in res.body and "![[_asset-X/sheet-1.png]]" in res.body


def test_markdown_link_style(assets):
    body = "![fig1](_asset-X/fig1.png)\n\ntext\n\n![fig 2](_asset-X/fig2.png)\n"
    res = apply_sheets(body, assets, style="markdown", mode="replace")
    assert res.tiled == ["fig1.png", "fig2.png"]
    assert "*[Fig. 1 → sheet-1.png]*" in res.body and "![sheet-1](_asset-X/sheet-1.png)" in res.body


def test_other_folder_or_no_embeds_changes_nothing(assets):
    body = "![[_asset-Y/fig1.png]]\n"
    res = apply_sheets(body, assets)
    assert res.sheets == [] and res.body == body
    assert not (assets / "sheet-1.png").exists()


def test_many_big_figures_span_several_sheets(tmp_path):
    d = tmp_path / ASSET
    d.mkdir()
    body = ""
    for i in range(1, 9):
        _png(d / f"fig{i}.png", 1268, 937, dpi=200, shade=40 + i * 20)    # paper-01's 2-column profile figures
        body += f"![[{ASSET}/fig{i}.png]]\n\nFigure {i}. x\n\n"
    res = apply_sheets(body, d, mode="replace")
    assert len(res.sheets) == 2                            # six 761 x 562 tiles (120 dpi) per 2,000 px sheet
    for s in res.sheets:
        w, h = _size(d / s)
        assert max(w, h) <= sheets.SHEET_EDGE and patches(w, h) <= MAX_PATCHES
    assert all(f"*[Fig. {i} → sheet-" in res.body for i in range(1, 9))
    assert "sheet-1.png: Fig. 1 · Fig. 2 · Fig. 3 · Fig. 4 · Fig. 5 · Fig. 6" in res.body
    assert "sheet-2.png: Fig. 7 · Fig. 8" in res.body
    res150 = apply_sheets(body, d, mode="add", dpi=150)   # sharper 951 x 703 tiles: only four per sheet
    assert len(res150.sheets) == 2 and "sheet-1.png: Fig. 1 · Fig. 2 · Fig. 3 · Fig. 4\n" in res150.body


# ----------------------------------------------------------------------------- whole conversions

@pytest.fixture
def convert_one(tmp_path, monkeypatch):
    """Converter._run on a one-page PDF with one uncaptioned picture (p1-img1.png); the layout
    analysis is stubbed so that no model is needed. convert_one(fmt, **options) -> ConversionResult."""
    import pymupdf4llm
    from pdf2word.converter import Converter
    from pdf2word.metadata import PaperMeta

    text = "Some text before.\n\n[picture]\n\nSome text after.\n"
    s = text.index("[picture]")
    box = {"class": "picture", "bbox": (100, 100, 300, 250), "pos": (s, s + len("[picture]")), "index": 0}
    monkeypatch.setattr(pymupdf4llm, "to_markdown",
                        lambda doc, **kw: [{"text": text, "page_boxes": [dict(box)], "metadata": {"page_number": 1}}])
    out = tmp_path / "out"

    def run(fmt: str, **opts):
        doc = pymupdf.open()
        page = doc.new_page(width=595, height=794)
        page.draw_rect(pymupdf.Rect(100, 100, 300, 250), color=(0, 0, 0), fill=(0.4, 0.6, 0.8))
        opt = Options(format=fmt, out_dir=out, math_engine="none", lighten=False, online=False,
                      vector_math=False, inline_image_math=False, inline_text_math=False, **opts)
        meta = PaperMeta(title="Paper", authors=["J. Kim"], first_author="Kim", year=2024)
        try:
            return Converter(opt)._run(doc, out / "paper.pdf", meta, "paper", "Kim-2024", "_asset-Kim-2024")
        finally:
            doc.close()
    return run


def test_replace_sheets_in_a_markdown_conversion(convert_one):
    res = convert_one("md", figure_sheet="replace")
    assert sorted(p.name for p in res.asset_dir.iterdir()) == ["sheet-1.png"]
    md = res.md_path.read_text(encoding="utf-8")
    assert "figure_sheets: 1" in md and "*[p1-img1 → sheet-1.png]*" in md
    assert "![[_asset-Kim-2024/sheet-1.png]]" in md and "![[_asset-Kim-2024/p1-img1.png]]" not in md
    assert res.stats["figure_sheets"] == 1


def test_both_formats_build_the_docx_before_the_single_images_go(convert_one):
    res = convert_one("both", figure_sheet="replace")
    assert res.docx_path.is_file() and res.md_path.is_file()
    assert (res.asset_dir / "sheet-1.png").is_file() and not (res.asset_dir / "p1-img1.png").exists()


def test_add_mode_in_a_conversion_keeps_the_single_images(convert_one):
    res = convert_one("md", figure_sheet="add")
    assert sorted(p.name for p in res.asset_dir.iterdir()) == ["p1-img1.png", "sheet-1.png"]
    md = res.md_path.read_text(encoding="utf-8")
    assert "![[_asset-Kim-2024/p1-img1.png]]" in md and "![[_asset-Kim-2024/sheet-1.png]]" in md


def test_default_conversion_makes_no_sheet(convert_one):
    res = convert_one("md")
    assert sorted(p.name for p in res.asset_dir.iterdir()) == ["p1-img1.png"]
    assert "figure_sheets" not in res.md_path.read_text(encoding="utf-8")
