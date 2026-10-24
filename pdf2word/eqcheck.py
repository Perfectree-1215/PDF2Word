"""Equation check page: one self-contained HTML file per conversion that shows every display
equation side by side - the crop from the PDF, the LaTeX pdf2word wrote and that LaTeX rendered -
so the OCR can be checked by eye and corrected, a few equations per page.

The page is stateless: when the reader connects the .md file (File System Access API in Chromium
browsers: Edge, Chrome) it reads the note's CURRENT text, finds every equation by its block anchor
(`^eq-3`, `^eq-u01` - the converter writes one after each `$$` block) and shows what the note holds
now. An equation whose LaTeX differs from the OCR result is marked as already corrected, so the
review can be resumed any number of times. Saving replaces only that `$$` block (or inserts one when
the note had only the image). Other browsers get the patched note as a download. "Reviewed" marks
for unchanged equations live in the browser's localStorage. A Word document cannot be edited here.

Images are embedded as base64 PNG, KaTeX comes from cdnjs (offline: the raw LaTeX is shown)."""
from __future__ import annotations

import base64
import html
import io
import json
from pathlib import Path
from typing import Optional

from .obsidian import block_id

KATEX = "https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.11/katex.min"


def equation_block(latex: str, label: Optional[str]) -> str:
    """The exact text `_format_equation` writes for one display equation (without the ^eq anchor)."""
    body = latex + (f" \\tag{{{label}}}" if label else "")
    return f"$$\n{body}\n$$"


def image_data_uri(img) -> str:
    """PIL image -> data: URI (PNG), '' when there is none."""
    if img is None:
        return ""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def write_equation_check(path: Path, equations: list, *, title: str, pdf_name: str,
                         md_name: Optional[str] = None) -> Path:
    """`equations`: dicts with page, label, uid, anchored, latex, in_md, uncertain, unverified,
    confidence, image (PIL or None)."""
    items = []
    for i, e in enumerate(equations):
        label = e.get("label")
        latex = e.get("latex") or ""
        uid = e.get("uid") or label
        items.append({
            "i": i, "page": e.get("page"), "label": label, "uid": uid, "latex": latex,
            "anchor_id": block_id("eq", uid)[1:] if (uid and e.get("anchored")) else "",
            "block": equation_block(latex, label) if e.get("in_md") else "",
            "anchor": f"*Eq. ({label})*" if (label and not e.get("in_md")) else "",
            "uncertain": bool(e.get("uncertain")), "unverified": bool(e.get("unverified")),
            "confidence": e.get("confidence"), "image": image_data_uri(e.get("image")),
        })
    data = {"title": title, "pdf": pdf_name, "md": md_name, "equations": items}
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = (_TEMPLATE.replace("%%TITLE%%", html.escape(title))
            .replace("%%META%%", html.escape(f"{pdf_name} · 수식 {len(items)}개" + (f" · {md_name}" if md_name else " · Word 출력(보기만)")))
            .replace("%%KATEX%%", KATEX).replace("%%DATA%%", payload))
    path.write_text(page, encoding="utf-8")
    return path


