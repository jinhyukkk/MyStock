# TickerDetail 개선 브리프 — finviz 쿼트 페이지와 동일한 구성

- 화면: TickerDetail · 라우트 `/ticker/:symbol` · 소스 `frontend/src/pages/TickerDetail.tsx`,
  `frontend/src/components/quote/*`, `frontend/src/quote/*`, `frontend/src/quote.css`
- 주 API: `GET /api/tickers/{symbol}` (`service.get_ticker_detail`), `GET /api/tickers/{symbol}/backtest`
- 레퍼런스: https://finviz.com/quote.ashx?t=NFLX&p=d (Overview 탭)

## 사용자 결정 (2026-08-21)
1. **배치는 이미 finviz와 동일하게 바꿨다** (헤더 → 탭 → 전폭 차트 → 6쌍×N행 스냅샷 → 2:1 하단). 이번 라운드는 **구성(내용)** 을 finviz와 같게 한다.
2. **순수 finviz 구성만.** MyStock 고유 블록(시그널 근거·백테스트·청산 플랜·커스텀 룰·시그널 히스토리)은 이 화면에서 제거한다. 헤더 아래 **판정 한 줄만** 남긴다. (제거된 블록은 다른 화면에 이미 있거나 추후 별도 탭으로 복귀 가능 — 지우는 게 아니라 이 화면 밖으로.)
3. 데이터 소스: 미국 종목은 yfinance. **국내 종목은 별도 소스 검토** 결과(`01_sources_kr.md`)를 반영해 결정.

## finviz Overview 구성 (실페이지 확인, 2026-08-21)
1. 헤더: 티커 · 회사명 · **섹터 · 산업 · 국가 · 거래소** 링크 / 현재가 · 등락 · 시각 (+ 시간외)
2. 탭: Overview · Snapshot · News · Description · Financials · Options · Latest filings
3. 전폭 차트 (기간 버튼)
4. **스냅샷 표 12열×14행(72칸)** — 정확한 라벨·순서는 `01_finviz_snapshot.md`
5. **재무 막대 차트 3개**: GAAP EPS · Sales · Shares Outstanding (연간/분기 토글, 약 7년 + TTM)
6. 하단: **뉴스 목록**(좌, 시각·제목·출처) + **애널리스트 등급 표**(우: Date · Action · Analyst · Rating Change · Price Target Change)
7. **회사 설명** (전폭)
8. **내부자 거래 표** (전폭: Insider · Relationship · Date · Transaction · Cost · #Shares · Value · #Shares Total · SEC Form 4)

## yfinance 가용성 (2026-08-21 실측, backend/.venv)
| 항목 | US (NFLX) | KR (000660.KS) |
|---|---|---|
| `info` 스냅샷 지표 | 거의 전부 (배당 없음은 종목 특성) | 대부분 있으나 **trailingPE·priceToBook·trailingEps·forwardEps·bookValue·공매도 3종 없음** |
| sector/industry/country/exchange/employees/longBusinessSummary | 있음 (영문) | 있음 (영문 설명 743자) |
| `news` | 10건 | 10건 (영문) |
| `income_stmt` / `quarterly_income_stmt` | 연 5 / 분기 5 | 연 4 / 분기 6 |
| `upgrades_downgrades` | 952건 | **0건** |
| `insider_transactions` | 150건 | **0건** |
| `calendar` (실적일·컨센서스) | 있음 | 있음 |

## 제약
- 백엔드 응답 필드는 추가만(기존 필드 유지 — 빌드본 호환).
- 외부 호출은 1시간 갱신 루프(`service.refresh_all`)에 얹어 캐시(`meta` 또는 새 테이블). 상세 화면 요청 시 동기 외부 호출 금지(yfinance `info`는 1~3초).
- 국내 종목에서 비는 칸은 `null` → 화면 `—`. 표 자체가 비면 "국내 종목은 제공되지 않는 데이터입니다" 같은 **이유 있는** 빈 상태.
- 현재 미커밋 변경이 작업 트리에 있다(배치 개편 프론트 + 이전 세션의 codef 백엔드 변경). 엔지니어 투입 전에 정리 필요.

## Phase 1 대체 사유
목표 화면이 외부 레퍼런스로 확정돼 있어 UX/트레이더 리뷰가 설계에 기여할 여지가 작다. Phase 1은
(a) finviz 실페이지 구조·72칸 라벨 추출(`01_finviz_snapshot.md`), (b) 국내 데이터 소스 조사(`01_sources_kr.md`),
(c) yfinance 가용성 실측(위 표)로 대체한다. layout-auditor는 Phase 4 회귀 계측에만 쓴다.

## 검수 제외 (2026-08-21 15:35 추가)
다른 세션이 **대시보드(finviz 스타일 히트맵·지수 차트)** 를 병행 작업 중이다. 아래 파일의 변경은 이 화면 작업과 무관하므로
검수·소유권 판정·회귀 계측에서 **제외**한다: `frontend/src/pages/Dashboard.tsx`, `frontend/src/components/Layout.tsx`,
`frontend/src/components/SentimentGauge.tsx`(삭제), `frontend/src/theme.css`, `frontend/src/finviz/**`.
`/`(대시보드) 화면은 계측하지 않는다. TickerDetail 변경이 이 파일들을 건드리면 안 된다.
- (16:30 추가) `frontend/src/api.ts` 변경도 대시보드 세션 소유(SPA 폴백 대응)로 분류 — FE 공용 파일 상한 계산에서 제외.
