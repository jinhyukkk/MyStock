# TickerDetail 개선 스펙 v2 — finviz Overview 동일 구성

> **v2 (2026-08-21): 계약 변경분은 `21_contract_v2.md`가 정본이다.** 변경 사유 — 구현 중 드러난
> 소스 한계(항상 null인 칸, 정의가 다른 지표)와 AC-4가 요구하는 배당수익률 칸이 §4.3 84칸에
> 없던 설계 누락. 추가 필드 4개(`snapshot.dividend_yield_pct`, `snapshot.note`, `profile.status`,
> `profile.note`)와 라벨 3건 변경. 삭제·개명 0. §6.1 캐시 블록에 내부 `perf10y` 추가.

- 화면: TickerDetail · `/ticker/:symbol`
- 입력: `00_brief.md`, `01_finviz_snapshot.md`, `01_sources_kr.md`, 현재 코드
- **Phase 1 리뷰 3종 미실행.** 브리프 "Phase 1 대체 사유"에 따라 finviz 실페이지 추출·KR 소스
  조사·yfinance 실측이 진단을 대신한다. `ux-reviewer`/`trader-mentor`의 평가가 없으므로
  "무엇이 사용자에게 더 나은가"의 근거는 **레퍼런스 동일성**뿐이다. layout-auditor는 Phase 4에서만.

---

## 1. 목표

종목상세를 열었을 때 사용자가 **이 회사가 무엇을 파는 회사이고(설명·섹터), 얼마나 비싸며(밸류
14칸), 얼마나 벌고 있고(수익성·성장), 시장이 뭐라고 하는지(뉴스·컨센서스·내부자)** 를 한 화면에서
스크롤만으로 확인할 수 있게 한다. 지금은 MyStock이 계산한 시그널·리스크만 있고 **회사 자체에 대한
사실이 없어서**, 사용자는 판단 근거의 절반을 다른 사이트에서 가져와야 한다.

부수 목표: 판단(시그널·백테스트·청산 플랜)과 사실(회사 데이터)을 다른 탭으로 분리해, 개요 화면이
"내가 만든 점수"가 아니라 "시장이 준 숫자"로 시작하게 한다.

---

## 2. 채택한 변경 (전부 P0 — 브리프 확정 사항)

| # | 변경 | 근거 |
|---|---|---|
| A1 | 헤더에 섹터·산업·국가·거래소·직원수 추가 | finviz 헤더 |
| A2 | 판정 한 줄 유지, 그 외 MyStock 고유 블록 5종을 개요에서 제거 | 브리프 결정 2 |
| A3 | 스냅샷 표를 finviz 84칸(6쌍×14행) 라벨 구성으로 교체 | `01_finviz_snapshot.md` |
| A4 | 재무 막대 차트 3종(EPS·매출·발행주식수) + 연간/분기 토글 | finviz |
| A5 | 하단 2:1 = 좌 뉴스 / 우 애널리스트 | finviz |
| A6 | 회사 설명 전폭 블록 | finviz |
| A7 | 내부자 거래 표 전폭 블록 | finviz |
| A8 | 제거되는 5블록을 `/ticker/:symbol/analysis` 탭으로 **이동**(삭제 아님) | 아래 §7-회귀 방지 |
| A9 | 개요에서 `/backtest` 호출 중단 | 백테스트 UI가 개요에 없어짐 |

P1(이번 라운드 안에서 마지막에):
| B1 | 블록별 출처·갱신시각 한 줄 표기("출처: yfinance · 네이버 · 3시간 전") | 캐시 신선도를 화면이 숨기면 안 된다 |
| B2 | 재무 차트의 컨센서스 막대를 반투명+`(E)` 라벨로 구분 | 추정치를 실적으로 읽으면 안 된다 |

---

## 3. 보류한 제안

| 항목 | 보류 이유 |
|---|---|
| pykrx(KR 공매도 잔고·투자자별) | 2025-12-27부터 KRX Data Marketplace 로그인 필수(`KRX_ID/PW`). 키 없는 1차 범위 밖. 스냅샷 공매도 3칸은 KR에서 `—`로 둔다 |
| KIS Open API(증권사별 등급 변경 이력) | 계좌+AppKey 필요. KR `ratings.changes`를 채울 유일한 구조화 소스지만 진입 비용이 화면 하나보다 크다. 대신 네이버 리포트 목록으로 대체(§5-ratings) |
| 재무제표 전체(Statements 탭: BS/IS/CF 전 계정) | finviz도 별도 탭. 개요 구성 밖 |
| Options / Latest filings 탭 | 국내 개인 투자자 사용률·데이터 소스 모두 근거 없음 |
| finviz 밸류 지표의 수준별 색상(낮은 P/E 초록) | 기준선이 업종마다 달라 색이 곧 조언이 된다. 무채색 유지 |
| Perf 10Y를 제외한 장기 시세 전면 수집 | `price_cache`가 이미 1100영업일(≈4.8년) 보유 → 5Y까지는 무비용. 10Y만 월봉 1콜 |
| 스냅샷 지표를 대시보드/관심목록에도 노출 | 화면 하나로 범위를 묶는다. 다음 라운드 |
| OpenDART 키 UI(설정 화면 입력폼) | 2차 범위. 1차는 `.env`의 `DART_API_KEY` 존재 여부만 읽는다 |

### Phase 4 검수(2026-08-22, `40_acceptance.md` §6)에서 추가된 보류

