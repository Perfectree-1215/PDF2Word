"""Figure panels: picture boxes that share one caption are rendered as ONE image
(docs/issues/figure-panel-merge.md). Synthetic pages, hand-made layout boxes, no model."""
from __future__ import annotations

import logging
from collections import Counter

import pymupdf

from pdf2word.config import Options
from pdf2word.converter import Converter, _DocContext

PANEL_L = (100, 200, 290, 350)
PANEL_R = (305, 200, 495, 350)
CAPTION_WIDE = (100, 362, 495, 380)
CAPTION_LEFT = (100, 362, 290, 380)


def _page(doc, images, texts=(), textboxes=(), shade=0):
    """A page with a grey bitmap at every `images` rect, (x, y, string, fontsize) texts and
    (rect, string, fontsize) text boxes. Returns the page."""
    page = doc.new_page(width=595, height=794)
    for k, r in enumerate(images):
        pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 40, 30), False)
        pix.clear_with(60 + 30 * k + shade)
        page.insert_image(pymupdf.Rect(r), pixmap=pix)
    for x, y, s, size in texts:
        page.insert_text((x, y), s, fontsize=size)
    for r, s, size in textboxes:
        assert page.insert_textbox(pymupdf.Rect(r), s, fontsize=size) >= 0, "text box too small"
    return page


def _chunk(spec):
    """spec: [(class, bbox, markdown text), ...] in reading order -> the chunk render_page expects."""
    text, boxes = "", []
    for i, (cls, bbox, s) in enumerate(spec):
        boxes.append({"class": cls, "bbox": tuple(bbox), "pos": (len(text), len(text) + len(s)), "index": i})
        text += s + "\n\n"
    return {"text": text, "page_boxes": boxes}


def _ctx(doc, tmp_path, **opts):
    opt = Options(math_engine="none", lighten=False, vector_math=False, inline_image_math=False,
                  inline_text_math=False, **opts)
    return _DocContext(doc, tmp_path, Counter(), Converter(opt))


def _pngs(tmp_path):
    return sorted(p.name for p in tmp_path.glob("*.png"))


def test_default_is_merge():
    assert Options().figure_panels == "merge"


def test_panels_sharing_a_caption_become_one_image(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="pdf2word")
    doc = pymupdf.open()
    page = _page(doc, [PANEL_L, PANEL_R], texts=[(100, 372, "Figure 2. Two panels of one figure.", 9)])
    chunk = _chunk([("picture", PANEL_L, ""), ("picture", PANEL_R, ""),
                    ("caption", CAPTION_WIDE, "Figure 2. Two panels of one figure.")])
    ctx = _ctx(doc, tmp_path)
    md = ctx.render_page(page, chunk)
    assert _pngs(tmp_path) == ["fig2.png"]
    assert md.count("![[") == 1 and "fig2.png" in md and "^fig-2" in md
    assert ctx.stats["figures"] == 1 and ctx.stats["panels_merged"] == 2
    pix = pymupdf.Pixmap(str(tmp_path / "fig2.png"))          # the union of both panels, 395 x 150 pt at 200 dpi
    assert abs(pix.width - 395 * 200 / 72) <= 3 and abs(pix.height - 150 * 200 / 72) <= 3
    assert "Figure 2: 2 panels merged into one image" in caplog.text
    doc.close()


def test_split_option_keeps_one_file_per_panel(tmp_path):
    doc = pymupdf.open()
    page = _page(doc, [PANEL_L, PANEL_R], texts=[(100, 372, "Figure 2. Two panels.", 9)])
    chunk = _chunk([("picture", PANEL_L, ""), ("picture", PANEL_R, ""), ("caption", CAPTION_WIDE, "Figure 2. Two panels.")])
    ctx = _ctx(doc, tmp_path, figure_panels="split")
    md = ctx.finalize_subfigures(ctx.render_page(page, chunk))
    assert _pngs(tmp_path) == ["fig2a.png", "fig2b.png"]          # the pre-merge behaviour
    assert md.count("![[") == 2 and ctx.stats["figures"] == 2 and ctx.stats["panels_merged"] == 0
    doc.close()


# two pieces of one figure stacked in a column, something between them, caption below
TOP = (100, 260, 300, 330)
BETWEEN = (100, 336, 300, 392)
BOTTOM = (100, 398, 300, 470)
CAPTION_LOW = (100, 476, 300, 490)


def test_paragraph_between_panels_blocks_the_merge(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="pdf2word")
    doc = pymupdf.open()
    body = "Body text that sits between two pieces of one figure. " * 4     # ~216 characters, 5 lines at 8 pt
    page = _page(doc, [TOP, BOTTOM], texts=[(100, 486, "Figure 3. Stacked pieces.", 9)], textboxes=[(BETWEEN, body, 8)])
    chunk = _chunk([("picture", TOP, ""), ("text", BETWEEN, body), ("picture", BOTTOM, ""),
                    ("caption", CAPTION_LOW, "Figure 3. Stacked pieces.")])
    ctx = _ctx(doc, tmp_path)
    md = ctx.render_page(page, chunk)
    assert _pngs(tmp_path) == ["fig3.png", "fig3a.png"]
    assert body in md and md.count("![[") == 2                   # the paragraph is untouched
    assert ctx.stats["panels_merged"] == 0
    assert "Figure 3: 2 panels kept separate (text between panels)" in caplog.text
    doc.close()


