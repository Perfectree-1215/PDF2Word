# 같은 캡션의 그림 패널이 파일 여러 개로 나뉘어 LLM 인제스트 때 비전 호출이 패널 수만큼 중복됨

- 날짜: 2026-10-23
- 상태: 수정됨 (2026-10-23 구현: `converter._panel_groups`·`_merge_blocker`·`_picture(merged=)`, `Options.figure_panels`,
  `tests/test_pictures.py` 9개 — verify-run 결과는 아래 "검증 결과")
- 만든 스킬: diagnose-blocker (decide-direction의 B1 인계)
- 관련 결정: docs/decisions/figures-for-llm-ingest.md

## 증상
- 패널이 별도 XObject로 들어간 PDF(README의 MDPI 예 `_asset-Ma-2025/fig2a.png fig2b.png`)에서 레이아웃 모델이 패널마다 `picture` 박스를 내고,
  `_DocContext._picture`가 박스마다 PNG 한 장을 만든다. `_nearest_caption`이 같은 (kind, num)을 주므로 `_unique`가 fig2, fig2a…를 붙이고
  `finalize_subfigures`가 fig2a, fig2b…로 바꾼다.
- LLM-Wiki 인제스트(Claude Code의 Read)에서는 그림 한 장 = 턴 하나라서, 패널 4개짜리 그림은 4턴 + 설명 4번이고 범례·축 설명이 패널마다 되풀이된다
  (결정 문서의 측정·비용 추정 참고).
- 이 PC의 유일한 샘플 `docs/paper-01.pdf`(Elsevier 2014)는 분할이 없다(그림 8개 → 파일 8개). 분할 샘플 PDF는 사용자에게 요청한 상태 → 검증 샘플 표의 마지막 줄.

## 원인
`pdf2word/converter.py` `render_page`가 박스를 하나씩 `_picture`로 넘기고, `_picture`는 "박스 하나 = 파일 하나"로만 동작한다. 같은 캡션을 공유하는
picture 박스끼리의 관계를 어디서도 보지 않는다. 캡션 매칭(`_nearest_caption`: 아래 160 pt 이내, 가로 겹침, 위는 +40 벌점)은 패널마다 따로 같은 캡션을
찾아 주므로 묶을 근거 자체는 이미 있다.

## 패턴
- 깨지는 샘플(실제 PDF 미확보, 합성으로 만든다): (1) 가로로 나란한 패널 2개 + 아래 공통 캡션(MDPI류). (2) 2×2 패널 + 각 패널 아래 "(a)"…"(d)" 소제목
  text 박스 + 캡션.
- 멀쩡해야 하는 샘플: (3) paper-01 전체(분할 없음) → 출력 불변. (4) 한 단에 그림 조각 둘이 위아래로 떨어져 있고 사이에 본문 문단 → 병합하면 안 됨.
  (5) 쪽이 다른 "Figure 3 (continued)" → 병합 안 함. (6) 패널 사이에 표(`table`) 박스 → 병합 안 함.
- 공통점: 같은 쪽·같은 (kind, num)·`picture` 클래스. 안전 조건은 "합집합 안에 패널 아닌 내용이 없다"로 요약된다.

## 수정안
| 안 | 영향 범위(어느 PDF 유형이 바뀌나) | 회귀 위험 |
|---|---|---|
| ① `render_page`에서 같은 캡션의 picture 박스를 묶어 합집합을 한 번 렌더(기본 `merge`, `--figure-panels split`이면 현행) | 패널이 별도 박스로 나오는 PDF만. paper-01류는 불변 | 합집합에 본문이 섞일 위험 → 아래 안전 조건으로 차단하고 어긋나면 현행 유지 |
| ② `finalize_subfigures` 뒤 PNG 파일들을 Pillow로 이어 붙이기 | 모든 분할 그림 | 패널 간격·2×2 배치를 모르므로 원본 배치가 깨짐. 기각 |
| ③ `lighten.py`처럼 분석용 사본에서 미리 합치기 | 레이아웃 모델 입력이 바뀜 | 레이아웃 결과 전체가 흔들림. 기각 |

선택: ①. 이유: 원본 배치를 그대로 한 장에 담고, 조건이 안 맞으면 현행으로 떨어지며, 옵션 하나로 즉시 되돌릴 수 있다.