| 항목 | 보류 이유 |
|---|---|
| `/analysis` 통화 혼재($ 손절가 ↔ ₩ 리스크·평가액) — D9 | 기준선 커밋 `eb6f6d3`에 이미 있던 결함이고 §7이 "리팩터링 금지, 잘라 붙이기"로 못박은 이동분이다. 환율·기준시각을 붙이려면 `risk` 응답에 환율 필드가 필요 → BE 계약 변경 동반 |
| `/analysis` 청산 플랜 소수점 주식수(`수량 1.667`) — D10 | 동일한 이동분. 국내 주식은 소수점 매도 불가. `제안 수량`에는 이미 있는 "1주 단위 내림" 규칙이 청산 플랜에만 없다 — `/analysis` 전용 라운드에서 통일 |
| 백테스트 표 11열 컨테이너 가로 넘침 — D13/R1/R3 | **회귀가 아니라 기준선 계측 누락.** `BacktestTable.tsx` 미변경이고 `.table-scroll`은 9개 화면이 쓰는 `theme.css` 전역 패턴이다. 어느 열을 버릴지는 트레이딩 판단이라 `trader-mentor` 없이 정하지 않는다 |
| 뉴스 제목 소스단 절단(000660 20건 중 9건이 `...`로 끝남) — D6b | 네이버가 절단해 보낸다. 복원하려면 다른 엔드포인트가 필요해 §6.2 콜 예산이 늘어난다 |
| 뉴스 종목 관련성 배지(시황·타종목 기사 구분) | 종목명 매칭 로직은 BE 신규 추가라 화면 하나 범위를 넘는다 |
| BE `quick_ratio > current_ratio` 정합성 가드 | 상류(yahoo) 이상값 `current_ratio 17.54`가 화면에 그대로 나갔다(재수집 후 2.59로 자기 정정). 값을 비우는 가드는 오탐 위험이 있어 실측 표본을 더 모은 뒤 결정 |
| `snapshot.perf` 기준 봉 혼재(`y5`·`y10`만 월봉 종가) | 같은 표에서 소수점 단위 차이가 날 수 있다. 툴팁 한 줄로 해결되나 이번 라운드 필수 목록을 늘리지 않는다 |
| 내부자 표 열·행 축소(`보유 총수`·`공시` 100% `—`, 30행 7,507px) | 열 삭제는 finviz 동일 구성(§2-A7)을 깨는 결정이라 브리프 확정 사항과 충돌 — 사용자 판단 필요 |
| `frontend/src/quote/cells.ts` 사장 코드 삭제 | `snapshotCells.ts`가 대체했으나 파일이 남아 참조 0건. 84칸 정의가 두 벌이면 다음 수정자가 틀린 쪽을 고친다. 리더가 커밋 정리 때 처리 |
| DART 2차 경로 실호출 검증(`elestock` 필드명 실측) | 계약 v2 §1-BE-7. `.env`에 키 없음 — 키 등록 시점 별도 라운드 |
| `refresh_all` 전체 8종목 상한 실서버 검증(V5) | CODEF 일 100회 한도로 실서버 미실행. 단위 테스트로 고정, "실행 미검증" 표기 유지 |
| 스냅샷 시각 검증(대비·색상·행간) | Phase 4에서 스크린샷 도구 불능 — DOM 계측치만으로 판정했다. 도구 복구 시 별도 라운드 |

---

## 4. 데이터 소스 결정

### 4.1 범위 구분

- **1차(키 없음, 이번 라운드 필수 구현)**: yfinance · Naver 모바일 JSON · Daum quotes · FDR `KRX-DESC`
- **2차(선택, `.env`의 `DART_API_KEY`가 있을 때만)**: OpenDART — KR 재무 7년·발행주식수 이력·내부자
- 2차 키가 없으면 해당 블록은 `status:"unavailable"` + BE가 준 한국어 `note`를 그대로 빈 상태로 출력한다.

### 4.2 블록 × 시장 커버리지

| 블록 | US(yfinance) | KR 1차 | KR 2차(DART 키) | 키 없을 때 화면 |
|---|---|---|---|---|
| profile(섹터·산업·국가·거래소·직원수·상장일) | 전부 | yf(영문 섹터/산업) + Daum `wicsSectorName`(한글) + FDR `KRX-DESC`(Sector/Industry/ListingDate) | 동일 | — |
| description(회사 설명) | yf `longBusinessSummary`(영문) | Daum `companySummary`(**한국어**) → 폴백 WiseReport `.cmp_comment` → 폴백 yf 영문 | 동일 | — |
| snapshot 84칸 | 66칸 채움(§4.3) | 52칸 채움 | +6칸(ROIC·EPS past 5Y 등) | 빈 칸은 `—` |
| financials(연/분기) | yf `income_stmt` 4~5년 / `quarterly_income_stmt` 5~6분기 | Naver `finance/annual` 3년+컨센 1 / `finance/quarter` 5분기+컨센 1. **발행주식수 이력 없음** | DART `fnlttSinglAcnt` 7년 + `stockTotqySttus` 발행주식수 | 발행주식수 차트만 빈 상태: "발행주식수 이력은 OpenDART 키 등록 후 표시됩니다" |
| news | yf `news` 10건(영문) | Naver `/api/news/stock/{code}` 20건(**한국어**) → 폴백 yf 영문 | 동일 | — |
| ratings.consensus | yf `recommendationMean`·`targetMeanPrice`·`numberOfAnalystOpinions` | Naver `consensusInfo`(recommMean·priceTargetMean·createDate) → 폴백 yf | 동일 | — |
| ratings.changes(브로커별 등급 변경 이력) | yf `upgrades_downgrades` 952건 | **없음(0건)** | 없음 | "국내 종목은 증권사별 투자의견 변경 이력을 제공하는 무료 소스가 없습니다 — 최근 리포트 목록으로 대신합니다" + `reports[]` 표시 |
| ratings.reports(KR 대체) | 없음(빈 배열) | Naver `researches[]`/`/api/research/stock/{code}` (증권사·제목·일자) | 동일 | — |
| insiders | yf `insider_transactions` 150건 | **없음(0건)** | DART `elestock`(임원·주요주주 소유보고) | "국내 종목 내부자 거래는 OpenDART 키(무료)를 등록해야 표시됩니다" |
| perf 1W~5Y | `price_cache`(1100영업일) 계산 | 동일 | 동일 | — |
| perf 10Y | yf 월봉 `period=10y, interval=1mo` 1콜 | FDR 월간 리샘플 | 동일 | `—` |

### 4.3 스냅샷 84칸 — finviz 라벨 → MyStock 매핑

표기 규칙: `snapshot.*` = 백엔드가 외부 소스에서 채우는 값, `FE:` = 프론트가 `candles`/`risk`에서
계산(백엔드에 새 필드를 요구하지 않는다 — `quote/stats.ts` 기존 방침).
라벨은 **한국어**, 국제 통용 약어(PER/PEG/ROE/ATR/RSI/SMA)는 원문 유지.

**열1 — 규모·배당**

