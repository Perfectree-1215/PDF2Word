# 개발 안내 (새 PC에서 이어서 개발하기)

사용자용 설명은 [README.md](../README.md)에, 변경 내역은 [CHANGELOG.md](../CHANGELOG.md)에 있습니다.
이 문서는 **다른 PC에서 저장소를 받아 개발을 이어가는 사람**(과 Claude Code)을 위한 것입니다.
저장소에는 소스, 테스트, 문서, `uv.lock`, `.python-version`, 실행 스크립트가 모두 들어 있고,
논문 PDF와 변환 결과·가상환경·PC별 설정만 빠져 있습니다([.gitignore](../.gitignore) 참고).

## 1. 준비물

| 항목 | 비고 |
|---|---|
| Git | 저장소 `https://github.com/Perfectree-1215/PDF2Word.git` |
| Python **3.10 ~ 3.12** | 3.13 이상은 설치가 실패합니다. 수식 OCR 패키지 `rapid_latex_ocr`가 `numpy<2`를 요구하는데 numpy 1.x에는 3.13용 wheel이 없기 때문입니다. uv가 있으면 uv가 맞는 버전을 내려받습니다. |
| uv (권장) | `pip install uv` 또는 https://docs.astral.sh/uv/ |
| Windows + Microsoft Office (선택) | Word **수식 개체** 변환에만 필요합니다(Office의 `MML2OMML.XSL`). 없으면 LaTeX 문자열로 들어갑니다. macOS/Linux에서도 나머지는 다 됩니다. |
| Tesseract (선택) | 스캔 PDF `--ocr-pages` 에만 필요 |
| GPU | 필요 없음. **torch 계열 의존성을 넣지 않는 것**이 이 프로젝트의 원칙입니다(CPU 전용 ONNX). |

## 2. 환경 만들기

```bash
git clone https://github.com/Perfectree-1215/PDF2Word.git
cd PDF2Word
uv sync --locked --extra dev
```

- `uv sync`는 `.python-version`(3.12)에 맞는 Python으로 `.venv`를 만들고 `uv.lock`에 고정된 버전을 그대로 설치합니다.
  `--locked`는 lock이 `pyproject.toml`과 어긋나면 실패하게 해서, 의존성을 바꾸고 `uv lock`을 잊은 경우를 잡아 줍니다.
  `--extra dev`는 pytest를 함께 넣습니다.
- 같은 일을 손으로 하려면 `uv venv` → `uv pip install -e ".[dev]"`, uv가 없으면 `py -3.12 -m venv .venv` →
  `.venv\Scripts\pip install -e ".[dev]"`.
- `main_gui.bat`는 폴더 안의 `.venv`를 가장 먼저 씁니다(그다음 `venv`, 환경변수 `PDF2WORD_VENV`,
  `D:\Venvs_collec\Common_venv\pdf2word_venv`). 개발 PC에서 쓰던 `D:\Venvs_collec\...`는 그 PC의 관례일 뿐이고
  새 PC에서는 `.venv`면 충분합니다. 환경이 없으면 bat가 3.10~3.12로 직접 만들고, Python 버전이 범위 밖인 환경은
  이유를 안내하고 멈춥니다.

의존성을 바꿨을 때:

1. `pyproject.toml`의 `dependencies`와 **`requirements.txt`를 같이** 고칩니다. `main_gui.bat`는 `requirements.txt`를
   읽어 빠진 패키지를 찾고, 이 파일이 바뀌면 다음 실행 때 패키지를 다시 맞춥니다.
2. `uv lock` 을 돌려 `uv.lock`을 갱신하고 함께 커밋합니다.
3. Python 지원 범위를 바꾸면 `pyproject.toml`의 `requires-python`, `.python-version`, `main_gui.bat`의
   `PY_MIN / PY_MAX / PY_TOP` 세 곳을 같이 바꿉니다.

## 3. 실행

```bash
.venv\Scripts\python main_gui.py                   # GUI
.venv\Scripts\python main_gui.py paper.pdf -v      # 명령줄 (pdf2word 와 같은 옵션)
.venv\Scripts\pdf2word paper.pdf --pages 1-5 -f md -o out -v
```

