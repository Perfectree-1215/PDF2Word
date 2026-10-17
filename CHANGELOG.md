# Changelog

버전은 `pdf2word/__init__.py`의 `__version__` 한 곳에서 관리합니다. 형식은 `MAJOR.MINOR.PATCH`이며
GUI와 결과물에는 `v1.0`처럼 앞 두 자리만 표시합니다.

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
