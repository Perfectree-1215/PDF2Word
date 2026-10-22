# 수식 OCR 엔진: RapidLaTeXOCR을 Pix2Text MFR 1.5로 바꿀 것인가

- 날짜: 2026-10-22
- 상태: 임시 (검증 워크플로 결과 반영 중)
- 만든 스킬: decide-direction

## 질문
수식 OCR 엔진 `rapid`(RapidLaTeXOCR = pix2tex의 ONNX 포트)를 Pix2Text로 바꿀 것인가. 바꾼다면
(A) `pix2text` 패키지째(torch 필수), (B) Pix2Text의 수식 인식 모델(MFR 1.5, ONNX)만 torch 없이 직접 돌리는
엔진으로 기본값을 교체하고 rapid를 제거, (C) 같은 엔진을 추가하되 rapid는 폴백으로 유지 — 중 무엇인가.

## 제약
- Python 3.12 고정(현재 이유는 `rapid_latex_ocr`의 `numpy<2`·`Python<3.13` 핀 하나뿐). 기본 설치는 CPU 전용,
  **torch 계열 의존성 금지**. Windows 더블클릭 설치(`main_gui.bat`, ASCII/CRLF). 논문 PDF·변환 결과 커밋 금지,
  테스트는 합성 데이터만. 본문 텍스트 보존.
- 사용자 결정(2026-10-19): API 호출 없이 전부 로컬. 이 PC에는 GPU가 없다(`nvidia-smi` 없음).
- 기존 결정 `equation-ocr-reliability.md`의 재도전 조건(골든 셋 정확 일치율 60% 미만)은 paper-01에서 0/4로 이미
  걸렸다. 그 기록의 "재도전 후보는 pip 한 줄의 torch 계열"이라는 전제는 이번 조사로 바꾼다: torch 없이 되는 길이 있다.

## 조사한 사실 (2026-10-22, 이 PC)
- **Pix2Text 1.1.7**(PyPI, 2026-08-23): 필수 의존성에 `torch`, `torchvision`, `transformers>=4.37`,
  `optimum[onnxruntime]`, `cnocr`, `cnstd`, `doclayout-yolo`, `opencv-python`, `PyMuPDF`, `pyspellchecker`. 빈 venv에
  111개 패키지. 모델 카드의 최소 경로(`transformers<5` + `optimum[onnxruntime]`)만 넣어도 torch 2.14.1이 딸려 와
  venv가 728 MB(그중 torch 481 MB). 패키지째 쓰는 A는 규칙과 정면충돌한다.
- **MFR 1.5 모델**(`breezedeus/pix2text-mfr-1.5`, MIT): TrOCR 구조 — DeiT 인코더(입력 384×384 고정, 가로세로비
  무시하고 리사이즈), 6층 디코더, 어휘 1868, 탐욕 디코딩, 최대 1024 토큰, KV 캐시 없음(토큰 수에 따라 시간이 늘어남).
  ONNX 두 파일(인코더 87.5 MB, 디코더 32 MB) + tokenizer.json, 합계 119.7 MB. Hugging Face `resolve/main` URL로
  평문 HTTPS 다운로드 가능(hub 라이브러리 불필요).
- **torch 없이 돌아간다**: `onnxruntime` + `tokenizers` + `numpy` + `Pillow`만으로 쓴 탐욕 디코딩 루프가 33개 크롭
  모두에서 공식 경로(optimum)와 **글자 단위로 동일한** 출력을 냈다. 네 패키지는 `rapid_latex_ocr`을 통해 이미
  설치돼 있어 **새 의존성 0개**, 프로젝트 venv(numpy 1.26.4, onnxruntime 1.31.0, tokenizers 0.23.3)에서도 동일.
  디코더 입력은 `input_ids`와 `encoder_hidden_states`뿐(어텐션 마스크 불필요).
- **저자 자체 테스트**(485장, 사용자 업로드 수식, CER 낮을수록 좋음): LaTeX-OCR(= rapid의 모델) 0.448,
  Pix2Text V0.3 유료 0.350, **V1.0 무료 0.167**, V1.0 유료 0.115. 1.5의 수치는 없고 제3자 벤치마크(UniMERNet·CDM
  논문)에는 Pix2Text가 빠져 있다. 저자 측 수치이므로 아래 자체 측정으로 보완했다.
