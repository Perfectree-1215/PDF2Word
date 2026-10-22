# 개발 안내 (새 PC에서 이어서 개발하기)

사용자용 설명은 [README.md](../README.md)에, 변경 내역은 [CHANGELOG.md](../CHANGELOG.md)에 있습니다.
이 문서는 **다른 PC에서 저장소를 받아 개발을 이어가는 사람**(과 Claude Code)을 위한 것입니다.
저장소에는 소스, 테스트, 문서, `uv.lock`, `.python-version`, 실행 스크립트가 모두 들어 있고,
논문 PDF와 변환 결과·가상환경·PC별 설정만 빠져 있습니다([.gitignore](../.gitignore) 참고).

## 1. 준비물

| 항목 | 비고 |
|---|---|
| Git | 저장소 `https://github.com/Perfectree-1215/PDF2Word.git` |
| Python **3.12** | `requires-python = ">=3.12,<3.13"`. 3.13 이상은 설치가 실패합니다. 수식 OCR 패키지 `rapid_latex_ocr`가 `numpy<2`를 요구하는데 numpy 1.x에는 3.13용 wheel이 없기 때문입니다. 개발 환경(`uv sync`)과 `main_gui.bat`가 만드는 환경은 모두 3.12이고, PC에 3.12가 없으면 uv가 내려받습니다. |
| uv (권장) | `pip install uv`, `winget install astral-sh.uv` 또는 https://docs.astral.sh/uv/ . `main_gui.bat`는 uv가 없고 3.12도 없으면 공식 설치 스크립트로 uv를 설치합니다. |
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
  새 PC에서는 `.venv`면 충분합니다. 환경이 없으면 bat가 **항상 Python 3.12**로 만듭니다(PC의 Python 버전과 무관):
  uv가 있으면 `uv venv --python 3.12`(없는 3.12는 uv가 내려받음), uv가 없으면 `py -3.12`/3.12인 `python`, 둘 다 없으면
  uv를 설치(astral.sh 공식 스크립트 → winget)한 뒤 uv로. 기존 환경도 Python이 3.12가 아니면 이유를 안내하고 멈춥니다
  (bat의 `PY_MIN`/`PY_MAX`가 3.12/3.13).

의존성을 바꿨을 때:

1. `pyproject.toml`의 `dependencies`와 **`requirements.txt`를 같이** 고칩니다. `main_gui.bat`는 `requirements.txt`를
   읽어 빠진 패키지를 찾고, 이 파일이 바뀌면 다음 실행 때 패키지를 다시 맞춥니다.
2. `uv lock` 을 돌려 `uv.lock`을 갱신하고 함께 커밋합니다.
3. Python 지원 범위를 바꾸면 `pyproject.toml`의 `requires-python`, `.python-version`, `main_gui.bat`의
   `PY_MIN / PY_MAX / PY_TOP` 세 곳을 같이 바꾸고 `uv lock`을 다시 돌립니다. 현재 세 곳 모두 **3.12만**
   (`>=3.12,<3.13`, `3.12`, `PY_MIN=PY_TOP=3.12`)입니다.

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
- 첫 변환 때 수식 OCR 모델을 내려받습니다: `p2t`(기본)는 Pix2Text MFR 1.5(약 120 MB, `%LOCALAPPDATA%\pdf2word\models\pix2text-mfr-1.5`, `PDF2WORD_MODELS`로 변경), 폴백 `rapid`는 RapidLaTeXOCR 모델(약 170 MB). PyMuPDF Layout 모델은 패키지에 들어 있습니다.

## 4. 테스트

```bash
.venv\Scripts\python -m pytest tests -q      # 222개, 약 8초, 모델·네트워크 불필요
```

파일마다 `python tests/test_basic.py` 처럼 단독 실행도 됩니다.