| 행 | finviz | MyStock 라벨 | 키 | US 출처 | KR 1차 출처 |
|---|---|---|---|---|---|
| 1 | Index | **시장·거래소** (대체) | `profile.exchange` | yf `exchange` | `tickers.market`(KOSPI/KOSDAQ) |
| 2 | Market Cap | 시가총액 | `snapshot.market_cap` | yf `marketCap` | Naver `marketValue`(억원→원 변환) / Daum |
| 3 | Enterprise Value | 기업가치(EV) | `snapshot.enterprise_value` | yf `enterpriseValue` | yf(있으면) |
| 4 | Income | 순이익(TTM) | `snapshot.income_ttm` | yf `netIncomeToCommon` | Naver 분기 4개 합 |
| 5 | Sales | 매출(TTM) | `snapshot.sales_ttm` | yf `totalRevenue` | Naver 분기 4개 합 |
| 6 | Book/sh | BPS | `snapshot.book_per_share` | yf `bookValue` | Naver `bps` |
| 7 | Cash/sh | 주당 현금 | `snapshot.cash_per_share` | yf `totalCash`/`sharesOutstanding` | yf 동일, 없으면 null |
| 8 | Dividend Est. | 예상 배당(주당) | `snapshot.dividend_est` | yf `dividendRate` | Naver annual 컨센서스 `dps` |
| 9 | Dividend TTM | 최근 배당(주당) | `snapshot.dividend_ttm` | yf `trailingAnnualDividendRate` | Naver `dividend` |
| 10 | Dividend Ex-Date | 배당락일 | `snapshot.dividend_ex_date` | yf `exDividendDate` | null(1차 미제공) |
| 11 | Dividend Gr. 3/5Y | 배당성장 3/5년 | `snapshot.dividend_growth_3y_pct`, `_5y_pct` | 배당 이력 계산 | Naver annual `dps` 3년 → 3Y만, 5Y null |
| 12 | Payout | 배당성향 | `snapshot.payout_pct` | yf `payoutRatio`×100 | `dps/eps`×100 계산 |
| 13 | Employees | 직원수 | `profile.employees` | yf `fullTimeEmployees` | yf(있음) |
| 14 | IPO | 상장일 | `profile.ipo_date` | yf `firstTradeDateEpochUtc` | FDR `KRX-DESC.ListingDate` |

**열2 — 밸류에이션·재무구조**

| 행 | finviz | MyStock 라벨 | 키 | US | KR 1차 |
|---|---|---|---|---|---|
| 1 | P/E | PER | `snapshot.pe` | yf `trailingPE` | **Naver `per`**(yf는 None) |
| 2 | Forward P/E | 선행 PER | `snapshot.forward_pe` | yf `forwardPE` | Naver `cnsPer` |
| 3 | PEG | PEG | `snapshot.peg` | yf `trailingPegRatio` | yf |
| 4 | P/S | PSR | `snapshot.ps` | yf `priceToSalesTrailing12Months` | yf |
| 5 | P/B | PBR | `snapshot.pb` | yf `priceToBook` | **Naver `pbr`**(yf는 None) |
| 6 | P/C | 주가/주당현금 | `snapshot.pc` | 계산 | 계산 |
| 7 | P/FCF | 주가/FCF | `snapshot.p_fcf` | `marketCap`/`freeCashflow` | yf |
| 8 | EV/EBITDA | EV/EBITDA | `snapshot.ev_ebitda` | yf `enterpriseToEbitda` | yf |
| 9 | EV/Sales | EV/매출 | `snapshot.ev_sales` | yf `enterpriseToRevenue` | yf |
| 10 | Quick Ratio | 당좌비율(배) | `snapshot.quick_ratio` | yf `quickRatio` | Naver 당좌비율(**%단위 → ÷100**) |
| 11 | Current Ratio | 유동비율(배) | `snapshot.current_ratio` | yf `currentRatio` | yf |
| 12 | Debt/Eq | 부채비율(배) | `snapshot.debt_eq` | yf `debtToEquity`(**%단위 → ÷100**) | Naver 부채비율(% → ÷100) |
| 13 | LT Debt/Eq | 장기부채비율(배) | `snapshot.lt_debt_eq` | balance_sheet 계산 | null |
| 14 | Option/Short | **유통주식 비율** (대체) | `snapshot.float_pct` | `floatShares/sharesOutstanding`×100 | 동일 |

**열3 — EPS·성장·실적**

| 행 | finviz | MyStock 라벨 | 키 | US | KR 1차 |
|---|---|---|---|---|---|
| 1 | EPS (ttm) | EPS(TTM) | `snapshot.eps_ttm` | yf `trailingEps` | **Naver `eps`** |
| 2 | EPS next Y(금액) | EPS 추정(내년) | `snapshot.eps_next_y` | yf `forwardEps` | Naver `cnsEps` |
| 3 | EPS next Q | EPS 추정(다음분기) | `snapshot.eps_next_q` | yf `eps_trend` 0q | Naver quarter 컨센서스 |
| 4 | EPS this Y | EPS 성장(올해) | `snapshot.eps_this_y_pct` | yf `growth_estimates` 0y | Naver annual 추정 vs 전년 |
| 5 | EPS next Y(성장) | EPS 성장(내년) | `snapshot.eps_next_y_pct` | yf `growth_estimates` +1y | 계산 |
| 6 | EPS next 5Y | EPS 성장(5년 추정) | `snapshot.eps_next_5y_pct` | yf `growth_estimates` +5y | null |
| 7 | EPS past 3/5Y | EPS 성장(과거 3/5년) | `snapshot.eps_past_3y_pct`, `_5y_pct` | income_stmt 계산 | 3Y만(3년치), 5Y는 DART 2차 |
| 8 | Sales past 3/5Y | 매출 성장(과거 3/5년) | `snapshot.sales_past_3y_pct`, `_5y_pct` | 계산 | 3Y만 |
| 9 | EPS Y/Y TTM | EPS 전년동기 | `snapshot.eps_yoy_ttm_pct` | 계산 | Naver quarter 계산 |
| 10 | Sales Y/Y TTM | 매출 전년동기 | `snapshot.sales_yoy_ttm_pct` | 계산 | 계산 |
| 11 | EPS Q/Q | EPS 전분기 | `snapshot.eps_qoq_pct` | 계산 | 계산 |
| 12 | Sales Q/Q | 매출 전분기 | `snapshot.sales_qoq_pct` | 계산 | 계산 |
| 13 | Earnings | 실적발표일 | `snapshot.earnings_date` + `earnings_timing` | yf `calendar` | yf `calendar`(timing은 null) |
| 14 | EPS/Sales Surpr. | 서프라이즈(EPS/매출) | `snapshot.eps_surprise_pct`, `sales_surprise_pct` | yf `earnings_dates` | null |

**열4 — 소유·수익성·이동평균**