- `--pages 1-5` 로 몇 쪽만 돌리면 빠릅니다. `-v`가 수식 OCR 결과, 본문 수식 치환(`text math '...' -> $...$`),
  페이지별 수식 블록 수를 보여 줍니다.
- 결과는 저장소 밖이나 `out/` 폴더(.gitignore에 있음)에 쓰세요. 변환된 `.md`는 루트에 두면 커밋 대상이 됩니다.
- 수식 OCR 결과는 `%LOCALAPPDATA%\pdf2word\mathocr-cache.json`에 캐시되어 같은 PDF를 다시 돌리면 빠릅니다. 엔진이나 전처리를
  바꿔 결과를 새로 보고 싶으면 `--no-cache`. GUI 설정(`gui.json`)도 같은 폴더에 있습니다.
- 첫 변환 때 RapidLaTeXOCR 모델(약 170 MB)을 내려받습니다. PyMuPDF Layout 모델은 패키지에 들어 있습니다.

## 4. 테스트

```bash
.venv\Scripts\python -m pytest tests -q      # 24개, 약 7초, 모델·네트워크 불필요
```

파일마다 `python tests/test_basic.py` 처럼 단독 실행도 됩니다.

| 파일 | 내용 |
|---|---|
| `tests/test_basic.py` | 서지정보 파싱, Symbol 폰트 복구, LaTeX 정리, 파일명, Obsidian 후처리, 본문 인라인 수식(합성 span) |
| `tests/test_docx.py` | Word 출력(문단·수식·이미지 구조) |
| `tests/test_outline.py` | 책갈피 트리, 챕터 쪽 범위, 인쇄 쪽 번호 |
| `tests/test_vectormath.py` | 벡터 도형 수식 묶기와 분류 |

테스트용 PDF는 저작권 때문에 저장소에 없습니다. 실제 변환 확인에는 종류가 다른 PDF 세 가지를 쓰는 것이 좋습니다.
개발 PC에서 기준으로 삼은 것은 **pdfTeX 논문**(MDPI *Minerals* 12-00480, CM/PazoMath 글꼴), **InDesign 논문**
(*MetaResource* "Numerical Modeling of Wet Milling Process by an Improved CFD-DEM-VOF Model", 쪽당 이미지 100개 이상),
**Word 논문**(ICCFD12 "A Compressible Flamelet-Based ...", SymbolMT/CambriaMath)이며, 책·매뉴얼 분할은 Ansys Fluent
Theory Guide로 확인했습니다. 새 PC에서는 같은 종류의 PDF를 아무거나 쓰면 됩니다(`*.pdf`는 어디에 두어도 커밋되지 않음).

## 5. 코드 지도

| 모듈 | 역할 |
|---|---|
| `main_gui.py` / `main_gui.bat` | tkinter GUI와 실행 스크립트. 인수가 있으면 CLI로 넘김. bat는 **ASCII만, CRLF**(`.gitattributes`가 보장) |
| `pdf2word/cli.py`, `config.py` | 옵션 정의(`Options` dataclass)와 명령줄. 새 옵션은 두 곳에 같이 넣고 README 옵션 표를 갱신 |
| `pdf2word/converter.py` | 파이프라인. `pymupdf4llm.to_markdown(page_chunks=True)` 결과의 `page_boxes`를 `_DocContext.render_page`가 클래스별로 처리(formula/picture/caption/text…) |
| `pdf2word/mathocr.py` | 수식 박스 렌더링 → 줄 분할 → RapidLaTeXOCR/Claude → 검증(괄호·반복·텍스트 대조), 캐시 |
| `pdf2word/inlinemath.py` | 텍스트 레이어의 인라인 수식(ρ_f, u_i, Ψ_⊥, \vec{v}) → `$...$`. 임계값은 파일 상단 상수(`SMALL_RATIO`, `SHIFT_RATIO`, `GLUE_GAP`, `ACCENT_RAISE`) |
| `pdf2word/vectormath.py` | 벡터 도형으로 그려진 수식·기호(매뉴얼) |
| `pdf2word/outline.py` | 책갈피 트리, 챕터 쪽 범위, 부분 문서 만들기, 인쇄 쪽 번호 |
| `pdf2word/lighten.py` | 이미지가 많은 쪽의 분석용 사본(레이아웃 분석 속도) |
| `pdf2word/docx_out.py` | Markdown → Word(.docx), LaTeX → MathML → OMML |
| `pdf2word/obsidian.py` | frontmatter, 콜아웃, `$$` 정리, 각주 인용 |
| `pdf2word/metadata.py` | DOI/arXiv 검출, CrossRef/arXiv 조회, 1쪽 휴리스틱 |
| `pdf2word/symbols.py` | Symbol 폰트 PUA 복구, Unicode → LaTeX 표 |
| `pdf2word/utils.py` | 로깅, 파일명, 캐시 폴더 |

