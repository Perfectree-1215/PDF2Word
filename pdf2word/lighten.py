"""Make a *lightened* copy of a PDF for layout analysis.

Some PDF producers (InDesign exports of plots, for instance) place the SAME full-resolution
bitmap dozens of times on a page, each occurrence clipped to a tiny tick label or marker.
Text extraction with images, and therefore PyMuPDF Layout, then decodes 50-120 large JPEGs
per page and takes minutes. For such pages we build a copy where each dense cluster of image
placements is replaced by ONE rendered image of the cluster region. Text is kept, so
extraction and reading order are unaffected; the original document is still used for
everything that needs pixels at full quality (equations, inline images).
"""
from __future__ import annotations

import logging

import pymupdf

log = logging.getLogger("pdf2word")

PAGE_THRESHOLD = 20        # image placements on a page before we bother ...
PAGE_PIXEL_THRESHOLD = 40e6  # ... or this many source pixels to decode (~10 large JPEGs)
CLUSTER_MIN_IMAGES = 6     # image placements a cluster needs to be replaced ...
CLUSTER_PIXEL_THRESHOLD = 16e6  # ... or this many source pixels inside the cluster
CLUSTER_GAP = 12.0         # pt: rects closer than this are joined
MAX_TEXT_DENSITY = 0.35    # clusters with more text than this are paragraphs, not figures


def cluster_rects(rects: list, gap: float = CLUSTER_GAP) -> list:
    """Union-find clustering: rects whose gap-expanded boxes intersect belong together.
    Returns [(bbox, [member indices]), ...]."""
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


def _text_density(page: pymupdf.Page, rect: pymupdf.Rect) -> float:
    area = rect.get_area()
    if area <= 0:
        return 0.0
    covered = 0.0
    flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    for block in page.get_text("dict", clip=rect, flags=flags)["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            lr = pymupdf.Rect(line["bbox"]) & rect
            if not lr.is_empty:
                covered += lr.get_area()
    return covered / area


def heavy_pages(doc: pymupdf.Document) -> dict:
    """{page_number: [(placement rect, source pixels), ...]} for pages that are expensive to
    extract: many image placements, or a lot of bitmap pixels to decode.

    Uses get_image_info(), which reads placements without decoding the bitmaps."""
    heavy = {}
    for pno in range(doc.page_count):
        try:
            infos = doc[pno].get_image_info()
        except Exception:
            continue
        items = []
        for i in infos:
            r = pymupdf.Rect(i["bbox"])
            if r.is_empty:
                continue
            items.append((r, float(i.get("width") or 0) * float(i.get("height") or 0)))
        pixels = sum(p for _, p in items)
        if len(items) >= PAGE_THRESHOLD or pixels >= PAGE_PIXEL_THRESHOLD:
            heavy[pno] = items
    return heavy


BIG_SOURCE_PIXELS = 1_000_000   # bitmaps at least this large are swapped for a stand-in


def big_image_xrefs(doc: pymupdf.Document) -> set:
    """XObject numbers of large bitmaps (decoding them dominates extraction time)."""
    big = set()
    for pno in range(doc.page_count):
        try:
            infos = doc[pno].get_images(full=True)
        except Exception:
            continue
        for info in infos:
            xref, w, h = info[0], info[2], info[3]
            if xref and w * h >= BIG_SOURCE_PIXELS:
                big.add(xref)
    return big


def shrink_big_images(light: pymupdf.Document, xrefs: set) -> int:
    """Replace large bitmaps by a 16x16 grey stand-in. Placement rectangles (what the layout
    model looks at) stay the same; the pixels are never needed from this copy."""
    if not xrefs:
        return 0
    stand_in = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 16, 16), 0)
    stand_in.set_rect(stand_in.irect, (200, 200, 200))
    done = set()
    for pno in range(light.page_count):
        page = light[pno]
        for info in page.get_images(full=True):
            xref = info[0]
            if xref in xrefs and xref not in done:
                try:
                    page.replace_image(xref, pixmap=stand_in)
                    done.add(xref)
                except Exception as exc:
                    log.debug("replace_image(%s) failed: %s", xref, exc)
    return len(done)


def lighten_document(doc: pymupdf.Document, dpi: int = 72):
    """Return (document for layout analysis, number of pages whose image clusters were merged).

    The returned document is `doc` itself when nothing needed to change. It must only be used
    for layout analysis / text extraction - pixels come from the original document."""
    heavy = heavy_pages(doc)
    big = big_image_xrefs(doc)
    if not heavy and not big:
        return doc, 0
    light = pymupdf.open("pdf", doc.tobytes())
    n_big = shrink_big_images(light, big)
    if n_big:
        log.info("  %d large bitmap(s) replaced by stand-ins for layout analysis", n_big)
    graphics_remove = getattr(pymupdf, "PDF_REDACT_LINE_REMOVE", 1)
    text_keep = getattr(pymupdf, "PDF_REDACT_TEXT_NONE", 1)
    image_remove = getattr(pymupdf, "PDF_REDACT_IMAGE_REMOVE", 1)
    changed = 0
    for pno, items in heavy.items():
        orig = doc[pno]
        page = light[pno]
        rects = [r for r, _ in items]
        pixels = [p for _, p in items]
        n_img = len(rects)
        drawings = []
        try:
            drawings = [pymupdf.Rect(d["rect"]) for d in orig.get_drawings()
                        if not pymupdf.Rect(d["rect"]).is_empty]
        except Exception:
            pass
        members = rects + [r for r in drawings if r.width < orig.rect.width * 0.9]
        replacements = []
        for bbox, idx in cluster_rects(members):
            img_idx = [i for i in idx if i < n_img]
            if len(img_idx) < CLUSTER_MIN_IMAGES and sum(pixels[i] for i in img_idx) < CLUSTER_PIXEL_THRESHOLD:
                continue
            if len(img_idx) == 1 and _text_density(orig, bbox) >= MAX_TEXT_DENSITY:
                continue                       # one big photo behind text: leave it alone
            bbox = (bbox + (-2, -2, 2, 2)) & orig.rect
            if bbox.is_empty:
                continue
            pix = None
            if _text_density(orig, bbox) < MAX_TEXT_DENSITY:
                pix = orig.get_pixmap(clip=bbox, dpi=dpi)
            replacements.append((bbox, pix))
        if not replacements:
            continue
        for bbox, _ in replacements:
            page.add_redact_annot(bbox)
        try:
            page.apply_redactions(images=image_remove, graphics=graphics_remove, text=text_keep)
        except TypeError:                       # older PyMuPDF without `graphics`
            page.apply_redactions(images=image_remove, text=text_keep)
        for bbox, pix in replacements:
            if pix is not None:
                page.insert_image(bbox, pixmap=pix)
        changed += 1
        log.info("  page %d: %d image placements -> %d region(s) merged for layout analysis",
                 pno + 1, n_img, len(replacements))
    if not changed and not n_big:
        light.close()
        return doc, 0
    return light, changed
