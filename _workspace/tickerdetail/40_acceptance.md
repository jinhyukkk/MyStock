# TickerDetail Phase 4 수용 검수 (2026-08-22)

- 대상: `20_spec.md` §9 AC-1~21 · `21_contract_v2.md` §6 검증항목 V1~V6 · `41_recheck_layout.md` D1~D13/R1~R4
- 검수 환경: **8722(빌드본)** — 백엔드 v2 서빙 확인, `frontend/dist` 재빌드 확인(`dist/assets/*.js` 08-21 16:09 ≥ 소스 최신 16:05, 번들에 v2 라벨 `EPS 전년동기(분기)`·`EPS 서프라이즈` 포함) → **V6 PASS**
- 도구 제약: **브라우저 사용 불가.** 화면 계측은 `41_recheck_layout.md`(빌드본 16:06 기준, 재빌드 **직전**)와 `30_frontend_report.md` v2-3(5173 dev, 재빌드와 동일 소스 기준)을 증거로 채택. 두 문서가 충돌하는 지점은 §4에 명시했다.
- 검수 제외(브리프 15:35): `Dashboard.tsx`, `Layout.tsx`, `SentimentGauge.tsx`, `theme.css`, `frontend/src/finviz/**`, `backend/app/market*.py`, `tests/test_market.py`, `/` 화면.

---

## 0. 결론

**전체 PASS — 단 AC-21 1건 FAIL.** 계약 교차 대조는 **불일치 0건**(§2). 나머지 20개 AC는 PASS(그중 5개는 브라우저 계측 대행 근거).

- **FAIL 1건**: AC-21 축약 표기 — KR 종목의 `평균 거래량(20)` 칸이 USD 규칙으로 축약되고(`5.73M`), 조 단위에 천단위 구분이 없다(`1263.8조`). 둘 다 FE 1~2줄 수정.
- **이번 라운드 수정 필수 8건**: D1·D3·D4·D6·D7·D8·D11(R2)·D12 (§5)
- **보류 7건**: D5(툴팁만 필수)·D9·D10·D13(R1/R3)·뉴스 제목 절단·`quote/cells.ts` 사장 코드·DART 2차 실호출 (§6, `20_spec.md` §3에 이관 완료)
- **회귀 아님으로 판정**: R1·R3(기준선 계측 누락), R4(재빌드로 해소), D2(이미 수정됨)
- **파일 소유권 위반 0건** — 공용 파일 BE 3/3 · FE 2/2 준수 (§3)

---

## 1. AC-1~21 판정

