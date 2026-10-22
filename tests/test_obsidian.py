"""Obsidian Markdown post-processing (pdf2word/obsidian.py) on synthetic Markdown only.

Every case also checks that no character of the source disappears (whitespace and Markdown
markup aside): a rewrite that cannot be placed must leave the text as it was.

Run:  python -m pytest tests/test_obsidian.py -q
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pdf2word import obsidian as ob  # noqa: E402
from pdf2word.config import Options  # noqa: E402

# heading markers and closing sequences, list / quote markers, emphasis, table pipes, math and
# footnote brackets, <br>: what a Markdown pass may add, drop or move without losing text
_MARKUP_RE = re.compile(r"(?m)^[ \t]*#{1,6}(?=[ \t]|$)|[ \t]#+[ \t]*$|<br\s*/?>|[\s*_>|$^\[\]!+-]")
_CITE_GROUP_RE = re.compile(r"\[\d{1,3}(?:\s*[,;–—-]\s*\d{1,3})*\]")     # '[2, 3]' -> '[^2][^3]'


def _chars(text: str) -> Counter:
    text = _CITE_GROUP_RE.sub(lambda m: re.sub(r"[,;–—]", "", m.group(0)), text)
    text = re.sub(r"(?m)^(\s*(?:[-*+]\s+)?\d{1,3})\.(?=\s)", r"\1", text)      # '1. Ref' -> '[^1]: Ref'
    return Counter(_MARKUP_RE.sub("", text))


def assert_text_kept(src: str, out: str) -> None:
    """Every character of src (whitespace and markup aside) is still somewhere in out."""
    lost = _chars(src) - _chars(out)
    assert not lost, f"characters lost: {dict(lost)}"


def test_markup_helper_sees_real_loss():
    assert_text_kept("## Using C#\n", "## Using C#\n\n")
    assert_text_kept("## Closing ##\n", "## Closing\n")
    for src, out in (("## Using C#\n", "## Using C\n"), ("A [1, 5-40]", "A [^1]"), ("Abstraction is", "ion is")):
        try:
            assert_text_kept(src, out)
        except AssertionError:
            continue
        raise AssertionError(f"loss not detected: {src!r} -> {out!r}")


# ----------------------------------------------------------------------------- #84 references section

def test_citations_keep_heading_preamble_and_trailing_blocks():
    md = ("Body cites [1] and [2].\n\n"
          "# Bibliography\n\n"
          "Entries marked with * are recommended reading.\n\n"
          "![[_asset-X/fig9.png]]\n\n"
          "[1] First ref.\n[2] Second ref.\n[3] Third ref.\n\n"
          "Table 9. Funding sources, placed here by reading order.\n\n"
          "## Appendix A\n\nAppendix text.\n")
    out = ob.citations_to_footnotes(md)
    assert "Body cites [^1] and [^2]." in out
    assert "\n# Bibliography\n" in out and "## References" not in out
    assert "Entries marked with * are recommended reading." in out
    assert "![[_asset-X/fig9.png]]" in out
    assert "[^3]: Third ref.\n" in out                       # the caption is not glued to the entry
    assert "\nTable 9. Funding sources, placed here by reading order.\n" in out
    assert (out.index("Entries marked") < out.index("[^1]: First ref.") < out.index("Table 9.")
            < out.index("## Appendix A") < out.index("Appendix text."))
    assert_text_kept(md, out)
    # level and wording of the heading are the original ones
    out2 = ob.citations_to_footnotes(md.replace("# Bibliography", "### References"))
    assert "\n### References\n" in out2 and "\n## References\n" not in out2
    assert_text_kept(md, out2.replace("### References", "# Bibliography"))


def test_citations_duplicate_numbers_left_alone():
    # a numbered list after the references (numbering restarts): one entry would overwrite another
    md = "Cites [1] and [2].\n\n## References\n\n1. Alpha.\n2. Beta.\n3. Gamma.\n1. Delta item.\n"
    out = ob.citations_to_footnotes(md)
    assert out == md
    assert_text_kept(md, out)


# ----------------------------------------------------------------------------- #82 '- [n]' entries

def test_citations_dash_bracket_entries():
    refs = "\n".join(f"- [{n}] Author{n}, A. Title {n}. J. Chem. {2000 + n}." for n in range(1, 6))
    md = "Body cites [1] and [2,3] and [4-5].\n\n## References\n\n" + refs + "\n"
    out = ob.citations_to_footnotes(md)
    assert "Body cites [^1] and [^2][^3] and [^4][^5]." in out
    assert "[^1]: Author1, A. Title 1. J. Chem. 2001.\n" in out
    assert "[^5]: Author5, A. Title 5. J. Chem. 2005." in out
    assert_text_kept(md, out)


def test_split_merged_bracket_references():
    # pymupdf4llm joins the entries of one layout box into one list item
    merged = ("## References\n\n"
              "- [1] Author1 A. J Chem 2001;1:1-10. [2] Author2 A. J Chem 2002;2:1-10. [3] Author3 A. J Chem 2003.\n"
              "- [4] Author4 A. J Chem 2004.\n")
    split = ob._split_merged_references(merged)
    assert "\n- [1] Author1 A. J Chem 2001;1:1-10.\n" in split
    assert "\n- [2] Author2 A. J Chem 2002;2:1-10.\n" in split
    assert "\n- [3] Author3 A. J Chem 2003.\n" in split
    assert_text_kept(merged, split)
    body = "See [2] and [3].\n\n"
    out = ob.postprocess(body + merged, Options(citations="footnotes"), paper=True)
    assert "See [^2] and [^3]." in out
    assert "[^2]: Author2 A. J Chem 2002;2:1-10.\n" in out and "[^4]: Author4 A. J Chem 2004." in out
    assert_text_kept(body + merged, out)
    # a number that is not the next one stays inside its entry; the numbered form still splits
    keep = "## References\n\n- [1] Smith A, cited in [7] Jones. J Chem 2001.\n"
    assert ob._split_merged_references(keep) == keep
    num = ob._split_merged_references("## References\n\n2. Galk, J. Köln, 1995. 3. Bauer, U. Aachen, 2002.\n")
    assert "\n2. Galk, J. Köln, 1995.\n\n3. Bauer, U. Aachen, 2002.\n" in num


# ----------------------------------------------------------------------------- #83 partial ranges

def test_citations_partial_range_kept():
    entries = "\n".join(f"{n}. Ref {n}." for n in range(1, 41))
    md = "A [1, 5-40] B [3, 2-3-4] C [1, 9-5] D [1, 5-7].\n\n## References\n\n" + entries + "\n"
    out = ob.citations_to_footnotes(md)
    assert "A [1, 5-40] B [3, 2-3-4] C [1, 9-5] D [^1][^5][^6][^7]." in out
    assert ob._expand_cites("1, 5-40") == [] and ob._expand_cites("3, 2-3-4") == []
    assert ob._expand_cites("1, 5-7") == [1, 5, 6, 7] and ob._expand_cites("4–6") == [4, 5, 6]
    assert_text_kept(md, out)


# ----------------------------------------------------------------------------- #80 / #88 blocks

def test_block_mask_only_closed_blocks():
    assert ob._block_mask(["x", "$$", "|a", "$$", "y"]) == [False, True, True, True, False]
    assert ob._block_mask(["```py", "# c", "$$", "```", "$$"]) == [True, True, True, True, False]
    assert ob._block_mask(["$$", "a", "```", "b", "```"]) == [False, False, True, True, True]


def test_fix_tables_skips_math_blocks():
    ket = ("Intro text.\n\n$$\n|\\psi\\rangle=\\alpha|0\\rangle+\\beta|1\\rangle \\tag{3}\n$$\n^eq-3\n"
           "Paragraph A.\n\n$$\nE=mc^{2} \\tag{4}\n$$\n^eq-4\n")
    absx = "Text.\n\n$$\n|x|\n$$\n\nMore.\n"
    gathered = ("$$\n\\begin{gathered}\na=b \\\\\n|A|=\\det A \\\\\nc=d\n\\end{gathered} \\tag{5}\n$$\n^eq-5\n"
                "\nNext para.\n")
    row_then_math = "|a|b\n$$\nx=1\n$$\n"
    row_then_open = "|a|b\n$$\nx=1\n"                      # unclosed: not a block, still not swallowed
    for md in (ket, absx, gathered, row_then_math, row_then_open):
        out = ob._fix_tables(md)
        assert out == md, out
        assert_text_kept(md, out)
    out = ob.postprocess(ket, Options(), paper=False)
    assert "\n$$\n|\\psi\\rangle" in out and "\\tag{3}\n$$\n^eq-3\n\nParagraph A.\n" in out
    assert sum(1 for ln in out.split("\n") if ln.strip() == "$$") == 4
    assert_text_kept(ket, out)
    # tables themselves are still repaired
    assert ob._fix_tables("|a|b|\n|---|---|\n|i\nStiffness k|0.86|\n") == "|a|b|\n|---|---|\n|i Stiffness k|0.86|\n"
    assert ob._fix_tables("Text\n|a|b|\n") == "Text\n\n|a|b|\n"


def test_headings_skip_code_fences():
    code = ("```\n"
            "# install the _dev_ extras first\n"
            "pip install mytool[dev]\n"
            "# run with *fast* mode\n"
            "mytool --fast\n"
            "| grep result\n"
            "  > out.txt\n"
            "#\n"
            "```\n")
    md = "# My Tool Manual\n\nIntro.\n\n## Usage\n\n" + code + "\nAfter.\n\n# Second part\n"
    out = ob.ensure_title(ob.postprocess(md, Options(), paper=False), "My Tool Manual")
    assert code in out                                      # byte for byte
    assert "\n## Second part\n" in out                       # H1 demotion outside the fence still works
    assert_text_kept(md, out)
    # headings outside fences keep their blank lines
    assert ob._clean_headings("text\n## H\nmore\n") == "text\n\n## H\n\nmore\n"
    assert ob._clean_headings("text\n## **H**\n") == "text\n\n## H\n\n"


# ----------------------------------------------------------------------------- #85 / #86 abstract

def test_abstract_fallback_needs_a_label():
    tail = " a fundamental concept in software engineering that hides details behind interfaces and contracts."
    for word in ("Abstraction is", "Abstracts of talks are", "Abstracted features were",
                 "Abstract-level reasoning is", "Abstract art is"):
        md = f"# Title\n\n{word}{tail}\n\n## 1. Introduction\n"
        out = ob._abstract_callout(md)
        assert out == md, out
        assert_text_kept(md, out)
    for label in ("Abstract: ", "**Abstract** ", "**Abstract.** ", "_Abstract_: ", "Abstract\n", "Abstract — ",
                  "ABSTRACT - "):
        md = "# T\n\n" + label + "x" * 100 + "\n\n## 1\n"
        out = ob._abstract_callout(md)
        assert "> [!abstract] Abstract\n> " + "x" * 100 + "\n" in out, label
        # the label becomes the callout header: only its punctuation and letter case go
        assert_text_kept(re.sub(r"[:.—]", "", md).lower(), out.lower())


def test_abstract_letter_spaced_heading():
    abstract = ("We study the grinding of fine powders in a spiral jet mill and report a new scaling law "
                "for the cut size.")
    info = "Article history:\nReceived 1 May 2020\n\nKeywords:\nJet mill\nCFD"
    head = "# Title\n\n### **a r t i c l e   i n f o**\n\n"
    md1 = f"{head}{info}\n\n### **a b s t r a c t**\n\n{abstract}\n\n## 1. Introduction\n\nBody.\n"
    md2 = f"{head}### **a b s t r a c t**\n\n{info}\n\n{abstract}\n\n## 1. Introduction\n\nBody.\n"
    for md in (md1, md2):
        out = ob.postprocess(md, Options(), paper=True)
        callout = [ln for ln in out.split("\n") if ln.startswith(">")]
        assert callout == ["> [!abstract] Abstract", "> " + abstract], out
        for text in ("Article history:", "Received 1 May 2020", "Keywords:", "Jet mill", "## 1. Introduction"):
            assert text in out
        assert out.index("Article history:") < out.index("> [!abstract]") < out.index("## 1. Introduction")
        assert_text_kept(md, out)
    plain = "## Abstract\n\n" + abstract + "\n\n## 1. Introduction\n"
    out = ob._abstract_callout(plain)
    assert out.startswith("> [!abstract] Abstract\n> " + abstract + "\n")
    assert_text_kept(plain, out)
    # only info paragraphs under the heading: nothing to quote, nothing moves
    only_info = "## a b s t r a c t\n\nKeywords: mill\n\n## 1. Introduction\n"
    assert ob._abstract_callout(only_info) == only_info


# ----------------------------------------------------------------------------- #87 '#' in headings

def test_heading_keeps_trailing_hash():
    assert ob._clean_headings("## Using C#\n").strip() == "## Using C#"
    assert ob._clean_headings("### 3.2 Interop with F#\n").strip() == "### 3.2 Interop with F#"
    assert ob._clean_headings("## Closing seq ##\n").strip() == "## Closing seq"
    md = "## Using C#\n\nText.\n"
    out = ob.ensure_title(ob.postprocess(md, Options(), paper=False), "A Manual for Programmers")
    assert "\n## Using C#\n" in out
    assert_text_kept(md, out)


# ----------------------------------------------------------------------------- #81 ensure_title

def test_ensure_title_short_or_empty_key():
    title_a = "Математическое моделирование"                   # key is empty
    md_a = "Some intro.\n\n## 1. Introduction to the problem\n\nBody.\n\n## 2. Methods and materials used\n"
    out_a = ob.ensure_title(md_a, title_a)
    assert out_a == "# " + title_a + "\n\n" + md_a
    assert_text_kept(md_a, out_a)
    title_b = "CFD Review"                                       # key shorter than 12
    md_b = "# CFD Review\n\nAbstract text.\n\n## A CFD review of jet milling\n\nBody.\n\n# Appendix\n"
    out_b = ob.ensure_title(md_b, title_b)
    assert out_b.startswith("# CFD Review\n\nAbstract text.\n")
    assert "\n## A CFD review of jet milling\n" in out_b and "\n## Appendix" in out_b
    assert_text_kept(md_b, out_b)
    title_f = "Jet milling of fine powders"                      # heading only contains the title
    md_f = "## A review of studies on jet milling of fine powders in industry\n\nText.\n"
    out_f = ob.ensure_title(md_f, title_f)
    assert out_f == "# " + title_f + "\n\n" + md_f
    assert_text_kept(md_f, out_f)


def test_ensure_title_still_finds_the_title():
    title = "Numerical modeling of wet milling by an improved CFD-DEM-VOF model"
    md = "## Numerical modeling of wet milling by an improved CFD-DEM-VOF model\n\nAbstract.\n"
    assert ob.ensure_title(md, title) == "# " + title + "\n\nAbstract.\n"
    # title split over two lines, only the first part detected as a heading
    title_e = "Development of a Model for the Separation of Fine Powders in Jet Mills"
    md_e = "# Development of a Model\n\nfor the Separation of Fine Powders in Jet Mills\n\nText.\n"
    out_e = ob.ensure_title(md_e, title_e)
    assert out_e.startswith("# " + title_e + "\n\nfor the Separation") and out_e.count("Development") == 1
    assert_text_kept(md_e, out_e)
    # the title heading with a stray marker (within 80 %)
    md_g = "## Jet milling of fine powders 1\n\nText.\n"
    assert ob.ensure_title(md_g, "Jet milling of fine powders").startswith("# Jet milling of fine powders\n\nText.")


# ----------------------------------------------------------------------------- #90 <br> in tables

def test_table_br_cells_stay_in_row():
    for row in ("|a<br>b|c|", "|Value<br>|c|", "|<br>Value|c|", "|Top<br><br>Bottom|c|", "|x<br/>y|z|"):
        md = f"Text.\n\n|h1|h2|\n|---|---|\n{row}\n|x|y|\n\nAfter.\n"
        out = ob.postprocess(md, Options(), paper=False)
        rows = out[out.index("|h1"):out.index("After.")].strip().split("\n")
        assert len(rows) == 4 and all(r.startswith("|") and r.endswith("|") for r in rows), rows
        assert_text_kept(md, out)
    pic = "line1<br>line2\n"                                     # outside tables: still a line break
    assert ob.postprocess(pic, Options(), paper=False) == "line1\nline2\n"


# ----------------------------------------------------------------------------- #91 frontmatter

def test_frontmatter_part_fields():
    from pdf2word.metadata import PaperMeta
    meta = PaperMeta(title="Chapter Three", kind="chapter", container="Big Book",
                     part_pages="p. 201-205 (PDF 249-253)", part_pages_pdf="249-253",
                     part_pages_printed="201-205", part_id="3.2")
    fm = ob.build_frontmatter(meta, Path("book.pdf"), "_asset-book-3", "9.9", "p2t")
    for line in ('title: "Chapter Three"', 'book: "Big Book"', 'pages: "201-205"', 'pages_in_pdf: "249-253"',
                 'chapter_id: "3.2"', "  - chapter"):
        assert line in fm, line
    paper = ob.build_frontmatter(PaperMeta(title="A Paper"), Path("p.pdf"), "_asset-x", "9.9", "p2t")
    assert "  - paper" in paper and "book:" not in paper and "pages_in_pdf" not in paper


if __name__ == "__main__":
    failures = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("ok  ", name)
            except AssertionError as exc:
                failures += 1
                print("FAIL", name, exc)
    sys.exit(1 if failures else 0)
