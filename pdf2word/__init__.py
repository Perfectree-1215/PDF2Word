"""pdf2word - PDF papers, books and manuals -> Word documents or Obsidian notes: layout-aware text, equations
as image + OCR (Word math / LaTeX), figures, front matter; big PDFs split by bookmark chapters."""
__version__ = "2.0.0"          # single source of truth (pyproject reads it); the GUI shows vMAJOR.MINOR


def short_version() -> str:
    """'1.0.0' -> 'v1.0'."""
    return "v" + ".".join(__version__.split(".")[:2])

from .config import Options                      # noqa: E402
from .converter import ConversionResult, convert  # noqa: E402

__all__ = ["Options", "ConversionResult", "convert", "__version__"]