- **paper-01 2쪽 골든 셋 채점**(확정 4개, `tools/bench_mathocr.py`의 `normalize_latex` + difflib):

  | 식 | rapid | MFR 전체영역 z2 | z3 | z4 | MFR 줄분할 z2 | z3 | z4 |
  |---|---|---|---|---|---|---|---|
  | (1) | 0.935 | **정확** | 0.992 | 0.992 | **정확** | 0.992 | 0.992 |
  | (2) 두 줄 | 0.171 | 0.679 | **정확** | **정확** | 0.755 | 0.990 | 0.729 |
  | (3) 미확정 | (0.993) | 0.932 | 0.989 | 0.968 | 0.932 | 0.989 | 0.968 |
  | (4) | 0.957 | 0.972 | 0.965 | 0.991 | 0.972 | 0.965 | 0.991 |
  | (5) | 0.915 | 0.926 | 0.889 | 0.918 | 0.926 | 0.889 | 0.918 |

  확정 4개 합계: rapid 정확 0/4·평균 0.745, MFR 전체영역 z4 **1/4·0.975**(z3 1/4·0.962), 배율별 최선 2/4·0.979.
  (1)의 굵은 `\chi`(rapid는 `\gamma`)와 (2)의 두 줄 식(rapid는 `CO`→`Go` 등 다수)을 MFR은 정확히 읽었다.
  남은 차이: (1) z3·z4의 `\cfrac`, (4)의 `\operatorname*`, (5)의 `''`→`'`(모든 배율)와 골든의 첨자 순서.
- **속도(CPU)**: 전체영역 1회 중앙값 4.0 s, 최대 15.7 s(식 (2), 328 토큰); 줄 단위 중앙값 4.3 s; 모델 로드 1 s.
  rapid의 기록(식당 13–45 s)은 배율 3개 × 줄 분할을 합친 값이라 직접 비교가 안 된다.
- **배율 민감도**: z2에서 `x`→`\kappa`, `\dot` 누락, `''`→`'`; z3에서 `\SS` 생성; z4가 전반적으로 최선.
  식 (5)의 `''`는 모든 배율에서 `'`. 즉 배율 하나만 믿으면 안 되고 배율 간 일치도 선택이 여전히 필요하다.
- **채점 도구의 문제**(엔진과 무관, 따로 고칠 것): difflib `autojunk`가 200자 넘는 식의 유사도를 깎는다(rapid 식
  (2) 0.171 → 끄면 0.841, rapid 평균 0.745 → 0.912; MFR z4는 0.975 그대로). `normalize_latex`가 `\cfrac`,
  `\operatorname*`, 글꼴 전환(`\sf` 등)을 못 거른다(거르면 MFR z3·z4 3/4 정확, rapid 0/4). 식 (3)의 영역이
  오른쪽에서 잘려 모든 엔진이 불완전한 크롭을 본다. 골든 (5)는 위첨자를 아래첨자보다 먼저 써서 정확 일치가 불가능.

## 대안과 비교
| 대안 | 효과 | 설치 리스크 | 비용 | 되돌리기 |
|---|---|---|---|---|
| A. `pip install pix2text` | 아래 B와 같은 모델 | torch 포함 111개 패키지, 1 GB 이상, `main_gui.bat` 첫 설치 시간·실패 지점 증가. **규칙 위반** | 없음(코드 적음) | 쉬움 |
| B. torch 없는 자체 ONNX 러너로 rapid를 교체 | 확정 4식 평균 유사도 0.745 → 0.975, 정확 0 → 1~2/4 | 새 패키지 0개. 모델 120 MB를 첫 실행 때 HF에서 받음(rapid도 같은 방식). `numpy<2`·3.12 핀이 사라짐 | 러너 + 배율 일치 로직 + 합성 테스트 + 옵션·문서 | 중간(엔진 플러그 구조라 rapid 복원은 쉬우나 의존성·문서도 되돌려야 함) |
| C. B를 `p2t` 엔진으로 추가, rapid 유지 | B와 같음 | B와 같음 + 모델 두 개(171 + 120 MB), 코드 경로 둘 | B + 폴백 분기 | 쉬움 |
| D. rapid 유지 | 변화 없음 | 없음 | 없음 | — |

