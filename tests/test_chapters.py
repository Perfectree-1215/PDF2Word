"""Chapter splitting edge cases (bookmarks -> parts -> sub-documents): PDFs without bookmarks,
cuts through a text line, entries further up the same page, rotated pages, bottom-of-page
destinations, ligatures in headings, non-Latin file names, empty chapter selections, printed
page labels in upper case and bookmarks without a destination. Synthetic PDFs only.

Run:  python -m pytest tests/test_chapters.py -q
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pdf2word.outline import (PageNumbers, _norm, _outline_entries, _text_lines, flatten,  # noqa: E402
                              parse_pages, part_document, read_outline, select_parts, title_for_name)
from pdf2word.utils import fold_ascii, safe_name, slugify_title  # noqa: E402

W, H = 595, 842


def _doc(pages, size=(W, H), rotate=0) -> pymupdf.Document:
    """pages: [[(x, baseline y, text, fontsize), ...], ...] -> an in-memory PDF."""
    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page(width=size[0], height=size[1])
        if rotate:
            page.set_rotation(rotate)
        for x, y, text, fs in lines:
            page.insert_text((x, y), text, fontsize=fs)
    return doc


def _reopen(doc) -> pymupdf.Document:
    """Save and read back, so the outline is parsed from the file as a viewer would."""
    return pymupdf.open("pdf", doc.tobytes())


def _line(doc, pno: int, text: str):
    return next(ln for ln in _text_lines(doc[pno]) if ln[2] == text)


def _owners(doc, parts, lines) -> dict:
    """line text -> indexes of the parts whose cut sub-document still shows the whole line."""
    texts = []
    for part in parts:
        sub = part_document(doc, part, cut="exact")
        texts.append("\n".join(p.get_text() for p in sub))
        sub.close()
    return {ln: [i for i, t in enumerate(texts) if ln in t] for ln in lines}


def _all_lines(pages) -> list:
    return [text for lines in pages for _, _, text, _ in lines]


def _assert_each_line_once(doc, parts, lines):
    owners = _owners(doc, parts, lines)
    bad = {ln: o for ln, o in owners.items() if len(o) != 1}
    assert not bad, f"lines not in exactly one part: {bad}"


# ----------------------------------------------------------------------------- #58 / #69

def test_pdf_without_bookmarks_does_not_crash(tmp_path):
    # MuPDF hands back a NULL outline root for a PDF without /Outlines; touching it used to kill
    # the interpreter (0xC0000005), so the check runs in its own process
    pdf = tmp_path / "plain.pdf"
    doc = _doc([[(50, 100, "Introduction", 16), (50, 140, "Body text line one.", 11)],
                [(50, 100, "Second page text.", 11)]])
    doc.save(pdf)
    code = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r})
        from pathlib import Path
        import pymupdf
        from pdf2word.cli import list_chapters
        from pdf2word.config import Options
        from pdf2word.converter import Converter
        from pdf2word.outline import _outline_entries, read_outline
        pdf = {str(pdf)!r}
        doc = pymupdf.open(pdf)
        assert _outline_entries(doc) == [], "entries"
        assert read_outline(doc) == [], "tree"
        mem = pymupdf.open()
        mem.new_page()
        assert read_outline(mem) == [], "in-memory"
        try:
            Converter(Options(chapters="all")).plan_parts(pdf)
        except RuntimeError as exc:
            assert "no bookmarks" in str(exc), exc
        else:
            raise AssertionError("--chapters on a PDF without bookmarks must explain itself")
        groups = Converter(Options(split_pages=1)).plan_parts(pdf)
        assert [(g.page_from, g.page_to) for g in groups] == [(0, 0), (1, 1)], groups
        assert list_chapters([Path(pdf)], 2) == 0
        print("NO-BOOKMARKS-OK")
    """)
    proc = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)
    assert proc.returncode == 0, f"exit {proc.returncode & 0xFFFFFFFF:#x}\n{proc.stdout}\n{proc.stderr}"
    assert "NO-BOOKMARKS-OK" in proc.stdout and "no bookmarks" in proc.stdout


