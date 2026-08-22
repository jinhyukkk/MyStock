---
name: screen-improve
description: MyStock 화면 하나를 "진단 → 설계 → FE/BE 병렬 구현 → 검수" 파이프라인으로 개선하는 오케스트레이터. 디자이너(ux-reviewer, layout-auditor)·트레이더(trader-mentor) 리뷰를 팬아웃하고, screen-architect가 스펙과 API 계약을 쓰고, frontend-engineer·backend-engineer가 병렬 구현한 뒤, architect가 경계면 검수한다. "Dashboard 개선해줘", "종목상세 화면 고치자", "Holdings 화면 멀티 에이전트로", "화면 단위 개선", "이 화면 리뷰받고 반영까지" 같은 요청이면 반드시 이 스킬을 사용한다. 리뷰만 원하면(수정 없이) 개별 리뷰 에이전트를 직접 부른다.
---

# Screen Improve — 화면 단위 개선 오케스트레이터

한 번에 **화면 하나**. 여러 화면을 동시에 돌리면 공용 파일(`types.ts`, `service.py`,
`components/*`)에서 충돌한다. 다음 화면은 이 화면이 끝나고 시작한다.

## 실행 모드: 서브 에이전트 (+ SendMessage 재개)

이 환경에는 팀 생성 도구가 없다. 리더(메인 세션)가 `Agent`로 각 역할을 띄우고, 수정 지시는
`SendMessage`로 같은 에이전트를 이어받아 보낸다(컨텍스트 보존). 에이전트끼리는 직접 말하지
않는다 — **`_workspace/{screen}/`의 파일이 유일한 접점**이다. 모든 `Agent` 호출에
`model: "opus"`를 명시한다.

## 에이전트 구성

| 역할 | subagent_type | Phase | 입력 | 출력 (`_workspace/{screen}/`) |
|---|---|---|---|---|
| 디자이너(정보구조) | `ux-reviewer` | 1 | 화면 소스 | `10_review_ux.md` |
| 디자이너(배치 실측) | `layout-auditor` | 1, 4 | 소스 + 실화면 | `10_review_layout.md`, `41_recheck_layout.md` |
| 트레이더 | `trader-mentor` | 1 | 실화면만 | `10_review_trading.md` |
| 설계자·검수자 | `screen-architect` | 2, 4 | 리뷰 3종 + 코드 / 구현 보고 | `20_spec.md`, `40_acceptance.md` |
| 백엔드 | `backend-engineer` | 3 | `20_spec.md` | `backend/` 변경 + `30_backend_report.md` |
| 프론트엔드 | `frontend-engineer` | 3 | `20_spec.md` | `frontend/` 변경 + `30_frontend_report.md` |

`{screen}`은 소문자 컴포넌트명 (`dashboard`, `tickerdetail`, `holdings`, `risk`, ...).
화면↔파일↔API 대응은 `mystock-dev` 스킬의 화면 지도를 쓴다.

## 워크플로우

### Phase 0 — 준비 (리더)

1. 사용자 요청에서 화면을 확정한다. 모호하면 `mystock-dev`의 화면 지도를 보여주고 고르게 한다.
2. `_workspace/{screen}/00_brief.md`에 적는다: 화면명, 라우트, 소스 파일, 주 API, 사용자가
   말한 제약(예: "API는 건드리지 말 것", "모바일 우선"). 없으면 "제약 없음".
3. `git status`로 작업 트리가 깨끗한지 본다. 미커밋 변경이 있으면 사용자에게 알리고
   커밋/스태시 여부를 묻는다 — 엔지니어의 변경과 섞이면 검수가 불가능하다.
4. 트레이딩 판단이 걸린 화면인지 정한다. Dashboard, TickerDetail, Holdings, Risk, Realized는
   `trader-mentor` 포함. Watchlist, Income, Journal, Settings는 기본 제외(브리프에 사유 기록).

### Phase 1 — 진단 (팬아웃, 병렬, 읽기 전용)

단일 메시지에서 리뷰 에이전트를 동시에 띄운다 (`run_in_background: true`). 각 프롬프트에
반드시 포함: 대상 화면·라우트·파일, **출력 경로를 `_workspace/{screen}/10_review_*.md`로
지정**(에이전트 기본 경로는 `_workspace/review_*.md`라 덮어쓰기 방지용), 브리프의 제약.