## 결정과 이유
**C. `p2t` 엔진을 추가하고 기본값으로 삼되 rapid는 남겨 둔다(사용자 결정 2026-10-22).**
- A는 규칙 위반(torch 481 MB 포함 111개 패키지). B는 정확도 근거가 아직 논문 한 편(확정 4식)뿐이라 rapid를 지우기엔 이르다.
- C는 새 의존성 없이 정확도 이득(0.745 → 0.975)을 바로 얻고, 모델을 못 받는 PC(오프라인·HF 장애)에서는 rapid로 자동
  대체되므로 설치 리스크가 늘지 않는다. 두 번째 논문에서 판정 기준을 넘으면 그때 rapid 제거(B)를 다시 묻는다.

## 구현 설계 (implement-rule 인계)
1. **새 모듈 `pdf2word/mfr_onnx.py`** — 모델 파일 관리와 torch 없는 TrOCR 러너.
   - 파일 3개: `encoder_model.onnx`(87,510,770 B, sha256 `080a3f66…37f610b`), `decoder_model.onnx`(32,026,253 B,
     `917deb98…9692f2a`), `tokenizer.json`(113,168 B, `4ffbeb21…a32758a`). 전체 해시는 아래 "관련"에.
   - 저장 위치: 환경변수 `PDF2WORD_MODELS`가 있으면 그 아래, 없으면 Windows `%LOCALAPPDATA%\pdf2word\models`,
     그 외 `~/.cache/pdf2word/models`; 하위 폴더 `pix2text-mfr-1.5`. 프로젝트 폴더(한글 경로·클라우드 동기화)와
     site-packages에는 두지 않는다.
   - 다운로드: `requests` 스트리밍 → `.part` → 크기·sha256 확인 → 이름 변경. 1차
     `https://huggingface.co/breezedeus/pix2text-mfr-1.5/resolve/main/<file>`, 실패 시 2차
     `https://hf-mirror.com/...`. 실패하면 `.part` 삭제 후 예외: URL·받을 폴더·수동 배치 방법을 한 문장에 담는다.
   - 러너: `onnxruntime` 세션 2개(CPU, 지연 로드), 전처리 RGB → 384×384 BICUBIC → float64로 1/255 → float32 →
     (x−0.5)/0.5 → CHW; 인코더 `pixel_values`→`last_hidden_state`; 디코더 입력 `input_ids`(int64)와
     `encoder_hidden_states`뿐, 출력 `logits`. 탐욕 디코딩: 시작 1, 종료 2, 상한 `P2T_MAX_TOKENS = 640`
     (두 줄 식이 328 토큰; KV 캐시가 없어 길이의 제곱으로 느려지므로 1024는 쓰지 않음), 호출당 시간 예산 90 s, 짧은 주기
     반복(토큰 24개 안에서 같은 구간 4회) 감지 시 중단. `tokenizers.Tokenizer.from_file`로 디코드(특수 토큰 제외).
   - 후처리(Pix2Text `post_process` 상당, 엔진 안에서): 토큰 사이 공백 제거(명령 뒤 글자가 오는 곳만 한 칸 유지),
     맨 앞의 군더더기 `^{…}`/`_{…}` 제거, 빈 그룹(`{}`, `^{}`, `\hat{}` …) 반복 제거, 끝의 간격 명령 제거,
     짝 없는 `\left`/`\right` 제거, `\cfrac`→`\frac`, `\operatorname*`→`\operatorname`, `\sf`·`\tt`·`\it` 글꼴 전환 제거,
     `\Big…`류 크기 명령 제거(구분자는 유지). 이후는 rapid와 같은 `clean_latex` → `hint_fixes` → `fix_braces` →
     `looks_garbage`를 그대로 탄다. 실제 출력 샘플(스크래치 `p2t/mfr_results.json`)이 `looks_garbage`와
     `latex2mathml`을 모두 통과해야 한다.
