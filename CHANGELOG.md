# Changelog

버전은 `pdf2word/__init__.py`의 `__version__` 한 곳에서 관리합니다. 형식은 `MAJOR.MINOR.PATCH`이며
GUI와 결과물에는 `v1.0`처럼 앞 두 자리만 표시합니다.

## 미공개

- `main_gui.bat`: 가상환경을 PC에 설치된 Python 버전과 무관하게 **항상 Python 3.12**로 만듦. uv가 있으면
  `uv venv --python 3.12`(설치된 3.12가 없으면 uv가 내려받음), uv가 없으면 `py -3.12`(또는 3.12인 `python`), 둘 다 없으면
  uv를 공식 설치 스크립트(astral.sh, 실패 시 winget)로 설치한 뒤 uv로 만듦. 그래서 3.13/3.14만 깔린 PC나 Python이 없는
  PC에서도 더블클릭 한 번으로 됨. 이유: PC의 기본 Python이 3.12가 아니면 환경 생성·패키지 설치가 실패하던 문제.
  3.10/3.11로 새 환경을 만들던 대체 경로는 없앴고, 기존 가상환경도 3.12가 아니면(`PY_MIN=3.12`) 받아들이지 않고 안내 후 멈춤.
  `pyproject.toml`의 `requires-python`도 `>=3.12,<3.13`으로 올리고 `uv lock`을 다시 돌림(3.10/3.11 전용 패키지
  exceptiongroup·tomli 등이 lock에서 빠짐). uv는 PATH 외에
  `%USERPROFILE%\.local\bin`과 WinGet 폴더에서도 찾음. 사용자 uv 설정이 다운로드를 막아도 되도록 `UV_PYTHON_DOWNLOADS=automatic`
- `main_gui.bat`: 가상환경을 만들 때 Python 3.10~3.12만 쓰도록 함. uv는 `>=3.10,<3.13`에 맞는 Python을 고르거나
  내려받고, uv가 없으면 `py -3.12`, `-3.11`, `-3.10` 순으로 찾은 뒤 `py -3`/`python`은 버전이 범위 안일 때만 씀.
  이미 있는 가상환경의 Python이 범위 밖이면 패키지 설치 도중 실패하는 대신 이유와 조치(폴더 삭제 또는 `PDF2WORD_VENV`)를
  안내하고 멈춤. 이유: 수식 OCR 패키지 `rapid_latex_ocr`가 `numpy<2`를 요구하는데 numpy 1.x는 Python 3.13 이상용
  배포 파일이 없어 설치가 실패함. 같은 범위를 `pyproject.toml`의 `requires-python`(`>=3.10,<3.13`)과 새 파일
  `.python-version`(3.12, `uv venv`가 읽음)에도 적음
- `.gitignore`: "배포에 필요한 파일만" 올리던 규칙을 개발용으로 바꿈. 루트의 `*.md`(메모·설계 문서), `.claude/`(공유 설정;
  `settings.local.json`만 제외), `.vscode/`의 `settings/launch/tasks/extensions.json`, `tests/` 아래의 작은 PDF
  픽스처는 더 이상 제외하지 않고, 생성물·가상환경·PC별 설정·비밀 값(`.env`, `*.key`)·논문 PDF와 변환 결과만 제외
- 다른 PC에서 개발을 이어가기 위한 정리: `docs/DEVELOPMENT.md`(환경 만들기 `uv sync --locked --extra dev`, 실행·테스트,
  코드 지도, 의존성·버전 규칙, 환경별 문제), 루트 `CLAUDE.md`(Claude Code용 프로젝트 요약), `.gitattributes`
  (`main_gui.bat`는 어느 PC에서든 CRLF로 체크아웃), `.editorconfig`

## v1.3.0 — 2026-10-18

매뉴얼(Ansys Fluent Theory Guide 등)을 챕터별로 변환하며 드러난 네 가지를 고쳤습니다.

- 챕터 선택: 상위 항목을 체크하면 하위 항목이 함께 체크되고, 그 묶음이 파일 하나가 됩니다. 하위 하나를 빼면 상위는
  ▣(일부 선택)으로 바뀌고 나머지 하위가 각각 파일이 됩니다. "하위 항목별 파일로 나누기" 옵션(`--subchapters`)을 켜면
  체크한 항목의 바로 아래 하위 항목마다 파일을 만들고, 첫 하위 항목 앞의 챕터 서론은 챕터 제목의 파일로 따로 저장합니다
- 인쇄 쪽 번호: PDF의 쪽 라벨(표지·목차의 로마 숫자 등)을 읽어 챕터 목록·GUI·문서 머리에 `p. 201 (PDF 249)`처럼
  적고, 라벨이 없는 PDF는 머리글·바닥글의 숫자로 추정합니다. Markdown frontmatter에 `pages`(인쇄)와 `pages_in_pdf`를
  나눠 적습니다. `--pages p201-205`처럼 `p`를 붙이면 인쇄 쪽 번호로 범위를 받습니다
