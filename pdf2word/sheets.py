"""Figure sheets: the block-level images a Markdown note embeds (figures, caption-less pictures,
equation crops) tiled onto a few labelled PNGs, so that an LLM ingesting the note reads 2-4
images instead of 20.

One sheet stays within what Claude reads at native resolution - long edge <= 2,000 px (the
API allows 2,576, but Claude Code's Read tool was seen to shrink wider images to about 2,000)
and <= 4,784 patches of 28 x 28 px (Claude 4.7 and later) - so nothing is downscaled on
upload. The tiles are drawn at `dpi` (default 120: on paper-01 axis ticks, legends and
equation structure read the same as at 150) from the saved PNGs, whose own resolution is read
from the file. Inline symbol images (`inline*`, part of a sentence) are left alone."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

import pymupdf

from .obsidian import image_link
from .utils import log

PATCH = 28               # Claude's visual token = one 28 x 28 px patch
MAX_PATCHES = 4784       # native-resolution limit (Claude 4.7+); 1,568 on older models
MAX_EDGE = 2576          # px, the API's native limit
SHEET_EDGE = 2000        # px, the default sheet edge: Claude Code's Read tool was seen to shrink wider images
                         # to about 2,000 px, and on paper-01 the smaller edge costs no extra sheets or tokens
GUTTER = 16              # px between tiles and around the sheet
LABEL_H = 26             # label strip above every tile
TITLE_H = 30             # title band at the top of every sheet: "<paper> · sheet 1/2"
FONT_SIZE = 13
TITLE_FONT = 15
SECTION_TITLE = "그림 모음 (figure sheets)"

# a line that is nothing but an embed: ![[folder/file.png]] (Obsidian, optional |alias) or ![alt](folder/file.png)
EMBED_LINE = re.compile(r"^[ \t]*(?:!\[\[([^\]|\n]+?)(?:\|[^\]\n]*)?\]\]|!\[[^\]\n]*\]\(([^)\n]+)\))[ \t]*$", re.M)

_LABELS = [
    (re.compile(r"^fig(\d+[a-z]?)$", re.I), "Fig. {}"),
    (re.compile(r"^(?:table)(\w+)$", re.I), "Table {}"),
    (re.compile(r"^(?:scheme)(\w+)$", re.I), "Scheme {}"),
    (re.compile(r"^(?:algorithm)(\w+)$", re.I), "Algorithm {}"),
    (re.compile(r"^(?:chart)(\w+)$", re.I), "Chart {}"),
    (re.compile(r"^(?:plate)(\w+)$", re.I), "Plate {}"),
    (re.compile(r"^eq-(.+)$", re.I), "Eq. ({})"),
]


def label_for(name: str) -> str:
    """fig3.png -> 'Fig. 3', fig3a.png -> 'Fig. 3a', table2.png -> 'Table 2', eq-12.png -> 'Eq. (12)',
    p4-img10.png -> 'p4-img10' (the file stem when nothing better is known)."""
    stem = Path(name).stem
    for pat, fmt in _LABELS:
        m = pat.match(stem)
        if m:
            return fmt.format(m.group(1))
    return stem


def patches(width: int, height: int) -> int:
    return math.ceil(width / PATCH) * math.ceil(height / PATCH)


def sheet_prefix(asset_folder: str) -> str:
    """The paper id that names the sheets: `_asset-Wang-2014` -> `Wang-2014`, so that sheets of
    several papers never share a file name (`Wang-2014-sheet-1.png`) even when uploaded together."""
    name = asset_folder[len("_asset-"):] if asset_folder.startswith("_asset-") else asset_folder
    return name.strip("-") or "paper"


def _title_font(text: str) -> str:
    """Helvetica-Bold for Latin text; PyMuPDF's built-in Korean font when the paper id has Hangul."""
    try:
        text.encode("latin-1")
        return "hebo"
    except UnicodeEncodeError:
        return "korea"


@dataclass
class Tile:
    name: str                  # file name in the asset folder
    pix: pymupdf.Pixmap
    w: int                     # size on the sheet (px)
    h: int
    label: str