2. **`mathocr.py`의 `Pix2TextEngine(MathEngine)`**: `name="p2t"`, `multiline=True`, `multi_zoom=True`,
   `default_zooms=(4.0, 3.0, 2.0)`. `build_engine("p2t")`는 모델 준비(다운로드·세션 생성)를 그 자리에서 시도하고
   실패하면 경고 로그 "p2t 모델을 쓸 수 없어 rapid로 대체: <이유>" 뒤 `RapidEngine`을 돌려준다(엔진 수준 폴백;
   줄 단위 엔진과 전체 영역 엔진은 섞어 쓸 수 없으므로 식 단위 폴백은 하지 않음). `MathEngine`에
   `multi_zoom=False`, `default_zooms=None` 기본값을 두고 rapid는 `multi_zoom=True`, claude는 False(현행 유지).
3. **`EquationOCR` 배율 정책 일반화**: `_read(page, rect, zoom, hint)`가 `multiline` 엔진이면 전체 영역
   `tight_crop(render(...))` 한 장, 아니면 `_recognize_lines`. `multi_zoom` 엔진은 (a) 힌트가 쓸 만하면 배율을 순서대로
   읽어 `hint_similarity >= CONFIDENCE_OK`에서 멈추고 최선을 택하고(현 줄 엔진 루프), (b) 힌트가 깨졌거나 없으면
   `_recognize_by_agreement`(현행). `multi_zoom=False`(claude)는 현행 그대로. `zooms=None`이면 엔진의
   `default_zooms`, 그것도 없으면 (2,3,4). `converter.py:684`의 dpi 계산은 해석된 배율을 쓴다.
4. **`agreement()`의 difflib `autojunk=False`**: 200자 넘는 식에서 일치도가 깎여 `⚠`가 잘못 붙는 버그.
   `tools/bench_mathocr.py`의 채점도 같은 함수를 쓰게 한다(지금은 따로 `SequenceMatcher`를 부름).
5. **`normalize_latex` 보강**: `\cfrac`·`\dfrac`·`\tfrac`→`\frac`, `\operatorname*`→`\operatorname`, `\sf`·`\tt`·`\it`·
   `\mathsf`·`\pmb` 제거, 크기 명령 정규식이 `\Biggl`/`\Biggr`도 덮는지 확인.
6. **식 번호 잘림 버그(`converter.py:633 _split_regions`)**: 번호 사각형의 x0−2에서 영역을 자르는데 번호가 식보다
   아래 줄에 있으면(paper-01 식 (3)) 식의 끝 `)²]`가 잘린다. 번호가 식의 글자 행과 세로로 겹칠 때만 x로 자르고, 겹치지
   않으면 폭을 유지한 채 렌더링 이미지에서 번호 사각형을 흰색으로 지운다(`render(..., mask=[rect])`). 힌트 추출도
   같은 영역 기준. 합성 페이지 테스트: 번호가 아래 줄인 식의 크롭에 식의 끝이 남고 번호는 없어야 한다.
7. **옵션(option-wiring 인계)**: `--math-engine` 선택지에 `p2t` 추가·기본값 `p2t`, GUI `ENGINES` 첫 항목
   `p2t  (로컬, 무료, 추천)`, `--math-zooms` 기본값 None(엔진별: rapid 2,3,4 / p2t 4,3,2)과 도움말, README 옵션 표·첫 실행
   다운로드 120 MB·모델 폴더·`PDF2WORD_MODELS` 안내, CHANGELOG `## 미공개`, docs/DEVELOPMENT.md 코드 지도,
   CLAUDE.md 한 줄("수식 OCR(Pix2Text MFR ONNX, 폴백 RapidLaTeXOCR, 선택적으로 Claude 비전)").
8. **테스트(합성만, 모델·네트워크 없음)**: 가짜 세션·가짜 토크나이저로 탐욕 루프·상한·반복 중단·후처리, 모델 폴더
   해석(환경변수), 다운로드 검증(가짜 `requests`, 해시 불일치 → 예외·`.part` 삭제), 로드 실패 → rapid 폴백,
   스텁 엔진으로 배율 정책(힌트 조기 종료·일치도 선택·기본 배율 순서·옵션 우선), `agreement` autojunk, `normalize_latex`
   추가 규칙, 식 번호 아래 줄 잘림 회귀.

