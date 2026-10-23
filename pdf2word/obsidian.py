"""Obsidian-flavoured Markdown post-processing: frontmatter, callouts, math delimiters,
image embeds, footnote citations and general clean-up."""
from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path
from urllib.parse import quote

from .symbols import map_pua
from .utils import strip_emphasis

_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
              "ﬅ": "st", "ﬆ": "st"}
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")      # closing '##' needs a space: 'C#' stays
_MATH_SPLIT_RE = re.compile(r"(\$\$.*?\$\$|\$[^$\n]+\$|```.*?```)", re.S)


def yaml_str(value) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def image_link(relpath: str, alt: str = "", style: str = "wiki") -> str:
    relpath = relpath.replace("\\", "/")
    if style == "markdown":
        return f"![{alt}]({quote(relpath)})"
    return f"![[{relpath}]]"


def block_id(prefix: str, label: str) -> str:
    label = re.sub(r"[^A-Za-z0-9-]+", "-", label).strip("-")
    return f"^{prefix}-{label}" if label else ""


# ----------------------------------------------------------------------------- frontmatter

def build_frontmatter(meta, pdf_path: Path, asset_dir_name: str, version: str, engine: str,
                      stats: dict | None = None) -> str:
    lines = ["---", f"title: {yaml_str(meta.title or pdf_path.stem)}"]
    if meta.authors:
        lines.append("authors:")
        lines += [f"  - {yaml_str(a)}" for a in meta.authors]
    if meta.first_author:
        lines.append(f"first_author: {yaml_str(meta.first_author)}")
    if meta.year:
        lines.append(f"year: {int(meta.year)}")
    if meta.journal:
        lines.append(f"journal: {yaml_str(meta.journal)}")
    if meta.volume:
        lines.append(f"volume: {yaml_str(meta.volume)}")
    if meta.issue:
        lines.append(f"issue: {yaml_str(meta.issue)}")
    if meta.pages:
        lines.append(f"pages: {yaml_str(meta.pages)}")
    if meta.doi:
        lines.append(f"doi: {yaml_str(meta.doi)}")
    if meta.arxiv:
        lines.append(f"arxiv: {yaml_str(meta.arxiv)}")
    if meta.url:
        lines.append(f"url: {yaml_str(meta.url)}")
    if meta.keywords:
        lines.append("keywords:")
        lines += [f"  - {yaml_str(k)}" for k in meta.keywords]
    kind = meta.kind
    if meta.container:                              # one chapter / page group of a bigger document
        lines.append(f"book: {yaml_str(meta.container)}")
        printed = meta.part_pages_printed
        in_pdf = meta.part_pages_pdf
        if printed:
            lines.append(f"pages: {yaml_str(printed)}")
        if in_pdf:
            lines.append(f"pages_in_pdf: {yaml_str(in_pdf)}")
        if meta.part_id:
            lines.append(f"chapter_id: {yaml_str(meta.part_id)}")
    lines += ["tags:", f"  - {'chapter' if kind == 'chapter' else 'paper' if kind == 'paper' else 'document'}"]
    lines.append(f"source_pdf: {yaml_str(pdf_path.name)}")
    lines.append(f"assets: {yaml_str(asset_dir_name)}")
    lines.append(f"converted: {_dt.date.today().isoformat()}")
    lines.append(f"converter: {yaml_str(f'pdf2word {version} (math: {engine})')}")
    if stats:
        eq = stats.get("eq_total", 0)
        if eq:
            lines.append(f"equations: {eq}")
            lines.append(f"equations_as_image: {stats.get('eq_fallback', 0)}")
            if stats.get('eq_unverified'):
                lines.append(f"equations_unverified: {stats['eq_unverified']}")
        if stats.get("figure_sheets"):
            lines.append(f"figure_sheets: {stats['figure_sheets']}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


# ----------------------------------------------------------------------------- helpers

def _outside_math(md: str, func) -> str:
    """Apply func to the parts of md that are not inside $...$, $$...$$ or code fences."""
    parts = _MATH_SPLIT_RE.split(md)
    return "".join(p if i % 2 else func(p) for i, p in enumerate(parts))


def _is_block_delim(line: str) -> bool:
    return line.strip() == "$$" or line.lstrip().startswith("```")


def _block_mask(lines: list) -> list:
    """True for the lines of a $$ math block or ``` code fence, delimiters included, so the
    line-based passes leave them alone. An opener without its closer is not a block."""
    mask = [False] * len(lines)
    i = 0
    while i < len(lines):
        if _is_block_delim(lines[i]):
            fence = lines[i].lstrip().startswith("```")
            j = i + 1
            while j < len(lines) and not (lines[j].lstrip().startswith("```") if fence
                                          else lines[j].strip() == "$$"):
                j += 1
            if j < len(lines):
                mask[i:j + 1] = [True] * (j + 1 - i)
                i = j + 1
                continue
        i += 1
    return mask


def _norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9가-힣一-鿿]+", "", (s or "").lower())


