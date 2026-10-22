from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# default name templates, chosen by document type when the user gives none
PAPER_NAME_TEMPLATE = "{author}-{year}-{title}"
PAPER_ASSET_TEMPLATE = "_asset-{author}-{year}"
DOC_NAME_TEMPLATE = "{stem}"
DOC_ASSET_TEMPLATE = "_asset-{stem}"
CHAPTER_NAME_TEMPLATE = "{stem}-{num}-{title}"
CHAPTER_ASSET_TEMPLATE = "_asset-{stem}-{num}"


@dataclass
class Options:
    """All knobs of a conversion. Defaults are tuned for journal/conference papers; books,
    manuals and reports are handled by doc_type='document' (auto-detected by default)."""

    # --- output ------------------------------------------------------------
    format: str = "docx"                        # "docx" | "md" | "both"
    docx_math: str = "native"                   # "native" (Word equations via Office XSL) | "text"
    out_dir: Optional[Path] = None              # default: the folder of the PDF
    asset_template: Optional[str] = None        # None -> by document type (see the constants above)
    name_template: Optional[str] = None         # None -> by document type
    overwrite: bool = True
    image_links: str = "wiki"                   # "wiki" -> ![[...]], "markdown" -> ![](...)
    block_ids: bool = True                      # add ^eq-3 / ^fig-2 block anchors
    citations: str = "keep"                     # "keep" | "footnotes"
    abstract_callout: bool = True

    # --- document type / chapters -------------------------------------------
    doc_type: str = "auto"                      # "auto" | "paper" | "document" (book, manual, report)
    chapters: Optional[str] = None              # bookmark ids to convert separately: "3,4.2-4.5", "all", "all:2"
    chapter_split: str = "exact"                # "exact" = cut at the bookmark position | "page" = whole pages
    chapter_template: str = CHAPTER_NAME_TEMPLATE   # file name of one chapter / page group
    split_pages: int = 0                        # > 0: one file per N pages (for PDFs without bookmarks)
    chapter_depth: int = 2                      # depth shown by --list-chapters
    subchapters: bool = False                   # split each selected entry into its direct sub-entries

    # --- metadata ----------------------------------------------------------
    online: bool = True                         # CrossRef / arXiv lookup
    author: Optional[str] = None                # override: first-author surname
    year: Optional[int] = None
    title: Optional[str] = None

    # --- layout / extraction -----------------------------------------------
    pages: Optional[str] = None                 # "1-5,8" (1-based)
    dpi: int = 200                              # figure rendering resolution
    keep_headers: bool = False                  # keep running page headers/footers
    keep_picture_text: bool = False             # keep text extracted inside figures
    ocr_pages: bool = False                     # Tesseract OCR for scanned pages (needs tesseract)
    lighten: bool = True                        # merge clusters of tiny images before layout analysis

    # --- equations ---------------------------------------------------------
    math_engine: str = "p2t"                    # "p2t" | "rapid" | "claude" | "none"
    math_zooms: tuple | None = None             # render scales tried in order; None = the engine's own order (p2t 4,3,2 / rapid 2,3,4)
    math_max_tokens: int = 320                  # decoder length cap (rapid engine)
    math_mode: str = "both"                     # "both" (image + LaTeX below) | "latex" | "image"
    inline_image_math: bool = True              # OCR small images embedded in text lines
    inline_text_math: bool = True               # text-layer inline math (ρ_f, u_i) -> $...$
    vector_math: bool = True                    # equations/symbols drawn as vector paths (manuals) -> OCR
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "low"
    cache: bool = True

    verbose: bool = False
