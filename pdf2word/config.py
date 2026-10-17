from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Options:
    """All knobs of a conversion. Defaults are tuned for journal/conference papers."""

    # --- output ------------------------------------------------------------
    format: str = "docx"                        # "docx" | "md" | "both"
    docx_math: str = "native"                   # "native" (Word equations via Office XSL) | "text"
    out_dir: Optional[Path] = None              # default: the folder of the PDF
    asset_template: str = "_asset-{author}-{year}"
    name_template: str = "{author}-{year}-{title}"
    overwrite: bool = True
    image_links: str = "wiki"                   # "wiki" -> ![[...]], "markdown" -> ![](...)
    block_ids: bool = True                      # add ^eq-3 / ^fig-2 block anchors
    citations: str = "keep"                     # "keep" | "footnotes"
    abstract_callout: bool = True

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
    math_engine: str = "rapid"                  # "rapid" | "claude" | "none"
    math_zooms: tuple = (2.0, 3.0, 4.0)         # render scales tried in order
    math_max_tokens: int = 320                  # decoder length cap (rapid engine)
    math_mode: str = "both"                     # "both" (image + LaTeX below) | "latex" | "image"
    inline_image_math: bool = True              # OCR small images embedded in text lines
    inline_text_math: bool = True               # text-layer inline math (ρ_f, u_i) -> $...$
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "low"
    cache: bool = True

    verbose: bool = False
    extra: dict = field(default_factory=dict)