흐름을 바꿀 때 기억할 점:

- pymupdf4llm은 flags가 같으면 글자 크기를 무시하고 span을 합칩니다(`u`+작은 `i` → `_ui_`). 그래서 `inlinemath`는
  Markdown이 아니라 `page.get_text("rawdict")`의 원본 span에서 run을 찾고 Markdown에서는 강조 기호를 무시하는
  정규식으로 자리를 찾습니다. 못 찾으면 본문을 그대로 둡니다.
- 수식·그림은 항상 **원본 PDF**에서 렌더링합니다. `lighten`으로 만든 사본은 레이아웃 분석에만 씁니다.
- 파일 읽고 쓸 때 `encoding="utf-8"`을 항상 명시합니다. Windows 콘솔은 cp949라서 생략하면 깨집니다.
  `utils.setup_console()`이 stdout/stderr를 UTF-8로 바꿉니다.
- 큰 PDF 변환은 수 분 걸립니다. 자동화 스크립트에서는 백그라운드로 돌리고 `-v` 로그 파일을 보세요.

## 6. 버전 올리기와 배포

1. `pdf2word/__init__.py`의 `__version__`만 올립니다(`pyproject.toml`이 읽어 가고 GUI 제목에도 표시).
2. `CHANGELOG.md`의 `## 미공개`를 `## vX.Y.Z — 날짜`로 바꾸고 새 `## 미공개`는 다음 변경 때 만듭니다.
3. `python -m pytest tests -q`, 그리고 세 종류 PDF 변환을 한 번씩.
4. 커밋 메시지는 지금까지처럼 `vX.Y.Z: 한 줄 요약` 형식이고 태그는 따로 쓰지 않습니다.

## 7. 환경별로 겪은 문제

- **Google Drive 폴더 안의 저장소**: 방금 만들었다 지운 폴더를 Drive 클라이언트가 잠가 "액세스 거부"가 나는 일이
  있습니다. 잠시 뒤 또는 탐색기에서 지우면 됩니다. 저장소를 Drive 밖에 두면 겪지 않습니다.
- **한글 경로**: Git Bash에서 `cmd /c some.bat`로 bat를 부르면 작업 폴더가 깨져 "not recognized"가 납니다.
  PowerShell에서 `.\main_gui.bat`로 부르거나 탐색기에서 더블클릭하세요.
- **uv가 고른 Python**: PATH에 LibreOffice 등이 넣은 다른 Python(3.13)이 있으면 범위를 주지 않은 `uv venv`가 그것을
  집어 실패할 수 있습니다. bat는 `>=3.10,<3.13`을 명시해서 피합니다. uv 관리 Python 저장소
  (`%APPDATA%\uv\python`)가 깨지면 `uv python install`이 "Missing expected target directory" 오류를 내는데, 그 폴더의
  빈 `cpython-*` 디렉터리를 지우면 됩니다.
- **Claude Code**: 루트의 `CLAUDE.md`가 프로젝트 요약이고, `.claude/`의 공유 설정은 커밋되며 `settings.local.json`만
  로컬입니다. 세션 메모리(`~/.claude/projects/...`)는 PC마다 따로 있으므로 PC를 옮기면 비어 있는 것이 정상입니다.