| 행 | finviz | MyStock 라벨 | 키 | US | KR 1차 |
|---|---|---|---|---|---|
| 1 | Insider Own | 내부자 지분 | `snapshot.insider_own_pct` | yf `heldPercentInsiders`×100 | yf |
| 2 | Insider Trans | 내부자 거래(6M) | `snapshot.insider_trans_pct` | `insider_transactions` 계산 | null |
| 3 | Inst Own | 기관 지분 | `snapshot.inst_own_pct` | yf `heldPercentInstitutions`×100 | yf |
| 4 | Inst Trans | **외국인 지분** (KR 대체) | `snapshot.inst_trans_pct` / `snapshot.foreign_own_pct` | yf 계산(기관 변동) | Naver `foreignRate` — **라벨이 시장별로 다르다**(BE가 `label_key` 대신 두 필드를 모두 내려주고 FE가 값 있는 쪽을 쓴다) |
| 5 | ROA | ROA | `snapshot.roa_pct` | yf `returnOnAssets`×100 | yf |
| 6 | ROE | ROE | `snapshot.roe_pct` | yf `returnOnEquity`×100 | yf → 폴백 Naver `roe` |
| 7 | ROIC | ROIC | `snapshot.roic_pct` | NOPAT/투하자본 계산 | null(DART 2차) |
| 8 | Gross Margin | 매출총이익률 | `snapshot.gross_margin_pct` | yf `grossMargins`×100 | yf |
| 9 | Oper. Margin | 영업이익률 | `snapshot.oper_margin_pct` | yf `operatingMargins`×100 | yf → 폴백 Naver |
| 10 | Profit Margin | 순이익률 | `snapshot.profit_margin_pct` | yf `profitMargins`×100 | yf |
| 11 | SMA20 | SMA20 이격 | FE `smaGapPct` | candles | candles |
| 12 | SMA50 | **SMA60 이격** (MyStock 지표 체계) | FE | `candles.sma60` | 동일 |
| 13 | SMA200 | **SMA120 이격** | FE | `candles.sma120` | 동일 |
| 14 | Trades(Elite) | **거래대금(20일 평균)** (대체) | FE `avgTurnover` | candles(close×volume) | 동일 |

**열5 — 주식수·공매도·변동성**

| 행 | finviz | MyStock 라벨 | 키 | US | KR 1차 |
|---|---|---|---|---|---|
| 1 | Shs Outstand | 발행주식수 | `snapshot.shares_outstanding` | yf | yf |
| 2 | Shs Float | 유통주식수 | `snapshot.shares_float` | yf `floatShares` | yf |
| 3 | Short Float | 공매도 비율 | `snapshot.short_float_pct` | yf ×100 | **null**(pykrx 보류) |
| 4 | Short Ratio | 공매도 상환일수 | `snapshot.short_ratio` | yf | null |
| 5 | Short Interest | 공매도 잔고 | `snapshot.short_interest` | yf `sharesShort` | null |
| 6 | 52W High | 52주 고가 | FE `range52w` | candles | candles |
| 7 | 52W Low | 52주 저가 | FE | candles | candles |
| 8 | Volatility | 변동성(주/월) | FE `volatility()` **신규** | 일간 수익률 표준편차 5일/21일 | 동일 |
| 9 | ATR (14) | ATR(14) | FE `risk.atr` | 기존 | 기존 |
| 10 | RSI (14) | RSI(14) | FE `candles.rsi` | 기존 | 기존 |
| 11 | Beta | 베타 | `snapshot.beta` | yf `beta` | yf |
| 12 | Rel Volume | 상대 거래량 | FE `relVolume` | 기존 | 기존 |
| 13 | Avg Volume | 평균 거래량(20) | FE `avgVolume` | 기존 | 기존 |
| 14 | Volume | 거래량 | FE `last.volume` | 기존 | 기존 |

**열6 — 성과·컨센서스·가격**

| 행 | finviz | MyStock 라벨 | 키 | 비고 |
|---|---|---|---|---|
| 1~6 | Perf Week~Year | 1주·1개월·3개월·6개월·연초대비·1년 | `snapshot.perf.w1/m1/m3/m6/ytd/y1` | **BE 계산**(`price_cache` 1100영업일). candles는 200봉뿐이라 FE로는 1Y를 못 만든다 |
| 7~8 | Perf 3Y / 5Y | 3년·5년 | `snapshot.perf.y3/y5` | `price_cache` 범위(≈4.8년) 안이면 값, 아니면 null |
| 9 | Perf 10Y | 10년 | `snapshot.perf.y10` | 월봉 10년 1콜(TTL 7일). 실패 시 null |
| 10 | Recom | 컨센서스 의견 | `snapshot.recommendation_mean` | **1=강력매수 기준으로 정규화**(§5 주의) |
| 11 | Target Price | 목표주가 | `snapshot.target_price` | 종목 통화 |
| 12 | Prev Close | 전일 종가 | FE | 기존 |
| 13 | Price | 현재가 | FE | 기존 |
| 14 | Change % | 등락률 | FE | 기존 |

**채움 칸 수 요약**: US 66/84, KR 1차 52/84, KR 2차 58/84. 나머지는 `—`.

**표기 규칙**(finviz 준수): 부호·색은 변화율/이격/성과 칸에만. 큰 수 축약은 USD `333.70B`/`92.20M`,
KRW `12.3조`/`4,560억`. 두 값 한 칸(`52주 고가 126.71 -36.75%`)은 기존 `snap-value small` 패턴 유지.

---

## 5. API 계약

### 5.1 공통 규칙

| 항목 | 규칙 |
|---|---|
| 금액 | **종목 통화 원단위 숫자**(USD=달러, KRW=원). 축약·기호는 FE 담당 |
| 비율 | **퍼센트 숫자**(49.54). 0~1 비율로 오는 원본은 BE가 ×100. 필드명 접미사 `_pct` |
| 배수 | 배수 그대로(부채비율 0.55). yfinance `debtToEquity`(55.0)·Naver 부채비율(%)은 BE가 ÷100 |
| 날짜 | `YYYY-MM-DD` |
| 일시 | ISO8601 로컬(KST) `YYYY-MM-DDTHH:MM:SS` |
| null | 값이 없으면 **`null`**(빈 문자열·`"—"`·`0` 금지). FE가 `—`로 렌더 |
| 신규/기존 | 기존 필드는 **하나도 지우거나 이름 바꾸지 않는다**. `fundamentals`(per/pbr/dividend_yield/market_cap)도 그대로 유지 — `snapshot`과 값이 중복돼도 남긴다 |

### 5.2 `GET /api/tickers/{symbol}` — 추가 필드만