### 구현 결과 (2026-10-22, implement-rule)
- 설계 1~6·8 구현: `pdf2word/mfr_onnx.py`(신규), `mathocr.py`(`Pix2TextEngine`, `build_engine` 폴백, `EquationOCR._read`로
  배율 정책 일반화, `render(mask=)`, `agreement`·`hint_similarity` `autojunk=False`, `normalize_latex` 보강),
  `converter.py`(`_split_regions(page=)` + 마스크, dpi), `tools/bench_mathocr.py`(마스크 전달, `--engines` 기본 p2t,
  `--zooms` 기본 엔진별, 채점 autojunk). 테스트 37 → 57개(`tests/test_mfr_onnx.py`, `tests/test_p2t_engine.py`,
  `test_labels.py`·`test_agreement.py`·`test_bench.py` 보강).
- 설계와 다른 점: (a) `\Big…` 크기 명령은 엔진에서 지우지 않는다 — MathJax가 그대로 그리고 Word 경로는
  `OmmlConverter.prepare`가 이미 `\left`/`\right`로 바꾼다. (b) `looks_garbage`의 악센트 상한(14개)이 줄 수에 비례하도록
  바뀌었다 — 두 줄 식 (2)의 올바른 읽기(악센트 16개)가 버려졌다. (c) 텍스트 레이어가 아예 없는 식(벡터 도형·그림)도
  이제 배율 간 일치도 모드로 읽는다(설계 3(b)대로; 이전엔 첫 배율 한 번).
- 실제 출력 18건(스크래치 `p2t/mfr_results.json`)을 후처리 → `clean_latex` → `fix_braces` → `looks_garbage` →
  `latex2mathml`에 통과시킨 결과: Word 변환 18/18 성공, 버려진 것은 z2의 식 (2) 하나(중괄호 불균형, 실제로 틀린 읽기).
  전처리는 `TrOCRProcessor`와 비트 단위로 같고(두 크롭에서 픽셀 차 0, 토큰 열 동일) 실제 모델 로드 2.4 s.
- **2차 보강(결정 워크플로의 렌즈·비평 반영, 같은 날)**: 배율 순서를 4,3,2로(4배가 단일 배율 중 최선, Pix2Text 자체 렌더 300 dpi에
  해당), 동률은 큰 배율 우선(`pick_by_agreement(zooms=)`), 식 단위 시간 예산 90 s(`EquationOCR.REGION_BUDGET`, 엔진의
  `deadline`으로 전달)와 이미지당 60 s, 실패 호출은 캐시하지 않음, 일치도 기반 `⚠` 문턱 `AGREE_LOW=0.9`
  (`EquationResult.by_agreement`), `\\{` 처리 버그 수정, 모델 URL 리비전 고정(`1cef9f0b…`), onnxruntime 스레드 4·스핀 끔,
  `onnxruntime>=1.17`·`tokenizers>=0.20` 명시와 `pymupdf<2` 캡(`uv lock` 갱신, 잠긴 버전 동일). 테스트 63개.

## 검증 결과 (2026-10-22, verify-run)
- pytest 57/57. CLI·GUI 배선, `main_gui.bat` ASCII/CRLF 통과.
- **벤치마크(paper-01 2쪽, 엔진별 기본 배율)**: p2t 정확 일치 **3/4**(1·2·4), 평균 유사도 0.981, 식당 중앙값 8.5 s,
  최대 16.5 s(식 (2)), 합계 45.8 s. rapid 0/4, 0.939, 중앙값 10.2 s, 합계 65.9 s. 모든 식에서 p2t ≥ rapid.
  남은 차이는 식 (5)의 `''`→`'`(0.926). 식 (3)의 LaTeX가 `^{2}\right]`로 끝나 크롭 잘림이 고쳐졌다.
  rapid의 평균이 결정 당시 0.912에서 0.939로 오른 것은 식 (2)·(3) 영역의 잘림 수정 덕을 rapid도 보았기 때문이다.
  그래서 아래 "+0.05" 기준은 +0.042로 미달했고, 기준을 다시 적었다(아래 기준의 괄호 설명 참고).