def ensure_title(md: str, title: str) -> str:
    """Make the paper title the single H1 at the top of the note."""
    if not title:
        return md
    target = _norm_key(title)
    if not target:                                  # Cyrillic / Greek / kana title: no key to compare
        return "# " + title + "\n\n" + md
    lines = md.split("\n")
    mask = _block_mask(lines)                       # skip '# comment' lines in code fences
    for i, line in enumerate(lines[:80]):
        if mask[i]:
            continue
        m = _HEADING_RE.match(line)
        if not m:
            continue
        h = _norm_key(m.group(2))
        if not h:
            continue
        if (h == target                                                         # any length
                or (len(target) >= 12 and target in h and len(target) >= 0.8 * len(h))
                or (len(h) >= 12 and target.startswith(h))      # title split, first part is the heading
                or (len(h) >= 12 and h[:40] == target[:40])):
            lines[i] = "# " + title
            # demote any later H1 to H2 (keeps a single H1)
            for j in range(i + 1, len(lines)):
                if not mask[j] and lines[j].startswith("# "):
                    lines[j] = "#" + lines[j]
            return "\n".join(lines)
    return "# " + title + "\n\n" + md


def _normalize_text(md: str) -> str:
    md = map_pua(md)
    for lig, rep in _LIGATURES.items():
        md = md.replace(lig, rep)
    md = md.replace("�", "")
    md = _CTRL_RE.sub("", md)
    md = md.replace("\r\n", "\n").replace("\r", "\n")
    md = re.sub(r"[ \t]+\n", "\n", md)
    # in a table row a <br> becomes a space: a line break there would split the row
    md = re.sub(r"(?m)^[ \t]*\|.*$", lambda m: re.sub(r"(?:\s*<br\s*/?>\s*)+", " ", m.group(0)), md)
    md = re.sub(r"<br\s*/?>", "\n", md)
    md = re.sub(r"!\[\]\(\s*\)", "", md)
    md = re.sub(r"_([×−+±·÷])_", r"\1", md)          # italic markers around lone operators (tables)
    return md


def _fix_math_delimiters(md: str) -> str:
    """LaTeX-style delimiters -> Obsidian ($...$ / $$ blocks), blank lines around blocks,
    block ids (^eq-3) kept glued to the closing $$."""
    md = re.sub(r"\\\[\s*(.*?)\s*\\\]", lambda m: "\n$$\n" + m.group(1).strip() + "\n$$\n", md, flags=re.S)
    md = re.sub(r"\\\((.*?)\\\)", lambda m: "$" + m.group(1).strip() + "$", md, flags=re.S)
    md = re.sub(r"(?m)^[ \t]*\$\$[ \t]*(.+?)[ \t]*\$\$[ \t]*$", r"$$\n\1\n$$", md)   # one-line $$ x $$

    out: list = []
    in_math = False
    lines = md.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == "$$":
            if not in_math:                                   # opening
                if out and out[-1].strip():
                    out.append("")
                out.append("$$")
                in_math = True
            else:                                             # closing
                out.append("$$")
                in_math = False
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                if re.match(r"^\^[\w-]+\s*$", nxt):
                    out.append(nxt.strip())
                    i += 1
                if i + 1 < len(lines) and lines[i + 1].strip():
                    out.append("")
        else:
            out.append(line)
        i += 1
    return "\n".join(out)


