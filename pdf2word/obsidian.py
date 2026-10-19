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
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
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
    kind = getattr(meta, "kind", "paper") or "paper"
    container = getattr(meta, "container", "")
    if container:                                   # one chapter / page group of a bigger document
        lines.append(f"book: {yaml_str(container)}")
        printed = getattr(meta, "part_pages_printed", "")
        in_pdf = getattr(meta, "part_pages_pdf", "") or getattr(meta, "part_pages", "")
        if printed:
            lines.append(f"pages: {yaml_str(printed)}")
        if in_pdf:
            lines.append(f"pages_in_pdf: {yaml_str(in_pdf)}")
        if getattr(meta, "part_id", ""):
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
    lines.append("---")
    return "\n".join(lines) + "\n\n"


# ----------------------------------------------------------------------------- helpers

def _outside_math(md: str, func) -> str:
    """Apply func to the parts of md that are not inside $...$, $$...$$ or code fences."""
    parts = _MATH_SPLIT_RE.split(md)
    return "".join(p if i % 2 else func(p) for i, p in enumerate(parts))


def _norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9가-힣一-鿿]+", "", (s or "").lower())


def ensure_title(md: str, title: str) -> str:
    """Make the paper title the single H1 at the top of the note."""
    if not title:
        return md
    target = _norm_key(title)
    lines = md.split("\n")
    for i, line in enumerate(lines[:80]):
        m = _HEADING_RE.match(line)
        if not m:
            continue
        h = _norm_key(m.group(2))
        if len(h) >= 12 and (h in target or target in h or h[:40] == target[:40]):
            lines[i] = "# " + title
            # demote any later H1 to H2 (keeps a single H1)
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("# "):
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
    out = []
    for line in md.split("\n"):
        if re.match(r"^#{1,6}\s*$", line):          # heading whose text was junk -> drop
            out.append("")
            continue
        m = _HEADING_RE.match(line)
        if m:
            text = re.sub(r"\s+", " ", strip_emphasis(m.group(2))).strip()
            out.append(f"{m.group(1)} {text}" if text else "")
        else:
            out.append(line)
    md = "\n".join(out)
    md = re.sub(r"(?m)([^\n])\n(#{1,6} )", r"\1\n\n\2", md)        # blank line before headings
    md = re.sub(r"(?m)^(#{1,6} .*)\n(?!\n)", r"\1\n\n", md)         # ... and after
    return md


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


def _abstract_callout(md: str) -> str:
    """Turn the abstract into an Obsidian `> [!abstract]` callout."""
    # 1) '## Abstract' heading followed by paragraphs
    m = re.search(r"(?mi)^#{1,6}\s*abstract\s*$\n+", md)
    if m:
        start = m.end()
        end_m = re.search(r"(?mi)^(#{1,6} |\*{0,2}_?keywords?\b)", md[start:])
        end = start + end_m.start() if end_m else len(md)
        body = md[start:end].strip()
        if body:
            quoted = "\n".join("> " + ln if ln.strip() else ">" for ln in body.split("\n"))
            return md[:m.start()] + "> [!abstract] Abstract\n" + quoted + "\n\n" + md[end:]
        return md
    # 2) paragraph starting with 'Abstract:' / '**Abstract.**' (only near the top of the note)
    window = min(len(md), 12000)
    m = re.search(r"(?m)^(?:\*\*|_)*\s*abstract\s*(?:\*\*|_)*\s*[:.—-]?\s*(?:\*\*|_)*[ \t]*(\S.*?)(?=\n\s*\n|\Z)",
                  md[:window], re.I | re.S)
    if m and len(m.group(1)) > 80:
        body = m.group(1).strip()
        quoted = "\n".join("> " + ln if ln.strip() else ">" for ln in body.split("\n"))
        return md[:m.start()] + "> [!abstract] Abstract\n" + quoted + "\n" + md[m.end():]
    return md


def _fix_tables(md: str) -> str:
    """Obsidian needs a blank line before a table; a row whose cell text wrapped onto the next
    line(s) (`|i` / `Stiffness ratio ...|0.86|`) is joined back into one row."""
    lines = md.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("|"):
            while (not line.rstrip().endswith("|") and i + 1 < len(lines)
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
    """'2. Galk ... 1995. 3. Bauer ...' on one line -> two reference entries."""
    m = re.search(r"(?mi)^#{1,6}\s*(references|bibliography|literature cited|reference list|참고\s*문헌)\s*$", md)
    if not m:
        return md
    head, refs = md[:m.end()], md[m.end():]
    out = []
    for line in refs.split("\n"):
        mm = re.match(r"^\s*(\d{1,3})\.\s", line)
        if mm:
            n = int(mm.group(1))
            while True:
                nxt = re.search(rf"(?<=[.\]\)])\s+{n + 1}\.\s+(?=[A-ZÀ-ɏ])", line)
                if not nxt:
                    break
                out.append(line[:nxt.start()].rstrip())
                out.append("")
                line = line[nxt.start():].lstrip()
                n += 1
        out.append(line)
    return head + "\n".join(out)


def _expand_cites(spec: str) -> list:
    nums = []
    for part in re.split(r"\s*[,;]\s*", spec.strip()):
        m = re.match(r"^(\d{1,3})\s*[-–—]\s*(\d{1,3})$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a <= b <= a + 30:
                nums += list(range(a, b + 1))
        elif part.isdigit():
            nums.append(int(part))
    return nums


def citations_to_footnotes(md: str) -> str:
    """[12] -> [^12] in the body, reference list -> footnote definitions (hover previews)."""
    m = re.search(r"(?mi)^#{1,6}\s*(references|bibliography|literature cited|reference list|참고\s*문헌)\s*$", md)
    if not m:
        return md
    head, refs = md[:m.start()], md[m.end():]
    ref_lines = refs.split("\n")
    entries: dict = {}
    rest_start = None
    cur = None
    for i, line in enumerate(ref_lines):
        if line.startswith("#"):
            rest_start = i
            break
        mm = re.match(r"^\s*(?:\[(\d{1,3})\]|(\d{1,3})\.)\s+(.*)", line)
        if mm:
            cur = int(mm.group(1) or mm.group(2))
            entries[cur] = mm.group(3).strip()
        elif cur is not None and line.strip():
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
    return new_head + "## References\n\n" + defs + "\n\n" + remainder


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
        if getattr(options, "abstract_callout", True):
            md = _abstract_callout(md)
        md = _split_merged_references(md)
        if getattr(options, "citations", "keep") == "footnotes":
            md = citations_to_footnotes(md)
    md = _fix_tables(md)
    md = _collapse(md)
    return md