| 에이전트 | 프롬프트 핵심 | run_in_background |
|---|---|---|
| `ux-reviewer` | "{screen} 화면만. 정보구조·의사결정 경로·상태 처리. 출력 `10_review_ux.md`" | true |
| `layout-auditor` | "{screen} 화면만. 5173과 8722 둘 다 계측. 출력 `10_review_layout.md`" | true |
| `trader-mentor` | "{screen} 화면 중심 동선. 출력 `10_review_trading.md`" (해당 시) | true |

셋이 같은 브라우저 탭을 쓰면 서로 화면을 바꿔버린다 — 프롬프트에 "새 탭(`tabs_create`)을
열어 쓰고 남의 탭은 건드리지 말 것"을 넣는다. 전부 끝나면 리더가 세 파일을 읽고 **겹치는
지적을 묶어 3~7줄로 요약**해 사용자에게 보여준다. 여기서 사용자가 "이건 빼자/이건 꼭"을
말할 수 있다 → `00_brief.md`에 추가.

### Phase 2 — 설계 (`screen-architect`, 순차)

```
Agent(subagent_type: "screen-architect", model: "opus", run_in_background: false,
  prompt: "{screen} 화면 개선 스펙 작성. 입력: _workspace/{screen}/00_brief.md, 10_review_*.md.
           출력: _workspace/{screen}/20_spec.md. mystock-dev 스킬 먼저 읽을 것.")
```

**승인 게이트.** 스펙이 나오면 리더가 읽고 사용자에게 다음만 보여준다: 채택 변경(P0/P1),
보류 목록, API 계약 유무, 공용 파일 변경 유무, 리스크. 사용자가 승인해야 Phase 3으로 간다.
수정 요청은 `SendMessage`로 architect에게 보내 `20_spec.md`를 v2로 올린다.

스펙에 "공용 파일 변경 3개 초과 → 리팩터링" 경고가 있으면 이 스킬을 멈추고 별도 계획
(`superpowers:writing-plans`)으로 넘긴다.

### Phase 3 — 구현 (FE/BE 병렬)

스펙의 "백엔드 작업"이 비어 있으면 BE는 띄우지 않는다(프론트 전용 개선이 흔하다).

단일 메시지에서 동시에:

| 에이전트 | 프롬프트 핵심 | run_in_background |
|---|---|---|
| `backend-engineer` | "스펙 `20_spec.md`의 5·4·7·8절. `backend/`만. TDD. 보고서 `30_backend_report.md`" | true |
| `frontend-engineer` | "스펙 `20_spec.md`의 6·4·7·8절. `frontend/`만. BE 미완이면 계약대로 타입 먼저. 보고서 `30_frontend_report.md`" | true |

둘 다 끝나면 리더가 보고서 두 개를 읽는다. 확인할 것:
- BE "계약 수정 요청" 또는 FE "계약 불일치"가 있으면 → architect에게 `SendMessage`로 계약
  판정을 받고, 바뀐 계약을 해당 엔지니어에게 `SendMessage`로 전달. **Phase 4로 넘어가지
  않는다** — 계약이 어긋난 채 검수하면 검수가 의미 없다.
- 두 보고서의 "변경 파일"이 겹치면 파일 소유권 위반 → 어느 쪽이 맞는지 architect에게 묻는다.

### Phase 4 — 검수 (순차 → 병렬)

1. `screen-architect`를 `SendMessage`로 이어받아(Phase 2 컨텍스트 보존) 검수를 시킨다:
   "`30_*_report.md`와 실행 중인 앱으로 `20_spec.md` 8절 수용 기준 검수. API 실응답 ↔
   `types.ts` 교차 비교표 필수. 출력 `40_acceptance.md`."
2. 동시에 `layout-auditor`를 다시 띄워 같은 화면을 재계측한다 → `41_recheck_layout.md`.
   Phase 1 수치와 비교해 **악화된 항목**만 뽑게 한다(개선 확인이 아니라 회귀 탐지).
3. FAIL이 있으면 해당 엔지니어에게 `SendMessage`로 `40_acceptance.md`의 수정 지시문을
   그대로 보낸다. 고친 뒤 architect가 FAIL 항목만 재검수. **최대 2라운드.** 그래도 남으면
   남은 FAIL을 사용자에게 보고하고 판단을 받는다(수용/보류/직접 수정).

### Phase 5 — 마무리 (리더)

1. `npm run build`로 8722 빌드본을 갱신한다 (사용자가 실제로 보는 쪽).
2. 사용자에게 보고: 바뀐 것(3~5줄), 보류된 제안, 남은 FAIL, 변경 파일 목록.
3. 커밋은 **사용자가 요청할 때만** 리더가 한다. 커밋 메시지 본문에 스펙 경로를 남긴다.
4. `_workspace/{screen}/`은 지우지 않는다 — 다음 화면의 architect가 "보류" 절을 다시 읽는다.

