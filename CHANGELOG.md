# Changelog

버전은 `pdf2word/__init__.py`의 `__version__` 한 곳에서 관리합니다. 형식은 `MAJOR.MINOR.PATCH`이며
GUI와 결과물에는 `v1.0`처럼 앞 두 자리만 표시합니다.

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
