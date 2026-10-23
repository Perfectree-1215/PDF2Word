# Changelog

버전은 `pdf2word/__init__.py`의 `__version__` 한 곳에서 관리합니다. 형식은 `MAJOR.MINOR.PATCH`이며
GUI와 결과물에는 `v1.0`처럼 앞 두 자리만 표시합니다.

## 미공개

- 노트가 임베드한 이미지를 라벨 붙은 모음 시트 몇 장으로 묶는 `--figure-sheet add|replace`(기본 none)와 타일 해상도 `--sheet-dpi 120`을 추가함
  (GUI는 저장 위치와 형식 카드의 "그림 파일" 콤보): `pdf2word/sheets.py`가 한 장이 Claude 원본 해상도 한도(긴 변 2,000 px(API 한도는 2,576이나 Claude Code Read 도구가 약 2,000으로 줄임)·28 px 패치
  4,784개) 안에 들도록 타일을 높이순으로 정렬해 선반 패킹함(여백이 줄고, 라벨이 있어 문서 순서는 필요 없음). 측정: paper-01 이미지 19장이 시트 2장이 되고
  토큰은 12,637 → 6,180(−51%, 문서 순서·150 dpi에서는 시트 3장 11,556). `replace`는 개별 PNG를 지우고 본문 임베드를 `*[Fig. 3 → sheet-1.png]*`로 바꾸며 끝에
  `## 그림 모음 (figure sheets)` 절을 붙이고, 프론트매터에 `figure_sheets: N`을 적음. Word 출력은 그대로. 재변환 때는 이전 `sheet-N.png`도
  생성물로 보고 지움. 이유: LLM 위키 인제스트에서 이미지 파일마다 읽기가 한 번이라 파일 수를 줄여야 함(`docs/decisions/figures-for-llm-ingest.md` B3)
- 같은 캡션의 그림 패널을 한 장으로 합치는 `--figure-panels merge`(기본)를 추가하고 `split`으로 예전처럼 패널마다 파일을 남길 수 있게 함
  (GUI는 저장 위치와 형식 카드의 체크박스). **기본 동작 변경**: 패널이 나뉜 PDF의 그림 파일이 `fig2a.png`·`fig2b.png`에서 `fig2.png` 한 장이 됨: `_DocContext._panel_groups`가 같은 캡션에 붙는 picture 박스를 묶어 합집합 영역을 한 번에
  렌더링하고(`fig2.png`), 캡션이 없는 12 pt 이내 인접 조각도 편입함. 안전 조건: 패널 사이에 본문이 10%·120자를 넘게 있거나, 합집합이
  다른 박스와 20% 이상 겹치거나, 합집합 면적이 패널 면적 합의 3배를 넘으면 병합하지 않고 패널별 파일(`fig2a.png`·`fig2b.png`)로
  남김(`_merge_blocker`). 이유: LLM 위키 인제스트에서 그림 한 장이 비전 호출 한 번이라 패널 수만큼 같은 그림의 토큰이 중복됨
  (`docs/decisions/figures-for-llm-ingest.md`, `docs/issues/figure-panel-merge.md`)

## v1.5.0 — 2026-10-23

수식 OCR 엔진을 Pix2Text MFR(`p2t`, CPU ONNX)로 바꾸고 기본값으로 삼았습니다. 깨진 텍스트 레이어의 식은 배율 간 일치도로 검증하고,
2026-10-22 전체 코드 검토에서 확인된 발견 100여 건(챕터 분할 크래시·본문 손실, 자산 폴더 삭제, CrossMark 가짜 수식, Word·서지정보·GUI)을
고쳤습니다. 수식 OCR 캐시 버전이 3으로 올라 첫 변환 때 모든 식을 다시 읽습니다. 테스트 63 → 222개.

- 수식 OCR 엔진 `p2t` 추가, 기본값 변경: Pix2Text MFR 1.5(TrOCR 구조, 모델 3개 합계 120 MB)를 torch 없이 onnxruntime·tokenizers만으로
  돌리는 러너(`pdf2word/mfr_onnx.py`)와 `mathocr.Pix2TextEngine`. `--math-engine`의 기본값이 `rapid`에서 `p2t`로 바뀌고(GUI는 첫 항목
  `p2t  (로컬, 무료, 추천)`), 여러 줄 수식을 줄 분할 없이 통째로 읽음. 첫 실행 때 `%LOCALAPPDATA%\pdf2word\models\pix2text-mfr-1.5`
  (그 외 `~/.cache/pdf2word/models`, `PDF2WORD_MODELS`로 변경)에 내려받아 크기·sha256을 검사하고, 내려받지 못하면(오프라인·방화벽)
  로그에 사유를 적고 `rapid`로 변환을 계속함. 설치되는 패키지는 그대로(러너가 직접 쓰는 `onnxruntime>=1.17`·`tokenizers>=0.20`를
  `pyproject.toml`·`requirements.txt`에 명시). `--math-zooms` 기본값은 고정 `2,3,4`에서 엔진별 기본(p2t 4,3,2 /
  rapid 2,3,4)으로 바뀜(옵션을 주면 그 값이 우선). 이유: paper-01 골든 4식에서 평균 유사도가 rapid 0.745(autojunk를 끄면 0.912)에서
  p2t 0.975로 오르고 두 줄 식·굵은 `\chi`를 정확히 읽음(`docs/decisions/math-engine-pix2text.md`; 두 번째 논문에서 판정 기준을
  못 넘으면 기본값을 rapid로 되돌림)