# ----------------------------------------------------------------------------- #59

def _results_book(gap: float, leading: float = 13):
    """Chapter 1 runs onto page 2; '2 Results and Discussion' starts `gap` pt (baseline to
    baseline) below the last chapter-1 line. 11 pt body at `leading` pt."""
    p1 = [(50, 80, "1 Introduction", 16)] + \
         [(50, 100 + 13 * i, f"Chapter one body line {i:02d}", 11) for i in range(1, 6)]
    p2 = [(50, 100 + leading * i, f"Body text of chapter one continues {i:02d}", 11) for i in range(1, 15)]
    last = 100 + leading * 14
    p2 += [(50, last + gap, "2 Results and Discussion", 16)] + \
          [(50, last + gap + leading * i, f"Chapter two body line {i:02d}", 11) for i in range(1, 6)]
    p3 = [(50, 100, "Chapter two final page", 11)]
    pages = [p1, p2, p3]
    return _doc(pages), pages


@pytest.mark.parametrize("leading,depth", [(13, 6), (13, 10), (11, 6), (11, 3)])
def test_cut_through_line_keeps_line_once(leading, depth):
    # the bookmark title differs from the printed heading, so the cut falls back to the
    # bookmark position - which lies inside the last line of chapter 1 (also at solid leading)
    doc, pages = _results_book(30, leading)
    inside = _line(doc, 1, "Body text of chapter one continues 14")[0] + depth
    doc.set_toc([[1, "1. Introduction", 1, 70], [1, "Chapter 2: Results", 2, inside]])
    doc = _reopen(doc)
    c1, c2 = read_outline(doc)
    assert (c1.page_to, c2.page_from) == (1, 1)                      # page 2 is shared
    _assert_each_line_once(doc, [c1, c2], _all_lines(pages))


@pytest.mark.parametrize("gap", [15, 17, 18, 20])
def test_cut_tight_heading_spacing(gap):
    # heading found, but set tight under the previous line: "heading top - 2" cuts that line
    doc, pages = _results_book(gap)
    head = _line(doc, 1, "2 Results and Discussion")
    doc.set_toc([[1, "1 Introduction", 1, 70], [1, "2 Results and Discussion", 2, head[0] - 5]])
    doc = _reopen(doc)
    c1, c2 = read_outline(doc)
    _assert_each_line_once(doc, [c1, c2], _all_lines(pages))


# ----------------------------------------------------------------------------- #60

def _same_page_book(two_col: bool):
    p1 = [(50, 80, "Preface", 16), (50, 110, "Preface text.", 11)]
    if two_col:      # left column: section A low on the page; right column: section B higher up
        p2 = [(50, 200, "Left column body before A", 11), (50, 400, "Alpha Section Heading", 14)] + \
             [(50, 400 + 14 * i, f"Alpha body line {i}", 11) for i in range(1, 8)] + \
             [(320, 300, "Beta Section Heading", 14)] + \
             [(320, 300 + 14 * i, f"Beta body line {i}", 11) for i in range(1, 8)]
    else:
        p2 = [(50, 200, "Body before", 11), (50, 400, "Part Two Title", 16), (50, 430, "Chapter Five Heading", 14)] + \
             [(50, 430 + 14 * i, f"Chapter five body line {i}", 11) for i in range(1, 8)]
    p3 = [(50, 100, "Next page text", 11)]
    pages = [p1, p2, p3]
    return _doc(pages), pages


def test_same_page_next_entry_above_keeps_text():
    # two columns: in document order A (left, low) comes before B (right, higher up)
    doc, pages = _same_page_book(two_col=True)
    doc.set_toc([[1, "Preface", 1, 60], [1, "Alpha Section Heading", 2, 385], [1, "Beta Section Heading", 2, 285]])
    doc = _reopen(doc)
    parts = flatten(read_outline(doc))
    owners = _owners(doc, parts, _all_lines(pages))
    assert all(owners.values()), {ln: o for ln, o in owners.items() if not o}      # nothing lost
    alpha = [ln for ln in owners if ln.startswith("Alpha")]
    assert all(1 in owners[ln] for ln in alpha), owners                           # A keeps its text


