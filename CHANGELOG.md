# Changelog

버전은 `pdf2word/__init__.py`의 `__version__` 한 곳에서 관리합니다. 형식은 `MAJOR.MINOR.PATCH`이며
GUI와 결과물에는 `v1.0`처럼 앞 두 자리만 표시합니다.

## 미공개

- 수식 OCR 검증 계층: 텍스트 레이어가 깨진 PDF(Type 1 사설 인코딩 — 구형 Elsevier 등, 본문을 복사하면 `¼`·`ð`·`þ`가 나오는 것)를
  감지해(`mathocr.hint_usable`: 한 수식 영역에 `ð`/`þ`/`Þ`가 2개 이상) 그 영역은 텍스트 레이어가 없는 것처럼 다룸. 힌트 기반 보정과
  신뢰도 대조를 건너뛰어 정답에 붙던 `⚠ OCR 신뢰도 낮음` 오경보를 없애고, 벡터 도형용 `doubtful_equation` 검사도 적용하지 않음.
  대신 배율 2·3으로 읽어 정규화한 결과(`normalize_latex`)가 같으면 채택하고 다르면 4배까지 읽어 **배율 간 일치도**로 고르며
  (`pick_by_agreement`), 그 일치도를 신뢰도로 써서 깨진 레이어에서도 근거 있는 `⚠`가 붙음.
  건수는 로그 요약(`N unverified`)과 Markdown 머리 `equations_unverified`에 적고, `--math-mode latex`에서는 검증 못 한 식에
  이미지를 함께 넣음. 이유: paper-01 벤치마크에서 불확실 표시 4건이 모두 깨진 레이어 때문인 오경보였음
  (`docs/issues/garbled-text-layer.md`, `docs/decisions/equation-ocr-reliability.md`)
- 식 번호: `ð3Þ`처럼 깨진 번호도 `(3)`으로 정규화해 찾음(`mathocr.label_text`). 2단 조판의 왼쪽 단 수식 번호가 탈락하던 기존
  버그를 고침 — `find_labels`가 오른쪽 정렬을 페이지 끝까지의 탐색 띠가 아니라 수식 박스 기준으로 판정하고, 박스와 번호 사이에
  다른 단의 글이 있으면 그 번호를 버림. 이제 2단 논문의 왼쪽 단 수식에도 `\tag`와 `^eq-N` 앵커가 붙음
- `tools/bench_mathocr.py`: 한 PDF의 디스플레이 수식을 변환기와 같은 방법으로 찾아 엔진별 LaTeX·신뢰도·시간을 `report.md`/
  `report.html`(MathJax)/`results.json`으로 비교(PDF마다 `bench/<stem>/` 한 폴더에 `golden.json`과 함께). `--golden`으로 사람이 확정한 정답 LaTeX(`bench/<stem>/golden.json`)와
  정확 일치율·유사도를 냄(`normalize_latex`: 굵기·괄호 크기·간격은 무시, 악센트·첨자·기호는 유지). 첫 실행 때 같은 폴더에 `golden.json` 틀을 자동 생성, `--rescore`로 OCR 없이 재채점
- 테스트 `tests/test_garbled_hint.py`, `tests/test_labels.py`(합성 2단 페이지), `tests/test_agreement.py`, `tests/test_bench.py` 추가(총 37개)
- `.claude/`(스킬·에이전트·settings.json)와 CLAUDE.md "작업 라우팅": 단계별 모델 배정(방향 결정·진단 Fable, 구현 Opus,
  배선·검증·문안 Sonnet). 인계물 틀 `docs/decisions/_template.md`, `docs/issues/_template.md`

## v1.4.0 — 2026-10-18

설치 환경을 Python 3.12 하나로 고정해, PC에 어떤 Python이 깔려 있든(또는 없든) `main_gui.bat` 더블클릭 한 번으로 설치가
끝나게 했습니다. 기능 변화는 없고 설치·개발 환경만 바뀝니다.

- Python **3.12만** 지원합니다(이전 3.10~3.12). 수식 OCR 패키지 `rapid_latex_ocr`가 `numpy<2`를 요구해 3.13 이상은 원래
  안 됐고, 이번에 하한도 3.12로 올려 `pyproject.toml`의 `requires-python`(`>=3.12,<3.13`), `.python-version`,
  `main_gui.bat`의 `PY_MIN/PY_MAX/PY_TOP` 세 곳을 하나로 맞췄습니다. `uv lock`을 다시 돌려 3.10/3.11 전용 패키지
  (exceptiongroup, tomli 등)가 lock에서 빠졌습니다
- `main_gui.bat`: 가상환경을 PC에 설치된 Python과 무관하게 **항상 Python 3.12로** 만듭니다. uv가 있으면
  `uv venv --python 3.12`(설치된 3.12가 없으면 uv가 내려받음), uv가 없고 `py -3.12`(또는 3.12인 `python`)가 있으면 그것으로,
  둘 다 없으면 uv를 공식 설치 스크립트(astral.sh, 실패 시 winget)로 설치한 뒤 uv로 만듭니다. 그래서 3.13/3.14만 깔린 PC나
  Python이 없는 PC에서도 됩니다. uv는 PATH 외에 `%USERPROFILE%\.local\bin`과 WinGet 폴더에서도 찾고, 사용자 uv 설정이
  다운로드를 막아도 되도록 `UV_PYTHON_DOWNLOADS=automatic`을 켭니다
- `main_gui.bat`: 이미 있는 가상환경도 Python이 3.12가 아니면(예: 다른 PC에서 3.11이나 3.13으로 만든 것) 패키지 설치 도중
  실패하는 대신 이유와 조치(폴더 삭제 후 재실행, 또는 `PDF2WORD_VENV`)를 안내하고 멈춥니다
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