- p2t 보강(결정 워크플로의 검증 렌즈 반영): 모델 URL을 커밋 리비전에 고정(sha256과 짝이 맞는 파일만 받음), 시간 예산을 식 하나에
  배율을 합쳐 90 s·이미지 한 장 60 s로 둠(넘으면 그 식은 이미지로 남김), 배율 간 동률은 큰 배율 우선, 엔진 호출 실패(예외·시간
  초과)는 캐시에 남기지 않음(이전엔 영구 실패로 기억됨), onnxruntime 스레드 4개·스핀 대기 끔(같은 속도에 CPU 시간 1/3)
- 배율 간 일치도로 고른 식의 `⚠` 문턱을 0.9로 올림(`mathocr.AGREE_LOW`; 텍스트 레이어 대조는 0.6 그대로). 이유: 틀린 읽기도
  배율끼리는 0.85~0.9로 일치해 0.6으로는 경고가 붙지 않았음
- `\\{`(줄 바꿈 뒤 그룹)를 이스케이프된 중괄호로 잘못 읽어 여러 줄 식을 버릴 수 있던 `braces_balanced`·`normalize_latex` 버그 수정
- 의존성: `pymupdf`·`pymupdf4llm`·`pymupdf-layout`을 `<2`로 제한(2026-10-19에 나온 2.0은 검증 전이고 `main_gui.bat`는
  pyproject 범위로 설치하므로 새 PC가 2.0을 받게 됨). `uv lock` 갱신(잠긴 버전은 그대로)
- 식 번호가 식보다 아래 줄에 있을 때 식의 끝(`)²]` 등)이 잘리던 버그를 고침: `_split_regions`가 번호 사각형의 x0에서 영역을
  자르는 대신, 번호가 식의 글자 행과 겹치지 않으면 폭을 유지하고 렌더링 이미지에서 번호 사각형을 흰색으로 지움
- 긴 식(200자 초과)에서 `difflib`의 autojunk 때문에 배율 간 일치도(`agreement`)와 벤치마크 골든 유사도가 실제보다 깎이던 버그를
  고침(`autojunk=False`). 잘못된 `⚠ OCR 신뢰도 낮음`의 원인이 될 수 있었음
- `looks_garbage`의 악센트 상한이 줄 수에 비례하도록 바뀜(여러 줄 식을 통째로 읽는 엔진에서 정상 식이 걸러지지 않게)
- `normalize_latex`가 `\cfrac`·`\dfrac`·`\tfrac`, `\operatorname*`, 글꼴 전환(`\sf`·`\tt`·`\it` 등)을 같게 취급해 골든 채점이
  표기 차이에 흔들리지 않음. `tools/bench_mathocr.py`의 `--engines` 기본값은 `p2t`
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
- 테스트 `tests/test_garbled_hint.py`, `tests/test_labels.py`(합성 2단 페이지), `tests/test_agreement.py`, `tests/test_bench.py` 추가(총 37개; p2t 관련 테스트까지 현재 63개)
- `.claude/`(스킬·에이전트·settings.json)와 CLAUDE.md "작업 라우팅": 단계별 모델 배정(방향 결정·진단 Fable, 구현 Opus,
  배선·검증·문안 Sonnet). 인계물 틀 `docs/decisions/_template.md`, `docs/issues/_template.md`
