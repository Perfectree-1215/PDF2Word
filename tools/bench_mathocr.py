"""Measure equation OCR on the display equations of one PDF.

Everything for one PDF lives in ONE folder, bench/<pdf stem>/ :

    golden.json    the correct LaTeX of each equation, confirmed by a person  <- the only file to edit
    report.html    each result rendered by MathJax next to the original crop, with its golden status
    report.md      the same as text
    results.json   everything, for further processing
    eq-*.png       the crops

    python tools/bench_mathocr.py docs/paper-01.pdf --pages 2
        -> bench/paper-01/.  On the first run golden.json is created from the engine's results with
           "verified": false everywhere.  Open report.html, fix the LaTeX of each equation in
           golden.json and set "verified": true; then `--rescore` re-scores the last results
           against golden.json in a second (no OCR) and rewrites the reports.

Only verified golden entries are scored. Exact match is judged after normalize_latex (pdf2word.
mathocr), which ignores bold, bracket sizes, \\mathrm wrappers, spacing and braces but keeps
accents, sub/superscripts and symbols. This is the one measurement that does not depend on the
PDF's text layer (docs/decisions/equation-ocr-reliability.md).

Confidence = similarity of the result to the PDF text layer of the region (mathocr.hint_similarity),
or, when the text layer is garbled (Type 1 private encodings) or missing, the agreement between render
scales (multi-scale engines); a doubtful reading of a region without any text layer is capped at 0.5
(vectormath.doubtful_equation) - exactly as the converter does. A result is uncertain below
CONFIDENCE_LOW (text-layer similarity) or AGREE_LOW (agreement). The OCR cache is bypassed so that the
times are real.
"""
from __future__ import annotations

import argparse
import html
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pymupdf  # noqa: E402

from pdf2word.mathocr import (AGREE_LOW, CONFIDENCE_LOW, LABEL_RE, EquationOCR, agreement,  # noqa: E402
                              build_engine, find_labels, hint_usable, label_text, normalize_latex,  # noqa: F401
                              png_bytes)                       # normalize_latex: for tests/test_bench.py
from pdf2word.outline import parse_pages  # noqa: E402
from pdf2word.symbols import map_pua  # noqa: E402
from pdf2word.utils import setup_console, setup_logging  # noqa: E402
from pdf2word.vectormath import doubtful_equation  # noqa: E402

GOLDEN_NOTE = ("Open report.html, correct 'latex' of each equation against the original crop and set "
               "'verified': true. Only verified entries are scored; 'verified': false entries are the "
               "engine's own output, kept as a starting point. An entry is matched by page, label and k; "
               "k (0, 1, ...) counts the equations with the same page and label in page order, which "
               "tells apart the unnumbered equations of one page.")


# ----------------------------------------------------------------------------- equation regions

def equation_regions(doc: pymupdf.Document, pages=None, lighten: bool = True) -> list:
    """[(page_number_1based, region Rect, hint, label, text_layer_garbled, mask)] for every display
    equation, found with the same layout analysis, label splitting and text-layer check as the
    converter. A garbled hint is passed on as it is: recognize_region handles it."""
    from pdf2word.converter import _DocContext, _patch_pymupdf4llm_pua
    from pdf2word.lighten import lighten_document
    _patch_pymupdf4llm_pua()
    import pymupdf4llm

    layout_doc = doc
    if lighten:
        layout_doc, _ = lighten_document(doc, dpi=200)
    # use_ocr=False as in the converter (Options.ocr_pages): no Tesseract probe, no page OCR
    chunks = pymupdf4llm.to_markdown(layout_doc, pages=pages, page_chunks=True, write_images=False,
                                     header=False, footer=False, use_ocr=False, force_text=True,
                                     show_progress=False)
    if isinstance(chunks, str):
        raise SystemExit("PyMuPDF Layout is not available: pip install pymupdf-layout")
    out = []
    for i, chunk in enumerate(chunks, 1):
        pno = int(chunk["metadata"].get("page_number", i)) - 1
        page = doc[pno]
        for box in chunk.get("page_boxes") or []:
            if box.get("class") != "formula":
                continue
            rect = pymupdf.Rect(box["bbox"])
            inside = (page.get_text("text", clip=rect) or "").strip()
            if LABEL_RE.match(label_text(inside)) and rect.width < 60:
                continue                      # an equation number alone (equation drawn as graphics)
            labels = find_labels(page, pymupdf.Rect(rect.x0, rect.y0 - 3, page.rect.x1, rect.y1 + 3), box=rect)
            for region, label, mask in _DocContext._split_regions(rect, labels, page):
                hint = map_pua(page.get_text("text", clip=region) or "").strip()
                garbled = bool(hint) and not hint_usable(hint)
                out.append((pno + 1, region, hint, label, garbled, mask))
    return out


