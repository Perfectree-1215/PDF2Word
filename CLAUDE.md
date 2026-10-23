# pdf2word

PDF(논문·책·매뉴얼) → Word(.docx) 또는 Obsidian Markdown. 레이아웃 분석(pymupdf4llm + pymupdf-layout, CPU ONNX),
수식 OCR(Pix2Text MFR ONNX `p2t`, 폴백 RapidLaTeXOCR, 선택적으로 Claude 비전), 그림 추출, 서지정보, 책갈피 기반 챕터 분할.
사용자 문서는 README.md, 변경 내역은 CHANGELOG.md, 개발 절차와 코드 지도는 docs/DEVELOPMENT.md.

## 환경과 명령

- Python **3.12만** (rapid_latex_ocr → numpy<2 → 3.13 이상 wheel 없음). `pyproject.toml` `requires-python`
  (`>=3.12,<3.13`), `.python-version`, `main_gui.bat`의 `PY_MIN/PY_MAX/PY_TOP` 세 곳에 같이 적혀 있고, 바꾸면 `uv lock`.
  `main_gui.bat`는 가상환경을 3.12로만 만들고 받아들인다(uv가 없으면 설치해서 3.12를 내려받음).
- 환경: `uv sync --locked --extra dev` (`.venv`, 3.12). 의존성을 바꾸면 `pyproject.toml`과 `requirements.txt`를
  같이 고치고 `uv lock`.
- 테스트: `.venv\Scripts\python -m pytest tests -q` (250개, 모델·네트워크 불필요, 약 10초).
- 실행: `.venv\Scripts\python main_gui.py` (GUI) / `... main_gui.py paper.pdf --pages 1-5 -f md -o out -v` (CLI).
  변환은 수 분 걸리므로 백그라운드로 돌리고 `-v` 로그 파일을 본다. 결과는 `out/`(gitignore)에.
- GPU 없음. **torch 계열 의존성 금지**(CPU 전용). Word 수식 개체 변환은 Windows + Office에서만.

## 구조

`pdf2word/converter.py`(파이프라인, `_DocContext.render_page`가 `page_boxes`를 클래스별 처리) · `mathocr.py`(수식
OCR·검증·캐시) · `mfr_onnx.py`(Pix2Text MFR 모델 파일·onnxruntime 러너) · `inlinemath.py`(텍스트 레이어 인라인 수식 → `$...$`) · `vectormath.py`(벡터 도형 수식) ·
`outline.py`(책갈피·챕터·인쇄 쪽 번호) · `docx_out.py`(Word) · `obsidian.py`(Markdown 후처리) · `sheets.py`(그림 모음 시트, `--figure-sheet`) · `metadata.py` ·
`lighten.py` · `symbols.py` · `config.py`/`cli.py`(옵션은 두 곳에 같이) · `main_gui.py`(tkinter GUI, 인수 있으면 CLI).

## 규칙

- 파일 입출력은 항상 `encoding="utf-8"` 명시(콘솔은 cp949). 경로에 한글이 있을 수 있다.
- `main_gui.bat`는 ASCII만, CRLF(.gitattributes). 수정 후 PowerShell에서 `.\main_gui.bat --help`로 확인
  (Git Bash의 `cmd /c`는 한글 작업 폴더에서 실패).
- 버전은 `pdf2word/__init__.py`의 `__version__` 한 곳. 변경은 CHANGELOG `## 미공개`에 적고 릴리스 때 버전 제목으로.
- 논문 PDF·변환 결과(.docx, .md, `_asset-*/`)는 커밋하지 않는다(저작권). 테스트는 합성 데이터만 쓴다.
- 본문 텍스트는 절대 망가뜨리지 않는다: 치환은 원문 위치를 찾았을 때만, 못 찾으면 그대로 둔다(inlinemath 원칙).
- 커밋·푸시는 사용자가 시킬 때만. 커밋 메시지는 한국어 한 줄 요약(릴리스는 `vX.Y.Z: ...`).

## 작업 라우팅