def test_table_between_panels_blocks_the_merge(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger="pdf2word")
    doc = pymupdf.open()
    page = _page(doc, [TOP, BOTTOM], texts=[(100, 486, "Figure 4. Pieces around a table.", 9)])
    chunk = _chunk([("picture", TOP, ""), ("table", BETWEEN, "| a | b |\n|---|---|\n| 1 | 2 |"), ("picture", BOTTOM, ""),
                    ("caption", CAPTION_LOW, "Figure 4. Pieces around a table.")])
    ctx = _ctx(doc, tmp_path)
    ctx.render_page(page, chunk)
    assert _pngs(tmp_path) == ["fig4.png", "fig4a.png"]
    assert ctx.stats["panels_merged"] == 0
    assert "Figure 4: 2 panels kept separate (other box inside)" in caplog.text
    doc.close()


def test_two_by_two_panels_with_short_labels_merge(tmp_path):
    doc = pymupdf.open()
    panels = [(100, 200, 290, 320), (305, 200, 495, 320), (100, 334, 290, 454), (305, 334, 495, 454)]
    labels = [(188, 323, 206, 333, "(a)"), (393, 323, 411, 333, "(b)"), (188, 457, 206, 467, "(c)"), (393, 457, 411, 467, "(d)")]
    page = _page(doc, panels, texts=[(x0 + 2, y1 - 2, s, 7) for x0, y0, x1, y1, s in labels] +
                 [(100, 486, "Figure 5. Four panels.", 9)])
    spec = []
    for p, (x0, y0, x1, y1, s) in zip(panels, labels):
        spec += [("picture", p, ""), ("text", (x0, y0, x1, y1), s)]
    spec.append(("caption", (100, 476, 495, 490), "Figure 5. Four panels."))
    ctx = _ctx(doc, tmp_path)
    md = ctx.render_page(page, _chunk(spec))
    assert _pngs(tmp_path) == ["fig5.png"]
    assert md.count("![[") == 1 and ctx.stats["panels_merged"] == 4
    assert "(a)" in md and "(d)" in md                            # the labels stay in the text
    doc.close()


def test_panels_on_different_pages_stay_separate(tmp_path):
    doc = pymupdf.open()
    _page(doc, [PANEL_L], texts=[(100, 372, "Figure 3. First part.", 9)])
    _page(doc, [PANEL_L], texts=[(100, 372, "Figure 3. Second part.", 9)], shade=50)
    ctx = _ctx(doc, tmp_path)                 # pages fetched after both exist: new_page() invalidates earlier Page objects
    md = ctx.render_page(doc[0], _chunk([("picture", PANEL_L, ""), ("caption", CAPTION_LEFT, "Figure 3. First part.")]))
    md += ctx.render_page(doc[1], _chunk([("picture", PANEL_L, ""), ("caption", CAPTION_LEFT, "Figure 3. Second part.")]))
    md = ctx.finalize_subfigures(md)
    assert _pngs(tmp_path) == ["fig3a.png", "fig3b.png"]
    assert ctx.stats["panels_merged"] == 0 and md.count("![[") == 2
    doc.close()


def test_caption_less_fragment_next_to_a_panel_joins_it(tmp_path):
    doc = pymupdf.open()
    near = (298, 200, 400, 350)          # 8 pt right of PANEL_L, no caption of its own (no horizontal overlap)
    page = _page(doc, [PANEL_L, near], texts=[(100, 372, "Figure 4. One panel and a fragment.", 9)])
    chunk = _chunk([("picture", PANEL_L, ""), ("picture", near, ""), ("caption", CAPTION_LEFT, "Figure 4. One panel and a fragment.")])
    ctx = _ctx(doc, tmp_path)
    md = ctx.render_page(page, chunk)
    assert _pngs(tmp_path) == ["fig4.png"]
    assert ctx.stats["panels_merged"] == 2 and md.count("![[") == 1
    doc.close()


def test_caption_less_picture_far_from_a_panel_stays_its_own_file(tmp_path):
    doc = pymupdf.open()
    far = (330, 200, 430, 350)           # 40 pt away: not a fragment of Figure 4
    page = _page(doc, [PANEL_L, far], texts=[(100, 372, "Figure 4. One panel.", 9)])
    chunk = _chunk([("picture", PANEL_L, ""), ("picture", far, ""), ("caption", CAPTION_LEFT, "Figure 4. One panel.")])
    ctx = _ctx(doc, tmp_path)
    md = ctx.render_page(page, chunk)
    assert _pngs(tmp_path) == ["fig4.png", "p1-img2.png"]
    assert ctx.stats["panels_merged"] == 0 and md.count("![[") == 2
    doc.close()