# ----------------------------------------------------------------------------- running

def build_engines(names: list, args) -> dict:
    engines = {}
    for name in names:
        try:
            eng = build_engine(name, max_tokens=args.math_max_tokens, model=args.claude_model,
                               effort=args.claude_effort)
        except SystemExit as exc:
            print(f"[skip] {name}: {exc}")
            continue
        if eng is None:
            print(f"[skip] {name}: no OCR engine")
            continue
        if eng.name != name.lower():                  # p2t without its model comes back as rapid
            print(f"[skip] {name}: model not available, fell back to {eng.name}")
            continue
        engines[name] = eng
    return engines


def run(doc, regions, engines: dict, zooms, out_dir: Path, warmup: bool = True) -> list:
    """rows: one dict per equation with the crop file and one entry per engine."""
    out_dir.mkdir(parents=True, exist_ok=True)
    ocrs = {n: EquationOCR(e, zooms=zooms, cache=False) for n, e in engines.items()}
    rows = []
    for idx, (pno, region, hint, label, garbled, mask) in enumerate(regions, 1):
        page = doc[pno - 1]
        tag = f"eq-{idx:03d}-p{pno}" + (f"-({label})" if label else "")
        row = {"index": idx, "page": pno, "label": label, "hint": "" if garbled else hint,
               "text_layer_garbled": garbled, "crop": None, "engines": {}}
        rows.append(row)
        crop_saved = False
        for name, ocr in ocrs.items():
            if warmup and idx == 1:
                ocr.recognize_region(page, region, hint, mask)     # model load / first-call overhead
            result = ocr.recognize_region(page, region, hint, mask)
            if not hint and not garbled and doubtful_equation(result.latex):
                result.confidence = min(result.confidence, 0.5)    # as _DocContext._format_equation does
            if result.image is not None and not crop_saved:
                fname = out_dir / f"{tag}.png"
                fname.write_bytes(png_bytes(result.image))
                row["crop"] = fname.name
                crop_saved = True
            row["engines"][name] = {
                "latex": result.latex, "confidence": round(result.confidence, 3),
                "uncertain": result.uncertain, "seconds": round(result.seconds, 2), "lines": result.lines,
            }
            print(f"  {tag:<22} {name:<8} {result.seconds:5.1f}s  conf {result.confidence:4.2f}  "
                  f"{(result.latex or '(none)')[:70]}")
    return rows


# ----------------------------------------------------------------------------- golden set

def is_uncertain(entry: dict) -> bool:
    """The engine entry of a row would carry the reader's warning (EquationResult.uncertain; rows of
    an older results.json have no such key and use the text-layer threshold)."""
    return bool(entry.get("uncertain", entry.get("confidence", 1.0) < CONFIDENCE_LOW))


def golden_key(page, label, k=0) -> tuple:
    """(page, label, k): k tells apart equations with the same page and label (the unnumbered
    ones of a page); a golden.json written before k existed has none, which reads as 0."""
    return int(page), str(label or ""), int(k or 0)


def golden_ordinals(rows: list) -> list:
    """k of each row: how many rows before it have the same (page, label). Counted within a
    page, so --pages and --limit do not change it; never stored, so older results.json files
    can be re-scored."""
    seen: dict = {}
    out = []
    for r in rows:
        pl = (int(r["page"]), str(r["label"] or ""))
        out.append(seen.get(pl, 0))
        seen[pl] = out[-1] + 1
    return out