| 필드 | 타입 | null | 단위 | 신규/기존 | 비고 |
|---|---|---|---|---|---|
| (기존 전부) | — | — | — | 기존 | `fundamentals`, `signal`, `candles`, `risk`, `cost_rates`, `cash`, `dividends`, `history`, `rules`, `entry_review`, `last_refresh` 유지 |
| `profile` | object\|null | O | — | **신규** | 캐시 없으면 null |
| `profile.sector` | string\|null | O | — | 신규 | KR은 한글(Daum WICS) 우선 |
| `profile.industry` | string\|null | O | — | 신규 | |
| `profile.country` | string\|null | O | — | 신규 | `"United States"` / `"South Korea"` |
| `profile.exchange` | string\|null | O | — | 신규 | `NMS`→`NASDAQ` 등 BE가 표시명으로 정규화 |
| `profile.employees` | int\|null | O | 명 | 신규 | |
| `profile.ipo_date` | string\|null | O | `YYYY-MM-DD` | 신규 | |
| `profile.website` | string\|null | O | URL | 신규 | |
| `profile.description` | string\|null | O | — | 신규 | 최대 2000자, 초과 시 잘라내고 `description_truncated:true` |
| `profile.description_lang` | `"ko"`\|`"en"`\|null | O | — | 신규 | KR에서 `"en"`이면 FE가 "영문 원문" 배지 |
| `profile.source` | string | X | — | 신규 | `"yfinance"`/`"daum"`/`"fdr"` 조합, `+` 연결 |
| `profile.fetched_at` | string\|null | O | ISO | 신규 | |
| `snapshot` | object\|null | O | — | **신규** | §4.3 키 전부. **모든 하위 키는 null 허용**, 키 자체는 항상 존재 |
| `snapshot.perf` | object | X | % | 신규 | `w1,m1,m3,m6,ytd,y1,y3,y5,y10` 각 number\|null |
| `snapshot.recommendation_mean` | number\|null | O | 1~5(**1=강력매수**) | 신규 | |
| `snapshot.recommendation_scale` | string | X | — | 신규 | 항상 `"1=strong_buy..5=strong_sell"` — 소스 스케일 뒤집힘을 화면이 검증할 수 있게 |
| `snapshot.target_price` | number\|null | O | 종목 통화 | 신규 | |
| `snapshot.sources` | string[] | X | — | 신규 | 예 `["yfinance","naver"]` |
| `snapshot.fetched_at` | string\|null | O | ISO | 신규 | |
| `snapshot.status` | `"ok"`\|`"pending"` | X | — | 신규 | `pending` = 아직 수집 전 |

> **`recommendation_mean` 정규화 주의(구현 전 실측 필수)**: yfinance는 1=strong buy, 네이버
> `recommMean`은 값이 클수록 매수인 사례가 보고돼 있다. BE는 **네이버 값을 실측한 뒤 1=강력매수로
> 뒤집어서** 내보낸다. 뒤집지 않으면 "강력매도"를 "강력매수"로 표시하는, 화면이 조용히 반대로
> 말하는 버그가 된다. 단위 테스트로 고정한다(`test_naver_recomm_normalized`).

### 5.3 `GET /api/tickers/{symbol}/company` — 신규 엔드포인트

**분리 근거**: 개요 응답은 이미 candles 200봉(≈40KB)을 싣는다. 여기에 뉴스 20건(≈8KB) ·
내부자 30건(≈12KB) · 재무 24포인트 · 등급 변경 20건을 더하면 **첫 페인트에 필요 없는 데이터가
첫 응답을 60% 이상 키운다**(finviz도 이 4블록은 스크롤 아래에 있다). 또한 이 4블록은 TTL이
서로 다르고(뉴스 1시간 vs 재무 7일) 부분 실패가 잦아, 하나 실패하면 개요 전체가 흔들리는 구조를
피해야 한다. 요청 수는 늘지 않는다 — 개요가 더 이상 `/backtest`를 부르지 않으므로 2회 그대로.

응답 = 4개 블록 래퍼. **모든 블록은 같은 래퍼 모양**을 가진다:

| 필드 | 타입 | null | 설명 |
|---|---|---|---|
| `symbol` | string | X | |
| `<block>.status` | `"ok"`\|`"pending"`\|`"unavailable"` | X | `pending`=수집 전(새로고침 안내), `unavailable`=구조적 미제공(키 없음/소스 없음) |
| `<block>.note` | string\|null | O | `unavailable`이면 **필수**. 한국어 사용자 문구 그대로 렌더된다 |
| `<block>.source` | string\|null | O | `"yfinance"`/`"naver"`/`"dart"` |
| `<block>.fetched_at` | string\|null | O | ISO |

블록별 payload:

| 블록 | 필드 | 타입 | null | 단위 |
|---|---|---|---|---|
| `financials` | `annual` | item[] | X(빈 배열 가능) | — |
| | `quarterly` | item[] | X | — |
| | item.`period` | string | X | `"2024"` / `"2024Q3"` / `"TTM"` / `"MRQ"` |
| | item.`end_date` | string\|null | O | `YYYY-MM-DD` |
| | item.`eps` | number\|null | O | 종목 통화(주당) |
| | item.`sales` | number\|null | O | 종목 통화(원단위 절대값) |
| | item.`shares_outstanding` | number\|null | O | 주 |
| | item.`estimate` | boolean | X | 컨센서스 추정치면 true |
| | `shares_note` | string\|null | O | KR 1차에서 "발행주식수 이력은 OpenDART 키 등록 후" |
| `news` | `items[].published_at` | string | X | ISO(KST) |
| | `items[].title` | string | X | |
| | `items[].source` | string\|null | O | 언론사 |
| | `items[].url` | string | X | |
| | `items[].lang` | `"ko"`\|`"en"` | X | |
| | 개수 | — | — | 최대 20 |
| `ratings` | `consensus` | object\|null | O | |
| | `consensus.recommendation_mean` | number\|null | O | 1~5(1=강력매수) |
| | `consensus.recommendation_label` | string\|null | O | `"매수"` 등 한국어 |
| | `consensus.target_mean` | number\|null | O | 종목 통화 |
| | `consensus.target_upside_pct` | number\|null | O | % (현재가 대비, BE 계산) |
| | `consensus.analyst_count` | int\|null | O | 명 |
| | `consensus.as_of` | string\|null | O | `YYYY-MM-DD` |
| | `changes[]` | object[] | X(빈 배열) | |
| | `changes[].date` | string | X | `YYYY-MM-DD` |
| | `changes[].firm` | string | X | |
| | `changes[].action` | string | X | `Upgrade/Downgrade/Reiterated/Initiated/Resumed/기타` |
| | `changes[].from_grade`,`to_grade` | string\|null | O | 원문 그대로 |
| | `changes[].from_target`,`to_target` | number\|null | O | 종목 통화 |
| | `reports[]`(KR 대체) | object[] | X(빈 배열) | `date`, `firm`, `title`, `url`\|null |
| | 개수 | — | — | changes 최대 20, reports 최대 10 |
| `insiders` | `items[].name` | string | X | |
| | `items[].relation` | string\|null | O | 직위·관계 |
| | `items[].date` | string | X | `YYYY-MM-DD` |
| | `items[].transaction` | string | X | `Buy/Sale/Option Exercise/장내매수` 등 원문 |
| | `items[].price` | number\|null | O | 종목 통화 |
| | `items[].shares` | number\|null | O | 주 |
| | `items[].value` | number\|null | O | 종목 통화 |
| | `items[].shares_total` | number\|null | O | 주 |
| | `items[].url` | string\|null | O | SEC Form 4 / DART 공시 |
| | 개수 | — | — | 최대 30 |

