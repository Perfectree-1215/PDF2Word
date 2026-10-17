from __future__ import annotations

import argparse
import glob
import sys
import time
from pathlib import Path

from .config import Options
from .utils import log, setup_console, setup_logging


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pdf2word",
        description="Convert academic PDFs to Obsidian Markdown: LaTeX equations (OCR), "
                    "figures in an _asset-<Author>-<Year> folder, YAML frontmatter.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("inputs", nargs="+", help="PDF files, folders or glob patterns")
    p.add_argument("-f", "--format", choices=["docx", "md", "both"], default="docx",
                   help="docx = Word document; md = Obsidian Markdown + _asset folder; both")
    p.add_argument("--docx-math", choices=["native", "text"], default="native",
                   help="native = Word equations (needs Microsoft Office's MML2OMML.XSL); text = LaTeX text")
    p.add_argument("-o", "--out-dir", type=Path, default=None,
                   help="output folder (default: next to each PDF)")
    p.add_argument("--asset-template", default="_asset-{author}-{year}",
                   help="asset folder name; fields: {author} {year} {title} {stem}")
    p.add_argument("--name-template", default="{author}-{year}-{title}",
                   help="markdown file name (without .md); same fields")
    p.add_argument("--no-overwrite", action="store_true", help="skip PDFs whose .md already exists")

    g = p.add_argument_group("metadata")
    g.add_argument("--author", help="override first-author surname")
    g.add_argument("--year", type=int, help="override publication year")
    g.add_argument("--title", help="override title")
    g.add_argument("--offline", action="store_true", help="no CrossRef/arXiv lookup")

    g = p.add_argument_group("equations")
    g.add_argument("--math-engine", choices=["rapid", "claude", "none"], default="rapid",
                   help="rapid = local RapidLaTeXOCR (CPU); claude = Claude vision API; none = images only")
    g.add_argument("--math-mode", choices=["both", "latex", "image"], default="both",
                   help="both = cropped equation image with the OCR result below it; "
                        "latex = OCR result only (image fallback); image = no OCR output")
    g.add_argument("--math-zooms", default="2,3,4", help="render scales tried in order (rapid engine)")
    g.add_argument("--math-max-tokens", type=int, default=320, help="decoder length cap (rapid engine)")
    g.add_argument("--no-inline-math", action="store_true", help="do not OCR small inline equation images")
    g.add_argument("--no-inline-text-math", action="store_true",
                   help="keep text-layer inline math (rho_f, u_i) as extracted text instead of $...$")
    g.add_argument("--claude-model", default="claude-opus-5-5")
    g.add_argument("--claude-effort", default="low", choices=["low", "medium", "high"])
    g.add_argument("--no-cache", action="store_true", help="disable the OCR result cache")

    g = p.add_argument_group("layout / output")
    g.add_argument("--pages", help="page range, 1-based, e.g. 1-5,8")
    g.add_argument("--dpi", type=int, default=200, help="figure resolution")
    g.add_argument("--image-links", choices=["wiki", "markdown"], default="wiki",
                   help="![[file]] (Obsidian) or ![](file) (standard)")
    g.add_argument("--citations", choices=["keep", "footnotes"], default="keep",
                   help="footnotes: [12] -> [^12] with the reference list as footnotes")
    g.add_argument("--no-block-ids", action="store_true", help="no ^eq-3 / ^fig-2 anchors")
    g.add_argument("--no-abstract-callout", action="store_true")
    g.add_argument("--keep-headers", action="store_true", help="keep running page headers/footers")
    g.add_argument("--keep-picture-text", action="store_true", help="keep text found inside figures")
    g.add_argument("--ocr-pages", action="store_true", help="Tesseract OCR for scanned pages")
    g.add_argument("--no-lighten", action="store_true",
                   help="do not merge clusters of tiny images before layout analysis (slower on plot-heavy pages)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def expand_inputs(items) -> list:
    files = []
    for item in items:
        path = Path(item)
        if path.is_dir():
            files += sorted(path.glob("*.pdf")) + sorted(path.glob("*.PDF"))
        elif path.is_file():
            files.append(path)
        else:
            files += [Path(f) for f in sorted(glob.glob(item, recursive=True))]
    seen = set()
    out = []
    for f in files:
        key = str(f.resolve()).lower()
        if key not in seen and f.suffix.lower() == ".pdf":
            seen.add(key)
            out.append(f)
    return out


def options_from_args(args) -> Options:
    zooms = tuple(float(z) for z in str(args.math_zooms).split(",") if z.strip())
    return Options(
        format=args.format, docx_math=args.docx_math,
        out_dir=args.out_dir, asset_template=args.asset_template, name_template=args.name_template,
        overwrite=not args.no_overwrite, image_links=args.image_links, block_ids=not args.no_block_ids,
        citations=args.citations, abstract_callout=not args.no_abstract_callout,
        online=not args.offline, author=args.author, year=args.year, title=args.title,
        pages=args.pages, dpi=args.dpi, keep_headers=args.keep_headers,
        keep_picture_text=args.keep_picture_text, ocr_pages=args.ocr_pages, lighten=not args.no_lighten,
        math_engine=args.math_engine, math_zooms=zooms or (2.0, 3.0, 4.0),
        math_max_tokens=args.math_max_tokens, math_mode=args.math_mode,
        inline_image_math=not args.no_inline_math, inline_text_math=not args.no_inline_text_math,
        claude_model=args.claude_model,
        claude_effort=args.claude_effort, cache=not args.no_cache, verbose=args.verbose,
    )


def main(argv=None) -> int:
    setup_console()
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)
    pdfs = expand_inputs(args.inputs)
    if not pdfs:
        log.error("no PDF files found for: %s", " ".join(args.inputs))
        return 2
    from .converter import Converter
    conv = Converter(options_from_args(args))
    ok, failed = [], []
    t0 = time.time()
    for pdf in pdfs:
        try:
            result = conv.convert(pdf)
            ok.append(result)
        except KeyboardInterrupt:
            log.error("interrupted")
            return 130
        except Exception as exc:
            failed.append((pdf, exc))
            log.error("  FAILED %s: %s", pdf.name, exc)
            if args.verbose:
                log.exception("traceback")
    log.info("")
    log.info("done: %d converted, %d failed, %.0fs", len(ok), len(failed), time.time() - t0)
    for r in ok:
        if not r.skipped:
            log.info("  %s", r.md_path)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