| # | 판정 | 증거 |
|---|---|---|
| AC-1 | **PASS** | `curl -s :8722/api/tickers/AAPL \| jq 'keys'` → `["candles","cash","cost_rates","currency","dividends","entry_review","fundamentals","history","is_etf","last_refresh","market","name","profile","risk","rules","signal","snapshot","symbol"]`. 기존 11키 전원 생존, 삭제·개명 0. 000660 동일 |
| AC-2 | **PASS** | `jq '.snapshot.perf\|keys'` → 9개(`m1,m3,m6,w1,y1,y10,y3,y5,ytd`). `profile`·`snapshot` 존재 |
| AC-3 | **PASS** | AAPL `snapshot` null 키 8개 중 `note`(칸 아님) 제외 **7칸** ≤ 12 — `eps_next_5y_pct, eps_past_5y_pct, sales_past_5y_pct, earnings_timing, sales_surprise_pct, inst_trans_pct, foreign_own_pct`. 필수 12칸 전부 non-null: `market_cap 4514709504000 · pe 35.48 · eps_ttm 8.72 · roe_pct 148.75 · oper_margin_pct 32.62 · shares_outstanding 14594180000 · beta 1.086 · target_price 326.3415 · recommendation_mean 2.11 · earnings_date 2026-10-30 · ipo_date 1980-12-12 · employees 150000` |
| AC-4 | **PASS** | 000660 필수 14칸 전부 non-null: `market_cap 1263751800000000 · pe 7.71 · pb 4.67 · eps_ttm 224313 · book_per_share 370432 · dividend_yield_pct 0.17 · roe_pct 92.68 · oper_margin_pct 76.33 · shares_outstanding 709854891 · beta 2.413 · target_price 3317917 · recommendation_mean 2.0 · ipo_date 1996-12-26 · employees 47639`. 공매도 3칸(`short_float_pct/short_ratio/short_interest`) 전부 null ✅. 계약 v2 BE-1 판정 기준("최근 배당 칸 보조값 `0.17%`") 충족 — FE 보고서 DOM 발췌 `<span class="snap-value">3,000<small>0.17%</small></span>` |
| AC-5 | **PASS** | `jq '{len:(.profile.description\|length), lang:.profile.description_lang}'` → `{"len":222,"lang":"ko"}` (≥100) |
| AC-6 | **PASS** | 000660 `/company`: `news.items` 20건·`lang` 전부 `ko` / `financials.annual` 4 / `ratings.reports` 10 / `ratings.changes` `[]` + `note` 57자 / `insiders.status "unavailable"` + `note` 41자 |
| AC-7 | **PASS** | AAPL `/company`: `news 10 · changes 20 · insiders.items 30 · annual 4 · quarterly 5` |
| AC-8 | **PASS**(대행 근거) | BE 실응답에 `insiders.note`(한국어 41자) 존재 확인. FE는 `BlockEmpty`가 `block.note`를 그대로 렌더(`components/quote/BlockEmpty.tsx`), 자체 문구를 만들지 않음. FE 보고서 v2-3 실데이터 계측 "빈 표 없음, DOM `undefined\|NaN\|null` 0건" + 레이아웃 계측 §1-3행 "PASS 0"(4개 경로 전부) — **두 문서 일치** |
| AC-9 | **PASS** | 소스 대조: `pages/TickerDetail.tsx`의 `get<>` 호출은 `/api/tickers/{s}`·`/api/tickers/{s}/company` 2건뿐, `/backtest` 문자열 없음. `pages/ticker/Analysis.tsx:57`에만 `/backtest`. FE 보고서 v2-3 네트워크 로그 일치 |
| AC-10 | **PASS**(대행 근거) | `grep -rn "api/rules" frontend/src` → 전부 `pages/ticker/Analysis.tsx`(129·138·139·397). 개요에는 0건 → 룰 등록·삭제 경로가 `/analysis`로 온전히 이동. FE 보고서: 등록 시 `rules` 0→1(`STOP 295.7143`), 삭제 1→0 |
| AC-11 | **PASS** | `cd backend && .venv/bin/pytest -q` → **338 passed, 4 deselected**. 네트워크 차단은 `tests/conftest.py`의 autouse `no_network_sources`가 `app.sources.{yf,naver,daum,krx_desc,dart}` 전 함수를 `AssertionError`로 치환해 구조적으로 보장 |
| AC-12 | **PASS** | `pytest -q tests/test_company.py` → 25 passed. 요구 5종 존재·통과: `test_ratio_to_percent`, `test_debt_to_equity_divided_by_100`(+`test_kr_debt_eq_is_ratio_not_percent`), `test_dividend_yield_scale_guard`(+`test_dividend_yield_stays_in_plausible_range`), `test_kr_per_pbr_falls_back_to_naver`, `test_naver_recomm_normalized` |
| AC-13 | **PASS** | `tests/test_api.py:514 test_detail_never_calls_network` — `yf.quote_info`/`naver.integration`/`daum.quote`가 `AssertionError`를 던지는 상태에서 `/api/tickers/005930`·`/company` 둘 다 200 |
| AC-14 | **PASS** | `test_cache_kept_on_failure` 통과(실패 주입 후 `payload`·`fetched_at` 보존, `error`만 채워짐) |
| AC-15 | **PASS**(실서버 미검증) | `test_refresh_respects_ttl_and_cap`(12종목 중 8종목만) · `test_refresh_prefers_holdings_then_watchlist` 통과. V5대로 실서버 전체 갱신은 CODEF 한도 때문에 미실행 — **"실행 미검증" 표기 유지** |
| AC-16 | **PASS** | `npx tsc -b` 종료코드 0·출력 없음, `npm run lint`(oxlint) 출력 없음 |
| AC-17 | **PASS**(대행 근거) | 레이아웃 계측 §1-1행: 8722 4경로 × 2폭 전부 `scrollWidth<=innerWidth`(1265/1280, 390/390). FE 보고서 v2-3도 동일. **주의**: 페이지 레벨만 PASS이고 내부 컨테이너는 §1-1b에서 FAIL(→ D13, §6 보류) — AC-17의 판정 문구(`document.documentElement.scrollWidth <= window.innerWidth`)로는 PASS다 |
| AC-18 | **PASS**(대행 근거) | 390px 스냅샷 2쌍/행(첫 행 동일 `top` 칸 2개), 내부자 표 `tr{display:block}` + `td::before{content:attr(data-label)}` 실측. 레이아웃 계측 §1-6행·§5-4와 FE 보고서 일치 |
| AC-19 | **PASS** | `curl :8722/api/tickers/KRW-BTC` → `profile.status "pending"` + `note` "회사 자료를 아직 받지 못했습니다 — 새로고침을 누르면 지금 가져옵니다.", `snapshot.status "pending"`, `perf` 9키 존재. `/company` 4블록 전부 `pending`+`note`. 없는 종목은 404. FE 보고서 v2-3에서 화면 무손상·가로 스크롤 0 확인 |
| AC-20 | **PASS**(대행 근거) | 레이아웃 계측 §1-5/5b: AAPL 연간 3 svg → 토글 시 4→5막대 교체, 000660 추정 막대 `fill-opacity 0.35` + `(E)`. FE 보고서 v2-3 동일. **AAPL은 추정 막대 0건이라 구분 자체는 000660에서만 검증됨** |
| AC-21 | **FAIL** | 아래 §1.1 |

### 1.1 AC-21 FAIL 상세

기준: "USD `333.70B`/`92.20M`, KRW `12.3조`/`4,560억`. KRW에 소수점 원 단위 없음."

| 위반 | 실측 | 원인 | 소유 |
|---|---|---|---|
| **KR 종목 칸에 USD 축약 단위** | 000660 `평균 거래량(20) = 5.73M` ↔ 같은 열 `발행주식수 7.1억`·`유통주식수 5.7억` | `frontend/src/quote/snapshotCells.ts:150` `abbrNum('USD', avgVolume(c, 20))` — **통화 하드코딩**. 같은 파일 41행이 `const abbr = v => abbrNum(ccy, v)`를 정의해 두고 이 한 칸만 쓰지 않는다 | FE |
| **조 단위 천단위 구분 없음** | 000660 `시가총액 1263.8조`, `기업가치(EV) 1131.2조` | `frontend/src/quote/fmt.ts:22` `if (a>=1e12) return (a/1e12).toFixed(1)+'조'` — 1e15 이상 분기·`toLocaleString` 없음. 실값 `1263751800000000 → 1263.8조` | FE |