에러: 종목 없음 → `HTTPException(404, "ticker not found")`. **캐시가 비어도 200**을 주고
전 블록 `status:"pending"`(404를 주면 FE가 종목 없음과 구분하지 못한다).

### 5.4 응답 예 (KR, 키 없음)

```json
{"symbol":"000660",
 "insiders":{"status":"unavailable","note":"국내 종목 내부자 거래는 OpenDART 키(무료)를 등록해야 표시됩니다.","source":null,"fetched_at":null,"items":[]},
 "ratings":{"status":"ok","note":"국내 종목은 증권사별 투자의견 변경 이력을 제공하는 무료 소스가 없어 최근 리포트 목록으로 대신합니다.","source":"naver","fetched_at":"2026-08-21T14:00:00","consensus":{"recommendation_mean":1.4,"recommendation_label":"강력매수","target_mean":320000,"target_upside_pct":12.4,"analyst_count":27,"as_of":"2026-08-19"},"changes":[],"reports":[{"date":"2026-08-20","firm":"미래에셋증권","title":"HBM 증설 효과 본격화","url":null}]}}
```

---

## 6. 갱신·캐시

### 6.1 캐시 테이블 (마이그레이션 포함)

`schema.sql`에 추가(기존 DB는 `get_conn`의 `executescript`가 매번 실행하므로 `IF NOT EXISTS`만으로
마이그레이션 완료 — `db.py` 수정 불필요):

```sql
CREATE TABLE IF NOT EXISTS company_cache (
  symbol TEXT NOT NULL,
  block TEXT NOT NULL,          -- profile|snapshot|financials|news|ratings|insiders
  payload TEXT NOT NULL,        -- JSON
  source TEXT,
  fetched_at TEXT NOT NULL,     -- 마지막 '성공' 시각
  attempted_at TEXT,            -- 마지막 시도(성공/실패 무관) — 실패 재시도 backoff 기준
  error TEXT,                   -- 마지막 실패 사유. 성공 시 NULL로 지운다
  PRIMARY KEY (symbol, block)
);
```

**실패 시 이전 캐시 유지 규칙**: 실패해도 `payload`/`fetched_at`은 건드리지 않고 `attempted_at`·
`error`만 갱신한다. 행 삭제 금지. 화면은 낡은 값 + `fetched_at`(상대시각)을 계속 보여준다 —
값을 지우면 "데이터가 원래 없는 종목"과 "이번에 실패한 종목"을 구분할 수 없다.

기존 `meta`의 `fund:{symbol}`은 **그대로 둔다**(구버전 빌드본 호환).

### 6.2 TTL과 루프당 상한

| 블록 | TTL | 호출 비용 |
|---|---|---|
| profile | 7일 | yf info 재사용 + Daum 1콜 + FDR(프로세스 캐시) |
| snapshot | 12시간 | yf `info` 1~3초 + Naver 2콜(integration, quarter) |
| financials | 7일 | yf 2콜 / Naver 2콜 |
| news | 1시간 | 1콜 |
| ratings | 24시간 | yf 1~2콜 / Naver 2콜 |
| insiders | 24시간 | yf 1콜 / DART 1콜 |
| perf 10Y(월봉) | 7일 | 1콜 |

- **`COMPANY_MAX_SYMBOLS_PER_RUN = 8`**. `refresh_all(symbol=None)` 한 번에 최대 8종목만 회사
  자료를 갱신한다. TTL 만료된 종목 중 `fetched_at` 오래된 순, 동률이면 **보유 > 관심 > 기타** 우선.
  종목 수가 늘어도 루프 시간이 선형으로 늘지 않는다(8종목 × 최악 5콜 ≈ 40콜/시간, 20~40초).
- 종목 40개·TTL 12시간 기준 한 바퀴 = 5시간 → snapshot이 최장 17시간 낡을 수 있다. 이 값은
  `fetched_at`으로 화면에 노출된다(B1). 40종목을 넘기면 상한을 올리는 게 아니라 **관심목록 우선**으로 좁힌다.
- 소스 호출은 **순차 + 종목 간 0.3초 sleep**, `User-Agent` 지정(Naver·Daum은 비공식 API — 병렬로 때리면 차단된다).
- 실패 backoff: `attempted_at`이 30분 이내면 같은 블록을 다시 시도하지 않는다.
- 시세·시그널 갱신은 지금 그대로 매 루프 전 종목. 회사 자료 실패가 시세 갱신을 막지 않도록
  `try/except`로 완전히 격리하고, 실패 심볼은 기존 `failed_tickers`가 **아니라** 새 키
  `failed_company`(신규, 추가 필드)로 보고한다.

### 6.3 요청 경로의 외부 호출 금지

- `get_ticker_detail`, `get_company`는 **`company_cache`만 읽는다.** 외부 호출 코드 경로가
  없어야 한다(테스트로 고정: §9 AC-13).
- 예외는 **명시적 수동 새로고침**: `POST /api/refresh?symbol=XXX`는 TTL을 무시하고 그 종목의
  6블록을 강제 갱신한다(사용자가 버튼을 눌렀고 이미 스피너가 돌고 있다). 최대 소요 10초 —
  기존 단일 갱신도 수 초라 UX 회귀는 없다.
- 새 종목 추가 직후 개요는 `status:"pending"` + "회사 자료를 아직 받지 못했습니다 — 새로고침을
  누르면 지금 가져옵니다".

---

## 7. 제거되는 블록 처리

| 블록 | 처리 |
|---|---|
| 시그널 근거(`#signal`) | `pages/ticker/Analysis.tsx`로 **JSX 이동**(리팩터링 금지, 잘라 붙이기) |
| 백테스트(`#backtest`) | 동일 이동. `/api/tickers/{symbol}/backtest` 호출도 Analysis로 이동 |
| 청산 플랜·포지션(`#position`) | 동일 이동 |
| 커스텀 룰(`#rules`) | 동일 이동 — **필수**(아래) |
| 시그널 히스토리(`#history`) | 동일 이동 |

**왜 삭제가 아니라 이동인가**: `POST /api/rules`·`DELETE /api/rules/{id}` UI는 **앱 전체에서 이
화면에만 있다**(grep 확인: `TickerDetail.tsx` 4곳이 전부). 개요에서 지우면 손절·목표 알림 룰을
등록·삭제할 경로가 사라져 알림 기능이 죽는다. 브리프 2항의 "추후 별도 탭으로 복귀 가능"을
이번 라운드에 함께 처리한다.