def test_same_destination_titles_not_found_keeps_text():
    doc, pages = _same_page_book(two_col=False)
    doc.set_toc([[1, "Preface", 1, 60], [1, "PART II", 2, 385], [1, "Chapter 5. Methods", 2, 385]])
    doc = _reopen(doc)
    parts = flatten(read_outline(doc))
    owners = _owners(doc, parts, _all_lines(pages))
    assert all(owners.values()), {ln: o for ln, o in owners.items() if not o}
    assert 1 in owners["Part Two Title"]                                          # its file is not blank


def test_same_destination_titles_found_still_cut():
    # same bookmark position, both headings printed: the end cut at the second heading stays
    doc, pages = _same_page_book(two_col=False)
    doc.set_toc([[1, "Preface", 1, 60], [1, "Part Two Title", 2, 385], [1, "Chapter Five Heading", 2, 385]])
    doc = _reopen(doc)
    _assert_each_line_once(doc, flatten(read_outline(doc)), _all_lines(pages))


# ----------------------------------------------------------------------------- #61

def _set_xyz(doc, item: int, pno: int, y: float) -> None:
    """Point bookmark `item` at the displayed (rotated) top-left y of page `pno` with a raw
    /XYZ destination (set_toc does not convert y on rotated pages)."""
    page = doc[pno]
    p = pymupdf.Point(40, y) * page.derotation_matrix                 # -> unrotated top-left
    doc.xref_set_key(doc.get_outline_xrefs()[item], "Dest",
                     f"[{page.xref} 0 R /XYZ {p.x:.2f} {page.mediabox.height - p.y:.2f} 0]")


@pytest.mark.parametrize("size", [(500, 700), (700, 500)])
def test_rotated_page_threshold_consistent(size):
    # chapter 2 starts at y=72 of a turned page: 'top of the page' (12 %) is 60 pt of the
    # displayed 500 pt height but 84 pt of the 700 pt cropbox - both tests must use one height
    pages = [[(40, 60, "Chapter One", 16)] + [(40, 60 + 14 * i, f"Chapter one body line {i}", 11) for i in range(1, 6)],
             [(40, 30, "Tail of chapter one on page two", 11), (40, 90, "Chapter Two", 16)] +
             [(40, 90 + 14 * i, f"Chapter two body line {i}", 11) for i in range(1, 6)]]
    doc = _doc(pages, size=size, rotate=90)
    doc.set_toc([[1, "Chapter One", 1, 40], [1, "Chapter Two", 2, 72]])
    doc = _reopen(doc)
    _set_xyz(doc, 0, 0, 40)
    _set_xyz(doc, 1, 1, 72)
    doc = _reopen(doc)
    c1, c2 = read_outline(doc)
    assert abs(c2.y_hint - 72) < 0.5 and c1.y_hint is not None and abs(c1.y_hint - 40) < 0.5
    _assert_each_line_once(doc, [c1, c2], _all_lines(pages))


# ----------------------------------------------------------------------------- #62

@pytest.mark.parametrize("dest", ["/XYZ 0 0 0", "/XYZ 0 -20 0"])
def test_bottom_destination_is_unknown_y(dest):
    pages = [[(50, 80, "Chapter One", 16)] + [(50, 80 + 14 * i, f"Chapter one body {i}", 11) for i in range(1, 6)],
             [(50, 80, "Chapter Two", 16)] + [(50, 80 + 14 * i, f"Chapter two body {i}", 11) for i in range(1, 6)],
             [(50, 80, "Chapter two continues", 11)]]
    doc = _doc(pages)
    doc.set_toc([[1, "Chapter One", 1, 60], [1, "Chapter Two", 2, 60]])
    doc = _reopen(doc)
    xref = doc.get_outline_xrefs()[1]
    doc.xref_set_key(xref, "Dest", f"[{doc[1].xref} 0 R {dest}]")          # PDF y 0 = page bottom
    doc = _reopen(doc)
    c1, c2 = read_outline(doc)
    assert c2.y_hint is None and (c1.page_to, c2.page_from) == (0, 1)
    owners = _owners(doc, [c1, c2], _all_lines(pages))
    assert all(o == [0] for ln, o in owners.items() if "one" in ln.lower()), owners
    assert all(o == [1] for ln, o in owners.items() if "two" in ln.lower()), owners