### ① 규칙 (implement-rule 인계)
1. `render_page`에서 박스의 `_text`를 채운 뒤, 루프 전에 `groups = self._panel_groups(page, boxes)`를 계산한다(`opt.figure_panels == "merge"`일 때만).
   - 후보: `class == "picture"`인 박스 중 `_nearest_caption(box, boxes)`가 `(kind, num)`을 주는 것. 같은 `(kind, num)`끼리 묶는다(`render_page`는
     쪽 단위라 같은 쪽 안에서만 묶인다).
   - 멤버 2개 이상인 묶음만 대상. 합집합 `U = (∪ Rect(bbox)) & page.rect`.
   - 안전 조건(모두 만족해야 병합):
     (a) `page.get_text("dict", clip=U, flags=TEXT_FLAGS)`의 텍스트 줄 중 어느 멤버 사각형에도 60% 이상 들어가지 않는 줄(`_inside` 기준)의
         면적 합 ≤ U 면적의 10% **이고** 글자 수 합 ≤ 120. "(a)", "(b) Case 2" 같은 패널 소제목은 통과, 본문 문단은 탈락.
     (b) 묶음 밖의 레이아웃 박스(다른 묶음의 picture 포함; `caption`·`page-header`·`page-footer`는 제외) 중 U와의 교집합이 그 박스 면적의 20%
         이상인 것이 없다. `table`·`formula`·`title`·`section-header`·`text`·`list-item`이 걸리면 탈락. **보정(구현 때)**: 본문 클래스 박스라도
         글자 수 40자 이하(`_DocContext.PANEL_LABEL_CHARS`)면 "(a)", "(b) Case 2" 같은 패널 소제목으로 보고 (b)에서 제외한다 — 그 글자는 (a)의
         120자 예산에 이미 들어간다. 이 보정이 없으면 2×2 패널 샘플이 (b)에서 탈락한다.
     (c) U 면적 ≤ 3 × Σ 멤버 면적.
   - 캡션 없는 picture 박스(`kind is None`)가 어떤 멤버 사각형을 12 pt(`lighten.CLUSTER_GAP`) 확장한 영역과 교차하면 그 묶음에 편입하고 조건을
     다시 검사한다. 로고(`_is_logo`)와 작은 박스(현행 20 pt·2,500 pt² 기준)는 편입하지 않는다.
2. 병합이 성립한 묶음은 첫 멤버(읽기 순서상 가장 앞 `index`) 자리에서 U를 한 번 렌더하고(`page.get_pixmap(clip=U, dpi=opt.dpi)`, 현행 `set_dpi`
   포함) 이름은 현행 규칙(`fig{num}` → `_unique`)으로 한 장만 만든다. 나머지 멤버는 `""`를 돌려주고 `stats["figures"]`에 더하지 않는다.
   `stats["panels_merged"] += len(members)`. 로그: 성공 `"  page %d: %s %s: %d panels merged into one image"`, 탈락
   `"  page %d: %s %s: %d panels kept separate (%s)"`에 이유(`text between panels` / `other box inside` / `too sparse`).
3. `keep_picture_text`가 켜져 있으면 멤버들의 `seg`에서 뽑던 "그림 속 텍스트"를 읽기 순서대로 이어 한 번만 붙인다.
4. 쪽이 다른 같은 번호(continued)는 지금처럼 `_unique`로 `fig3`, `fig3a` → `finalize_subfigures`가 a/b를 붙인다(변경 없음).
5. 수식으로 판정되는 picture(`_label_right_of`로 번호가 잡히거나 가늘고 넓은 띠)는 캡션이 없어 묶음에 들어오지 않는다(현행 분기 유지).
6. 옵션(option-wiring 인계): `Options.figure_panels: str = "merge"`(`"merge" | "split"`), CLI `--figure-panels {merge,split}` 도움말
   "같은 캡션의 패널을 한 장으로 합침(merge, 기본) / 패널마다 파일(split)", GUI는 기존 체크 항목 줄에 "패널 병합"(기본 켬) 또는 콤보, README 옵션 표
   한 줄과 그림 설명(`fig2a.png fig2b.png` 예시를 "패널은 기본적으로 한 장, `--figure-panels split`이면 a/b/c"로), docs/DEVELOPMENT.md 코드 지도
   한 줄, CHANGELOG `## 미공개`(없으면 새로 만든다).
