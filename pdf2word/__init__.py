"""pdf2word - academic PDF -> Obsidian Markdown (LaTeX equations via OCR, figures as assets)."""
__version__ = "1.3.0"          # single source of truth (pyproject reads it); shown as v1.0 in the GUI


def short_version() -> str:
    """'1.0.0' -> 'v1.0'."""
    return "v" + ".".join(__version__.split(".")[:2])

from .config import Options                      # noqa: E402
from .converter import ConversionResult, convert  # noqa: E402

__all__ = ["Options", "ConversionResult", "convert", "__version__"]