| 파일 | 내용 |
|---|---|
| `tests/test_basic.py` | 서지정보 파싱, Symbol 폰트 복구, LaTeX 정리, 파일명, Obsidian 후처리, 본문 인라인 수식(합성 span) |
| `tests/test_docx.py` | Word 출력(문단·수식·이미지 구조) |
| `tests/test_outline.py` | 책갈피 트리, 챕터 쪽 범위, 인쇄 쪽 번호 |
| `tests/test_vectormath.py` | 벡터 도형 수식 묶기와 분류 |
| `tests/test_garbled_hint.py` | 깨진 텍스트 레이어 감지(`hint_usable`)·식 번호 정규화(`label_text`)·판단 유보 |
| `tests/test_labels.py` | 합성 2단 페이지에서 식 번호 찾기(`find_labels`, 왼쪽 단·다른 단 번호 배제·깨진 번호) |
| `tests/test_agreement.py` | 배율 간 일치도(`agreement`, `pick_by_agreement`)로 읽기 결과 고르기 |
| `tests/test_bench.py` | `tools/bench_mathocr.py`의 LaTeX 정규화·골든 채점·요약 |
| `tests/test_mfr_onnx.py` | Pix2Text MFR 러너(가짜 세션·토크나이저·다운로더): 탐욕 루프·상한·반복 중단·후처리·모델 폴더·해시 검증 |
| `tests/test_p2t_engine.py` | p2t 엔진의 배치: 모델 로드 실패 → rapid 폴백, 엔진별 기본 배율, 전체 영역 읽기(스텁 엔진) |
| `tests/test_assets.py` | 자산 폴더 소유(`_own_asset_dir`): docx 변환이 같은 이름 폴더의 .md 그림을 건드리지 않음, 같은 저자·연도 논문은 `-2` 폴더, `[ ] #`가 든 PDF 이름 |
| `tests/test_chapters.py` | 챕터 분할 경계: 책갈피 없는 PDF, 글줄을 지나는 자르기, 같은 쪽 위쪽 항목, 회전 쪽, 쪽 아래 목적지, 합자 제목, 한글 파일명(NFC), 빈 선택 오류, 대문자 쪽 라벨, 목적지 없는 책갈피 |
| `tests/test_cli.py` | 파서가 미리 거절하는 값(`--math-zooms` 형식, 빈 `--chapters`; 종료 코드 2) |
| `tests/test_gui.py` | 창 없는 GUI 로직: `split_extra`, `load_settings`(v1.3 설정의 rapid → p2t 한 번), `plan_for`/`parts_for`, `run_jobs`(파트별 변환·오류 중단·`--list-chapters` 거절), 상태 문구 |
| `tests/test_inlinemath.py` | 인라인 수식 run을 Markdown에 놓을 때 주변 글 보존(산문 단어, 강조 묶음, `∗` 위첨자) |
| `tests/test_lighten.py` | 경량화 사본의 그림 묶기, `cluster_rects` sweep = 쌍별 비교, redaction 상수 |
| `tests/test_metadata.py` | 1쪽 휴리스틱(합성 PDF)과 CrossRef/arXiv(가짜 HTTP): 공백 span, 키워드, 마스트헤드, 연도, DOI, 복합 성, `&` 저자 |
| `tests/test_obsidian.py` | Markdown 후처리(`_block_mask`, Abstract 콜아웃, 각주, 제목, 표). 모든 경우 원문 글자가 사라지지 않음을 단언 |
| `tests/test_utils.py` | `wiki_safe_name`, 캐시 폴더(옛 pdf2obsidian 폴더 무시) |