def load_golden(path: Path) -> dict:
    """{(page, label, k): entry} for every entry of golden.json; entry['verified'] says whether
    it is scored. Two entries with the same key are refused (one would silently replace the
    other)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data["equations"] if isinstance(data, dict) else data
    golden, dup = {}, []
    for e in entries:
        key = golden_key(e["page"], e.get("label"), e.get("k", 0))
        if key in golden:
            dup.append(key)
        golden[key] = e
    if dup:
        raise SystemExit(f"{path}: several entries for (page, label, k) {', '.join(map(str, dup))} - "
                         "give the equations with the same page and label \"k\": 0, 1, ... in page order")
    return golden


def write_golden_skeleton(path: Path, pdf: Path, rows: list, engine: str) -> None:
    """golden.json to be corrected by hand: the first engine's result per equation, unverified.
    Never overwrites an existing file (that is the person's work)."""
    if path.exists():
        raise SystemExit(f"{path} exists - delete it or pass --rewrite-golden to start over")
    entries = [{"page": r["page"], "label": r["label"], "k": k, "verified": False,
                "latex": (r["engines"].get(engine) or {}).get("latex") or ""}
               for r, k in zip(rows, golden_ordinals(rows))]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pdf": pdf.name, "note": GOLDEN_NOTE, "equations": entries},
                               ensure_ascii=False, indent=1), encoding="utf-8")


def score_against_golden(rows: list, golden: dict) -> dict:
    """Per-engine exact-match rate and mean similarity against the *verified* golden entries,
    after normalize_latex. Each row gets 'golden_status': verified / unverified / missing, and
    each scored engine entry gets 'golden_exact' and 'golden_sim'. Pure: used by the tests."""
    names = sorted({n for r in rows for n in r["engines"]})
    scored = {n: {"compared": 0, "exact": 0, "sims": []} for n in names}
    for r, k in zip(rows, golden_ordinals(rows)):
        for e in r["engines"].values():                # scores of a previous run
            e.pop("golden_sim", None)
            e.pop("golden_exact", None)
        r["golden_k"] = k
        g = golden.get(golden_key(r["page"], r["label"], k))
        if not g:
            r["golden_status"] = "missing"
            continue
        if not g.get("verified") or not g.get("latex"):
            r["golden_status"] = "unverified"
            continue
        r["golden_status"] = "verified"
        for n in names:
            e = r["engines"].get(n)
            if not e:
                continue
            sim = agreement(g["latex"], e["latex"] or "")      # normalize_latex, then similarity
            e["golden_sim"] = round(sim, 3)
            e["golden_exact"] = sim == 1.0
            s = scored[n]
            s["compared"] += 1
            s["exact"] += int(e["golden_exact"])
            s["sims"].append(sim)
    return {n: {"compared": s["compared"], "exact": s["exact"],
                "exact_rate": round(s["exact"] / s["compared"], 3) if s["compared"] else 0.0,
                "mean_sim": round(statistics.fmean(s["sims"]), 3) if s["sims"] else 0.0}
            for n, s in scored.items()}


# ----------------------------------------------------------------------------- summary / reports

def summarize(rows: list) -> dict:
    """Per-engine counts and averages. Pure: used by the tests."""
    names = sorted({n for r in rows for n in r["engines"]})
    summary = {}
    for name in names:
        results = [r["engines"][name] for r in rows if name in r["engines"]]
        got = [x for x in results if x["latex"]]
        confs = [x["confidence"] for x in got]
        secs = [x["seconds"] for x in results]
        summary[name] = {
            "equations": len(results),
            "recognized": len(got),
            "failed": len(results) - len(got),
            "uncertain": sum(1 for x in got if is_uncertain(x)),
            "mean_confidence": round(statistics.fmean(confs), 3) if confs else 0.0,
            "median_seconds": round(statistics.median(secs), 2) if secs else 0.0,
            "total_seconds": round(sum(secs), 1),
            "text_layer_garbled": sum(1 for r in rows if r["text_layer_garbled"] and name in r["engines"]),
        }
    return summary


def _layer_note(r: dict) -> str:
    if r["text_layer_garbled"]:
        return "text layer: garbled (not used; confidence = agreement between render scales)"
    if r["hint"]:
        return f"text layer: `{r['hint'][:200]}`"
    return "text layer: none (multi-scale engines: confidence = agreement between render scales)"