원 단위 소수점 금지·`4,560억`·`333.70B`/`92.20M`/`4.51T` 규칙은 준수(`fmt.ts` 단위 테스트 24/24 통과). **위 2건만 고치면 PASS.**

---

## 2. 계약 교차 대조 (V4)

### 2.1 실응답 ↔ `frontend/src/types.ts` — **불일치 0건**

`GET /api/tickers/{AAPL,000660}` · `/company` 실응답의 전 키를 `types.ts`의 15개 인터페이스(`TickerDetail, Profile, Snapshot, SnapshotPerf, Company, CompanyBlock, Financials, FinancialsItem, News, NewsItem, Ratings, RatingsConsensus, RatingChange, ResearchReport, Insiders, InsiderItem`)와 기계 대조했다. 배열은 원소 전체를 합집합으로 접어 "어떤 원소에서든 null이 나오는가"까지 봤다.

| 검사 | 결과 |
|---|---|
| 응답에만 있고 `types.ts`에 없는 키 | **0건** |
| `types.ts`에만 있고 응답에 없는 키 | **0건** |
| **응답이 null인데 `types.ts`가 non-null 선언** | **0건** (과거 화면을 깨뜨린 버그 유형) |
| **이름 같고 타입 다름**(`"12.5"` vs `12.5`) | **0건** — 모든 수치는 JSON number, 날짜·문구는 string |
| `snapshot` 키 집합 US↔KR 동일성 | 70키 완전 일치(`diff` SAME) — 시장에 따라 키가 사라지지 않는다 |

세부 확인 몇 가지:
- `profile.status`는 계약 v2에서 non-null(`'ok'|'pending'`)로 정했고 실응답도 항상 존재. `types.ts`는 `status?:`(선택)로 더 느슨하다 — **호환 방향이 안전한 쪽**(구버전 백엔드 대비)이라 불일치로 잡지 않는다.
- `Company` 최상위에는 `status/note/source/fetched_at`이 없고 4블록 각각이 `CompanyBlock`을 상속 — 계약 §5.3과 일치.
- `snapshot.recommendation_scale`은 US·KR 모두 `"1=strong_buy..5=strong_sell"` 고정, `recommendation_mean` AAPL 2.11 / 000660 2.0(네이버 4.00을 `6-v`로 뒤집은 값). **스케일 뒤집힘 리스크 해소 확인.**

### 2.2 D5 / V1 판정 — **KR `current_ratio` 단위 이상 아님. (a) 현행 유지 + 툴팁 출처 표기로 결정**

계측 이력이 엇갈려 세 갈래로 판정했다.

| 시점 | 000660 `current_ratio` | 000660 `quick_ratio` | 비고 |
|---|---|---|---|
| BE 보고 v2-3(08-21 15:4x) | **17.54** | 1.3297 | "당좌비율이 유동비율의 1/13" — 불가능한 조합으로 보고됨 |
| 레이아웃 계측(08-21 16:06, 빌드본) | 17.54 | 1.33 | D5로 "÷100 누락 의심" 기록 |
| **이번 검수(08-22 08:55, 8722 실응답)** | **2.59** | 1.3297 | `snapshot.fetched_at 2026-08-22T04:23:56` — 캐시 재수집 후 |

**소스 직접 확인**(`backend/.venv/bin/python`, yfinance 실호출):

```
000660.KS  currentRatio 2.591  quickRatio 2.26   debtToEquity 8.037
AAPL       currentRatio 1.003  quickRatio 0.812  debtToEquity 78.445
005930.KS  currentRatio 2.83   quickRatio 2.195  debtToEquity 3.868
```

→ **yfinance `currentRatio`는 KR에서도 % 단위가 아니라 배수다.** 17.54는 상류(yahoo)의 일시적 이상값이었고 재수집으로 자기 정정됐다. 코드 경로도 무해하다 — `company.py:694` `"current_ratio": _round(info.get("currentRatio"), 2)`는 변환 없이 그대로 싣고, `debtToEquity`만 `pct_to_ratio(...)`로 ÷100한다(`company.py:698`). **정규화 누락 없음.**

- **(b) KR null 기각**: 소스가 정상 배수를 준다. 값이 있는 칸을 비우면 정보만 잃는다.
- **(c) 정규화 기각**: 나눌 것이 없다.
- **(a) 채택 + 조건**: 남는 진짜 문제는 **한 쌍의 출처가 다르다**는 것이다 — KR `quick_ratio`는 네이버(국내 공시 당좌비율 132.97% → 1.3297), `current_ratio`는 yfinance(2.591). 정의 체계가 섞이면 두 칸을 비교하는 순간 사용자가 틀린 결론을 낸다. **FE는 두 칸 툴팁에 출처를 명시**(§5 F-c), **BE는 `quick_ratio > current_ratio`를 잡는 정합성 가드**를 넣는다(§6 보류 — 이번 라운드 필수 아님. 이번 사례에서 화면은 실제로 모순된 두 값을 보여줬고, 가드가 있었으면 그 칸을 비웠을 것이다).