def _clean_headings(md: str) -> str:
    lines = md.split("\n")
    mask = _block_mask(lines)                       # '# comment' in a code fence is no heading
    out = []
    for line, in_block in zip(lines, mask):
        if in_block:
            out.append(line)
            continue
        if re.match(r"^#{1,6}\s*$", line):          # heading whose text was junk -> drop
            out.append("")
            continue
        m = _HEADING_RE.match(line)
        if m:
            text = re.sub(r"\s+", " ", strip_emphasis(m.group(2))).strip()
            out.append(f"{m.group(1)} {text}" if text else "")
        else:
            out.append(line)
    res = []                                        # blank line before and after each heading
    last = len(out) - 1
    for k, line in enumerate(out):
        heading = not mask[k] and re.match(r"#{1,6} ", line)
        if heading and res and res[-1]:
            res.append("")
        res.append(line)
        if heading and k < last and (out[k + 1] or k + 1 == last):
            res.append("")
    return "\n".join(res)


def _merge_title_lines(md: str) -> str:
    """Multi-line titles arrive as consecutive '# ...' lines; join them into one."""
    lines = md.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines) or not lines[i].startswith("# "):
        return md
    parts = [lines[i][2:].strip()]
    j = i + 1
    while j < len(lines):
        if not lines[j].strip():
            j += 1
            continue
        if lines[j].startswith("# ") and j - i <= 6:
            parts.append(lines[j][2:].strip())
            j += 1
            continue
        break
    if len(parts) == 1:
        return md
    return "\n".join(lines[:i] + ["# " + " ".join(parts), ""] + lines[j:])


# '## Abstract', Elsevier's letter-spaced '### **a b s t r a c t**'
_ABSTRACT_HEADING_RE = re.compile(
    r"(?mi)^#{1,6}[ \t]*[*_]*[ \t]*a[ \t]?b[ \t]?s[ \t]?t[ \t]?r[ \t]?a[ \t]?c[ \t]?t[ \t]*[*_]*[ \t]*$\n+")
# 'Abstract:' / '**Abstract.**' / '_Abstract_:' / 'Abstract' alone on its line / 'Abstract — ...'
# (not 'Abstraction is ...' or 'Abstract art ...': the label needs punctuation, emphasis or a line end)
_ABSTRACT_LABEL_RE = re.compile(
    r"(?m)^[ \t]*(?:(?:\*\*|_)+[ \t]*abstract(?![A-Za-z0-9])[ \t]*[:.—–]?[ \t]*(?:\*\*|_)+[ \t]*[:.—–]?"
    r"|abstract(?![A-Za-z0-9])[ \t]*(?:[:.—–]|[ \t]-[ \t]|\n))\s*(\S.*?)(?=\n\s*\n|\Z)", re.I | re.S)
# Elsevier's 'article info' column, read before the abstract in two-column order
_ARTICLE_INFO_RE = re.compile(
    r"^[*_ ]*(article\s+history|received|accepted|available\s+online|keywords?|handling\s+editor)\b", re.I)
_PARA_END_RE = re.compile(r"\n[ \t]*\n|\n(?=#{1,6} )|\Z")


def _abstract_callout(md: str) -> str:
    """Turn the abstract into an Obsidian `> [!abstract]` callout."""
    # 1) '## Abstract' heading followed by paragraphs
    m = _ABSTRACT_HEADING_RE.search(md)
    if m:
        start = m.end()
        while True:                                 # skip 'Article history' / 'Keywords' paragraphs
            e = _PARA_END_RE.search(md, start)
            para = md[start:e.start()].lstrip()
            if not para or not _ARTICLE_INFO_RE.match(para):
                break
            start = e.end()
        end_m = re.search(r"(?mi)^(#{1,6} |\*{0,2}_?keywords?\b)", md[start:])
        end = start + end_m.start() if end_m else len(md)
        body = md[start:end].strip()
        if body:
            info = md[m.end():start].strip()        # kept, just above the callout
            quoted = "\n".join("> " + ln if ln.strip() else ">" for ln in body.split("\n"))
            return (md[:m.start()] + (info + "\n\n" if info else "") + "> [!abstract] Abstract\n" + quoted
                    + "\n\n" + md[end:])
        return md
    # 2) paragraph starting with 'Abstract:' / '**Abstract.**' (only near the top of the note)
    window = min(len(md), 12000)
    m = _ABSTRACT_LABEL_RE.search(md[:window])
    if m and len(m.group(1)) > 80:
        body = m.group(1).strip()
        quoted = "\n".join("> " + ln if ln.strip() else ">" for ln in body.split("\n"))
        return md[:m.start()] + "> [!abstract] Abstract\n" + quoted + "\n" + md[m.end():]
    return md