7. 바꾸지 않는 것: 레이아웃 분석(`lighten`), 캡션 탐지, 수식 경로, Word 출력(임베드를 그대로 쓴다), 본문 텍스트.

## 검증 샘플
verify-run이 그대로 돌리는 형식. 합성 테스트는 `tests/test_pictures.py`(신규)에서 `_DocContext.render_page(page, chunk)`를 직접 부른다
(`tests/test_assets.py`·`tests/test_p2t_engine.py`처럼 `page_boxes`를 손으로 만든다: 각 박스 `{"class", "bbox", "pos", "index"}`와 `chunk["text"]`,
PDF는 `tests/test_basic.py::_pdf`처럼 `pymupdf.open()` + `insert_image` + `insert_text`로 합성, 모델·네트워크 없음).

| PDF 경로 | 쪽 | 식/박스 | 기대 결과(판정) |
|---|---|---|---|
| 합성: 패널 2개 (100,200,290,350)·(305,200,495,350), 캡션 text "Figure 2. Two panels." (100,360)…; picture 박스 2 + caption 박스 1 | 1 | 그림 | PNG 1장 `fig2.png`, 픽셀 크기 ≈ U(395×150 pt)×200/72, `![[…/fig2.png]]` 1개, `stats["figures"] == 1`, `stats["panels_merged"] == 2` |
| 합성: 같은 배치, `Options(figure_panels="split")` | 1 | 그림 | PNG 2장 `fig2a.png`·`fig2b.png`(현행과 동일) |
| 합성: 패널 2개가 위아래 (100,200,300,300)·(100,520,300,620), 사이 (100,320,300,500)에 본문 text 박스(300자) | 1 | 그림 | 병합 안 함: PNG 2장, 로그에 `kept separate (text between panels)` |
| 합성: 패널 2개 사이에 `table` 박스 | 1 | 그림 | 병합 안 함: 로그 `other box inside` |
| 합성: 2×2 패널 + 각 패널 아래 "(a)"…"(d)" 짧은 text 박스 + 캡션 | 1 | 그림 | PNG 1장(소제목 글자 수 ≤ 120이라 통과) |
| 합성: 패널이 쪽 1·쪽 2에 하나씩, 둘 다 "Figure 3." 캡션 | 1–2 | 그림 | `fig3a.png`·`fig3b.png`(현행), `panels_merged == 0` |
| 합성: 캡션 있는 패널에서 8 pt 떨어진 캡션 없는 picture 조각 | 1 | 그림 | 조각이 편입되어 PNG 1장, `p1-img…` 파일 없음 |
| `docs/paper-01.pdf`(로컬, 커밋 안 함) | 1–10 | 그림 전체 | 현행과 파일 수·이름 동일(fig1–4·9–12 각 1장, p-img 6, eq 5), `panels_merged == 0` |
| (사용자 제공) 패널 분할이 생기는 MDPI류 논문 | 전체 | 그림 전체 | 그림 파일 수 = 캡션 수(쪽 걸침 제외), 병합 이미지 안에 본문 문단 0건 — **미확보** |

## 검증 결과 (2026-10-23, verify-run)
- pytest 233/233 (기존 222 + 신규 11: `tests/test_pictures.py` 9, `test_cli.py` 1, `test_gui.py` 1).
- paper-01 전체 변환(md) 전후 대조: PNG 19개 이름·픽셀 크기 동일, 본문 diff 0줄(`converted:` 날짜 제외), 로그에 병합·분리 줄 0건(이 논문은
  분할이 없으므로 정답). `--figure-panels split`도 CLI 통과·결과 동일.
- `main_gui.bat` 변경 없음, ASCII/CRLF/라벨 검사 통과.
- **남은 것**: 실제로 패널이 분할되는 PDF(MDPI류)의 회귀는 샘플이 없어 못 돌렸다. 사용자가 한 편을 주면 "그림 파일 수 = 캡션 수, 병합 이미지 안에
  본문 0건"을 확인한다.

## 관련 결정
docs/decisions/figures-for-llm-ingest.md (B1 선택, 판정 기준·되돌릴 조건)