def _golden_note(r: dict) -> str:
    st = r.get("golden_status")
    k = r.get("golden_k", 0)
    key = f'golden.json entry page {r["page"]}, label "{r["label"] or ""}"'
    if k or not r["label"]:
        key += f", k {k}"
    if st == "verified":
        return f"golden: verified ({key})"
    if st == "unverified":
        return f"golden: NOT VERIFIED - check the LaTeX in {key} and set \"verified\": true"
    return f"golden: no entry ({key})"


def write_markdown(path: Path, pdf: Path, rows: list, summary: dict, golden_scores: dict) -> None:
    names = list(summary)
    lines = [f"# Equation OCR benchmark: {pdf.name}", "",
             f"{len(rows)} display equation(s). Confidence = similarity to the PDF text layer, or, when the "
             f"layer is garbled or missing, the agreement between render scales (multi-scale engines). "
             f"Uncertain (⚠) = text-layer similarity < {CONFIDENCE_LOW} or agreement < {AGREE_LOW}.", "",
             "| engine | recognized | failed | uncertain | garbled layer | mean conf | median s/eq | total s |",
             "|---|---|---|---|---|---|---|---|"]
    for n in names:
        s = summary[n]
        lines.append(f"| {n} | {s['recognized']}/{s['equations']} | {s['failed']} | {s['uncertain']} | "
                     f"{s['text_layer_garbled']} | {s['mean_confidence']:.3f} | {s['median_seconds']:.2f} | "
                     f"{s['total_seconds']:.1f} |")
    n_unv = sum(1 for r in rows if r.get("golden_status") == "unverified")
    lines += ["", "## Against golden.json", "",
              f"{n_unv} equation(s) still unverified in golden.json." if n_unv else "All equations verified.", "",
              "| engine | compared | exact | exact rate | mean similarity |", "|---|---|---|---|---|"]
    for n, g in golden_scores.items():
        lines.append(f"| {n} | {g['compared']} | {g['exact']} | {g['exact_rate']:.3f} | {g['mean_sim']:.3f} |")
    lines += ["", "## Equations", ""]
    for r in rows:
        head = f"### {r['index']}. page {r['page']}" + (f", eq. ({r['label']})" if r["label"] else "")
        lines += [head, ""]
        if r["crop"]:
            lines += [f"![]({r['crop']})", ""]
        lines += [_layer_note(r), "", _golden_note(r), ""]
        lines += ["| engine | conf | golden | s | LaTeX |", "|---|---|---|---|---|"]
        for n in names:
            e = r["engines"].get(n)
            if not e:
                continue
            latex = (e["latex"] or "(none)").replace("|", "\\|").replace("\n", " ")
            flag = " ⚠" if e["latex"] and is_uncertain(e) else ""
            gold = ("✓" if e.get("golden_exact") else f"{e['golden_sim']:.2f}") if "golden_sim" in e else "–"
            lines.append(f"| {n} | {e['confidence']:.2f}{flag} | {gold} | {e['seconds']:.1f} | `{latex}` |")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


_HTML_HEAD = """<!doctype html><html><head><meta charset="utf-8"><title>Equation OCR benchmark</title>
<script>MathJax = {tex: {displayMath: [['$$','$$']]}, svg: {fontCache: 'global'}};</script>
<script defer src="https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-svg.js"></script>
<style>
body{font-family:system-ui,sans-serif;margin:24px;max-width:1400px}
table{border-collapse:collapse;width:100%;margin-bottom:28px}
td,th{border:1px solid #ccc;padding:6px 8px;vertical-align:top;text-align:left}
th{background:#f3f3f3}
img.crop{max-width:100%;background:#fff;border:1px solid #ddd}
code{font-size:12px;white-space:pre-wrap;word-break:break-all}
.low{background:#fff3cd}.none{background:#f8d7da}.exact{background:#d4edda}
.todo{color:#b45309;font-weight:600}.ok{color:#15803d}
.summary td,.summary th{text-align:right}.summary th:first-child,.summary td:first-child{text-align:left}
</style></head><body>
"""