### 2.3 그 외 단위 전수 점검 — 불일치 0건

AAPL·000660 `snapshot` 62개 수치 칸을 나란히 놓고 `_pct`·배수·통화를 확인했다.

| 분류 | 검사 | 결과 |
|---|---|---|
| `_pct` 접미사 칸 (28칸) | 퍼센트 숫자(0~1 비율 잔존 없음) | ✅ 예: `roe_pct` 148.75/92.68, `gross_margin_pct` 48.65/76.27, `float_pct` 99.83/79.78, `dividend_yield_pct` 0.35/0.17, `insider_own_pct` 1.65/20.21 |
| 배수 칸 (`debt_eq`,`quick_ratio`,`current_ratio`,`lt_debt_eq`) | US·KR 같은 단위(배수) | ✅ `debt_eq` 0.7844/0.4595 · `quick_ratio` 0.812/1.3297 · `current_ratio` 1.0/2.59 · `lt_debt_eq` 1.06/0.12 — 전부 0.x~2.x 자릿수 체계 |
| 배수 칸 (`pe,forward_pe,peg,ps,pb,pc,p_fcf,ev_ebitda,ev_sales,beta`) | 배수 그대로 | ✅ |
| 통화 원단위 (`market_cap, enterprise_value, income_ttm, sales_ttm, book_per_share, cash_per_share, dividend_*, eps_*, target_price`) | USD=달러 / KRW=원, 축약·기호 없음 | ✅ 내부 정합성 교차 확인: KR `market_cap/sales_ttm = 6.68 ≈ ps 6.49`, `market_cap/income_ttm = 7.80 ≈ pe 7.71`, `eps_ttm × shares = 159.2조 ≈ income_ttm`. **억원→원 변환 정상** |
| 주식수 (`shares_outstanding, shares_float, short_interest`) | 주 단위 정수 | ✅ |
| 날짜 (`earnings_date, dividend_ex_date, ipo_date, as_of, end_date`) | `YYYY-MM-DD` | ✅ |
| 일시 (`fetched_at, published_at`) | ISO 로컬(KST) | ✅ `2026-08-22T04:23:56` |
| `perf` 9칸 | 퍼센트 숫자 | ✅ AAPL `y5 108.89`·`y10 1096.58`, KR `y5 1613.17` — **B2(y5 채움) 반영 확인** |

**관찰 1건(단위 버그 아님, 기록만)**: 000660 `profit_margin_pct 85.62 > oper_margin_pct 76.33`. 영업외이익이 큰 분기면 성립하고 `income_ttm/sales_ttm = 85.6%`로 내부 정합하므로 단위 사고가 아니다. 상류 값 그대로.

### 2.4 V2·V3·V5·V6

| # | 판정 | 근거 |
|---|---|---|
| V1 | **해소** | §2.2 |
| V2 (`perf.ytd` 기준일 일치) | **실행 미검증** | 브라우저 없이 "snapshot을 지운 상태의 FE 폴백"을 만들 수 없다. 소스 대조로는 `snapshotCells.ts`가 `s.perf.ytd ?? perfYtdPct(c)`, `stats.ts:perfYtdPct`가 "작년 마지막 종가, 없으면 올해 첫 봉"으로 BE(`price_cache` 작년 마지막 종가)와 **1순위 기준일이 같다**. 폴백의 2순위(올해 첫 봉)만 달라질 수 있고, 이는 작년 데이터가 없는 신규 종목에 한정된다 → **수용** |
| V3 (84칸 라벨·순서) | **PASS**(대행 근거) | 레이아웃 계측 §1-2a: 4경로 전부 `.snap-cell` **84**개. §6-O1의 `.snap-label` 텍스트 diff가 v2 라벨 변경 3건과 정확히 일치(`EPS 전년동기(분기)`·`매출 전년동기(분기)`·`EPS 서프라이즈`), 나머지는 §4.3 표대로. 순서까지의 전수 대조는 브라우저 없이 불가 → **라벨 집합은 확인, 순서는 소스(`snapshotCells.ts` 열1~열6 배열 순서)로 확인** |
| V5 (8종목 상한 실서버) | **실행 미검증** | AC-15 참조 |
| V6 (빌드본이 신규 필드 서빙) | **PASS** | 8722 실응답에 `profile.status`·`snapshot.note`·`perf.y5`·`dividend_yield_pct` 전부 존재(v2 백엔드). `dist` 재빌드 확인(§ 상단) |

---

## 3. 파일 소유권 점검

`git status --short` · `git diff --stat` 기준. 브리프 "검수 제외" 파일은 대시보드 세션 소유로 분리했다.

### 3.1 이번 화면 작업분

