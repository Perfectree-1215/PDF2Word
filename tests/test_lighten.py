"""Lightened layout copy (lighten.py): image-cluster merging on heavy pages and the
union-find clustering behind it. Synthetic PDFs and rectangles only.

Run:  python -m pytest tests -q      (or)      python tests/test_lighten.py
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf2word import lighten  # noqa: E402
from pdf2word.lighten import CLUSTER_GAP, cluster_rects  # noqa: E402


def _cluster_rects_pairwise(rects: list, gap: float = CLUSTER_GAP) -> list:
    """Reference: cluster_rects as it was before the sweep (every pair compared)."""
    n = len(rects)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    expanded = [pymupdf.Rect(r) + (-gap, -gap, gap, gap) for r in rects]
    for i in range(n):
        for j in range(i + 1, n):
            if expanded[i].intersects(expanded[j]):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj
    groups: dict = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    out = []
    for members in groups.values():
        bbox = pymupdf.Rect(rects[members[0]])
        for m in members[1:]:
            bbox |= rects[m]
        out.append((bbox, members))
    return out


def _groups(clusters) -> list:
    return sorted((tuple(members), tuple(bbox)) for bbox, members in clusters)


def _random_rects(seed: int, n: int, gap: float = CLUSTER_GAP) -> list:
    """Separated, overlapping, exactly touching (edges 2*gap apart), nearly touching, duplicate
    and long thin rects, mixed."""
    rnd = random.Random(seed)
    rects: list = []
    while len(rects) < n:
        kind = rnd.random()
        if not rects or kind < 0.35:                       # anywhere (mostly separated)
            x, y = rnd.uniform(0, 600), rnd.uniform(0, 780)
            rects.append(pymupdf.Rect(x, y, x + rnd.uniform(0.5, 8), y + rnd.uniform(0.5, 8)))
            continue
        b = rnd.choice(rects)
        if kind < 0.55:                                    # overlapping a placed rect
            x, y = rnd.uniform(b.x0 - 4, b.x1), rnd.uniform(b.y0 - 4, b.y1)
            rects.append(pymupdf.Rect(x, y, x + rnd.uniform(1, 6), y + rnd.uniform(1, 6)))
        elif kind < 0.75:                                  # integer grid: exactly touching / just inside
            x0, y0 = rnd.randrange(0, 600), rnd.randrange(0, 780)
            w, h = rnd.randrange(1, 9), rnd.randrange(1, 9)
            a = pymupdf.Rect(x0, y0, x0 + w, y0 + h)
            d = 2 * gap - rnd.choice((0, 0, 1))
            c = (pymupdf.Rect(a.x1 + d, y0, a.x1 + d + w, y0 + h) if rnd.random() < 0.5
                 else pymupdf.Rect(x0, a.y1 + d, x0 + w, a.y1 + d + h))
            rects += [a, c]
        elif kind < 0.85:                                  # duplicate placement
            rects.append(pymupdf.Rect(b))
        else:                                              # long rule (wide or tall)
            x, y = rnd.uniform(0, 500), rnd.uniform(0, 700)
            rects.append(pymupdf.Rect(x, y, x + rnd.uniform(40, 300), y + 1) if rnd.random() < 0.5
                         else pymupdf.Rect(x, y, x + 1, y + rnd.uniform(40, 300)))
    return rects[:n]


def test_cluster_rects_sweep_matches_pairwise():
    """#110: the x-sorted sweep finds exactly the clusters of the all-pairs comparison."""
    for seed in range(4):
        for n in (0, 1, 2, 7, 60, 300):
            rects = _random_rects(seed, n)
            assert _groups(cluster_rects(rects)) == _groups(_cluster_rects_pairwise(rects)), (seed, n)
    rects = _random_rects(99, 600)
    got, ref = _groups(cluster_rects(rects)), _groups(_cluster_rects_pairwise(rects))
    assert got == ref and 1 < len(ref) < 600
    for gap in (0.0, 3.0, 30.0):
        rects = _random_rects(7, 300, gap)
        assert _groups(cluster_rects(rects, gap)) == _groups(_cluster_rects_pairwise(rects, gap)), gap


