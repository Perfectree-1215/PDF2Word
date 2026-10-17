#!/usr/bin/env python
"""pdf2word launcher: a small GUI, or the full command line.

    python main_gui.py                          -> opens the GUI
    python main_gui.py paper.pdf -f md -v       -> same as the `pdf2word` command (every option)
    python -m main_gui paper.pdf --help         -> module form (no ".py" after -m)

Run it with the project's virtual environment (.venv\\Scripts\\python.exe) or through main_gui.bat.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import sys
import threading
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

APP_TITLE = "pdf2word"
SETTINGS_NAME = "gui.json"


def app_version() -> str:
    """'v1.0' from the package (falls back gracefully when the package is missing)."""
    try:
        from pdf2word import short_version
        return short_version()
    except Exception:
        return ""

FORMATS = [("📝 Word (.docx)", "docx"), ("🔗 Obsidian Markdown", "md"), ("둘 다", "both")]
ENGINES = [("rapid  (로컬, 무료)", "rapid"), ("claude  (API, 정확)", "claude"), ("none  (OCR 없이 이미지만)", "none")]
MATH_MODES = [("이미지 + OCR 결과", "both"), ("OCR 결과만", "latex"), ("이미지만", "image")]


# ----------------------------------------------------------------------------- command line

def run_cli(argv: list) -> int:
    """Delegate to pdf2word's command line (all options available)."""
    from pdf2word.cli import main as cli_main
    return cli_main(argv)


# ----------------------------------------------------------------------------- helpers

def _settings_path() -> Path:
    try:
        from pdf2word.utils import cache_dir
        return cache_dir() / SETTINGS_NAME
    except Exception:
        return HERE / SETTINGS_NAME


class _QueueLogHandler(logging.Handler):
    def __init__(self, q: "queue.Queue"):
        super().__init__()
        self.q = q

    def emit(self, record):
        try:
            self.q.put(("log", self.format(record)))
        except Exception:
            pass


class _StreamToQueue:
    """Catches print()/tqdm output (model download progress) while a conversion runs."""

    def __init__(self, q: "queue.Queue"):
        self.q = q
        self.buf = ""

    def write(self, s):
        if not s:
            return
        self.buf += s.replace("\r", "\n")
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            if line.strip():
                self.q.put(("log", line.rstrip()))

    def flush(self):
        pass

    def isatty(self):
        return False


# ----------------------------------------------------------------------------- GUI