@dataclass
class Placed:
    tile: Tile
    x: int
    y: int                     # top of the label strip
    w: int
    h: int                     # image height (label strip excluded)


@dataclass
class SheetResult:
    body: str
    sheets: list = field(default_factory=list)     # sheet file names, in order
    tiled: list = field(default_factory=list)      # image file names that went onto the sheets, in order
    stale: list = field(default_factory=list)      # files to delete (mode "replace") once every output is written


def load_tile(path: Path, dpi: int, fallback_dpi: int) -> Optional[Tile]:
    try:
        pix = pymupdf.Pixmap(str(path))
    except Exception as exc:
        log.debug("  sheet: cannot read %s (%s)", path.name, exc)
        return None
    if pix.width <= 0 or pix.height <= 0:
        return None
    src_dpi = pix.xres if pix.xres and pix.xres >= 100 else fallback_dpi   # pHYs of our own PNGs (200 / 216 ...)
    scale = dpi / max(src_dpi, 1)
    w = max(1, int(round(pix.width * scale)))
    h = max(1, int(round(pix.height * scale)))
    return Tile(path.name, pix, w, h, label_for(path.name))


def _fit(t: Tile, max_edge: int, max_patches: int) -> tuple:
    """Tile size on a sheet: shrunk only when the tile alone would exceed the sheet limits."""
    s = min(1.0, (max_edge - 2 * GUTTER) / t.w, (max_edge - 2 * GUTTER - LABEL_H - TITLE_H) / t.h)
    tw, th = t.w, t.h
    for _ in range(80):
        tw, th = max(1, int(t.w * s)), max(1, int(t.h * s))
        if patches(tw + 2 * GUTTER, th + LABEL_H + TITLE_H + 2 * GUTTER) <= max_patches:
            break
        s *= 0.97
    return tw, th


def pack(tiles: list, max_edge: int = SHEET_EDGE, max_patches: int = MAX_PATCHES, by_height: bool = True) -> list:
    """Shelf packing -> [[Placed, ...] per sheet]. `by_height` (default) sorts the tiles tallest
    first so that each shelf holds tiles of similar height and little space is wasted (the
    labels on the tiles make the order irrelevant for reading); False keeps document order.
    A sheet may grow up to `max_edge` px on either side as long as its used area stays within
    `max_patches` (the width is trimmed to what is used, so a column of narrow tiles can be
    tall and a row of wide tiles stays short). A new sheet starts when neither the current
    shelf nor a new shelf keeps the sheet within the budget."""
    def fits(w: int, h: int) -> bool:
        return w <= max_edge and h <= max_edge and patches(w, h) <= max_patches

    sized = [(t, *_fit(t, max_edge, max_patches)) for t in tiles]
    if by_height:
        sized.sort(key=lambda s: -s[2])                     # stable: equal heights keep document order
    sheets: list = []
    cur: list = []
    x, y = GUTTER, GUTTER + TITLE_H                     # tiles start below the title band
    shelf_h = used_w = 0
    for t, tw, th in sized:
        need = LABEL_H + th
        if cur and fits(max(used_w, x + tw + GUTTER), max(y + shelf_h, y + need) + GUTTER):
            pass                                        # same shelf
        elif cur and fits(max(used_w, 2 * GUTTER + tw), y + shelf_h + GUTTER + need + GUTTER):
            x, y, shelf_h = GUTTER, y + shelf_h + GUTTER, 0   # next shelf
        else:
            if cur:
                sheets.append(cur)                      # next sheet
            cur, x, y, shelf_h, used_w = [], GUTTER, GUTTER + TITLE_H, 0, 0
        cur.append(Placed(t, x, y, tw, th))
        used_w = max(used_w, x + tw + GUTTER)
        x += tw + GUTTER
        shelf_h = max(shelf_h, need)
    if cur:
        sheets.append(cur)
    return sheets