- 벡터 도형으로 그려진 수식(텍스트도 이미지도 아닌 글리프 외곽선): 도형 묶음을 찾아 식 전체는 "이미지 + OCR 결과"로,
  본문 속 기호(Ω, ε_w, q_in …)는 OCR 결과가 단순한 기호 꼴일 때만 수식으로 넣고 미심쩍으면 글자 크기의 작은 이미지로
  그 자리에 넣습니다(Word·Obsidian 모두). 식 번호만 잡힌 "수식" 박스는 번호로만 쓰고, 그림으로 잡힌 번호 있는 식은
  번호마다 나눠 읽습니다. 텍스트 대조가 불가능한 식의 OCR이 깨진 꼴이면 ⚠ 표시 (`--no-vector-math`로 끌 수 있음)
- 본문 기호를 끼워 넣는 위치를 읽기 순서의 앞 두 단어로 잡아 "of", "the" 같은 흔한 단어 뒤에 잘못 들어가던 문제와
  쉼표 앞에 끼던 문제를 고침. 아래첨자 OCR의 띄어쓰기(`q_{i n}` → `q_{in}`) 정리

## v1.2.0 — 2026-10-17

논문이 아닌 PDF(책·매뉴얼·보고서·슬라이드)와 수천 쪽짜리 대용량 PDF 지원.

- 문서 종류 `--doc-type auto|paper|document` (GUI: 문서 종류). 자동 판별은 첫 두 쪽에 DOI·arXiv·Abstract가
  있으면 논문, 아니면 일반 문서. 일반 문서는 서지 조회·초록·참고문헌 처리를 건너뛰고 파일명은 PDF 이름(`{stem}`) 그대로
- 책갈피(목차) 분석: `--list-chapters`로 트리와 쪽 범위를 보고, `--chapters 3,4.2,5.1-5.4` / `all` / `all:2`로
  고른 항목만 각각 한 파일로 변환. GUI는 **📑 챕터 선택…** 버튼으로 트리에서 체크
- 챕터 파일 이름 `문서명-번호-제목` (`--chapter-template`). 번호는 같은 단계 책갈피의 문서 전체 순번으로 고정(선택과
  무관), 자릿수는 그 단계 항목 수에 맞춤(01 / 001). 이미지 폴더 `_asset-문서명-번호`
- 챕터가 쪽 중간에서 시작·끝나면 책갈피 위치(제목 줄)에서 잘라 이웃 챕터 내용을 제외 (`--chapter-split page`로 쪽 단위 전환)
- 책갈피 없는 PDF: `--split-pages 50`(GUI: 일정 쪽수마다 나누기)로 `문서명-01-p0001-0050` 식 분할
- 큰 PDF 성능: 챕터·쪽 범위는 부분 문서로 떼어 내 처리하므로 6,056쪽 매뉴얼의 한 챕터도 수 초~수 분이면 끝남.
  책갈피 읽기는 4,783개 항목에 0.05초
- 한국어 이름 "신 지원"의 성을 "신"으로 인식, PowerPoint 내보내기의 가짜 제목("PowerPoint 프레젠테이션") 무시

## v1.0.0 — 2026-10-17

첫 공개판.

- PDF 논문 → Word(.docx, 기본) / Obsidian Markdown(.md + `_asset-<저자>-<연도>/`) 변환
- 레이아웃 분석(PyMuPDF Layout)으로 제목·섹션·본문·표·그림·수식 블록을 읽기 순서대로 추출
- 수식: 원본에서 잘라낸 이미지 + 그 아래 OCR 결과(Word 수식 또는 LaTeX). PDF 텍스트와 대조한 신뢰도가 낮으면 ⚠ 표시
- 본문 속 텍스트 인라인 수식(ρ_f, u_i …)을 `$...$`/Word 수식으로 변환, Symbol 폰트 글자(ρ, ∂ …) 복구
- 그림을 캡션에 맞춰 `fig3a.png`처럼 저장, 반복 로고 제거
- DOI/arXiv로 서지정보(CrossRef/arXiv) 조회 → 문서 머리 정보 / YAML frontmatter
- 이미지가 많은 페이지의 분석 속도 개선(큰 비트맵 대체), OCR 결과 캐시
- GUI(`main_gui.py`, `main_gui.bat`)와 명령줄(`pdf2word`) 제공
- `main_gui.bat`: 가상환경 자동 선택(`.venv`/`venv` → `D:\Venvs_collec\Common_venv\pdf2word_venv` → 새 `.venv`), 없으면 만들고 빠진 패키지를 자동 설치. 명령 프롬프트와 PowerShell 양쪽에서 실행 가능