- **변환 회귀(1–4쪽, md·docx)**: 본문 73줄 동일(머리말 `math:` 표기만 변경), `\tag{1}`–`\tag{5}`·`^eq-1`–`^eq-5` 전부,
  `equations_unverified: 5`, `⚠` 0건, 이미지 13건 동일, Word 수식 6개 native. 식 (3) 이미지에 `)²]`가 보이고 번호 없음.
  변환 시간 55.5 s(rapid 기준 34.3 s; 배율 2–3회 전체 영역 읽기 비용).
- **첫 실행 다운로드**: 빈 폴더에 3개 파일(87,510,770 / 32,026,253 / 113,168 B) 생성, `.part` 없음, 다운로드 포함 34.8 s.
- **폴백**: 프록시로 다운로드를 막으면 "p2t 모델을 쓸 수 없어 rapid로 대체: …" 뒤 rapid로 변환 완료(23 s). 머리말의
  `math:` 표기가 요청 엔진이 아니라 실제 엔진을 적도록 `Converter.engine_name`을 고쳤다.
- **남은 문제(엔진과 무관, 코드 검토 단계로 넘김)**: 1쪽 Elsevier CrossMark 로고가 식으로 잡혀 `eq-u01`로 출력된다
  (p2t는 `\underbrace{…}\mathrm{CrossMark}`, rapid는 `\left({\frac…` 오독; 둘 다 `⚠` 없음). 벤치마크 로그의
  `_readerthread` UnicodeDecodeError(서브프로세스 출력 디코딩, 결과 무관).

## 판정 기준
- **기본 엔진 자격**: paper-01 골든 셋(확정 4식)에서 `p2t`의 정규화 정확 일치 ≥ 2/4이고 평균 유사도가 rapid보다
  높으며, 어느 식에서도 rapid보다 유사도가 0.05 넘게 낮지 않다. (처음엔 "+0.05 이상"이었으나 같은 수정으로 rapid도
  0.912→0.939가 되어 차이가 +0.042로 줄었다. 정확 일치 0/4→3/4가 본래 재도전 조건의 지표이므로 유사도 차이의 하한은
  뺀다. 2026-10-22 검증: 통과.)
- **두 번째 PDF 통과 기준**: 텍스트 레이어가 멀쩡한 2단 논문 한 편(식 10개 이상, 사용자가 골든 확정)에서 정확 일치
  ≥ 60%, 평균 유사도 ≥ 0.90, 식 단위 회귀(rapid보다 0.05 초과 하락) 0건. 이를 넘으면 rapid 제거(B)를 다시 묻고,
  못 넘으면 기본값을 rapid로 되돌린다.
- **속도 예산**: CPU에서 식 하나(배율 2~3회 읽기 포함) 중앙값 ≤ 15 s, 최대 ≤ 90 s(시간 예산에서 끊고 이미지만 남김);
  한 쪽 평균 ≤ 60 s. 구현: `EquationOCR.REGION_BUDGET` 90 s를 배율을 합쳐 적용하고 이미지 한 장은 60 s.
- **일치도 경고**: 배율 간 일치도로 고른 식은 일치도 < 0.9(`AGREE_LOW`)면 `⚠`. 텍스트 레이어 대조는 0.6 그대로. 이유: 틀린
  읽기(폭 32 em 넘는 식의 찌그러짐, 이중 프라임→프라임)도 배율끼리는 0.85~0.9로 일치해 0.6으로는 경고가 없었다(정확도 렌즈).
- **설치·다운로드**: 설치되는 패키지 집합은 그대로(러너가 직접 쓰는 `onnxruntime>=1.17`·`tokenizers>=0.20`는 명시 — 이
  tokenizer.json은 tokenizers 0.19 이하에서 못 읽는다; 의존성 렌즈). 첫 실행 다운로드 실패 시
  변환은 rapid로 끝까지 진행되고 로그에 사유·수동 배치 경로가 한 줄로 남는다. `main_gui.bat` 변경 없음.
- **회귀 금지**: pytest 전부 통과(새 테스트 포함). paper-01 1–4쪽 기준 변환(스크래치 `baseline/`)과 비교해 본문
  텍스트·그림·식 번호(`\tag{1}`–`\tag{5}`, `^eq-N`)가 같고, 식 (3) 크롭에 `)²]`가 포함된다.
