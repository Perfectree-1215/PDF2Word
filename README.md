# pdf2word

현재 버전 **v1.0.0** · 변경 내역은 [CHANGELOG.md](CHANGELOG.md)

논문 PDF 한 편을 **Word 문서(.docx)** 또는 **Obsidian 노트(.md)** 로 바꿔 주는 작은 도구입니다.
본문·그림·표는 물론 **수식까지** 옮기고, 제목·저자·DOI 같은 서지정보도 자동으로 채워 줍니다.
GPU가 없는 보통 노트북에서 돌아가고, 인터넷은 서지정보 조회에만 씁니다(없어도 됩니다).

![pdf2word GUI](docs/gui.png)

**이런 걸 해 줍니다**

- 📄 본문, 제목, 섹션, 표, 그림을 원래 읽는 순서대로 옮깁니다.
- ∑ 수식은 **원본을 잘라낸 이미지**를 먼저 넣고, 그 아래에 OCR로 읽은 수식을 둡니다. Word에서는 **편집 가능한 Word 수식**, Obsidian에서는 `$$ … $$` LaTeX입니다. OCR이 미심쩍으면 `⚠ OCR 신뢰도 낮음` 표시가 붙으니 이미지와 대조하면 됩니다.
- 🖼 그림은 "Figure 3" 캡션에 맞춰 `fig3.png`, `fig3a.png`처럼 이름을 붙입니다.
- 🔖 DOI를 찾아 제목·저자·저널·연도를 받아 문서 머리(Word) 또는 frontmatter(Obsidian)에 넣습니다.

---

## 1. 설치 (처음 한 번)

**준비물**