- 전체 코드 검토 반영(`docs/issues/code-review-2026-10-22.md`, 괄호는 발견 번호). 테스트 63 → 222개(새 파일 9개)
- 버그 수정
  - 챕터 분할: 책갈피 없는 PDF에서 프로그램이 죽던 것(#58), 자르는 위치를 지나는 본문 줄이 양쪽 파트에서 지워지던 것(#59),
    빈 파트·회전 쪽·쪽 맨 아래 목적지·합자 든 제목(#60–#63), 대문자 쪽 라벨(#67)
  - 자산 폴더: docx 변환이 같은 이름 폴더에 있던 다른 .md(같은 PDF, 같은 저자·연도 논문)의 그림을 지우던 것(#93, #111)
  - 수식: Elsevier CrossMark 배지가 가짜 수식 `eq-u01`이 되던 것(#94, #122, #123), 2단 쪽에서 다른 단 식 번호를 가져가던 것(#95),
    깨진 식 번호 옆 그린 수식이 사라지던 것(#108), 3행 수식이 버려지던 것(#72), 인라인 OCR이 앞 식의 시간 제한을 물려받던 것(#71),
    ` }` 넷 같은 정상 반복을 디코더 루프로 보던 것(#70), 보정 규칙 오작동(#48, #73, #76, #77), `\overline{{X}}`에 붙던 ⚠(#107)
  - 본문 보존: 인라인 수식이 영어 단어(up, as, min)를 바꾸거나 강조 기호를 삼키고 프라임·근호를 `$…$` 밖으로 떼던 것(#52–#54),
    `u^∗`(#55). Markdown의 `$$` 안 `|`·코드 펜스 안 `#`·`## Using C#`(#80, #87, #88), 짧은 제목이 다른 제목을 덮던 것(#81),
    각주 변환의 글·범위 손실(#82–#84), 표 칸 `<br>`(#90)
  - Word: 큰 연산자 `\bigcup` 등(#44), `--image-links markdown`에서 한글·괄호 폴더 그림 누락(#46), 한글 제목 중복(#47), `2^31`로
    끝나는 줄(#49). 서지정보: 공백 글리프 없는 PDF의 붙은 단어(#32), 키워드 하나만(#33), CrossRef HTML 태그(#34), 저널 머리글·
    Received 연도(#35, #36), 괄호 든 DOI(#37), 복합 성(#38), 데이터 DOI 오인(#39), `&` 저자(#40)
  - GUI: 추가 옵션의 `--chapters`·`--split-pages`·`--subchapters` 무시(#8, #117), anthropic 미설치 같은 오류에 조용히 멈춤(#9),
    따옴표 든 값(#10). 그 밖에 `--ocr-pages`의 경량화 사본 레이아웃(#106), `--image-links markdown` 하위 그림 링크(#100)
- 동작 변화
  - 수식 OCR 캐시 버전 3: 기존 캐시를 쓰지 않고 모든 식을 다시 OCR함(캐시에 보정 뒤 결과가 들어가므로 #72 등을 반영하려면 필요)
  - 이름: 한글·가나 파일·폴더 이름이 NFC(이전엔 자모 분리, #64, #112)이고 한글 제목 챕터가 `untitled`가 되지 않음. 자산 폴더 이름의
    `[ ] # ^ |`는 `-`로(#89, #113; 파일 이름은 그대로), 남의 그림이 든 같은 이름 폴더면 `-2`·`-3`…(#93). `p<쪽>-img<n>`은 전체 PDF
    쪽 번호(#99). 챕터 id는 목적지 없는 Part 책갈피를 버리지 않아 PDF 트리 모양을 따름(#68). 다시 변환하면 새 이름으로 생김
  - .md 수식 이미지 144 dpi(#97). `--math-mode image`는 수식 OCR을 돌리지 않음(#96), `--no-cache`는 캐시 파일을 건드리지 않음(#18)
  - Abstract 콜아웃: `a b s t r a c t`·`### **Abstract**`도 인식, Article history·Keywords 문단은 콜아웃 앞에 둠,
    구두점 없는 `Abstract We propose…`는 콜아웃 아님(#85, #86)
  - Word 번호 목록은 원문 번호를 그대로 둔 일반 문단(이전엔 Word 자동 번호가 문서 전체를 한 번호로 다시 매김), 글머리표는 `- * +`만(#45)
  - 입력 검증: 아무것도 고르지 않는 `--pages`·`--chapters`(`3-1`, `all:9`, 공백)는 전체 변환 대신 오류(#65, #66, #98, #114, #115),
    `--math-zooms`의 `4x,3x`·0·음수·nan은 종료 코드 2(#118). CrossRef·arXiv 조회 실패는 `-v` 없이도 경고 한 줄(#41)
  - `gui.json`에 `"v": 2`: 버전 없는 예전 설정의 `rapid`는 한 번만 `p2t`로 바꿈(#11). `Options.extra` 제거(`extra=`는 TypeError, #6)
- 정리·효율
  - 경량화 `cluster_rects` x 정렬 sweep(그림 경로 3000개 11.1 s → 1.5 s, #110), `get_image_info` 쪽당 1회(#128), 변환당
    `requests.Session` 하나(#125). bench: 골든 키에 같은 쪽 순번 `k`(#22), 폴백 엔진 건너뜀(#23, #28), HTML 이스케이프(#26), cp949(#27)
  - 미사용 코드·낡은 문구 정리(#0–#3, #5, #12, #13, #19–#21, #24, #29, #30, #43, #50, #51, #56, #57, #69, #74, #78, #79, #91,
    #101–#104, #109, #119–#121), 테스트 보강(#14–#17). 보류·기각한 발견과 이유는 검토 기록의 "결과 (2026-10-23)" 절

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