| 소유 | 파일 | 공용 카운트 |
|---|---|---|
| **BE** | `backend/app/schema.sql`(M), `backend/app/service.py`(M), `backend/app/api.py`(M) | **3 / 상한 3** ✅ |
| BE | `backend/app/company.py`(신규), `backend/app/sources/`(신규 6파일) | 화면 전용 |
| BE | `backend/tests/{conftest.py, test_api.py, test_service.py}`(M), `test_company.py`(신규) | 아래 주1 |
| **FE** | `frontend/src/types.ts`(M), `frontend/src/App.tsx`(M) | **2 / 상한 2** ✅ |
| FE | `quote/{fmt,fmt.test,snapshotCells}.ts`(신규), `quote/stats*.ts`(M), `components/quote/{BlockEmpty,FinancialsChart,InsiderTable,NewsList,RatingsTable}.tsx`(신규), `{QuoteHeader,SnapshotTable}.tsx`(M), `pages/TickerDetail.tsx`(M), `pages/ticker/Analysis.tsx`(신규), `quote.css`(M) | 화면 전용 |

- **BE가 `frontend/`를 건드린 흔적 0건, FE가 `backend/`를 건드린 흔적 0건.** ✅
- `api.py` 변경은 라우트 1개 + `POST /refresh`의 `force_company=symbol is not None` 1줄 — 계약 v2 BE-3 승인 범위 그대로. 다른 라우트 무변경.
- `App.tsx` 변경은 `/ticker/:symbol/analysis` lazy 라우트 1개 + import 1줄. 기존 `/ticker/:symbol` 불변. ✅

> **주1 — `tests/conftest.py`는 공용 카운트에 넣지 않았다.** 스펙 §8.3의 공용 3개는 소스 파일(`schema.sql`/`service.py`/`api.py`)을 셌고, conftest 변경은 **추가만 하는 autouse 픽스처**(`no_network_sources`)라 기존 테스트 동작을 바꾸지 않는다(338 passed로 확인). BE 보고서 §7-5가 "양쪽 세션이 만질 수 있는 파일"로 경고했으나, `git diff`상 이번 변경분은 **전부 `app.sources.*` 차단·`company.SYMBOL_SLEEP_SEC=0`**으로 회사 자료 세션 소유가 100%다. 대시보드 세션 코드 없음 → **충돌 없음.**

### 3.2 다른 세션분 (검수·소유권 판정 제외)

`backend/app/{main.py, codef.py, market.py, market_api.py, market_fetch.py}`, `backend/tests/test_market.py`, `backend/scripts/`, `.gitignore`, `frontend/src/{pages/Dashboard.tsx, components/Layout.tsx, components/SentimentGauge.tsx(삭제), theme.css, finviz/**}`.

`main.py` diff 확인 결과 `env.load(ROOT)` + `market_api` 라우터 등록뿐 — 이번 화면과 접점 없음.

### 3.3 리더 판단 필요 1건 — `frontend/src/api.ts`

`api.ts`는 **브리프 "검수 제외" 목록에 없는데 변경돼 있다**(`json()` 헬퍼 추가: 200인데 JSON이 아니면 "백엔드 구버전" 메시지). FE 보고서 §v2-6이 "내가 만들지 않은 작업 트리 변경, 다른 세션이 넣은 것"이라고 자인했다. 코드 내용도 대시보드 세션의 `/api/market*` 신규 엔드포인트 상황(백엔드 미재시작 → SPA 폴백)에 정확히 대응한다.

- 이번 화면 소유로 계산하면 **FE 공용 파일이 3개**가 되어 상한 2를 넘는다.
- 판정: **대시보드 세션 소유로 분리** → 이번 라운드 상한 준수. 다만 이 변경은 `/api/tickers/{s}/company`의 오류 문구도 함께 바꾸므로, **커밋 시 어느 커밋에 담을지 리더가 정해야 한다.**

---

## 4. 레이아웃 계측 D1~D13 · R1~R4 판정

두 계측 문서의 기준선이 다르다는 점을 먼저 정리한다.

> **계측 시점 충돌 (해소)**: `41_recheck_layout.md`(16:06)는 **재빌드 직전의 8722**를 쟀고, `30_frontend_report.md` v2-3은 **같은 소스의 5173 dev**를 쟀다. 그래서 §6-O1이 "빌드본이 낡았다"고 보고한 라벨 7칸·값 2칸 불일치는 전부 "dev가 맞고 build가 틀림"이었다. 이번 검수에서 `dist/assets/TickerDetail-*.js`(16:09)에 v2 라벨이 들어 있음을 확인했으므로 **O1·R4는 해소**다. 따라서 **D2·D5의 `0.09%`/구 라벨 관련 지적과 "5년 —" 지적은 이미 무효**이고, 나머지 D 항목은 재빌드와 무관한 소스 결함이라 그대로 유효하다.