| 항목 | 비고 |
|---|---|
| Windows 10/11 | macOS, Linux에서도 되지만 Word *수식* 변환은 Windows + Microsoft Office에서만 됩니다(없으면 LaTeX 문자열로 대신 적음). |
| Python 3.10 이상 | 명령 프롬프트에서 `python --version` 으로 확인. 없으면 [python.org](https://www.python.org/downloads/)에서 설치하고 "Add Python to PATH"에 체크. |
| uv (권장) | 가상환경을 쉽게 만들어 줍니다: `pip install uv` |

**설치**

1. 이 저장소를 `git clone` 하거나 ZIP으로 받아 적당한 폴더에 풉니다.
2. 그 폴더에서 명령 프롬프트(또는 PowerShell)를 열고 아래 두 줄을 실행합니다.

```bash
uv venv
```

```bash
uv pip install -e .
```

uv가 없으면 대신:

```bash
python -m venv .venv && .venv\Scripts\activate && pip install -e .
```

3. 끝입니다. 첫 변환 때 수식 인식 모델(약 170 MB)을 한 번 내려받습니다.

> 폴더를 다른 곳으로 옮기면 `.venv` 폴더를 지우고 2번을 다시 실행하세요. 가상환경은 만든 위치에 묶여 있습니다.

---

## 2. 사용하기 (GUI)

1. **`main_gui.bat`** 를 더블클릭합니다. (콘솔 창 없이 창만 뜹니다. 가상환경 안에서 `python main_gui.py` 를 실행해도 같습니다.)
2. **📄 PDF 파일** – `파일 추가`로 논문 PDF를 고릅니다. 여러 개를 한 번에 골라도 되고, `폴더 추가`로 폴더째 넣어도 됩니다.
3. **📁 저장 위치와 형식** – 기본은 *PDF 옆에 Word 저장*입니다. Obsidian 노트가 필요하면 `Obsidian Markdown`(또는 `둘 다`)을 고르고, `폴더 선택…`으로 vault 안의 폴더를 지정하면 바로 노트가 됩니다.
4. **∑ 수식** – 기본값 그대로 두면 됩니다. `rapid`는 무료 로컬 OCR, `claude`는 더 정확하지만 Anthropic API 키와 요금이 듭니다.
5. **✨ 변환 시작** – 아래 로그 창에 진행 상황이 흐르고, 끝나면 **📂 결과 폴더 열기**가 켜집니다.

처리 시간은 20쪽 논문 기준 보통 2~8분이고, 수식이 많을수록 깁니다. 같은 논문을 다시 돌리면 OCR 결과가 캐시되어 1분 안팎이면 끝납니다. 마지막에 쓴 설정은 기억됩니다.

GUI에 없는 옵션은 **추가 옵션** 칸에 명령줄 옵션을 그대로 적으면 됩니다(예: `--author Kim --year 2024 --citations footnotes`). 옵션 목록은 [5절](#5-고급-명령줄과-옵션)에 있습니다.

---

## 3. 결과물 보는 법

### Word (.docx) — 기본

파일 하나에 모든 그림과 수식 이미지가 들어 있습니다.

- 머리: 제목 → 저자 → 저널·연도·DOI → Keywords
- 본문: 섹션 제목(제목 1~3), 문단, 표(Word 표), 그림(캡션 스타일)
- 수식: `[원본 수식 이미지]` 바로 아래에 Word 수식과 오른쪽 정렬된 식 번호. 수식 위에서 더블클릭하면 Word 수식 편집기로 고칠 수 있습니다.
- 본문 속 작은 수식(ρ<sub>f</sub>, u<sub>i</sub> 같은 것)도 Word 수식으로 들어갑니다.

### Obsidian (.md + 에셋 폴더)

```
papers\
├── Ma-2025-Numerical-modeling-wet-milling-improved-CFD-DEM-VOF.md
└── _asset-Ma-2025\
    ├── fig1.png  fig2a.png  fig2b.png …   # 캡션(Figure 2.)에 맞춘 이름, 서브패널은 a/b/c
    ├── p7-img3.png                        # 캡션을 못 찾은 그림: p<페이지>-img<번호>
    └── eq-12.png                          # 수식 이미지(식 번호 기준)
```

- 노트 머리에 YAML frontmatter(title, authors, year, journal, doi, keywords, tags: paper …)가 들어가 Dataview 등에서 바로 쓸 수 있습니다.
- 그림은 `![[_asset-Ma-2025/fig2a.png]]` 위키링크로, Abstract는 `> [!abstract]` 콜아웃으로 들어갑니다.
- 수식은 이미지 다음에 `$$ … \tag{3} $$`가 오고 `^eq-3` 앵커가 붙어 `[[노트#^eq-3]]`처럼 링크할 수 있습니다.

---

## 4. 자주 묻는 질문

**수식이 틀리게 읽혔어요.**
OCR은 완벽하지 않습니다. 그래서 항상 원본 이미지를 수식 위에 같이 넣습니다. 이미지를 보고 Word에서 고치거나, `--math-engine claude`(API 키 필요)로 다시 변환해 보세요. 정도가 심하면 자동으로 `⚠ OCR 신뢰도 낮음 (34%)` 표시가 붙습니다.

**Word에 수식 대신 `\frac{…}` 같은 글자가 들어가요.**
Microsoft Office가 없는 PC입니다. Word 수식은 Office에 포함된 변환 파일(`MML2OMML.XSL`)로 만들기 때문에, Office가 없으면 LaTeX 문자열로 대신 적습니다. Word 365에서는 그 글자를 선택해 `Alt + =` 로 수식으로 바꿀 수 있습니다.

**처음 실행이 오래 걸려요.**
첫 변환 때 수식 인식 모델 약 170 MB를 내려받습니다. 한 번만 받습니다.

**"pdf2word 패키지를 불러올 수 없습니다" 창이 떠요.**
가상환경 밖의 파이썬으로 실행된 것입니다. `main_gui.bat`로 실행하거나 `.venv\Scripts\python.exe main_gui.py`를 쓰세요.

**폴더를 옮겼더니 안 돼요.**
`.venv`를 지우고 1절의 설치 2번을 다시 하세요.

**스캔한 PDF(글자가 선택되지 않는 PDF)는요?**
글자가 없으면 본문을 뽑을 수 없습니다. Tesseract OCR을 설치한 뒤 `--ocr-pages` 옵션을 쓰면 됩니다.

**한 페이지에 그림이 수십 장인 PDF가 너무 느려요.**
자동으로 이미지 묶음을 가볍게 만들어 처리하지만(`--no-lighten`으로 끌 수 있음), 그래도 느리면 `--pages 1-10`처럼 범위를 나눠 돌리세요.

---

## 5. 고급: 명령줄과 옵션

GUI와 같은 기능을 명령줄로 쓸 수 있습니다(여러 파일 일괄 처리, 스크립트 자동화에 유리).

```bash
pdf2word paper.pdf                       # Word (기본)
pdf2word paper.pdf -f md -o D:\Vault\papers   # Obsidian 노트를 vault 폴더에
pdf2word "E:\Download\*.pdf" -f both     # 폴더 안 모든 PDF를 둘 다로
pdf2word paper.pdf --math-engine claude  # 수식 OCR을 Claude 비전으로
pdf2word paper.pdf --author Kim --year 2024 --offline   # 서지정보 직접 지정
python main_gui.py paper.pdf -f md       # main_gui.py 도 인자를 주면 명령줄로 동작
```

### 옵션

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `-f, --format` | `docx` | `docx`(Word) / `md`(Obsidian Markdown + 에셋 폴더) / `both` |
| `-o, --out-dir` | PDF 폴더 | 출력 폴더 |
| `--math-engine` | `rapid` | `rapid`(로컬, 무료) / `claude`(API) / `none`(OCR 없이 이미지만) |
| `--math-mode` | `both` | `both`(이미지 + OCR 결과) / `latex`(OCR 결과만, 실패·불확실 시 이미지) / `image` |
| `--docx-math` | `native` | Word 수식: `native`(편집 가능한 수식, Office 필요) / `text`(LaTeX 문자열) |
| `--author`, `--year`, `--title` | 자동 | 서지정보를 직접 지정 (파일·폴더 이름에 쓰임) |
| `--offline` | 끔 | CrossRef/arXiv 조회 안 함 |
| `--asset-template` | `_asset-{author}-{year}` | 에셋 폴더 이름. `{title}`, `{stem}` 사용 가능 |
| `--name-template` | `{author}-{year}-{title}` | 결과 파일 이름 |
| `--image-links` | `wiki` | `wiki` = `![[…]]`, `markdown` = `![](…)` |
| `--citations` | `keep` | `footnotes`로 하면 `[12]` → `[^12]` 각주 |
| `--pages` | 전체 | `1-5,8`처럼 1부터 세는 페이지 범위 |
| `--dpi` | 200 | 그림 해상도 |
| `--keep-headers` | 끔 | 머리글/바닥글 유지 |
| `--no-inline-math` | 끔 | 본문 속 수식 *이미지* OCR 끄기 |
| `--no-inline-text-math` | 끔 | 본문 속 *텍스트* 수식(ρ_f, u_i)의 변환 끄기 |
| `--no-block-ids` | 끔 | `^eq-3`, `^fig-2` 앵커 생략 |
| `--no-lighten` | 끔 | 이미지가 많은 페이지의 분석용 경량화 끄기 |
| `--ocr-pages` | 끔 | 스캔 PDF용 Tesseract OCR |
| `--no-overwrite` | 끔 | 결과가 이미 있으면 건너뜀 |
| `--claude-model`, `--claude-effort` | `claude-opus-5-5`, `low` | Claude 엔진 설정 (`ANTHROPIC_API_KEY` 환경변수 필요) |
| `--no-cache` | 끔 | OCR 결과 캐시 끄기 (캐시: `%LOCALAPPDATA%\pdf2word`) |
| `-v` | | 상세 로그 (OCR 결과, 인라인 수식 치환 내역) |

### Python에서 쓰기

```python
from pdf2word import convert
r = convert("paper.pdf", out_dir="D:/Vault/papers", format="both")
print(r.docx_path, r.md_path, r.asset_dir, r.stats)
```

---

## 6. 동작 원리 (간단히)

1. **레이아웃 분석** – `pymupdf4llm` + `pymupdf-layout`(CPU 전용 모델)이 페이지를 제목/본문/수식/그림/캡션/표/머리글 박스로 나누고 읽기 순서를 정합니다. 머리글·바닥글은 버립니다.
2. **수식** – 수식 박스를 원본에서 다시 그려 여백을 자르고, 오른쪽의 식 번호를 분리한 뒤 RapidLaTeXOCR(pix2tex의 ONNX 버전)로 읽습니다. 여러 줄 식은 줄 단위로 읽어 합칩니다. 결과를 PDF 텍스트 레이어와 글자 단위로 대조해 유사도를 매기고, 낮으면 다른 배율로 다시 읽어 가장 잘 맞는 것을 고릅니다.
3. **Word 수식** – LaTeX → MathML(`latex2mathml`) → OMML(Office의 `MML2OMML.XSL`)로 바꿔 Word 수식 개체로 넣습니다.
4. **본문 수식** – 글꼴(CM, Symbol, CambriaMath …)·크기·기준선을 보고 ρ_f, u_i 같은 인라인 수식을 찾아 LaTeX로 바꿉니다. Word/MathType 문서에서 사라지는 Symbol 폰트 글자(ρ, ∂, α …)도 복구합니다.
5. **그림** – 그림 박스를 원본에서 렌더링하고 바로 아래/위 캡션으로 이름을 정합니다. 페이지마다 반복되는 로고는 뺍니다.
6. **서지정보** – 첫 두 쪽에서 DOI/arXiv ID를 찾아 CrossRef/arXiv API로 받고, 없으면 1쪽의 큰 글자(제목)·그 아래 줄(저자)·연도 패턴으로 추정합니다.

처리 시간 예(GPU 없는 노트북): MDPI 논문 23쪽·수식 13개 약 1~2분, 학회 논문 24쪽·수식 57개 약 7분. 대부분이 수식 OCR 시간입니다.

---

## 7. 알려진 한계

- 수식 OCR 정확도는 "보통"입니다. 굵은 벡터 기호, 긴 다중 행 식, 특이한 글꼴의 ∂에서 틀리기 쉽습니다. 이미지가 항상 함께 들어가는 이유입니다.
- 레이아웃 모델이 수식을 본문으로 분류하면 그 수식은 LaTeX로 바뀌지 않습니다(`-v` 로그에서 페이지별 수식 블록 수를 볼 수 있습니다).
- Word 수식 변환은 Windows + Office에서만 됩니다. 다른 환경에서는 LaTeX 문자열로 들어갑니다.
- 스캔 PDF는 Tesseract가 있어야 합니다.

---

## 8. 테스트와 개발

```bash
python tests/test_basic.py   # 순수 함수 테스트 (모델·네트워크 불필요)
python tests/test_docx.py    # Word 출력 테스트
pdf2word sample.pdf --pages 1-5 -v   # 실제 변환 확인
```

버전은 `pdf2word/__init__.py`의 `__version__` 한 곳에서 올립니다(`pyproject.toml`이 읽어 감). 변경 내역은 [CHANGELOG.md](CHANGELOG.md)에 적습니다.

---

## 9. 사용한 오픈소스

| 구성 요소 | 라이선스 | 용도 |
|---|---|---|
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF), [PyMuPDF4LLM](https://github.com/pymupdf/pymupdf4llm), pymupdf-layout | AGPL-3.0 (또는 Artifex 상용) | PDF 읽기, 레이아웃 분석, Markdown 변환 |
| [RapidLaTeXOCR](https://github.com/RapidAI/RapidLaTeXOCR) ([LaTeX-OCR](https://github.com/lukas-blecher/LaTeX-OCR) 모델) | Apache-2.0 / MIT | 수식 OCR |
| [python-docx](https://github.com/python-openxml/python-docx) | MIT | Word 문서 작성 |
| [latex2mathml](https://github.com/roniemartinez/latex2mathml) | MIT | LaTeX → MathML |
| [Anthropic SDK](https://github.com/anthropics/anthropic-sdk-python) (선택) | MIT | Claude 비전 수식 OCR |

이 프로그램을 재배포할 때는 PyMuPDF 계열의 AGPL-3.0 조건이 적용된다는 점에 유의하세요.
