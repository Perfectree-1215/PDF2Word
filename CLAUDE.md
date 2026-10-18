# pdf2word

PDF(논문·책·매뉴얼) → Word(.docx) 또는 Obsidian Markdown. 레이아웃 분석(pymupdf4llm + pymupdf-layout, CPU ONNX),
수식 OCR(RapidLaTeXOCR, 선택적으로 Claude 비전), 그림 추출, 서지정보, 책갈피 기반 챕터 분할.
사용자 문서는 README.md, 변경 내역은 CHANGELOG.md, 개발 절차와 코드 지도는 docs/DEVELOPMENT.md.

## 환경과 명령

- Python **3.10~3.12만** (rapid_latex_ocr → numpy<2 → 3.13 이상 wheel 없음). 범위는 `pyproject.toml`
  `requires-python`, `.python-version`, `main_gui.bat`의 `PY_MIN/PY_MAX/PY_TOP` 세 곳에 같이 적혀 있다.
  단 `main_gui.bat`는 가상환경을 **3.12만** 만들고 받아들인다(`PY_MIN=PY_TOP=3.12`, uv가 없으면 설치해서 3.12를 내려받음).
- 환경: `uv sync --locked --extra dev` (`.venv`, 3.12). 의존성을 바꾸면 `pyproject.toml`과 `requirements.txt`를
  같이 고치고 `uv lock`.
- 테스트: `.venv\Scripts\python -m pytest tests -q` (24개, 모델·네트워크 불필요, 약 7초).
- 실행: `.venv\Scripts\python main_gui.py` (GUI) / `... main_gui.py paper.pdf --pages 1-5 -f md -o out -v` (CLI).
  변환은 수 분 걸리므로 백그라운드로 돌리고 `-v` 로그 파일을 본다. 결과는 `out/`(gitignore)에.
- GPU 없음. **torch 계열 의존성 금지**(CPU 전용). Word 수식 개체 변환은 Windows + Office에서만.

## 구조

`pdf2word/converter.py`(파이프라인, `_DocContext.render_page`가 `page_boxes`를 클래스별 처리) · `mathocr.py`(수식
OCR·검증·캐시) · `inlinemath.py`(텍스트 레이어 인라인 수식 → `$...$`) · `vectormath.py`(벡터 도형 수식) ·
`outline.py`(책갈피·챕터·인쇄 쪽 번호) · `docx_out.py`(Word) · `obsidian.py`(Markdown 후처리) · `metadata.py` ·
`lighten.py` · `symbols.py` · `config.py`/`cli.py`(옵션은 두 곳에 같이) · `main_gui.py`(tkinter GUI, 인수 있으면 CLI).

## 규칙

- 파일 입출력은 항상 `encoding="utf-8"` 명시(콘솔은 cp949). 경로에 한글이 있을 수 있다.
- `main_gui.bat`는 ASCII만, CRLF(.gitattributes). 수정 후 PowerShell에서 `.\main_gui.bat --help`로 확인
  (Git Bash의 `cmd /c`는 한글 작업 폴더에서 실패).
- 버전은 `pdf2word/__init__.py`의 `__version__` 한 곳. 변경은 CHANGELOG `## 미공개`에 적고 릴리스 때 버전 제목으로.
- 논문 PDF·변환 결과(.docx, .md, `_asset-*/`)는 커밋하지 않는다(저작권). 테스트는 합성 데이터만 쓴다.
- 본문 텍스트는 절대 망가뜨리지 않는다: 치환은 원문 위치를 찾았을 때만, 못 찾으면 그대로 둔다(inlinemath 원칙).
- 커밋·푸시는 사용자가 시킬 때만. 커밋 메시지는 한국어 한 줄 요약(릴리스는 `vX.Y.Z: ...`).