| # | 판정 | 소유 | 한 줄 수정안 |
|---|---|---|---|
| **D1** 값·보조값 구분자 없음 | **이번 라운드 수정 필수** | FE | **사실 확인 완료.** `SnapshotTable.tsx:26-27`이 `{c.value}{c.sub && <small>{c.sub}</small>}`로 붙이고 `quote.css:88`이 `margin-left:4px`뿐 → `172,0439.94%`. `<small>` 앞에 `·` 구분자를 넣거나 `margin-left:10px` + 좌측 1px divider |
| **D2** 스냅샷 출처 줄 ISO 원시 시각 | **수용(이미 수정됨)** | — | `TickerDetail.tsx:217`이 현재 `relativeTime(detail.snapshot.fetched_at, now)`를 쓴다. 16:06 계측이 낡은 빌드 기준 |
| **D3** KRW 종목에 USD 축약(`5.73M`) | **이번 라운드 수정 필수 (AC-21 FAIL)** | FE | **사실 확인 완료.** `snapshotCells.ts:150` `abbrNum('USD', avgVolume(c,20))` → 같은 파일 41행의 `abbr(...)`로 교체 |
| **D4** `1263.8조` 천단위 구분 없음 | **이번 라운드 수정 필수 (AC-21 관련)** | FE | `fmt.ts:22`를 `(a/1e12).toFixed(1)`의 결과에 `toLocaleString('ko-KR')` 적용 → `1,263.8조` |
| **D5** 당좌 1.33 vs 유동 17.54 | **수용(단위 버그 아님) + 툴팁만 필수** | FE(툴팁) / BE(가드는 보류) | §2.2. 현행 값 유지. FE는 두 칸 툴팁에 출처(`당좌비율: 네이버 공시 기준 / 유동비율: yfinance`)를 명시 |
| **D6** 뉴스 제목 `&quot;` 원문 노출 | **이번 라운드 수정 필수** | BE | 실응답 재확인: 000660 20건 중 **2건**에 `&quot;` 리터럴. `sources/naver.py`의 뉴스 제목에 `html.unescape()` 1줄 (현재 `unescape` 미사용 확인) |
| D6b 제목 소스단 절단(`...`) | **보류** | BE | 실응답 20건 중 **9건**이 `...`로 끝난다. 네이버가 절단해 보내는 것이라 복원하려면 다른 필드·다른 엔드포인트가 필요 → 별도 라운드 |
| **D7** `unavailable` 블록에 근거 없는 갱신시각 / 회사 설명 출처 줄에 시각 없음 | **이번 라운드 수정 필수(저비용)** | FE | `BlockEmpty.tsx:35-36` — `block.source`가 없으면 시각도 넣지 않는다(`if (!block.source) return null`). `TickerDetail.tsx:248` 회사 설명 `<small>`에 `relativeTime(profile.fetched_at)` 추가 → 스펙 B1 형식으로 통일 |
| **D8** 헤더 현재가가 센트를 잃는다(`$311.3` vs 스냅샷 `311.30`) | **이번 라운드 수정 필수** | FE | **사실 확인 완료.** `format.ts:9 cur()` → `fmt()`가 `maximumFractionDigits:2`만 지정하고 `minimum`이 없다. **`format.ts`는 건드리지 않는다**(전역 공용, §8.3 회피 대상) — `QuoteHeader.tsx:44`가 `quote/fmt.ts`의 `moneyCell(currency, v)` + 통화기호로 바꾼다 |
| **D9** `/analysis`에서 $와 ₩ 혼재 | **보류** | FE | `git show eb6f6d3:...TickerDetail.tsx:285,287,291`에 `리스크 ₩`·`평가액 ₩`·`(계산값 ...)`가 **기준선에 이미 있다.** §7이 "리팩터링 금지, 잘라 붙이기"로 못박은 이동분 → 이번 라운드 범위 밖 |
| **D10** `/analysis` 청산 플랜 소수점 주식수 | **보류** | FE | 동일 — 기준선 `<th>수량</th>` 표가 그대로 이동. 별도 라운드에서 `Math.floor` + "1주 단위 내림" 문구 통일 |
| **D11 / R2** 390px 스냅샷 라벨 말줄임 | **이번 라운드 수정 필수(저비용)** | FE | 재빌드 후 현재 라벨 기준 예상 5칸(`EPS 성장(과거 3/5년)`·`매출 성장(과거 3/5년)`·`배당성장 3/5년`·`EPS 전년동기(분기)`·`매출 전년동기(분기)`). **기준선 0칸 → 악화 맞다.** 두 갈래 중 하나: (i) 3/5년 결합 칸 3개를 `sub` 없는 단일 값으로(레이아웃 §3 제안, AAPL은 5Y가 어차피 전부 `—`), (ii) 390px에서 `.snap-label{font-size:11px}` |
| **D12** 390px에서 `분석` 탭이 화면 밖 | **이번 라운드 수정 필수(저비용)** | FE | 기준선도 7탭이라 넘침 자체는 있었으나, **§7이 룰 등록 UI의 유일한 진입점을 `/analysis`로 옮겼기 때문에** 이번 라운드에서 기능 도달성 문제로 승격됐다. `.quote-tabs`에 우측 페이드(`mask-image`) 또는 `분석`을 헤더 버튼으로 승격 |
| **D13 / R1 / R3** `/analysis` 백테스트 표 컨테이너 넘침 | **수용(회귀 아님) → 보류** | FE | **기준선 계측 누락이 맞다.** ①`components/BacktestTable.tsx:62`는 이번 라운드 **미변경**(`git status`에 없음)이고 ②`.table-scroll`은 `theme.css:200`의 앱 전역 패턴으로 Watchlist·Risk·Holdings 등 **9개 화면이 이미 쓴다** ③ 기준선 커밋에서 이 표는 `/ticker/:symbol` 개요에 있었으므로 같은 내부 스크롤이 그때도 있었다. 기준선이 `documentElement.scrollWidth`만 재서 못 본 것. **11열 축소는 별도 라운드** |
| **R4** 빌드본이 소스보다 낡음 | **수용(해소됨)** | — | `dist` 16:09 재빌드 확인. 커밋 전에 소스가 또 바뀌면 `npm run build`를 다시 돌린다 |

---