# ----------------------------------------------------------------------------- #63

def test_norm_folds_ligatures():
    assert _norm("2 Classiﬁcation of ﬂames") == _norm("2 Classification of flames")
    assert _norm("서론") == "서론" and _norm("1.2 서론 개요") == "12서론개요"
    assert _norm("Ｃｈａｐｔｅｒ １") == "chapter1"                      # full-width forms


# ----------------------------------------------------------------------------- #64

def test_names_keep_hangul_and_kana_composed():
    for name in (title_for_name("1.2 서론"), title_for_name(unicodedata.normalize("NFD", "1.2 서론"))):
        assert name == "1.2-서론" and unicodedata.is_normalized("NFC", name)
    assert safe_name("がぎパ") == "がぎパ"                                # dakuten / handakuten kept
    assert slugify_title("한국어 논문 제목") == "한국어-논문-제목"
    assert slugify_title("한국어 논문 제목 Deep Learning") == "한국어-논문-제목-Deep-Learning"
    # Latin diacritics are still folded, ligatures still expanded
    assert safe_name("Müller") == "Muller"
    assert safe_name("Müller Café Ångström") == "Muller-Cafe-Angstrom"
    assert slugify_title("Étude des Écoulements Rapides") == "Etude-des-Ecoulements-Rapides"
    assert fold_ascii("ﬁnite ﬂow") == "finite flow" and fold_ascii("naïve résumé") == "naive resume"


# ----------------------------------------------------------------------------- #65 / #66

def _three_chapters():
    pages = [[(50, 80, f"Chapter {i}", 16), (50, 110, f"Chapter {i} text", 11)] for i in range(1, 4)]
    doc = _doc(pages)
    doc.set_toc([[1, "Chapter 1", 1, 60], [2, "Section 1.1", 1, 100], [1, "Chapter 2", 2, 60], [1, "Chapter 3", 3, 60]])
    return _reopen(doc)


def test_empty_chapter_selection_raises():
    tree = read_outline(_three_chapters())
    for bad in ("3-1", "all:5", "all:9", "1.1-1.0"):
        with pytest.raises(ValueError):
            select_parts(tree, bad)
    assert [p.id for p in select_parts(tree, "1-3")] == ["1", "2", "3"]
    assert [p.id for p in select_parts(tree, "all:2")] == ["1.1"]
    assert select_parts(tree, "") == [] and select_parts(tree, " ") == []    # nothing asked: whole PDF


def test_empty_chapter_selection_is_not_a_whole_conversion(tmp_path, monkeypatch):
    from pdf2word import cli, converter
    from pdf2word.utils import log
    pdf = tmp_path / "book.pdf"
    _three_chapters().save(pdf)
    calls = []
    monkeypatch.setattr(converter.Converter, "convert",
                        lambda self, p: calls.append(("whole", p)) or SimpleNamespace(skipped=True))
    monkeypatch.setattr(converter.Converter, "convert_parts",
                        lambda self, p, parts, stop=None: calls.append(("parts", [x.id for x in parts])) or [])
    level = log.level
    try:
        assert cli.main([str(pdf), "--chapters", "3-1", "-o", str(tmp_path), "-f", "md"]) == 1
        assert cli.main([str(pdf), "--chapters", "2", "-o", str(tmp_path), "-f", "md"]) == 0
    finally:
        log.setLevel(level)
    assert calls == [("parts", ["2"])]


def test_parse_pages_selecting_nothing_raises():
    doc = _doc([[(50, 100, f"page {i + 1}", 11)] for i in range(10)])
    for spec in ("50-60", "5-3", "0", "11"):
        with pytest.raises(ValueError):
            parse_pages(spec, doc)
    assert parse_pages("3-4", doc) == [2, 3]


# ----------------------------------------------------------------------------- #67