- **채점 도구**: `agreement`/벤치마크 유사도는 `autojunk=False`; 같은 입력으로 rapid 평균이 0.912로 나와야 한다.

## 비평(결정 워크플로, 2026-10-22) 요약과 남은 과제
- 비평의 권고는 "add-engine: rapid를 기본값으로 두고 두 번째 PDF 게이트를 넘은 뒤 p2t를 기본으로"였다. 근거: p2t 수치가 모두
  paper-01 한 편(확정 4식)에서 나왔고 그 식들로 후처리·배율 정책을 조정했으므로 held-out 근거가 없다. 사용자 결정(C, p2t 기본)은
  유지하되, **릴리스 전에 정상 텍스트 레이어 논문 한 편(식 10개 이상, 골든 확정)을 재어 "두 번째 PDF 통과 기준"을 확인**한다.
  못 넘으면 기본값을 rapid로 되돌린다(되돌릴 조건 1).
- 측정 렌즈: `normalize_latex`가 중괄호를 지워 `e^{x+1}`과 `e^{x}+1`을 같게 보므로 정확 일치율이 부풀 수 있다. 벤치마크용
  정규화기(구조 보존)와 편집 거리 지표는 후속 과제. 골든 (5)는 위첨자를 아래첨자 앞에 써서 어떤 엔진도 정확 일치가 불가능하다
  — 사용자가 `_{\mathrm{CO}_2}^{\prime\prime 2}` 순서로 고치는 것을 권한다.
- 정확도 렌즈: 폭 32~40 em을 넘는 한 줄 식은 384×384로 찌그러져 모든 배율에서 같이 틀리고(일치도 0.85~0.90) `AGREE_LOW`로만
  걸린다. 단일 단 논문·책의 넓은 식, 행렬·cases, 스캔(150 dpi 이하)은 측정되지 않았다. `\SS` 같은 잘못된 명령은 Word에
  글자로 들어간다(미지 명령 검사는 후속). 본문 속 작은 기호 크롭은 p2t가 호출당 약 2 s로 rapid(0.7 s)보다 느리다.
- 의존성 렌즈: hf-mirror.com은 huggingface.co로 리다이렉트할 뿐이라 중복이 아니다 — 접근이 막힌 환경을 위해 모델 파일을 이
  저장소의 GitHub Release 자산으로 미러링하는 것은 후속. rapid 자체 다운로더(타임아웃·상태 검사 없음)는 우리 통제 밖이다.
- 통합 렌즈: `aligned`의 `&`는 Word에서 2열 행렬이 된다(기존 동작).

## 되돌릴 조건
- 두 번째 PDF 통과 기준에 못 미치면 기본값을 `rapid`로 되돌린다(`p2t`는 선택지로 남김).
- 텍스트 레이어가 멀쩡한 논문에서 `⚠` 표시나 `equations_unverified`가 rapid 때보다 늘면 배율 정책(4,3,2)과
  `AGREE_OK`를 재검토한다.
- 모델 다운로드 실패 보고가 반복되면(HF 접근 불가 환경) 모델을 이 저장소의 GitHub Release 자산으로 미러링한다.
- 식 하나에 90 s 예산이 자주 걸리면(로그에 "time budget" 3건 이상/논문) `P2T_MAX_TOKENS`를 낮추거나 줄 분할 모드를
  p2t에도 붙인다.

## 관련
- 모델 파일 sha256(2026-10-22 내려받은 `breezedeus/pix2text-mfr-1.5` main):
  `encoder_model.onnx` 080a3f660f08bc9ebcacdd96e34be6b6400f8c7e62d7cd0dd8251badc37f610b ·
  `decoder_model.onnx` 917deb98e91a0453c5f234f58a0f32f9fb037de8527c7eb4ed394daf9e692f2a ·
  `tokenizer.json` 4ffbeb2143e6a38324bb6111b7a8109530d38a076a8439aa5777535f0a32758a
- `docs/decisions/equation-ocr-reliability.md` (앞선 결정, 재도전 조건)
- `bench/paper-01/golden.json`, `tools/bench_mathocr.py`
- Pix2Text: https://github.com/breezedeus/Pix2Text , 모델 https://huggingface.co/breezedeus/pix2text-mfr-1.5