## 5. 수정 지시 (엔지니어에게 그대로 전달 가능)

### FE 수정 지시 — 이번 라운드 필수

> 담당 `frontend-engineer`. 범위 `frontend/` 만. `format.ts`·`theme.css`·`Dashboard.tsx`·`Layout.tsx`·`finviz/**`는 건드리지 않는다.

| 우선 | # | 파일 | 지시 |
|---|---|---|---|
| **P0** | F-a (D3, **AC-21 FAIL**) | `src/quote/snapshotCells.ts:150` | `abbrNum('USD', avgVolume(c, 20))` → `abbr(avgVolume(c, 20))`. 검증: 000660 `평균 거래량(20)`이 `573만` 계열로 나오고 `M`이 사라진다 |
| **P0** | F-b (D4, **AC-21 FAIL**) | `src/quote/fmt.ts:22` | 조 단위에 천단위 구분을 넣는다 — `(a/1e12).toFixed(1)`을 그대로 붙이지 말고 `Number(...).toLocaleString('ko-KR',{minimumFractionDigits:1,maximumFractionDigits:1})+'조'`. 검증: `fmt.test.ts`에 `1263751800000000 → '1,263.8조'` 케이스 추가 후 `node --test` |
| **P0** | F-c (D1) | `src/components/quote/SnapshotTable.tsx:26-27`, `src/quote.css:88` | 값과 `sub` 사이에 시각적 구분자를 넣는다(`<small>` 앞 `·`, 또는 `margin-left:10px` + `border-left:1px solid var(--line); padding-left:8px`). 검증: 000660 `ATR (14)`가 `172,043 · 9.94%`로 두 숫자로 읽힌다 |
| **P1** | F-d (D8) | `src/components/quote/QuoteHeader.tsx:44,46` | `cur(detail.currency, ...)` 대신 `quote/fmt.ts`의 `moneyCell(detail.currency, ...)`에 통화기호를 앞에 붙인다. **`format.ts`는 수정 금지.** 검증: AAPL 헤더 `$311.30`이 스냅샷 `현재가 311.30`과 자릿수가 같다 |
| **P1** | F-e (D7) | `src/components/quote/BlockEmpty.tsx:34-38`, `src/pages/TickerDetail.tsx:248` | ① `block.source`가 null이면 `BlockSource`가 `null`을 반환(시각만 뜨는 상태 제거) ② 회사 설명 `<small>`에 `· {relativeTime(profile.fetched_at, now)}` 추가. 검증: 000660 내부자 헤더에서 `3분 전`이 사라지고, 회사 설명은 `출처: yfinance+daum+fdr · N분 전` |
| **P1** | F-f (D11/R2) | `src/quote/snapshotCells.ts:61,93,95` | 3/5년 결합 칸 3개를 3년 단일 값으로 축소하고 라벨을 `배당성장 3년`·`EPS 성장(3년)`·`매출 성장(3년)`으로 줄인다(5Y는 US·KR 모두 `sales_past_5y_pct`/`eps_past_5y_pct`가 항상 null — 실응답 확인). **84칸 총수는 유지.** 검증: 390px에서 `.snap-label` 말줄임 0칸 |
| **P1** | F-g (D12) | `src/quote.css` `.quote-tabs` | 우측 페이드 어포던스(`mask-image: linear-gradient(to right, #000 85%, transparent)`) 추가. 검증: 390px에서 탭 줄 우측이 잘린 것이 보인다 |
| **P2** | F-h (D5) | `src/quote/snapshotCells.ts` 당좌·유동비율 칸 | 두 칸 `title`에 출처를 명시 — 당좌비율 "국내 공시 기준(네이버)", 유동비율 "yfinance 기준". 국내 종목에서 두 칸의 정의 체계가 다르다는 사실을 화면이 숨기지 않게 |

### BE 수정 지시 — 이번 라운드 필수

| 우선 | # | 파일 | 지시 |
|---|---|---|---|
| **P1** | B-a (D6) | `backend/app/sources/naver.py` 뉴스 파서 | 제목에 `html.unescape()`를 적용한다(현재 미적용 확인). 검증: `curl -s :8722/api/tickers/000660/company \| jq -r '.news.items[].title' \| grep -c '&quot;'` → 0. 단위 테스트에 `'&quot;A&quot;' → '"A"'` 케이스 추가 |

**BE는 이 1건 외에 이번 라운드 필수 수정이 없다.** B1~B4(계약 v2 §4)는 실응답으로 전부 반영 확인했다 — `profile.status/note` ✅, `perf.y5` ✅(AAPL 108.89 / 000660 1613.17), `debt_eq`·`quick_ratio` 4자리 배수 통일 ✅, `dividend_yield_pct` 스케일 가드 ✅.

---

## 6. 보류 (→ `20_spec.md` §3 이관 완료)