def render_sheet(placed: list, path: Path, title: str = "") -> tuple:
    """Draw one sheet (title band, then a label strip + bordered tile each) and save it;
    returns (width, height) in px."""
    width = max(p.x + p.w for p in placed) + GUTTER
    height = max(p.y + LABEL_H + p.h for p in placed) + GUTTER
    doc = pymupdf.open()
    try:
        page = doc.new_page(width=width, height=height)          # 1 pt = 1 px at get_pixmap(Identity)
        if title:
            page.insert_text((GUTTER, GUTTER + TITLE_H - 9), title, fontsize=TITLE_FONT, fontname=_title_font(title))
        for p in placed:
            page.insert_text((p.x + 2, p.y + LABEL_H - 7), p.tile.label, fontsize=FONT_SIZE, fontname="helv")
            rect = pymupdf.Rect(p.x, p.y + LABEL_H, p.x + p.w, p.y + LABEL_H + p.h)
            page.insert_image(rect, pixmap=p.tile.pix)
            page.draw_rect(rect, color=(0.55, 0.55, 0.55), width=1)
        pix = page.get_pixmap(matrix=pymupdf.Identity, alpha=False)
        pix.save(str(path))
    finally:
        doc.close()
    return width, height


def apply_sheets(body: str, asset_dir: Path, style: str = "wiki", dpi: int = 120, fallback_dpi: int = 200,
                 mode: str = "replace", by_height: bool = True, max_edge: int = SHEET_EDGE) -> SheetResult:
    """Tile the images `body` embeds (block-level lines pointing into `asset_dir`) onto
    `<paper>-sheet-N.png` files in `asset_dir` and rewrite the body: mode "replace" turns each embed
    line into `*[Fig. 3 → _asset-Wang-2014/Wang-2014-sheet-1.png]*` (folder included, so the marker
    stays unambiguous when several papers share a context), mode "add" keeps the embeds; both append
    a section listing the sheets. Nothing is deleted here - `stale` names the files the caller
    removes after every output (Word included) has been written."""
    folder = asset_dir.name
    found: list = []                                   # (match, file name) in document order
    for m in EMBED_LINE.finditer(body):
        ref = (m.group(1) or unquote(m.group(2) or "")).strip().replace("\\", "/")
        if "/" not in ref:
            continue
        where, name = ref.rsplit("/", 1)
        if where != folder or name.lower().startswith("inline") or not (asset_dir / name).is_file():
            continue
        found.append((m, name))
    if not found:
        return SheetResult(body)
    tiles: list = []
    seen: set = set()
    for _, name in found:
        if name in seen:
            continue
        seen.add(name)
        tile = load_tile(asset_dir / name, dpi, fallback_dpi)
        if tile is not None:
            tiles.append(tile)
    if not tiles:
        return SheetResult(body)
    sheets = pack(tiles, max_edge=max_edge, by_height=by_height)
    prefix = sheet_prefix(folder)
    sheet_of: dict = {}
    names: list = []
    for i, placed in enumerate(sheets, 1):
        sname = f"{prefix}-sheet-{i}.png"
        render_sheet(placed, asset_dir / sname, f"{prefix} · sheet {i}/{len(sheets)}")
        names.append(sname)
        for p in placed:
            sheet_of[p.tile.name] = sname
    tiled = [t.name for t in tiles]
    if mode == "replace":
        def marker(m):
            ref = (m.group(1) or unquote(m.group(2) or "")).strip().replace("\\", "/")
            name = ref.rsplit("/", 1)[-1]
            if ref.rsplit("/", 1)[0] != folder or name not in sheet_of:
                return m.group(0)
            return f"*[{label_for(name)} → {folder}/{sheet_of[name]}]*"
        body = EMBED_LINE.sub(marker, body)
    lines = [f"\n\n## {SECTION_TITLE}\n"]
    for sname, placed in zip(names, sheets):
        labels = " · ".join(p.tile.label for p in placed)
        lines.append(f"\n{sname}: {labels}\n{image_link(f'{folder}/{sname}', Path(sname).stem, style)}\n")
    body = body.rstrip() + "".join(lines)
    return SheetResult(body, names, tiled, list(tiled) if mode == "replace" else [])