def test_index_of_label_case():
    doc = _doc([[(50, 100, f"page {i + 1}", 11)] for i in range(12)])
    doc.set_page_labels([{"startpage": 0, "prefix": "", "style": "r", "firstpagenum": 1},    # i ii iii
                         {"startpage": 3, "prefix": "", "style": "R", "firstpagenum": 1},    # I II III
                         {"startpage": 6, "prefix": "S", "style": "D", "firstpagenum": 1},   # S1 S2 S3
                         {"startpage": 9, "prefix": "", "style": "A", "firstpagenum": 1}])   # A B C
    nums = PageNumbers(doc)
    assert [nums.label(i) for i in range(12)] == ["i", "ii", "iii", "I", "II", "III", "S1", "S2", "S3", "A", "B", "C"]
    assert nums.index_of("II") == 4 and nums.index_of("ii") == 1                  # exact match first
    assert nums.index_of("S2") == 7 and nums.index_of("s2") == 7                  # case-folded fallback
    assert nums.index_of("B") == 10 and nums.index_of("b") == 10
    assert nums.index_of("Ii") == 1 and nums.index_of("Z") is None
    assert parse_pages("pS2-pS3", doc, nums) == [7, 8] and parse_pages("pII", doc, nums) == [4]

    upper = _doc([[(50, 100, f"page {i + 1}", 11)] for i in range(4)])
    upper.set_page_labels([{"startpage": 0, "prefix": "", "style": "R", "firstpagenum": 1}])
    assert parse_pages("pii-piii", upper) == [1, 2] and parse_pages("pIV", upper) == [3]


# ----------------------------------------------------------------------------- #68

def _no_dest_book(extra_toc=(), null_items=(1,)):
    pages = [[(50, 80, f"Chapter {i}", 16), (50, 110, f"Chapter {i} text", 11)] for i in range(1, 5)]
    doc = _doc(pages)
    doc.set_toc([[1, "Chapter 1", 1, 60], [1, "Part II", 2, 60], [2, "Chapter 2", 2, 60],
                 [2, "Chapter 3", 3, 60], [1, "Chapter 4", 4, 60], *extra_toc])
    doc = _reopen(doc)
    xrefs = doc.get_outline_xrefs()
    for i in null_items:
        doc.xref_set_key(xrefs[i], "Dest", "null")
        doc.xref_set_key(xrefs[i], "A", "null")
    return _reopen(doc), pages


def test_destinationless_bookmark_keeps_tree_shape():
    doc, pages = _no_dest_book(extra_toc=[[1, "Index (no target)", 4, 300]], null_items=(1, 5))
    assert [t[2] for t in doc.get_toc(simple=True)][1] == -1                      # Part II has no target
    tree = read_outline(doc)
    nodes = flatten(tree)
    assert [(n.id, n.title) for n in nodes] == [("1", "Chapter 1"), ("2", "Part II"), ("2.1", "Chapter 2"),
                                                ("2.2", "Chapter 3"), ("3", "Chapter 4")]  # trailing leaf dropped
    by_id = {n.id: n for n in nodes}
    assert [p.pages_label for p in select_parts(tree, "1")] == ["1"]               # no longer swallows part II
    assert by_id["2"].pages_label == "2-3" and by_id["2"].page_from == by_id["2.1"].page_from
    assert by_id["2.1"].pages_label == "2" and by_id["2.2"].pages_label == "3" and by_id["3"].pages_label == "4"
    _assert_each_line_once(doc, [by_id[i] for i in ("1", "2.1", "2.2", "3")], _all_lines(pages))
    entries = _outline_entries(doc)
    assert entries[1][1:] == ("Part II", 1, entries[2][3])                         # inherits its first child


def test_destinationless_leaf_between_siblings_loses_nothing():
    doc, pages = _no_dest_book(null_items=(2,))                                    # 'Chapter 2' has no target
    nodes = flatten(read_outline(doc))
    assert [n.id for n in nodes] == ["1", "2", "2.1", "2.2", "3"]
    owners = _owners(doc, nodes, _all_lines(pages))
    assert all(owners.values()), {ln: o for ln, o in owners.items() if not o}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