def write_html(path: Path, pdf: Path, rows: list, summary: dict, golden_scores: dict) -> None:
    names = list(summary)
    n_unv = sum(1 for r in rows if r.get("golden_status") == "unverified")
    h = [_HTML_HEAD, f"<h1>Equation OCR benchmark: {html.escape(pdf.name)}</h1>",
         f"<p>{len(rows)} display equation(s). Confidence = similarity to the PDF text layer, or, when the "
         f"layer is garbled or missing, the agreement between render scales (multi-scale engines). "
         f"Yellow = text-layer similarity &lt; {CONFIDENCE_LOW} or agreement &lt; {AGREE_LOW}, "
         f"red = no result, green = exact match with golden.json.</p>",
         (f"<p class='todo'>{n_unv} equation(s) still unverified in golden.json (same folder as this file): "
          f"compare each result with its crop below, fix the LaTeX there and set \"verified\": true.</p>"
          if n_unv else "<p class='ok'>All equations of golden.json are verified.</p>"),
         "<table class='summary'><tr><th>engine</th><th>recognized</th><th>failed</th><th>uncertain</th>"
         "<th>garbled layer</th><th>mean conf</th><th>median s/eq</th><th>total s</th>"
         "<th>golden exact</th><th>golden mean sim</th></tr>"]
    for n in names:
        s = summary[n]
        g = golden_scores.get(n, {})
        h.append(f"<tr><td>{html.escape(n)}</td><td>{s['recognized']}/{s['equations']}</td><td>{s['failed']}</td>"
                 f"<td>{s['uncertain']}</td><td>{s['text_layer_garbled']}</td><td>{s['mean_confidence']:.3f}</td>"
                 f"<td>{s['median_seconds']:.2f}</td><td>{s['total_seconds']:.1f}</td>"
                 f"<td>{g.get('exact', 0)}/{g.get('compared', 0)}</td><td>{g.get('mean_sim', 0):.3f}</td></tr>")
    h.append("</table>")
    for r in rows:
        title = f"{r['index']}. page {r['page']}" + (f", eq. ({r['label']})" if r["label"] else "")
        h.append(f"<h3>{html.escape(title)}</h3>")
        cls = "ok" if r.get("golden_status") == "verified" else "todo"
        h.append(f"<p><small>{html.escape(_layer_note(r).replace('`', ''))} · "
                 f"<span class='{cls}'>{html.escape(_golden_note(r))}</span></small></p>")
        h.append("<table><tr><th style='width:34%'>original</th>" +
                 "".join(f"<th>{html.escape(n)}</th>" for n in names) + "</tr><tr>")
        h.append("<td>" + (f"<img class='crop' src='{html.escape(r['crop'])}'>" if r["crop"] else "") + "</td>")
        for n in names:
            e = r["engines"].get(n) or {}
            latex = e.get("latex")
            cls = ("none" if not latex else "exact" if e.get("golden_exact")
                   else "low" if is_uncertain(e) else "")
            body = f"$${html.escape(latex)}$$<hr><code>{html.escape(latex)}</code>" if latex else "<i>no result</i>"
            gold = f" · golden {e['golden_sim']:.2f}" if "golden_sim" in e else ""
            h.append(f"<td class='{cls}'>{body}<br><small>conf {e.get('confidence', 0):.2f} · "
                     f"{e.get('seconds', 0):.1f}s{gold}</small></td>")
        h.append("</tr></table>")
    h.append("</body></html>")
    path.write_text("\n".join(h), encoding="utf-8")


# ----------------------------------------------------------------------------- main