- 라우트: `/ticker/:symbol/analysis` 추가(`App.tsx` 1줄). 개요 탭 줄 마지막에 `분석` 탭 → 링크 이동.
- **컴포넌트 파일 삭제 없음**: `BacktestTable.tsx`(TickerDetail 전용)는 Analysis가 계속 쓴다.
  `SignalBadge`/`ScoreBar`는 Dashboard/Watchlist도 쓴다 — 손대지 않는다.
- 개요에 남는 MyStock 요소: **판정 한 줄**, 헤더의 `새로고침`·`매매 기록` 버튼(기능 진입점이라 유지),
  차트의 손절/목표/평단 라인. 스냅샷 표에서는 MyStock 고유 칸(스윙 점수·등급·손절가·보유수량·
  승률·판별력 등 22칸)을 **전부 빼고** finviz 84칸으로 교체한다.
- 백엔드 `/backtest` 엔드포인트·`backtest.py`·테스트는 **그대로 둔다**(Analysis가 부른다).

---

## 8. 작업 분할

### 8.1 백엔드 (`backend/` 만)

| 순서 | 파일 | 할 일 |
|---|---|---|
| 1 | `backend/app/schema.sql` (공용) | `company_cache` 테이블 추가 |
| 2 | `backend/app/company.py` (**신규**) | 캐시 read/write 헬퍼, TTL·우선순위 선정, 블록 조립기 `build_profile/snapshot/financials/news/ratings/insiders`, `refresh_company_blocks(conn, tickers)`, `get_company(conn, symbol)` |
| 3 | `backend/app/sources/` (**신규 패키지**) | `yf.py`, `naver.py`, `daum.py`, `krx_desc.py`, `dart.py` — **HTTP/라이브러리 호출은 여기서만**. 테스트가 이 계층만 monkeypatch하면 네트워크 0 |
| 4 | `backend/app/service.py` (공용) | `refresh_all`에 `company.refresh_company_blocks(...)` 호출 1곳(예외 격리) + `failed_company` 키 추가, `get_ticker_detail`에 `profile`·`snapshot` 2필드 추가, `POST /api/refresh?symbol=`의 강제 갱신 경로 |
| 5 | `backend/app/api.py` (공용) | `GET /tickers/{symbol}/company` 라우트 1개 |
| 6 | `backend/tests/test_company.py` (신규) | §9 AC-10~14 |
| 7 | `backend/tests/test_service.py`, `test_api.py` | 기존 필드 회귀 + 신규 필드 존재 |

`fetchers.py`는 **건드리지 않는다**(시세 담당). `fetch_fundamentals`도 그대로 — `fund:{symbol}` 계약 유지.

### 8.2 프론트엔드 (`frontend/` 만)

| 순서 | 파일 | 할 일 |
|---|---|---|
| 1 | `src/types.ts` (공용) | `Profile`, `Snapshot`, `Company`(4블록), 기존 `TickerDetail`에 `profile`/`snapshot` **선택 필드**(`?:`)로 추가 — 구버전 백엔드에서도 타입이 깨지지 않게 |
| 2 | `src/quote/fmt.ts` (**신규**) | `abbrNum(currency, n)`(B/M ↔ 조/억), `pctText`, `moneyCell`. **`format.ts`는 건드리지 않는다** — 축약 규칙이 대시보드까지 번지면 화면 하나 범위를 벗어난다 |
| 3 | `src/quote/stats.ts` | `volatility(candles, bars)`, `avgTurnover(candles, bars)` 추가 (`stats.test.ts`에 케이스 추가) |
| 4 | `src/quote/snapshotCells.ts` (**신규**) | 84칸 조립(§4.3) — `TickerDetail.tsx`에서 셀 정의를 통째로 옮긴다 |
| 5 | `src/components/quote/QuoteHeader.tsx` | 섹터·산업·국가·거래소·직원수 줄 추가(링크 아닌 텍스트 — 스크리너가 없다) |
| 6 | `src/components/quote/FinancialsChart.tsx` (신규) | recharts 막대 3개 + 연간/분기 토글 + 추정 막대 반투명 |
| 7 | `src/components/quote/NewsList.tsx` (신규) | 날짜 바뀔 때만 날짜 표기, 같은 날은 시각만(finviz 규칙) |
| 8 | `src/components/quote/RatingsTable.tsx` (신규) | consensus 요약 + changes 표 + KR `reports` 대체 표 + `note` 빈 상태 |
| 9 | `src/components/quote/InsiderTable.tsx` (신규) | 9열 표, 모바일에서 카드로 접힘 |
| 10 | `src/components/quote/BlockEmpty.tsx` (신규) | `status`/`note` 공통 빈 상태·스켈레톤 |
| 11 | `src/pages/ticker/Analysis.tsx` (신규) | §7 이동분 |
| 12 | `src/pages/TickerDetail.tsx` | 개요만 남기고 재조립. `/company` 지연 로드(첫 페인트 후) |
| 13 | `src/App.tsx` (공용) | `/ticker/:symbol/analysis` 라우트 1줄 |
| 14 | `src/quote.css` | 신규 블록 스타일(화면 전용 파일) |

### 8.3 파일 소유권

- **BE만**: `backend/app/{schema.sql, company.py, sources/*, service.py, api.py}`, `backend/tests/*`
- **FE만**: `frontend/src/**`
- **양쪽이 만지는 파일 없음.**
- **공용 파일 카운트** — BE 3개(`schema.sql`, `service.py`, `api.py`), FE 2개(`types.ts`, `App.tsx`).
  각각 상한 3 이내. `db.py`·`format.ts`·`fetchers.py`·`costs.py`는 의도적으로 회피했다
  (§6.1 `IF NOT EXISTS` 마이그레이션, §8.2-2 로컬 포맷 모듈).

---

## 9. 수용 기준

실행 전제: `preview_start mystock`(8722) + `npm run build`. KR/US 종목이 워치리스트에 있고
`POST /api/refresh?symbol=...`을 한 번 눌러 캐시가 채워진 상태.