_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>수식 검토 — %%TITLE%%</title>
<link rel="stylesheet" href="%%KATEX%%.css">
<script defer src="%%KATEX%%.js"></script>
<style>
  :root { --bg: #f6f7f9; --card: #fff; --ink: #1f2328; --muted: #6b7280; --line: #e5e7eb; --warn: #b45309; --ok: #15803d; --accent: #2563eb; --done: #ecfdf5; }
  @media (prefers-color-scheme: dark) { :root { --bg: #111418; --card: #1a1f26; --ink: #e6e8eb; --muted: #9aa3ad; --line: #2b3240; --done: #0f2a1f; } }
  body { margin: 0; padding: 16px; background: var(--bg); color: var(--ink); font: 14px/1.5 system-ui, "Malgun Gothic", sans-serif; }
  header, main, nav.pager { max-width: 1200px; margin: 0 auto; }
  header { margin-bottom: 12px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .muted { color: var(--muted); }
  .bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 10px 0; }
  button, select { font: inherit; padding: 6px 12px; border: 1px solid var(--line); border-radius: 6px; background: var(--card); color: var(--ink); cursor: pointer; }
  button.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
  button:disabled { opacity: .5; cursor: default; }
  nav.pager { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 10px auto; }
  nav.pager .pages { display: flex; gap: 4px; flex-wrap: wrap; }
  nav.pager .pages button.cur { background: var(--accent); color: #fff; border-color: var(--accent); }
  main { display: grid; gap: 12px; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 12px; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .card.done { background: var(--done); }
  @media (max-width: 800px) { .card { grid-template-columns: 1fr; } }
  .head { grid-column: 1 / -1; display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
  .head b { font-size: 15px; }
  .head label { margin-left: auto; font-size: 13px; color: var(--muted); }
  .badge { font-size: 12px; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--line); }
  .badge.warn { color: var(--warn); border-color: var(--warn); }
  .badge.ok { color: var(--ok); border-color: var(--ok); }
  .crop { background: #fff; border: 1px solid var(--line); border-radius: 6px; padding: 8px; overflow: auto; }
  .crop img { max-width: 100%; display: block; }
  .render { border: 1px solid var(--line); border-radius: 6px; padding: 8px; overflow: auto; min-height: 48px; }
  textarea { width: 100%; box-sizing: border-box; min-height: 72px; font: 13px/1.4 ui-monospace, Consolas, monospace; border: 1px solid var(--line); border-radius: 6px; padding: 6px; background: var(--card); color: var(--ink); }
  .row { display: flex; gap: 8px; align-items: center; margin-top: 6px; flex-wrap: wrap; }
  .orig { font: 12px/1.4 ui-monospace, Consolas, monospace; color: var(--muted); word-break: break-all; margin-top: 4px; }
  .status { font-size: 13px; }
  .status.ok { color: var(--ok); } .status.err { color: var(--warn); }
  .katex-display { margin: 4px 0; }
</style>
</head>
<body>
<header>
  <h1>수식 검토</h1>
  <div class="muted">%%META%%</div>
  <div class="bar">
    <button id="connect" class="primary">MD 파일 연결 (현재 내용 읽기·수정 저장)</button>
    <span id="file" class="muted">연결 안 됨 — 연결 전에는 변환 직후의 OCR 결과를 보여 줍니다</span>
    <button id="saveall" disabled>수정한 항목 모두 저장</button>
    <span id="gstatus" class="status"></span>
  </div>
  <div class="bar muted" id="counts"></div>
  <p class="muted">왼쪽은 PDF에서 잘라낸 원본, 오른쪽은 문서에 들어간 LaTeX와 그 렌더링입니다. LaTeX를 고치고 <b>저장</b>(Ctrl+Enter)을 누르면
  Edge·Chrome에서는 연결한 MD 파일의 해당 <code>$$</code> 블록만 제자리에서 바꿉니다. 다른 브라우저에서는 파일을 고르면 수정본을 내려받습니다.
  다시 열어 MD를 연결하면 그동안 고친 식은 <b>수정 반영됨</b>으로, 수정 없이 확인한 식은 <b>검토 완료</b> 체크로 이어서 볼 수 있습니다.
  Word(.docx)는 여기서 고칠 수 없습니다. 렌더링에는 인터넷(KaTeX)이 필요합니다.</p>
</header>
<nav class="pager" id="pager-top"></nav>
<main id="list"></main>
<nav class="pager" id="pager-bottom"></nav>
<input type="file" id="fallback" accept=".md,text/markdown" style="display:none">
<script type="application/json" id="data">%%DATA%%</script>
<script>
(function () {
  const data = JSON.parse(document.getElementById('data').textContent);
  const items = data.equations;
  items.forEach(it => { it.original = it.latex; it.current = it.latex; it.pending = null; it.exists = null; });
  const list = document.getElementById('list');
  const fileLabel = document.getElementById('file');
  const gstatus = document.getElementById('gstatus');
  const saveAllBtn = document.getElementById('saveall');
  const LS_KEY = 'pdf2word-eqcheck:' + (data.md || data.pdf);
  let handle = null, text = null, crlf = false, fallbackName = null;
  let pageSize = 10, pageNo = 1;

  const block = (latex, label) => '$$\\n' + latex + (label ? ' \\\\tag{' + label + '}' : '') + '\\n$$';
  const esc = s => String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  const latexOf = (body, label) => { const t = ' \\\\tag{' + label + '}'; return (label && body.endsWith(t)) ? body.slice(0, -t.length) : body; };

  // ---- reviewed marks (browser storage) ----
  let reviewed = {};
  try { reviewed = JSON.parse(localStorage.getItem(LS_KEY) || '{}'); } catch (e) { reviewed = {}; }
  function saveReviewed() { try { localStorage.setItem(LS_KEY, JSON.stringify(reviewed)); } catch (e) {} }

  // ---- locating an equation in the note text ----
  function anchorPos(it) {
    if (!it.anchor_id) return -1;
    const re = new RegExp('(^|\\\\s)\\\\^' + it.anchor_id.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&') + '(?=\\\\s|$)', 'm');
    const m = re.exec(text);
    return m ? m.index + m[1].length : -1;
  }
  function locate(it) {
    // the current $$ block of this equation: {start, end, body}; {insertAt} when the note has no block yet; null when lost
    const a = anchorPos(it);
    if (a >= 0) {
      const ls = text.lastIndexOf('\\n', a - 1) + 1;              // start of the anchor's line
      if (ls === a && ls >= 4 && text.slice(ls - 3, ls - 1) === '$$' && (ls - 4 < 0 || text[ls - 4] === '\\n')) {
        const closeStart = ls - 3;
        const openStart = text.lastIndexOf('$$\\n', closeStart - 1);
        if (openStart >= 0) return {start: openStart, end: closeStart + 2, body: text.slice(openStart + 3, closeStart - 1)};
      }
      return {insertAt: ls, inlineCaption: text.slice(ls, a).startsWith('*Eq. (')};
    }
    if (it.block) { const p = text.indexOf(it.block); if (p >= 0) return {start: p, end: p + it.block.length, body: it.block.slice(3, -3)}; }
    if (it.anchor) { const p = text.indexOf(it.anchor); if (p >= 0) { const eol = text.indexOf('\\n', p); return {insertAt: eol < 0 ? text.length : eol + 1}; } }
    return null;
  }
  function sync() {
    items.forEach(it => {
      const loc = locate(it);
      if (loc && loc.body !== undefined) { it.current = latexOf(loc.body, it.label); it.exists = true; }
      else it.exists = loc ? false : null;                          // false = can insert, null = lost
    });
  }

  // ---- rendering ----
  function render(el, tex) {
    if (!tex) { el.innerHTML = '<span class="muted">(LaTeX 없음)</span>'; return; }
    if (window.katex) { try { katex.render(tex, el, {displayMode: true, throwOnError: false}); return; } catch (e) {} }
    el.textContent = tex;
  }
  function badges(it) {
    let b = '';
    if (it.uncertain) b += ' <span class="badge warn">⚠ OCR 신뢰도 낮음' + (it.confidence != null ? ' ' + Math.round(it.confidence * 100) + '%' : '') + '</span>';
    if (it.unverified) b += ' <span class="badge">텍스트 레이어로 검증 안 됨</span>';
    if (text !== null && it.current !== it.original) b += ' <span class="badge ok">✔ 수정 반영됨</span>';
    if (text !== null && it.exists === false) b += ' <span class="badge">문서에 LaTeX 없음 · 저장하면 추가</span>';
    if (text !== null && it.exists === null) b += ' <span class="badge warn">문서에서 못 찾음</span>';
    if (text === null && !it.block && !it.anchor && !it.anchor_id) b += ' <span class="badge">문서에 LaTeX 없음(이미지만)</span>';
    return b;
  }
  function card(it) {
    const div = document.createElement('div');
    const corrected = text !== null && it.current !== it.original;
    div.className = 'card' + ((corrected || reviewed[it.uid]) ? ' done' : '');
    const where = (it.page ? 'p. ' + it.page : '') + (it.label ? ' · Eq. (' + it.label + ')' : ' · 번호 없는 식 ' + (it.uid || ''));
    const value = it.pending !== null ? it.pending : it.current;
    div.innerHTML =
      '<div class="head"><b>' + esc(where) + '</b>' + badges(it) +
      '<label><input type="checkbox" id="c' + it.i + '"' + (reviewed[it.uid] ? ' checked' : '') + '> 검토 완료</label></div>' +
      '<div class="crop">' + (it.image ? '<img alt="PDF crop" src="' + it.image + '">' : '<span class="muted">(크롭 없음)</span>') + '</div>' +
      '<div><div class="render" id="r' + it.i + '"></div>' +
      '<textarea id="t' + it.i + '" spellcheck="false">' + esc(value) + '</textarea>' +
      (corrected ? '<div class="orig">원래 OCR: ' + esc(it.original) + ' <button id="o' + it.i + '" style="padding:1px 6px;font-size:12px">되돌리기</button></div>' : '') +
      '<div class="row"><button id="s' + it.i + '" disabled>저장</button><span class="status" id="st' + it.i + '"></span></div></div>';
    list.appendChild(div);
    const ta = div.querySelector('#t' + it.i), rd = div.querySelector('#r' + it.i), btn = div.querySelector('#s' + it.i);
    render(rd, value);
    const dirty = () => (it.pending !== null && it.pending !== it.current);
    ta.addEventListener('input', () => { it.pending = ta.value.trim(); render(rd, it.pending); btn.disabled = !(dirty() && text !== null); refreshAll(); });
    ta.addEventListener('keydown', e => { if (e.ctrlKey && e.key === 'Enter' && !btn.disabled) btn.click(); });
    btn.addEventListener('click', () => save(it));
    btn.disabled = !(dirty() && text !== null);
    div.querySelector('#c' + it.i).addEventListener('change', e => { if (e.target.checked) reviewed[it.uid] = true; else delete reviewed[it.uid]; saveReviewed(); div.classList.toggle('done', e.target.checked || corrected); counts(); });
    const ob = div.querySelector('#o' + it.i);
    if (ob) ob.addEventListener('click', () => { ta.value = it.original; ta.dispatchEvent(new Event('input')); });
    it.el = {ta, btn, st: div.querySelector('#st' + it.i), rd};
  }
  function pageCount() { return pageSize >= items.length ? 1 : Math.ceil(items.length / pageSize); }
  function renderPage() {
    pageNo = Math.min(Math.max(1, pageNo), pageCount());
    list.innerHTML = '';
    items.forEach(it => { it.el = null; });
    const start = pageSize >= items.length ? 0 : (pageNo - 1) * pageSize;
    const end = pageSize >= items.length ? items.length : Math.min(items.length, start + pageSize);
    items.slice(start, end).forEach(card);
    ['pager-top', 'pager-bottom'].forEach(id => pager(document.getElementById(id), start, end));
    counts();
    location.hash = 'p=' + pageNo + '&n=' + (pageSize >= items.length ? 'all' : pageSize);
  }
  function pager(nav, start, end) {
    const n = pageCount();
    let pages = '';
    for (let p = 1; p <= n; p++) pages += '<button data-p="' + p + '"' + (p === pageNo ? ' class="cur"' : '') + '>' + p + '</button>';
    nav.innerHTML = '<span>한 쪽에 </span><select class="size"><option value="5">5개</option><option value="10">10개</option><option value="20">20개</option><option value="all">전체</option></select>' +
      '<button class="prev"' + (pageNo <= 1 ? ' disabled' : '') + '>◀ 이전</button><div class="pages">' + pages + '</div>' +
      '<button class="next"' + (pageNo >= n ? ' disabled' : '') + '>다음 ▶</button><span class="muted">' + (start + 1) + '–' + end + ' / ' + items.length + '</span>';
    nav.querySelector('.size').value = pageSize >= items.length ? 'all' : String(pageSize);
    nav.querySelector('.size').addEventListener('change', e => { pageSize = e.target.value === 'all' ? items.length : parseInt(e.target.value, 10); pageNo = 1; renderPage(); });
    nav.querySelector('.prev').addEventListener('click', () => { pageNo--; renderPage(); });
    nav.querySelector('.next').addEventListener('click', () => { pageNo++; renderPage(); });
    nav.querySelectorAll('.pages button').forEach(b => b.addEventListener('click', () => { pageNo = parseInt(b.dataset.p, 10); renderPage(); }));
  }
  function counts() {
    const corrected = text !== null ? items.filter(it => it.current !== it.original).length : 0;
    const checked = items.filter(it => reviewed[it.uid]).length;
    const warn = items.filter(it => it.uncertain || it.unverified).length;
    document.getElementById('counts').textContent = '총 ' + items.length + '개 · 수정 반영 ' + corrected + ' · 검토 완료 ' + checked + ' · 경고 ' + warn;
  }
  function refreshAll() {
    const dirty = items.filter(it => it.pending !== null && it.pending !== it.current).length;
    saveAllBtn.disabled = !(dirty && text !== null);
  }
  function setStatus(el, msg, ok) { el.textContent = msg; el.className = 'status ' + (ok ? 'ok' : 'err'); }

  // ---- saving ----
  function apply(it, newLatex) {
    const loc = locate(it);
    if (!loc) return false;
    const nb = block(newLatex, it.label);
    if (loc.body !== undefined) {
      text = text.slice(0, loc.start) + nb + text.slice(loc.end);
    } else {
      let at = loc.insertAt;
      if (loc.inlineCaption) {                     // "*Eq. (n)* ^eq-n" -> block, then the bare anchor line
        const eol = text.indexOf('\\n', at); const lineEnd = eol < 0 ? text.length : eol;
        text = text.slice(0, at) + nb + '\\n^' + it.anchor_id + text.slice(lineEnd);
      } else {
        text = text.slice(0, at) + nb + '\\n' + text.slice(at);
      }
    }
    it.current = newLatex; it.pending = null; it.exists = true;
    return true;
  }
  async function writeBack() {
    const out = crlf ? text.replace(/\\n/g, '\\r\\n') : text;
    if (handle) {
      const w = await handle.createWritable(); await w.write(out); await w.close();
      return '저장됨 → ' + handle.name;
    }
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([out], {type: 'text/markdown'}));
    a.download = fallbackName || 'edited.md';
    a.click();
    return '수정본을 내려받았습니다 (' + a.download + ') — 원본 자리에 덮어쓰세요';
  }
  async function save(it) {
    if (text === null) { setStatus(it.el.st, '먼저 MD 파일을 연결하세요', false); return; }
    const v = it.el.ta.value.trim();
    if (!apply(it, v)) { setStatus(it.el.st, '문서에서 이 수식을 찾지 못했습니다 (앵커가 지워졌나요?)', false); return; }
    try { const msg = await writeBack(); renderPage(); setStatus(gstatus, msg, true); }
    catch (e) { setStatus(gstatus, '저장 실패: ' + e.message, false); }
  }
  async function saveAll() {
    let n = 0, miss = 0;
    for (const it of items) if (it.pending !== null && it.pending !== it.current) { if (apply(it, it.pending)) n++; else miss++; }
    try { const msg = await writeBack(); renderPage(); setStatus(gstatus, n + '개 ' + msg + (miss ? ' · 못 찾은 항목 ' + miss : ''), true); }
    catch (e) { setStatus(gstatus, '저장 실패: ' + e.message, false); }
  }

  // ---- connecting the note ----
  function loadText(raw, name) {
    crlf = raw.includes('\\r\\n');
    text = crlf ? raw.replace(/\\r\\n/g, '\\n') : raw;
    fileLabel.textContent = '연결됨: ' + name + (handle ? ' (제자리에 저장)' : ' (수정본 내려받기)');
    sync(); renderPage(); refreshAll();
  }
  document.getElementById('connect').addEventListener('click', async () => {
    if (window.showOpenFilePicker) {
      try {
        [handle] = await showOpenFilePicker({types: [{description: 'Markdown', accept: {'text/markdown': ['.md']}}]});
        loadText(await (await handle.getFile()).text(), handle.name);
      } catch (e) { if (e.name !== 'AbortError') setStatus(gstatus, '연결 실패: ' + e.message, false); }
    } else {
      document.getElementById('fallback').click();
    }
  });
  document.getElementById('fallback').addEventListener('change', e => {
    const f = e.target.files[0]; if (!f) return;
    fallbackName = f.name; handle = null;
    const r = new FileReader(); r.onload = () => loadText(r.result, f.name); r.readAsText(f);
  });
  saveAllBtn.addEventListener('click', saveAll);

  // ---- start ----
  const h = new URLSearchParams(location.hash.slice(1));
  if (h.get('n')) pageSize = h.get('n') === 'all' ? items.length : (parseInt(h.get('n'), 10) || 10);
  if (h.get('p')) pageNo = parseInt(h.get('p'), 10) || 1;
  renderPage();
  window.addEventListener('load', () => items.forEach(it => { if (it.el) render(it.el.rd, it.pending !== null ? it.pending : it.current); }));
  if (!data.md) { document.getElementById('connect').disabled = true; fileLabel.textContent = 'Word 출력: 보기 전용'; }
})();
</script>
</body>
</html>
"""