def launch_gui() -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except Exception as exc:  # pragma: no cover
        print("tkinter is not available:", exc)
        return 2

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    # --- palette ---------------------------------------------------------------
    BG, CARD, TEXT, MUTED = "#FFF7F0", "#FFFFFF", "#4A4A4A", "#8C8C8C"
    PINK, PINK_DARK, MINT, BLUE, LAVENDER = "#FF9AA2", "#F27D86", "#B5EAD7", "#C7CEEA", "#E2D6F5"
    FONT = ("Malgun Gothic", 10) if sys.platform == "win32" else ("Helvetica", 11)
    FONT_B = (FONT[0], FONT[1], "bold")
    FONT_TITLE = (FONT[0], 18, "bold")
    FONT_MONO = ("Consolas", 9) if sys.platform == "win32" else ("Menlo", 10)

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.version = app_version()
            self.title(f"{APP_TITLE} {self.version}  ·  논문 PDF → Word / Obsidian".replace("  ·", " ·"))
            self.configure(bg=BG)
            self.minsize(700, 640)
            self.q: "queue.Queue" = queue.Queue()
            self.worker: threading.Thread | None = None
            self.stop_flag = threading.Event()
            self.last_out_dir: Path | None = None
            self.files: list = []
            self._style()
            self._build()
            self._load_settings()
            self.protocol("WM_DELETE_WINDOW", self._on_close)
            self.after(100, self._poll)
            if os.environ.get("PDF2WORD_GUI_SMOKE"):
                self.after(1500, self._smoke)

        # ---- look ----------------------------------------------------------------
        def _style(self):
            st = ttk.Style(self)
            try:
                st.theme_use("clam")
            except tk.TclError:
                pass
            st.configure(".", background=BG, foreground=TEXT, font=FONT)
            st.configure("Card.TFrame", background=CARD)
            st.configure("Card.TLabel", background=CARD, foreground=TEXT)
            st.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=(FONT[0], 9))
            st.configure("Head.TLabel", background=BG, foreground=TEXT, font=FONT_TITLE)
            st.configure("Sub.TLabel", background=BG, foreground=MUTED)
            st.configure("Sec.TLabel", background=CARD, foreground=PINK_DARK, font=FONT_B)
            st.configure("TButton", background=LAVENDER, foreground=TEXT, borderwidth=0, padding=(10, 5), font=FONT)
            st.map("TButton", background=[("active", BLUE), ("disabled", "#EDEDED")], foreground=[("disabled", "#B0B0B0")])
            st.configure("Accent.TButton", background=PINK, foreground="white", font=FONT_B, padding=(16, 7))
            st.map("Accent.TButton", background=[("active", PINK_DARK), ("disabled", "#F3C9CD")])
            st.configure("TRadiobutton", background=CARD, foreground=TEXT, font=FONT)
            st.map("TRadiobutton", background=[("active", CARD)])
            st.configure("TCheckbutton", background=CARD, foreground=TEXT, font=FONT)
            st.map("TCheckbutton", background=[("active", CARD)])
            st.configure("TCombobox", fieldbackground="white", padding=3)
            st.configure("TEntry", fieldbackground="white", padding=3)
            st.configure("Cute.Horizontal.TProgressbar", troughcolor="#F3EDE7", background=MINT, borderwidth=0, thickness=10)

        def _card(self, parent, title):
            card = ttk.Frame(parent, style="Card.TFrame", padding=(12, 8))
            card.pack(fill="x", padx=14, pady=(0, 8))
            ttk.Label(card, text=title, style="Sec.TLabel").grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 4))
            return card

        # ---- widgets --------------------------------------------------------------
        def _build(self):
            head = ttk.Frame(self, padding=(16, 12, 16, 6))
            head.pack(fill="x")
            ttk.Label(head, text="🐣 pdf2word", style="Head.TLabel").pack(side="left")
            ttk.Label(head, text=f" {self.version}", style="Sub.TLabel", font=(FONT[0], 11, "bold")).pack(side="left", pady=(10, 0))
            ttk.Label(head, text="   논문 PDF를 Word 문서나 Obsidian 노트로", style="Sub.TLabel").pack(side="left", pady=(8, 0))

            # files
            card = self._card(self, "📄 PDF 파일")
            ttk.Button(card, text="파일 추가", command=self._add_files).grid(row=1, column=0, padx=(0, 6))
            ttk.Button(card, text="폴더 추가", command=self._add_folder).grid(row=1, column=1, padx=(0, 6))
            ttk.Button(card, text="비우기", command=self._clear_files).grid(row=1, column=2)
            self.count_var = tk.StringVar(value="선택된 파일 없음")
            ttk.Label(card, textvariable=self.count_var, style="Muted.TLabel").grid(row=1, column=3, columnspan=3, sticky="e")
            box = ttk.Frame(card, style="Card.TFrame")
            box.grid(row=2, column=0, columnspan=6, sticky="nsew", pady=(6, 0))
            card.columnconfigure(5, weight=1)
            self.listbox = tk.Listbox(box, height=5, font=FONT, bd=0, highlightthickness=1, highlightbackground="#EFE6DD",
                                      selectbackground=BLUE, selectforeground=TEXT, activestyle="none")
            sb = ttk.Scrollbar(box, orient="vertical", command=self.listbox.yview)
            self.listbox.configure(yscrollcommand=sb.set)
            self.listbox.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            self.listbox.bind("<Delete>", lambda e: self._remove_selected())

            # output + format
            card = self._card(self, "📁 저장 위치와 형식")
            self.beside_var = tk.BooleanVar(value=True)
            ttk.Checkbutton(card, text="PDF 옆에 저장", variable=self.beside_var, command=self._toggle_outdir).grid(row=1, column=0, sticky="w")
            self.outdir_btn = ttk.Button(card, text="폴더 선택…", command=self._choose_outdir)
            self.outdir_btn.grid(row=1, column=1, padx=(10, 6))
            self.outdir_var = tk.StringVar(value="")
            ttk.Label(card, textvariable=self.outdir_var, style="Muted.TLabel").grid(row=1, column=2, columnspan=4, sticky="w")
            self.format_var = tk.StringVar(value="docx")
            row = ttk.Frame(card, style="Card.TFrame")
            row.grid(row=2, column=0, columnspan=6, sticky="w", pady=(6, 0))
            for text, value in FORMATS:
                ttk.Radiobutton(row, text=text, value=value, variable=self.format_var).pack(side="left", padx=(0, 14))

            # equations
            card = self._card(self, "∑ 수식")
            ttk.Label(card, text="OCR 엔진", style="Card.TLabel").grid(row=1, column=0, sticky="w")
            self.engine_var = tk.StringVar(value=ENGINES[0][0])
            ttk.Combobox(card, textvariable=self.engine_var, values=[e[0] for e in ENGINES], state="readonly", width=26).grid(row=1, column=1, padx=(6, 18), sticky="w")
            ttk.Label(card, text="표시", style="Card.TLabel").grid(row=1, column=2, sticky="w")
            self.mode_var = tk.StringVar(value=MATH_MODES[0][0])
            ttk.Combobox(card, textvariable=self.mode_var, values=[m[0] for m in MATH_MODES], state="readonly", width=18).grid(row=1, column=3, padx=(6, 0), sticky="w")

            # options
            card = self._card(self, "⚙ 기타 옵션")
            self.offline_var = tk.BooleanVar(value=False)
            ttk.Checkbutton(card, text="온라인 서지 조회 안 함 (--offline)", variable=self.offline_var).grid(row=1, column=0, columnspan=2, sticky="w")
            ttk.Label(card, text="페이지", style="Card.TLabel").grid(row=1, column=2, sticky="e", padx=(18, 4))
            self.pages_var = tk.StringVar(value="")
            ttk.Entry(card, textvariable=self.pages_var, width=10).grid(row=1, column=3, sticky="w")
            ttk.Label(card, text="예: 1-5,8", style="Muted.TLabel").grid(row=1, column=4, sticky="w", padx=(6, 0))
            ttk.Label(card, text="추가 옵션", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=(6, 0))
            self.extra_var = tk.StringVar(value="")
            ttk.Entry(card, textvariable=self.extra_var).grid(row=2, column=1, columnspan=4, sticky="ew", pady=(6, 0))
            ttk.Label(card, text="명령줄 옵션 그대로 (예: --author Kim --year 2024 --citations footnotes -v)", style="Muted.TLabel").grid(row=3, column=1, columnspan=4, sticky="w")
            card.columnconfigure(4, weight=1)

            # actions
            act = ttk.Frame(self, padding=(14, 2, 14, 4))
            act.pack(fill="x")
            self.start_btn = ttk.Button(act, text="✨ 변환 시작", style="Accent.TButton", command=self._start)
            self.start_btn.pack(side="left")
            self.stop_btn = ttk.Button(act, text="⏹ 중지", command=self._stop, state="disabled")
            self.stop_btn.pack(side="left", padx=(8, 0))
            self.open_btn = ttk.Button(act, text="📂 결과 폴더 열기", command=self._open_outdir, state="disabled")
            self.open_btn.pack(side="right")
            self.progress = ttk.Progressbar(self, style="Cute.Horizontal.TProgressbar", mode="determinate", value=0)
            self.progress.pack(fill="x", padx=14, pady=(2, 6))

            # log
            logf = ttk.Frame(self, style="Card.TFrame", padding=(8, 6))
            logf.pack(fill="both", expand=True, padx=14, pady=(0, 6))
            self.log = tk.Text(logf, height=9, font=FONT_MONO, bg="#FFFDFB", fg=TEXT, bd=0, wrap="word", state="disabled",
                               highlightthickness=1, highlightbackground="#EFE6DD")
            lsb = ttk.Scrollbar(logf, orient="vertical", command=self.log.yview)
            self.log.configure(yscrollcommand=lsb.set)
            self.log.pack(side="left", fill="both", expand=True)
            lsb.pack(side="right", fill="y")
            self.log.tag_configure("ok", foreground="#2E8B57")
            self.log.tag_configure("err", foreground=PINK_DARK)

            self.status_var = tk.StringVar(value="준비됨 · PDF를 추가하고 변환 시작을 누르세요")
            ttk.Label(self, textvariable=self.status_var, style="Sub.TLabel", padding=(16, 0, 16, 10)).pack(fill="x")

        # ---- file list --------------------------------------------------------------
        def _add_files(self):
            paths = filedialog.askopenfilenames(title="PDF 선택", filetypes=[("PDF", "*.pdf"), ("모든 파일", "*.*")])
            self._add_paths(paths)

        def _add_folder(self):
            folder = filedialog.askdirectory(title="PDF가 있는 폴더")
            if folder:
                self._add_paths(sorted(str(p) for p in Path(folder).glob("*.pdf")))

        def _add_paths(self, paths):
            for p in paths:
                p = str(Path(p))
                if p.lower().endswith(".pdf") and p not in self.files:
                    self.files.append(p)
                    self.listbox.insert("end", p)
            self._update_count()

        def _remove_selected(self):
            for idx in reversed(self.listbox.curselection()):
                self.listbox.delete(idx)
                del self.files[idx]
            self._update_count()

        def _clear_files(self):
            self.files.clear()
            self.listbox.delete(0, "end")
            self._update_count()

        def _update_count(self):
            n = len(self.files)
            self.count_var.set(f"{n}개 파일" if n else "선택된 파일 없음")

        # ---- output folder -----------------------------------------------------------
        def _toggle_outdir(self):
            self.outdir_btn.configure(state="disabled" if self.beside_var.get() else "normal")

        def _choose_outdir(self):
            folder = filedialog.askdirectory(title="저장 폴더 (Obsidian vault 안 폴더 등)")
            if folder:
                self.outdir_var.set(folder)

        def _open_outdir(self):
            target = self.last_out_dir
            if target and Path(target).exists():
                try:
                    os.startfile(str(target))  # type: ignore[attr-defined]
                except Exception:
                    messagebox.showinfo(APP_TITLE, str(target))

        # ---- conversion ------------------------------------------------------------------
        def _argv(self) -> list:
            import shlex
            argv = list(self.files)
            argv += ["-f", self.format_var.get()]
            argv += ["--math-engine", dict(ENGINES)[self.engine_var.get()]]
            argv += ["--math-mode", dict(MATH_MODES)[self.mode_var.get()]]
            if not self.beside_var.get() and self.outdir_var.get().strip():
                argv += ["-o", self.outdir_var.get().strip()]
            if self.offline_var.get():
                argv.append("--offline")
            if self.pages_var.get().strip():
                argv += ["--pages", self.pages_var.get().strip()]
            extra = self.extra_var.get().strip()
            if extra:
                argv += shlex.split(extra, posix=False)
            return argv

        def _start(self):
            if self.worker and self.worker.is_alive():
                return
            if not self.files:
                messagebox.showinfo(APP_TITLE, "먼저 PDF 파일을 추가하세요.")
                return
            argv = self._argv()
            try:
                from pdf2word.cli import build_parser, options_from_args
                args = build_parser().parse_args(argv)
                options = options_from_args(args)
            except SystemExit:
                messagebox.showerror(APP_TITLE, "추가 옵션을 해석할 수 없습니다. 명령줄 옵션 이름을 확인하세요.\n\n"
                                     + " ".join(argv))
                return
            except Exception as exc:
                messagebox.showerror(APP_TITLE, f"옵션 오류: {exc}")
                return
            self._save_settings()
            self._set_running(True)
            self._log_clear()
            self._log(f"$ pdf2word {' '.join(argv)}", "ok")
            self.stop_flag.clear()
            self.worker = threading.Thread(target=self._work, args=(list(self.files), options, args.verbose), daemon=True)
            self.worker.start()

        def _work(self, files: list, options, verbose: bool):
            logger = logging.getLogger("pdf2word")
            handler = _QueueLogHandler(self.q)
            handler.setFormatter(logging.Formatter("%(message)s"))
            old_level = logger.level
            logger.setLevel(logging.DEBUG if verbose else logging.INFO)
            logger.addHandler(handler)
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = _StreamToQueue(self.q)
            ok = failed = 0
            try:
                from pdf2word.converter import Converter
                conv = Converter(options)
                for pdf in files:
                    if self.stop_flag.is_set():
                        self.q.put(("log", "중지했습니다."))
                        break
                    try:
                        result = conv.convert(pdf)
                        ok += 1
                        self.q.put(("result", result))
                    except Exception as exc:
                        failed += 1
                        self.q.put(("error", f"실패: {Path(pdf).name}: {exc}"))
                        if verbose:
                            self.q.put(("log", traceback.format_exc()))
            except Exception as exc:
                self.q.put(("error", f"오류: {exc}"))
                self.q.put(("log", traceback.format_exc()))
            finally:
                sys.stdout, sys.stderr = old_out, old_err
                logger.removeHandler(handler)
                logger.setLevel(old_level)
                self.q.put(("finished", (ok, failed)))

        def _stop(self):
            self.stop_flag.set()
            self.status_var.set("현재 파일이 끝나면 중지합니다 …")

        def _set_running(self, running: bool):
            self.start_btn.configure(state="disabled" if running else "normal")
            self.stop_btn.configure(state="normal" if running else "disabled")
            if running:
                self.progress.configure(mode="indeterminate")
                self.progress.start(12)
                self.status_var.set("변환 중 … (첫 실행은 수식 OCR 모델 171 MB를 내려받습니다)")
            else:
                self.progress.stop()
                self.progress.configure(mode="determinate", value=0)

        def _poll(self):
            try:
                while True:
                    kind, payload = self.q.get_nowait()
                    if kind == "log":
                        self._log(payload)
                    elif kind == "error":
                        self._log(payload, "err")
                    elif kind == "result":
                        r = payload
                        out = r.docx_path or r.md_path
                        if out:
                            self.last_out_dir = Path(out).parent
                            self._log(f"완료: {Path(out).name}", "ok")
                    elif kind == "finished":
                        ok, failed = payload
                        self._set_running(False)
                        self.status_var.set(f"끝 · 성공 {ok} · 실패 {failed}")
                        if self.last_out_dir:
                            self.open_btn.configure(state="normal")
                        self.bell()
            except queue.Empty:
                pass
            self.after(100, self._poll)

        # ---- log ------------------------------------------------------------------------
        def _log(self, text: str, tag: str | None = None):
            self.log.configure(state="normal")
            self.log.insert("end", text + "\n", tag or ())
            self.log.see("end")
            self.log.configure(state="disabled")

        def _log_clear(self):
            self.log.configure(state="normal")
            self.log.delete("1.0", "end")
            self.log.configure(state="disabled")

        # ---- settings -----------------------------------------------------------------------
        def _load_settings(self):
            try:
                data = json.loads(_settings_path().read_text(encoding="utf-8"))
            except Exception:
                data = {}
            self.format_var.set(data.get("format", "docx"))
            self.engine_var.set(next((t for t, v in ENGINES if v == data.get("engine", "rapid")), ENGINES[0][0]))
            self.mode_var.set(next((t for t, v in MATH_MODES if v == data.get("math_mode", "both")), MATH_MODES[0][0]))
            self.beside_var.set(data.get("beside", True))
            self.outdir_var.set(data.get("out_dir", ""))
            self.offline_var.set(data.get("offline", False))
            self.extra_var.set(data.get("extra", ""))
            self._toggle_outdir()

        def _save_settings(self):
            if os.environ.get("PDF2WORD_GUI_SMOKE"):       # automated runs must not change the user's settings
                return
            data = {
                "format": self.format_var.get(),
                "engine": dict(ENGINES)[self.engine_var.get()],
                "math_mode": dict(MATH_MODES)[self.mode_var.get()],
                "beside": self.beside_var.get(),
                "out_dir": self.outdir_var.get(),
                "offline": self.offline_var.get(),
                "extra": self.extra_var.get(),
            }
            try:
                _settings_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

        def _on_close(self):
            if self.worker and self.worker.is_alive():
                if not messagebox.askyesno(APP_TITLE, "변환이 진행 중입니다. 정말 닫을까요?"):
                    return
            self._save_settings()
            self.destroy()

        # ---- automated smoke test ------------------------------------------------------------
        # PDF2WORD_GUI_SMOKE=<png path>  : screenshot the window, then quit.
        # PDF2WORD_GUI_SMOKE_PDF=<pdf>    : additionally convert this file (Markdown, pages 4-5,
        #                                       offline) through the GUI's own code path first.
        def _smoke(self):
            pdf = os.environ.get("PDF2WORD_GUI_SMOKE_PDF", "")
            if pdf and not getattr(self, "_smoke_started", False):
                self._smoke_started = True
                self._add_paths([pdf])
                self.format_var.set("md")
                self.pages_var.set("4-5")
                self.offline_var.set(True)
                self.beside_var.set(False)
                self.outdir_var.set(os.environ.get("PDF2WORD_GUI_SMOKE_OUT", str(Path(pdf).parent)))
                self._start()
            if self.worker and self.worker.is_alive():
                self.after(500, self._smoke)
                return
            target = os.environ.get("PDF2WORD_GUI_SMOKE", "")
            try:
                self.update_idletasks()
                self.update()
                if target.lower().endswith(".png"):
                    from PIL import ImageGrab
                    x, y = self.winfo_rootx(), self.winfo_rooty()
                    w, h = self.winfo_width(), self.winfo_height()
                    ImageGrab.grab(bbox=(x, y, x + w, y + h)).save(target)
            except Exception as exc:
                print("smoke screenshot failed:", exc)
            self.after(300, self.destroy)

    try:
        import pdf2word  # noqa: F401  (fails outside the project venv)
    except Exception as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_TITLE, "pdf2word 패키지를 불러올 수 없습니다.\n\n"
                             "프로젝트의 가상환경으로 실행하세요:\n  .venv\\Scripts\\python.exe main_gui.py\n\n" + str(exc))
        return 2
    app = App()
    app.mainloop()
    return 0


# ----------------------------------------------------------------------------- entry point

def main(argv: list | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        return run_cli(argv)
    return launch_gui()


if __name__ == "__main__":
    sys.exit(main())