| # | 기준 | 확인 방법 |
|---|---|---|
| AC-1 | `GET /api/tickers/AAPL`에 기존 11개 키(`fundamentals,signal,candles,risk,cost_rates,cash,dividends,history,rules,entry_review,last_refresh`)가 모두 남아 있다 | `curl -s .../api/tickers/AAPL \| jq 'keys'` |
| AC-2 | 같은 응답에 `profile`,`snapshot` 존재. `snapshot.perf`의 9키 전부 존재(값은 null 허용) | `jq '.snapshot.perf \| keys'` → 9개 |
| AC-3 | **AAPL 스냅샷**: 84칸 중 `—` 표시가 **12칸 이하**. 다음 12칸은 반드시 값이 있다 — 시가총액·PER·EPS(TTM)·ROE·영업이익률·발행주식수·베타·목표주가·컨센서스 의견·실적발표일·상장일·직원수 | 화면 육안 + `jq` 각 키 non-null |
| AC-4 | **000660 스냅샷**: 다음 14칸에 값 — 시가총액·PER·PBR·EPS(TTM)·BPS·배당수익률·ROE·영업이익률·발행주식수·베타·목표주가·컨센서스 의견·상장일·직원수. 공매도 3칸(공매도 비율/상환일수/잔고)은 `—` | 동일 |
| AC-5 | 000660 `profile.description`이 **한국어 100자 이상**, `description_lang=="ko"` | `jq '.profile.description \| length'` ≥ 100 |
| AC-6 | `GET /api/tickers/000660/company`: `news.items` ≥ 5, 전부 `lang=="ko"`; `financials.annual` ≥ 3; `ratings.reports` ≥ 3; `ratings.changes == []`이고 `ratings.note`가 비어있지 않다; `insiders.status=="unavailable"`이고 `insiders.note`가 비어있지 않다 | `curl \| jq` |
| AC-7 | `GET /api/tickers/AAPL/company`: `news.items` ≥ 5, `ratings.changes` ≥ 5, `insiders.items` ≥ 5, `financials.annual` ≥ 4, `financials.quarterly` ≥ 4 | 동일 |
| AC-8 | KR 화면에서 내부자 표 자리에 **`note` 문장이 그대로** 보이고 빈 표·`undefined`·`NaN`이 없다 | 육안 + DOM 텍스트 검색 `undefined\|NaN\|null` 0건 |
| AC-9 | 개요 화면에서 `/backtest` 요청이 **0건**. `/analysis`에서만 1건 | DevTools Network / `preview_logs` 접근 로그 |
| AC-10 | 손절 룰 등록·삭제가 `/ticker/:symbol/analysis`에서 동작한다(등록 후 `rules` 배열 길이 +1) | 화면 조작 + `curl .../api/tickers/{s}` |
| AC-11 | `cd backend && .venv/bin/pytest -q` 통과, **네트워크 차단 상태에서도** 통과 | 명령 실행 |
| AC-12 | `test_company.py`에 다음이 있고 통과: 비율→퍼센트 정규화, `debtToEquity` ÷100, 배당수익률 스케일 가드, KR `per/pbr`이 Naver 폴백으로 채워짐, `recommendation_mean` 1=강력매수 정규화 | `pytest -q backend/tests/test_company.py -v` |
| AC-13 | **요청 경로 외부 호출 0**: `app.sources` 전 모듈을 `raise AssertionError`로 monkeypatch한 상태에서 `GET /api/tickers/X`·`/company`가 200 | `test_detail_never_calls_network` |
| AC-14 | 외부 호출 실패를 주입해도 이전 캐시 `payload`·`fetched_at`이 보존되고 `error`만 채워진다 | `test_cache_kept_on_failure` |
| AC-15 | `refresh_all`이 한 번에 **최대 8종목**만 회사 자료를 갱신하고, TTL 내 종목은 호출하지 않는다 | `test_refresh_respects_ttl_and_cap` |
| AC-16 | `cd frontend && npx tsc -b && npm run lint` 무경고 통과 | 명령 실행 |
| AC-17 | **390px 폭에서 가로 스크롤 0** (개요·분석 두 화면 모두) | `document.documentElement.scrollWidth <= window.innerWidth` |
| AC-18 | 390px에서 스냅샷 2쌍/행, 내부자 표가 가로 스크롤 없이 카드로 접힘 | 육안 계측 |
| AC-19 | 캐시가 없는 신규 종목에서 4블록이 전부 `pending` 문구를 띄우고 화면이 깨지지 않는다 | 새 종목 추가 직후 접속 |
| AC-20 | 재무 차트 연간/분기 토글이 두 데이터셋을 실제로 바꾸고, 추정 막대가 시각적으로 구분된다(불투명도 또는 `(E)` 라벨) | 육안 |
| AC-21 | 축약 표기: USD `333.70B`/`92.20M`, KRW `12.3조`/`4,560억`. **KRW에 소수점 원 단위 없음** | 육안(AAPL·000660 시가총액 칸) |

---

## 10. 리스크

| 리스크 | 영향 | 완화 |
|---|---|---|
| Naver/Daum은 비공식 API — 예고 없이 스키마·차단 변경 | KR 스냅샷·뉴스·컨센서스 동시 사망 | 소스별 어댑터를 `sources/`로 격리, 파싱 실패 시 블록만 `unavailable`, 캐시 보존(§6.1). yfinance 폴백 경로를 KR에서도 항상 유지 |
| `recommendation_mean` 스케일 뒤집힘 | 화면이 **정반대 조언**을 표시 | 계약에 `recommendation_scale` 고정 + 단위 테스트(AC-12) |
| 비율 단위 혼동(0.4954 vs 49.54, dividendYield 0.5 vs 50) | 수익성·배당 칸이 100배 틀림 | `_pct` 접미사 + BE 정규화 + 범위 가드 테스트 |
| `refresh_all` 루프가 길어져 시세 갱신·CODEF 동기화가 밀림 | 대시보드 전체 신선도 저하 | 8종목 상한·순차 0.3초·완전 예외 격리·30분 backoff. 회사 자료는 시세 루프 **뒤에** 실행 |
| `service.py`가 커지는 중(1279줄) | 다른 화면 회귀 | 신규 로직은 전부 `company.py`. `service.py` 변경은 호출 1곳 + 응답 2필드로 제한 |
| `types.ts` 변경 | 포트폴리오·대시보드 타입 영향 | **추가만**, 신규 필드는 `?:` 선택으로 선언 → 구버전 백엔드/빌드본에서도 컴파일 유지 |
| `App.tsx` 라우트 추가 | 라우터 공용 | 1줄 추가, 기존 `/ticker/:symbol` 경로 불변 |
| `company_cache` 크기 증가 | DB 파일 팽창 | 종목당 6행 · 블록당 상한(뉴스20/내부자30/등급20)으로 종목당 ≈40KB. 100종목 4MB — 허용 |
| 개요에서 MyStock 판단 근거가 사라짐 | "왜 이 판정인가"를 못 봄 | 판정 한 줄 유지 + `분석` 탭 링크를 판정 줄 우측에 배치 |
| 미커밋 작업 트리(codef 백엔드 + 배치 개편 프론트) | 엔지니어 병렬 작업 시 충돌 | **엔지니어 투입 전 리더가 커밋/스태시로 정리**(브리프 제약) |
