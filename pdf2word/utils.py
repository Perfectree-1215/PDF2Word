from __future__ import annotations

import logging
import os
import re
import sys
import unicodedata
from pathlib import Path

log = logging.getLogger("pdf2word")

_INVALID_FN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_STOP_WORDS = {
    "a", "an", "the", "of", "on", "in", "for", "and", "to", "by", "with", "at",
    "from", "via", "using", "based", "into", "its", "their", "toward", "towards",
}


def setup_console() -> None:
    """Make stdout/stderr UTF-8 tolerant (Windows consoles default to a legacy code page)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    log.setLevel(level)                       # only our own logger goes to DEBUG with -v
    for noisy in ("urllib3", "httpx", "httpcore", "anthropic", "PIL", "onnxruntime"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def fold_ascii(text: str) -> str:
    """Strip combining diacritics (Müller -> Muller); non-Latin scripts are kept as-is."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def safe_name(text: str, maxlen: int = 80, sep: str = "-") -> str:
    """A string usable as a file/folder name on Windows, macOS and Linux (underscores kept)."""
    text = fold_ascii(text or "")
    text = _INVALID_FN.sub(" ", text)
    text = re.sub(r"\s+", sep, text.strip())
    text = re.sub(rf"{re.escape(sep)}{{2,}}", sep, text)
    text = text.strip(sep + ". ")
    return text[:maxlen].rstrip(sep + ". ") or "untitled"


def slugify_title(title: str, max_words: int = 8, maxlen: int = 70) -> str:
    words = re.findall(
        r"[A-Za-z0-9À-ɏ가-힣぀-ヿ一-鿿]+", fold_ascii(title or "")
    )
    kept = [w for w in words if w.lower() not in _STOP_WORDS][:max_words]
    out: list = []
    for w in kept:                        # cut at a word boundary, never mid-word
        if out and len("-".join(out + [w])) > maxlen:
            break
        out.append(w)
    return safe_name("-".join(out or kept[:1]), maxlen=maxlen + 20) if kept else "untitled"


def cache_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    path = Path(base) / "pdf2word"
    path.mkdir(parents=True, exist_ok=True)
    legacy = Path(base) / "pdf2obsidian"           # the tool's former name: reuse its caches once
    if legacy.is_dir():
        import shutil
        for f in legacy.glob("*.json"):
            target = path / f.name
            if not target.exists():
                try:
                    shutil.copy2(f, target)
                except OSError:
                    pass
    return path


def parse_page_range(spec: str | None, page_count: int) -> list[int] | None:
    """'1-3,7' (1-based, inclusive) -> [0,1,2,6]. None/'' -> None (all pages)."""
    if not spec:
        return None
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a) if a.strip() else 1
            end = int(b) if b.strip() else page_count
        else:
            start = end = int(part)
        for p in range(start, end + 1):
            if 1 <= p <= page_count and (p - 1) not in pages:
                pages.append(p - 1)
    return pages or None


def strip_emphasis(text: str) -> str:
    """Remove Markdown bold/italic markers and inline HTML tags (<u>, <mark>, <sup> ...)
    - used for headings and captions."""
    text = re.sub(r"</?(?:u|mark|i|b|em|strong|s|del|sup|sub)>", "", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"(?<![A-Za-z0-9])_(.+?)_(?![A-Za-z0-9])", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"\1", text)
    return text.strip()