테스트용 PDF는 저작권 때문에 저장소에 없습니다. 실제 변환 확인에는 종류가 다른 PDF 세 가지를 쓰는 것이 좋습니다.
개발 PC에서 기준으로 삼은 것은 **pdfTeX 논문**(MDPI *Minerals* 12-00480, CM/PazoMath 글꼴), **InDesign 논문**
(*MetaResource* "Numerical Modeling of Wet Milling Process by an Improved CFD-DEM-VOF Model", 쪽당 이미지 100개 이상),
**Word 논문**(ICCFD12 "A Compressible Flamelet-Based ...", SymbolMT/CambriaMath)이며, 책·매뉴얼 분할은 Ansys Fluent
Theory Guide로 확인했습니다. 새 PC에서는 같은 종류의 PDF를 아무거나 쓰면 됩니다(`*.pdf`는 어디에 두어도 커밋되지 않음).

## 5. 코드 지도

| 모듈 | 역할 |
|---|---|
| `main_gui.py` / `main_gui.bat` | tkinter GUI와 실행 스크립트. 인수가 있으면 CLI로 넘김. 창 없이 테스트되는 함수: `run_jobs`(작업 스레드 본체, 오류·SystemExit를 큐로), `parts_for`·`plan_for`(챕터·쪽 분할 계획, cli `plan_parts`와 같음), `split_extra`(추가 옵션 칸, 큰따옴표만), `load_settings`(gui.json `"v": 2`). bat는 **ASCII만, CRLF**(`.gitattributes`가 보장) |
| `pdf2word/cli.py`, `config.py` | 옵션 정의(`Options` dataclass)와 명령줄. 새 옵션은 두 곳에 같이 넣고 README 옵션 표를 갱신 |
| `pdf2word/converter.py` | 파이프라인. `pymupdf4llm.to_markdown(page_chunks=True)` 결과의 `page_boxes`를 `_DocContext.render_page`가 클래스별로 처리(formula/picture/caption/text…). 자산 폴더는 `_own_asset_dir`(md: 없음·빈 폴더·이번 .md가 참조하는 첫 이름, 아니면 `-2`·`-3`…; docx는 임시 폴더에서 만들고 지움) |
| `pdf2word/mathocr.py` | 수식 박스 렌더링 → 줄 분할 → `p2t`(Pix2Text MFR, 기본; 모델을 못 쓰면 rapid로 대체)/RapidLaTeXOCR/Claude → 검증(괄호·반복·텍스트 대조), 캐시. 깨진 텍스트 레이어 감지(`hint_usable`, `label_text`), 식 번호 찾기(`find_labels`, 2단 조판은 `box=` 필수), 레이어가 깨진 식의 배율 간 일치도 선택(`_recognize_by_agreement`, `normalize_latex`). 저장 crop은 `EquationOCR.DISPLAY_ZOOM`(2 = 144 dpi, 엔진이 읽는 배율과 별개), `recognize_region(read=False)`는 OCR 없이 crop만(`--math-mode image`). 캐시에는 보정(`fix_braces`·`looks_garbage`·`hint_fixes`) 뒤 결과가 들어가므로 그 규칙을 바꾸면 `OCRCache.VERSION`(현재 3)을 올림 |
| `pdf2word/mfr_onnx.py` | Pix2Text MFR 1.5 모델 파일 관리(내려받기·크기/sha256 검사·`PDF2WORD_MODELS`)와 onnxruntime 탐욕 디코딩 러너(torch 없음), 출력 후처리 |
| `tools/bench_mathocr.py` | 한 PDF의 디스플레이 수식을 변환기와 같은 방법으로 찾아 `--engines`(기본 `p2t`) 엔진별 결과를 `report.md`/`report.html`(MathJax)/`results.json`으로 비교. PDF마다 `bench/<stem>/` 한 폴더에 `report.html`·`results.json`·크롭·`golden.json`(사람이 확정한 정답 LaTeX)을 두고, 같은 폴더의 `golden.json`과 정확 일치율·유사도를 냄(없으면 첫 실행이 틀을 만들고, `--rescore`는 OCR 없이 재채점). 골든 키는 (쪽, 라벨, `k`)이고 `k`는 같은 쪽·같은 라벨 안의 순번(번호 없는 식이 한 쪽에 여럿일 때), 옛 golden.json처럼 없으면 0 |
| `pdf2word/inlinemath.py` | 텍스트 레이어의 인라인 수식(ρ_f, u_i, Ψ_⊥, \vec{v}) → `$...$`. 임계값은 파일 상단 상수(`SMALL_RATIO`, `SHIFT_RATIO`, `GLUE_GAP`, `ACCENT_RAISE`) |
| `pdf2word/vectormath.py` | 벡터 도형으로 그려진 수식·기호(매뉴얼). 웹 링크 아래의 묶음은 배지로 보고 뺌(`_uri_links`, `LINK_BADGE_RATIO`; Elsevier CrossMark), OCR 결과가 글자 단어면 수식이 아님(`reads_as_text`) |
| `pdf2word/outline.py` | 책갈피 트리, 챕터 쪽 범위, 부분 문서 만들기, 인쇄 쪽 번호. 경계가 글줄을 지나면 `_snap_cut`이 그 줄 가장자리로 옮김(`_lost`로 양쪽 손실 비교). `parse_pages`·`select_parts`는 고른 것이 없으면 ValueError |
| `pdf2word/lighten.py` | 이미지가 많은 쪽의 분석용 사본(레이아웃 분석 속도) |
| `pdf2word/docx_out.py` | Markdown → Word(.docx), LaTeX → MathML → OMML |
| `pdf2word/obsidian.py` | frontmatter, 콜아웃, `$$` 정리, 각주 인용. 줄 단위 정리는 `_block_mask`로 짝 맞는 `$$`·코드 펜스 블록을 건너뜀 |
| `pdf2word/metadata.py` | DOI/arXiv 검출, CrossRef/arXiv 조회, 1쪽 휴리스틱 |
| `pdf2word/symbols.py` | Symbol 폰트 PUA 복구, Unicode → LaTeX 표 |
| `pdf2word/utils.py` | 로깅, 파일명(`fold_ascii`는 결합 악센트만 지우고 NFC), 자산 폴더 이름 `wiki_safe_name`(위키링크를 깨는 `[ ] # ^ \|` → `-`), 캐시 폴더 |

