"""pdf2word.utils: asset-folder names that survive an Obsidian wiki link, and the cache folder.
No PDF, no network, no model.

Run:  python -m pytest tests/test_utils.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf2word.docx_out import _IMG_WIKI  # noqa: E402
from pdf2word.obsidian import image_link  # noqa: E402
from pdf2word.utils import cache_dir, safe_name, wiki_safe_name  # noqa: E402


# ----------------------------------------------------------------------------- #89 / #113

def test_wiki_safe_name_drops_link_breaking_chars():
    name = wiki_safe_name("_asset-Manual [2nd ed] #3 ^x")
    assert not set("[]#^|") & set(name)
    assert name == "_asset-Manual-2nd-ed-3-x"                    # no '--' left behind
    assert wiki_safe_name("[draft]") == "draft" and wiki_safe_name("[]#^") == "untitled"
    assert _IMG_WIKI.match(image_link(f"{wiki_safe_name('_asset-Report [final]')}/fig1.png"))
    assert not _IMG_WIKI.match(image_link(f"{safe_name('_asset-Report [final]')}/fig1.png"))


def test_wiki_safe_name_leaves_plain_names_alone():
    for name in ("_asset-Kim-2024", "_asset-김-2024", "_asset-book_v2-03", "_asset-C-Guide"):
        assert wiki_safe_name(name) == safe_name(name) == name
    assert len(wiki_safe_name("x" * 200, 120)) == 120
    assert safe_name("Report [final] #2") == "Report-[final]-#2"   # file names are not changed


# ----------------------------------------------------------------------------- #119

def test_cache_dir_ignores_the_legacy_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    legacy = tmp_path / "pdf2obsidian"
    legacy.mkdir()
    (legacy / "mathocr-cache.json").write_text('{"k": "STALE"}', encoding="utf-8")
    (legacy / "gui.json").write_text("{}", encoding="utf-8")
    path = cache_dir()
    assert path == tmp_path / "pdf2word" and path.is_dir()
    assert list(path.iterdir()) == []                             # nothing copied over
    (path / "gui.json").write_text("{}", encoding="utf-8")
    (path / "gui.json").unlink()                                  # the user deletes a cache ...
    cache_dir()
    assert list(path.iterdir()) == []                             # ... and it stays deleted