| 항목 | 보류 이유 |
|---|---|
| `/analysis` 통화 혼재($ 손절가 ↔ ₩ 리스크·평가액) — D9 | 기준선 커밋 `eb6f6d3`에 이미 있던 결함. §7이 "리팩터링 금지, 잘라 붙이기"로 못박은 이동분이라 이번 라운드 범위 밖. 환율·기준시각 표기를 붙이려면 `risk` 응답에 환율 필드가 필요 → BE 계약 변경을 동반한다 |
| `/analysis` 청산 플랜 소수점 주식수(`수량 1.667`) — D10 | 동일. 국내 주식은 소수점 매도 불가 — `Math.floor` + "1주 단위 내림" 문구를 개요와 통일해야 하는데, 같은 규칙이 `제안 수량`에는 이미 있고 청산 플랜에만 없다. `/analysis` 전용 라운드에서 함께 |
| 백테스트 표 11열 컨테이너 넘침 — D13/R1/R3 | **회귀가 아니라 기준선 계측 누락**(§4). `BacktestTable.tsx`는 미변경이고 `.table-scroll`은 9개 화면이 쓰는 전역 패턴이다. 열 축소는 "어느 열을 버릴 것인가"가 트레이딩 판단이라 `trader-mentor` 없이 정하지 않는다 |
| 뉴스 제목 소스단 절단 9/20건 — D6b | 네이버가 절단해 보낸다. 복원하려면 다른 엔드포인트가 필요하고 비공식 API 호출이 1콜 늘어난다(§6.2 콜 예산) |
| 뉴스 종목 관련성 배지(시황 기사 구분) — 레이아웃 §4-4 | 000660 20건 중 상당수가 코스피 시황·타종목 기사. 종목명 매칭은 BE 로직 신규 추가라 화면 하나 범위를 넘는다 |
| BE `quick_ratio > current_ratio` 정합성 가드 | §2.2. 이번 사례에서 상류 이상값(17.54)이 화면에 그대로 나갔다. 값을 비우는 가드는 "정상인데 비는" 오탐 위험이 있어 실측 표본을 더 모은 뒤 결정 |
| `snapshot.perf` 기준 봉 혼재(`y5`·`y10`만 월봉) | BE 보고 §v2-4-8. 같은 표에서 소수점 단위 차이가 날 수 있다. 툴팁 한 줄로 해결되나 이번 라운드 필수 목록을 늘리지 않는다 |
| 내부자 표 열·행 축소(`보유 총수`·`공시` 100% `—`, 30행 7,507px) — 레이아웃 §3 | 열 삭제는 finviz 동일 구성(A7)을 깨는 결정이라 브리프 확정 사항과 충돌한다. 사용자 판단 필요 |
| `frontend/src/quote/cells.ts` 사장 코드 | `snapshotCells.ts`가 대체했으나 파일이 남아 있다(`grep -rn "quote/cells"` → 참조 0건). 84칸 정의가 두 벌 존재하면 다음 수정자가 틀린 쪽을 고친다. 삭제는 리더가 커밋 정리 때 |
| DART 2차 경로 실호출 검증 | 계약 v2 §1-BE-7. `.env`에 키 없음 — 키 등록 시점 별도 라운드 |
| `refresh_all` 전체 8종목 상한 실서버 검증(V5) | CODEF 일 100회 한도 때문에 실서버 미실행. 단위 테스트로 고정 |

---

## 7. 실행 미검증 표기

| 항목 | 사유 |
|---|---|
| AC-8·17·18·20, V3 | 브라우저 도구 사용 불가. `41_recheck_layout.md`(빌드본 DOM 계측)와 `30_frontend_report.md` v2-3(dev DOM 계측)이 **모두 PASS로 일치**하므로 대행 근거로 채택. 두 문서 모두 스크린샷 없음 → **시각적 대비·색상·행간은 이번 라운드 전체가 미검증** |
| AC-15 / V5 | 실서버 전체 갱신 미실행(CODEF 한도) |
| V2 | `snapshot`을 지운 상태의 FE 폴백을 만들 수 없음. 소스 대조로 1순위 기준일 일치만 확인 |
| D11/R2의 현재 칸 수 | 재빌드 후 390px 재계측 불가. 라벨 문자열로부터 5칸으로 추정(계측치는 재빌드 전 4칸/5칸) |

## v3 재계측 (리더, 2026-08-22 09:30, 8722 빌드본 `npm run build` 후 재시작)

| 항목 | 결과 | 증거 |
|---|---|---|
| AC-21 (유일 FAIL) | **PASS** | 000660 `시가총액 1,263.8조`, `평균 거래량(20) 573만`; AAPL `53.05M` (FE v3 보고) |
| D1 구분자 | PASS | DOM `ATR (14) 172,043 · 9.94%`, `최근 배당(주당) 3,000 · 0.17%` |
| D6 엔티티 | PASS | `/company` news JSON에 `quot` 0건, 제목 `"2배보다 3배"…` |
| 84칸·가로 넘침·금지 문자열 | PASS | `.snap-cell` 84, `scrollWidth-innerWidth` 0, `undefined|NaN|null|&quot;` 0 |
| 게이트 | PASS | pytest 339 passed(네트워크 0), `tsc -b` 0, oxlint 무경고, node:test 24/24 |
| **신규 발견·수정: 차트 캔버스 300px 고정** | PASS(수정 후) | 빌드본에서 lightweight-charts가 컨테이너 폭 0 시점에 생성돼 캔버스가 기본 300px로 굳음(RSI/MACD 포함 3패널 빈 화면). `QuoteChart.tsx`에 `autoSize: true` + `levels` 의존성을 내용 키로 안정화. 재시작 후 1232px 전폭 렌더 확인 |

결론: **AC 21/21 PASS.** 보류 12건은 `20_spec.md` §3.