흐름을 바꿀 때 기억할 점:

- pymupdf4llm은 flags가 같으면 글자 크기를 무시하고 span을 합칩니다(`u`+작은 `i` → `_ui_`). 그래서 `inlinemath`는
  Markdown이 아니라 `page.get_text("rawdict")`의 원본 span에서 run을 찾고 Markdown에서는 강조 기호를 무시하는
  정규식으로 자리를 찾습니다. 못 찾으면 본문을 그대로 둡니다.
- 수식·그림은 항상 **원본 PDF**에서 렌더링합니다. `lighten`으로 만든 사본은 레이아웃 분석에만 씁니다(`Converter._layout_doc`; `--ocr-pages`거나 `--no-lighten`이면 레이아웃도 원본으로).
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
- **uv가 고른 Python**: PATH에 LibreOffice 등이 넣은 다른 Python(3.13)이 있으면 버전을 주지 않은 `uv venv`가 그것을
  집어 실패할 수 있습니다. bat는 `--python 3.12`를 명시하고 `UV_PYTHON_DOWNLOADS=automatic`을 켜서(사용자 uv 설정이
  `python-downloads = never`여도) 3.12를 쓰거나 내려받게 합니다. uv 관리 Python 저장소
  (`%APPDATA%\uv\python`)가 깨지면 `uv python install`이 "Missing expected target directory" 오류를 내는데, 그 폴더의
  빈 `cpython-*` 디렉터리를 지우면 됩니다.
- **Claude Code**: 루트의 `CLAUDE.md`가 프로젝트 요약이고, `.claude/`의 공유 설정은 커밋되며 `settings.local.json`만
  로컬입니다. 세션 메모리(`~/.claude/projects/...`)는 PC마다 따로 있으므로 PC를 옮기면 비어 있는 것이 정상입니다.