def test_cluster_rects_touching_edges_stay_apart():
    """Expanded boxes that only share an edge do not intersect (same as before the sweep)."""
    a, b = pymupdf.Rect(0, 0, 4, 4), pymupdf.Rect(4 + 2 * CLUSTER_GAP, 0, 8 + 2 * CLUSTER_GAP, 4)
    c = pymupdf.Rect(b.x1 + 2 * CLUSTER_GAP - 1, 0, b.x1 + 2 * CLUSTER_GAP + 3, 4)
    assert _groups(cluster_rects([a, b, c])) == [((0,), tuple(a)), ((1, 2), tuple(b | c))]


def test_cluster_rects_sweep_skips_far_pairs(monkeypatch):
    """#110: rects far apart along x are never compared (was n*(n-1)/2 comparisons)."""
    calls = [0]
    real = pymupdf.Rect.intersects

    def counting(self, other):
        calls[0] += 1
        return real(self, other)

    monkeypatch.setattr(pymupdf.Rect, "intersects", counting)
    n = 200
    rects = [pymupdf.Rect(30 * k, 0, 30 * k + 4, 4) for k in range(n)]   # 26 pt apart > 2*gap
    assert len(cluster_rects(rects)) == n
    assert calls[0] < n


def _heavy_doc(n_img: int = 40, n_draw: int = 0, seed: int = 1) -> pymupdf.Document:
    """One page: the SAME small bitmap placed n_img times (tick labels), n_draw plot markers
    (one path each) and a line of body text below."""
    rnd = random.Random(seed)
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 64, 64), 0)
    pix.set_rect(pix.irect, (30, 90, 160))
    xref = 0
    for k in range(n_img):
        x, y = 60 + (k % 10) * 24, 80 + (k // 10) * 24
        r = pymupdf.Rect(x, y, x + 8, y + 8)
        xref = page.insert_image(r, pixmap=pix) if not xref else page.insert_image(r, xref=xref)
    if n_draw:
        sh = page.new_shape()
        for _ in range(n_draw):
            sh.draw_circle((rnd.uniform(40, 560), rnd.uniform(400, 680)), 1.5)
            sh.finish(color=(0, 0, 0), fill=(0, 0, 0))
        sh.commit()
    page.insert_text((72, 740), "Body text stays after lightening.", fontsize=11)
    return pymupdf.open("pdf", doc.tobytes())


def _snapshot(doc: pymupdf.Document) -> tuple:
    page = doc[0]
    rnd = lambda r: tuple(round(v, 2) for v in r)  # noqa: E731
    return (sorted(rnd(i["bbox"]) for i in page.get_image_info()),
            sorted(rnd(d["rect"]) for d in page.get_drawings()),
            page.get_text())


def test_lighten_heavy_page_merges_image_cluster():
    """40 placements of one bitmap become one rendered image; the text layer is untouched."""
    doc = _heavy_doc()
    assert len(doc[0].get_image_info()) == 40
    light, changed = lighten.lighten_document(doc)
    assert changed == 1 and light is not doc
    infos = light[0].get_image_info()
    assert len(infos) == 1
    assert pymupdf.Rect(infos[0]["bbox"]).contains(pymupdf.Rect(60, 80, 284, 160))
    assert light[0].get_text() == doc[0].get_text()
    assert len(doc[0].get_image_info()) == 40                          # original left alone


def test_lighten_redacts_with_pymupdf_constants(monkeypatch):
    """#109: redaction modes are pymupdf's named constants (a misspelt getattr name fell back
    to a literal 1), passed in one apply_redactions call per merged page."""
    calls = []
    real = pymupdf.Page.apply_redactions

    def spy(self, *args, **kwargs):
        calls.append((args, kwargs))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(pymupdf.Page, "apply_redactions", spy)
    monkeypatch.setattr(pymupdf, "PDF_REDACT_LINE_ART_REMOVE_IF_COVERED",
                        pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED)
    _, changed = lighten.lighten_document(_heavy_doc())
    assert changed == 1
    assert calls == [((), {"images": pymupdf.PDF_REDACT_IMAGE_REMOVE,
                           "graphics": pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,
                           "text": pymupdf.PDF_REDACT_TEXT_NONE})]


def test_lighten_copy_same_as_pairwise_clustering(monkeypatch):
    """#110 end to end: with images and 300 marker paths the light copy is the same as with
    the old all-pairs clustering."""
    doc = _heavy_doc(n_img=60, n_draw=300, seed=3)
    new, changed = lighten.lighten_document(doc)
    monkeypatch.setattr(lighten, "cluster_rects", _cluster_rects_pairwise)
    old, changed_old = lighten.lighten_document(doc)
    assert changed == changed_old == 1
    assert _snapshot(new) == _snapshot(old)


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