def _fix_tables(md: str) -> str:
    """Obsidian needs a blank line before a table; a row whose cell text wrapped onto the next
    line(s) (`|i` / `Stiffness ratio ...|0.86|`) is joined back into one row."""
    lines = md.split("\n")
    mask = _block_mask(lines)                       # '|x|' or '|\psi\rangle' inside $$ is no table row
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if mask[i]:
            out.append(line)
            i += 1
            continue
        if line.lstrip().startswith("|"):
            while (not line.rstrip().endswith("|") and i + 1 < len(lines) and not mask[i + 1]
                   and not _is_block_delim(lines[i + 1])
                   and lines[i + 1].strip() and not lines[i + 1].lstrip().startswith("|")):
                i += 1
                line = line.rstrip() + " " + lines[i].strip()
            if out and out[-1].strip() and not out[-1].lstrip().startswith("|"):
                out.append("")
        out.append(line)
        i += 1
    return "\n".join(out)


_JOURNAL_LABELS = {"article", "review", "communication", "letter", "editorial", "research article",
                   "original article", "original research", "full paper", "short communication",
                   "technical note", "research paper", "regular paper", "open access"}


def _clean_front_matter(md: str) -> str:
    """Drop journal labels ('Article') above the title and un-bold the author line, whose
    affiliation markers otherwise turn into a mess of ** and <sup> fragments."""
    lines = md.split("\n")
    # the title is the first heading (ensure_title() promotes it to '# ' later in the pipeline)
    title_idx = next((i for i, ln in enumerate(lines[:60]) if re.match(r"^#{1,6} ", ln)), None)
    if title_idx is None:
        return md
    for i in range(title_idx):
        if strip_emphasis(lines[i]).strip().lower() in _JOURNAL_LABELS:
            lines[i] = ""
    end = next((i for i in range(title_idx + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    for i in range(title_idx + 1, min(end, title_idx + 12)):
        ln = lines[i]
        if ln.count("<sup>") >= 2 and ln.count("**") >= 2:
            ln = re.sub(r"\*\*|(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])", "", ln)
            lines[i] = re.sub(r"\s+,", ",", ln)
    return "\n".join(lines)


def _split_merged_references(md: str) -> str:
    """'2. Galk ... 1995. 3. Bauer ...' or '- [1] ... [2] ...' (pymupdf4llm list item) on one
    line -> separate reference entries."""
    m = re.search(r"(?mi)^#{1,6}\s*(references|bibliography|literature cited|reference list|참고\s*문헌)\s*$", md)
    if not m:
        return md
    head, refs = md[:m.end()], md[m.end():]
    out = []
    for line in refs.split("\n"):
        mm = re.match(r"^\s*([-*+]\s+)?(?:\[(\d{1,3})\]|(\d{1,3})\.)\s", line)
        if mm:
            marker = (mm.group(1) or "").strip()
            bracket = mm.group(2) is not None
            n = int(mm.group(2) or mm.group(3))
            while True:
                if bracket:
                    nxt = re.search(rf"(?<=\S)\s+\[{n + 1}\]\s+(?=\S)", line)
                else:
                    nxt = re.search(rf"(?<=[.\]\)])\s+{n + 1}\.\s+(?=[A-ZÀ-ɏ])", line)
                if not nxt:
                    break
                out.append(line[:nxt.start()].rstrip())
                out.append("")
                line = (marker + " " if marker else "") + line[nxt.start():].lstrip()
                n += 1
        out.append(line)
    return head + "\n".join(out)


def _expand_cites(spec: str) -> list:
    """'1, 5-7' -> [1, 5, 6, 7]; [] when any part cannot be expanded (the caller keeps the text)."""
    nums = []
    for part in re.split(r"\s*[,;]\s*", spec.strip()):
        if not part:
            continue
        m = re.match(r"^(\d{1,3})\s*[-–—]\s*(\d{1,3})$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if not a <= b <= a + 30:
                return []
            nums += list(range(a, b + 1))
        elif part.isdigit():
            nums.append(int(part))
        else:
            return []
    return nums


# a line after a reference entry that starts something else (picture, equation, table, quote,
# comment, caption) is kept as it is instead of being glued into the entry
_REF_BREAK_RE = re.compile(r"^\s*(!\[|\$\$|\||>|<!--|[*_]{0,2}(Table|Fig(?:ure)?|Scheme)\.?\s*\d)")


def citations_to_footnotes(md: str) -> str:
    """[12] -> [^12] in the body, reference list -> footnote definitions (hover previews).
    The section heading, lines before the first entry and pictures / captions / tables after an
    entry are kept as they are; a list whose numbers repeat is left alone."""
    m = re.search(r"(?mi)^#{1,6}\s*(references|bibliography|literature cited|reference list|참고\s*문헌)\s*$", md)
    if not m:
        return md
    head, refs = md[:m.start()], md[m.end():]
    heading = md[m.start():m.end()].strip()
    ref_lines = refs.split("\n")
    entries: dict = {}
    pre: list = []                  # lines before the first entry (a note, a picture ...)
    post: list = []                 # structural lines after an entry, in their order
    rest_start = None
    cur = None
    in_post = False
    for i, line in enumerate(ref_lines):
        if line.startswith("#"):
            rest_start = i
            break
        mm = re.match(r"^\s*(?:[-*+]\s+)?(?:\[(\d{1,3})\]|(\d{1,3})\.)\s+(.*)", line)
        if mm:
            cur = int(mm.group(1) or mm.group(2))
            if cur in entries:                      # numbering restarts: one entry would overwrite another
                return md
            entries[cur] = mm.group(3).strip()
            in_post = False
        elif cur is None:
            pre.append(line)
        elif in_post or _REF_BREAK_RE.match(line):
            post.append(line)
            in_post = True
        elif line.strip():
            entries[cur] += " " + line.strip()
    if len(entries) < 3:
        return md

    cited = set()

    def repl(mo):
        nums = _expand_cites(mo.group(1))
        if not nums or not all(n in entries for n in nums):
            return mo.group(0)
        cited.update(nums)
        return "".join(f"[^{n}]" for n in nums)

    new_head = _outside_math(head, lambda s: re.sub(r"\[(\d{1,3}(?:\s*[,;–—-]\s*\d{1,3})*)\]", repl, s))
    if not cited:
        return md
    defs = "\n".join(f"[^{n}]: {t}" for n, t in sorted(entries.items()))
    remainder = "\n".join(ref_lines[rest_start:]) if rest_start is not None else ""
    section = [heading, "\n".join(pre).strip(), defs, "\n".join(post).strip()]
    return new_head + "\n\n".join(s for s in section if s) + "\n\n" + remainder


def _collapse(md: str) -> str:
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"


# ----------------------------------------------------------------------------- entry point

def postprocess(md: str, options, paper: bool = True) -> str:
    """General clean-up for every document; the paper-specific steps (journal labels, author
    line, abstract callout, reference list) only when `paper` is True."""
    md = _normalize_text(md)
    md = _merge_title_lines(md)
    md = _fix_math_delimiters(md)
    md = _clean_headings(md)
    if paper:
        md = _clean_front_matter(md)
        if options.abstract_callout:
            md = _abstract_callout(md)
        md = _split_merged_references(md)
        if options.citations == "footnotes":
            md = citations_to_footnotes(md)
    md = _fix_tables(md)
    md = _collapse(md)
    return md