def finish(out_dir: Path, golden_path: Path, pdf: Path, rows: list, summary: dict, engines_meta: dict,
           first_engine: str, rewrite_golden: bool = False) -> int:
    """Golden scoring, results.json and the reports - shared by a run and by --rescore."""
    if rewrite_golden and golden_path.exists():
        golden_path.unlink()
    if not golden_path.exists():
        write_golden_skeleton(golden_path, pdf, rows, first_engine)
        print(f"\ngolden.json created: {golden_path}  (all entries unverified - see report.html)")
    golden = load_golden(golden_path)
    golden_scores = score_against_golden(rows, golden)

    (out_dir / "results.json").write_text(
        json.dumps({"pdf": str(pdf), "engines": engines_meta, "summary": summary, "golden": golden_scores,
                    "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    write_markdown(out_dir / "report.md", pdf, rows, summary, golden_scores)
    write_html(out_dir / "report.html", pdf, rows, summary, golden_scores)
    n_unv = sum(1 for r in rows if r.get("golden_status") == "unverified")
    print()
    print(f"{'engine':<10}{'recognized':>12}{'uncertain':>11}{'garbled':>9}{'mean conf':>11}{'median s':>10}"
          f"{'golden exact':>14}{'golden sim':>12}")
    for n, s in summary.items():
        g = golden_scores.get(n, {})
        print(f"{n:<10}{s['recognized']:>6}/{s['equations']:<5}{s['uncertain']:>11}{s['text_layer_garbled']:>9}"
              f"{s['mean_confidence']:>11.3f}{s['median_seconds']:>10.2f}"
              f"{g.get('exact', 0):>8}/{g.get('compared', 0):<5}{g.get('mean_sim', 0):>12.3f}")
    print(f"\nfolder: {out_dir}  -> open report.html"
          + (f"; {n_unv} golden entr{'y' if n_unv == 1 else 'ies'} still to verify in golden.json" if n_unv else ""))
    return 0


def main(argv=None) -> int:
    setup_console()               # before any print: a label such as (2–3) on a cp949 stdout (as cli.main)
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("pdf", type=Path)
    p.add_argument("--engines", default="p2t", help="comma list of math engines (p2t, rapid, claude)")
    p.add_argument("--pages", help="PDF page range, 1-based, e.g. 3-8,12")
    p.add_argument("-o", "--out", type=Path, help="folder for everything (default: bench/<pdf stem>)")
    p.add_argument("--golden", type=Path, help="golden set to score against (default: <out>/golden.json)")
    p.add_argument("--rescore", action="store_true",
                   help="no OCR: re-score the last results.json against golden.json and rewrite the reports")
    p.add_argument("--rewrite-golden", action="store_true",
                   help="replace golden.json with a fresh skeleton from this run (loses hand edits)")
    p.add_argument("--zooms", help="render scales tried in order (default: the engine's own order, "
                   "rapid 2,3,4 / p2t 4,3,2)")
    p.add_argument("--limit", type=int, default=0, help="stop after N equations")
    p.add_argument("--no-lighten", action="store_true")
    p.add_argument("--no-warmup", action="store_true", help="count model loading in the first equation's time")
    p.add_argument("--math-max-tokens", type=int, default=320)
    p.add_argument("--claude-model", default="claude-opus-5-5")
    p.add_argument("--claude-effort", default="low")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    setup_logging(args.verbose)                       # pdf2word logger only; PIL / onnxruntime stay quiet
    out_dir = args.out or Path("bench") / args.pdf.stem
    golden_path = args.golden or out_dir / "golden.json"

    if args.rescore:
        res_path = out_dir / "results.json"
        if not res_path.exists():
            p.error(f"{res_path} not found - run without --rescore first")
        res = json.loads(res_path.read_text(encoding="utf-8"))
        print(f"re-scoring {len(res['rows'])} equation(s) of {res_path} against {golden_path} (no OCR)")
        names = list(res["engines"])
        return finish(out_dir, golden_path, args.pdf, res["rows"], res["summary"], res["engines"], names[0])

    if not args.pdf.exists():
        p.error(f"PDF not found: {args.pdf}")
    zooms = tuple(float(z) for z in args.zooms.split(",") if z.strip()) if args.zooms else None
    names = [n.strip() for n in args.engines.split(",") if n.strip()]

    doc = pymupdf.open(args.pdf)
    pages = parse_pages(args.pages, doc) if args.pages else None
    t0 = time.time()
    print(f"layout analysis of {args.pdf.name} ...")
    regions = equation_regions(doc, pages, lighten=not args.no_lighten)
    if args.limit:
        regions = regions[: args.limit]
    n_garbled = sum(1 for r in regions if r[4])
    print(f"{len(regions)} display equation(s) found ({time.time() - t0:.0f}s)"
          + (f", {n_garbled} with a garbled text layer" if n_garbled else ""))
    if not regions:
        return 1
    engines = build_engines(names, args)
    if not engines:
        print("no engine could be built")
        return 1
    rows = run(doc, regions, engines, zooms, out_dir, warmup=not args.no_warmup)
    summary = summarize(rows)
    engines_meta = {n: getattr(e, "name", n) for n, e in engines.items()}
    return finish(out_dir, golden_path, args.pdf, rows, summary, engines_meta, next(iter(engines)),
                  args.rewrite_golden)                # the skeleton from an engine that was built


if __name__ == "__main__":
    raise SystemExit(main())