## 데이터 흐름

```
00_brief ─┬→ ux-reviewer ─────→ 10_review_ux ──────┐
          ├→ layout-auditor ──→ 10_review_layout ──┼→ screen-architect → 20_spec ─[승인]─┐
          └→ trader-mentor ───→ 10_review_trading ─┘                                    │
                                                                  ┌──────────────────────┘
                                                                  ├→ backend-engineer  → backend/  + 30_backend_report ─┐
                                                                  └→ frontend-engineer → frontend/ + 30_frontend_report ┤
                                                                                                                       ↓
                                              screen-architect(재개) → 40_acceptance ←─ layout-auditor → 41_recheck
                                                                  │
                                                     FAIL → 엔지니어(재개) → 재검수 (≤2회) → 리더 보고
```

## 에러 핸들링

| 상황 | 전략 |
|---|---|
| 리뷰 에이전트 1개 실패 | 1회 재시도. 재실패 시 나머지로 설계 진행, 스펙 상단에 "○○ 리뷰 누락" 명시 |
| 리뷰 전부 실패 | 사용자에게 보고. 앱 실행 문제면 `preview_logs`로 원인 제시 후 중단 |
| 앱이 안 뜸 | 이미 떠 있는 5173/8722 재사용 시도 → 없으면 코드 정적 리뷰만으로 진행, "실행 미검증" 표기 |
| 엔지니어 1명 실패 | `SendMessage`로 상태 확인 → 응답 없으면 새 Agent로 같은 스펙 재투입. `git diff`로 반쯤 된 변경 확인 후 프롬프트에 "이어서" 명시 |
| FE/BE 계약 불일치 | Phase 4 진입 금지. architect가 계약 판정 → 한쪽만 수정 |
| 파일 소유권 충돌 | 두 엔지니어가 같은 파일 수정 → architect 판정 전까지 커밋·빌드 금지 |
| 검수 2라운드 후 FAIL 잔존 | 사용자 판단. 리더가 직접 고치는 것도 선택지 — 단 그 변경도 `40_acceptance.md`에 기록 |
| 리뷰 간 상충 제안 | 삭제하지 않고 architect가 "보류" 절에 출처와 함께 병기 |

## 테스트 시나리오

### 정상 흐름 — Holdings 화면
1. 사용자: "Holdings 화면 개선하자"
2. Phase 0: `_workspace/holdings/00_brief.md` (라우트 `/portfolio`, `Holdings.tsx`,
   `GET /api/portfolio`, 트레이더 포함, 제약 없음)
3. Phase 1: 리뷰 3개 병렬 → `10_review_*.md` 3개. 리더 요약: "평가액·수익률 중복 표시 2곳,
   손절 거리 미노출, 375px 표 넘침"
4. Phase 2: architect → `20_spec.md`. 채택 P0 3건, API 계약: `/api/portfolio` holdings[]에
   `stop_distance_pct: number|null` 추가(기존 필드 유지). 사용자 승인.
5. Phase 3: BE(portfolio.py + test_portfolio.py) ∥ FE(Holdings.tsx + types.ts). 보고서 2개,
   계약 불일치 없음.
6. Phase 4: architect 검수 — 수용 기준 7/7 PASS, 교차 비교표 일치. layout-auditor 재계측 —
   악화 항목 0.
7. Phase 5: 빌드 갱신, 보고. 산출물: `_workspace/holdings/{00,10×3,20,30×2,40,41}.md`

### 에러 흐름 — 계약 불일치
1. Phase 3에서 BE 보고서 "계약 수정 요청: `stop_distance_pct`는 ATR 없는 종목에서 계산 불가,
   null이 아니라 `stop_source: null`로 구분해야 함"
2. 리더가 Phase 4로 가지 않고 architect에게 `SendMessage` → 계약 v2 (`stop_source` 필드 추가)
3. FE에게 `SendMessage`로 v2 전달 → `types.ts` 수정 → 보고서 갱신
4. 그 후 Phase 4 진입. `40_acceptance.md`에 "계약 v2 적용" 기록

### 에러 흐름 — 트레이더 리뷰 실패
1. Phase 1에서 `trader-mentor`가 앱 실행 실패로 종료
2. 1회 재시도(떠 있는 8722로 `navigate`) → 재실패
3. ux/layout 리뷰만으로 Phase 2 진행. `20_spec.md` 상단 "trading 리뷰 누락 — 시그널·손익
   표기 관련 판단은 다음 라운드에 재검토"
4. Phase 5 보고에 누락 명시