| # | 단계 | 담당 | 호출 시점 |
|---|---|---|---|
| ① | 방향 결정(엔진·판정 기준·의존성·분할 방식) | `decide-direction` 스킬 | 구현 요청 안에 전략 선택이 숨어 있을 때, 코드보다 먼저 |
| ② | 막힌 문제 진단(OCR 보정 규칙, 레이아웃 예외) | `diagnose-blocker` 스킬 | "왜 깨지지", 같은 땜질이 두 번째 반복될 때 |
| ③ | 규칙·로직 구현 + 단위 테스트 | `implement-rule` 스킬 | ②의 `docs/issues/<slug>.md`가 있을 때 |
| ④ | 옵션 다섯 곳 배선 | `option-wiring` 에이전트 | 옵션이 생기거나 기본값이 바뀔 때 |
| ⑤ | pytest · 샘플 회귀 · bat 검사 | `verify-run` 에이전트 | 코드 수정 뒤마다, 커밋 전 |
| ⑥ | 커밋·PR·CHANGELOG 문안 | `commit-pr-draft` 에이전트 | 사용자가 커밋/PR을 시킬 때 |

### 원칙
- 로그·변환 결과·벤치마크 출력은 서브에이전트 안에서만 읽는다. 메인 세션에는 요약만 올린다.
- 순서는 ① → ② → ③ → (④) → ⑤ → ⑥. 전략이 정해지지 않은 채 ③을 시작하지 않고, ⑤ 없이 ⑥을 하지 않는다.
- 커밋·푸시는 메인 세션이, 사용자가 시킬 때만. 에이전트는 문안만 만든다.
- 인계물: ①→`docs/decisions/<slug>.md`(판정 기준 포함), ②→`docs/issues/<slug>.md`(검증 샘플 포함). 틀은 각 폴더의 `_template.md`.
- 읽는 쪽 작업(변환 결과를 원본과 대조 검토, 벤치마크 해석)은 아직 라우팅하지 않았다. 기본값으로 둔다.

### 폴백 (인계물이 없을 때)
- ③인데 `docs/issues` 기록이 없음: 한 파일·한 함수 이내면 바로 진행하고 원인은 커밋 메시지에 적는다. 두 파일 이상이거나 `mathocr`/`vectormath`/`converter`의 분류·보정 로직이면 ②를 먼저 돈다.
- ①②인데 관련 `docs/decisions` 기록이 없음: 기준을 새로 정하되 상태를 "임시"로 표시하고 되돌릴 조건을 적는다. 멈추지 않는다.
- ⑤인데 검증 샘플 목록이 없거나 PDF가 이 PC에 없음: pytest와 bat 검사만 돌리고 "회귀 샘플 없음"을 명시한다.
- ⑥인데 CHANGELOG에 `## 미공개`가 없음: 그 절을 새로 만든다.

### 등급 근거
| 단계 | 모델 | 이유 |
|---|---|---|
| 팀장(메인 세션) | Fable 5.1 xhigh (`.claude/settings.json`의 `CLAUDE_CODE_EFFORT_LEVEL`) | 배차·대화·판단. 프로젝트 설정이 모델을 고정하므로 `/model`로 바꿔도 다음 세션에 되돌아온다. 플랜에 따라 구독 한도가 아닌 별도 크레딧으로 청구될 수 있다 |
| ① ② | Fable 5.1 xhigh | 대조할 원본이 없고 틀리면 한참 뒤에 드러나며 되돌리기 어렵다(인터뷰 Q2) |
| ③ | Opus 5.5 xhigh | 판단은 ②에서 끝났고 코드로 옮기는 일. 테스트로 즉시 검출된다 |
| ④ ⑤ ⑥ | Sonnet 5.5 high | 기계적이고 원본·테스트와 대조 가능. 사용자가 GUI·샘플로 바로 확인한다(Q3) |
| 이름 없는 서브에이전트(general-purpose·claude) | Haiku 5.5 medium (`CLAUDE_CODE_SUBAGENT_MODEL`). 파일 세기·명령 실행·로그 요약 같은 기계적 작업용. 이미지 판독·회귀 대조·판단이 필요하면 호출 때 `model: sonnet`, 어려운 조사는 `model: opus`로 그 건만 올린다. Explore는 메인이 Fable일 때 내장 규칙으로 Opus, Plan은 메인 모델 상속 | 이 에이전트들은 설계상 로그·결과물을 통째로 읽어 토큰 비중이 크다(2026-10-23 `/usage` 74%, 10-24 62%). 비중은 줄지 않으므로 단가를 낮춘다 |

effort는 환경변수 `CLAUDE_CODE_EFFORT_LEVEL=xhigh`로 건다(2026-10-24 사용자 결정으로 `max`에서 내림). 이 환경변수는 스킬·에이전트 frontmatter의 `effort`보다 우선하므로, Opus xhigh·Sonnet high·Haiku medium은 `modelSettings`의 모델별 `maxEffortLevel` 상한으로 지킨다(Claude Code 2.1.267 이상).
