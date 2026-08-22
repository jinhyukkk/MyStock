# TickerDetail 백엔드 구현 보고 (2026-08-21)

스펙: `_workspace/tickerdetail/20_spec.md` · 범위: `backend/`만. `frontend/` 미변경, 커밋 없음.

---

## 1. 변경 파일 목록

| 파일 | 상태 | 한 줄 요약 |
|---|---|---|
| `backend/app/schema.sql` | 수정 | `company_cache` 테이블 추가(`IF NOT EXISTS` → 기존 DB 자동 마이그레이션) |
| `backend/app/company.py` | **신규 1,100줄** | 캐시 read/write, TTL·backoff·우선순위 선정, 6블록 조립기, `refresh_company_blocks`, `get_company/get_profile/get_snapshot`, `compute_perf` |
| `backend/app/sources/__init__.py` | 신규 | 패키지 선언 — "외부 호출은 여기서만" 규칙 문서화 |
| `backend/app/sources/yf.py` | 신규 | yfinance 어댑터(info·차트메타·캘린더·추정치·손익계산서·뉴스·등급변경·내부자·배당이력·월봉10년). pandas/NaN을 plain JSON으로 정리 |
| `backend/app/sources/naver.py` | 신규 | 네이버 모바일 JSON(비공식) — integration·finance·news·research. UA 필수 주석 |
| `backend/app/sources/daum.py` | 신규 | 다음 quotes(비공식) — `Referer` 필수 주석 |
| `backend/app/sources/krx_desc.py` | 신규 | FDR `KRX-DESC` 업종·상장일·홈페이지, 프로세스 lru_cache |
| `backend/app/sources/dart.py` | 신규 | OpenDART 2차 소스(키 있을 때만). corpCode 매핑·elestock·stockTotqySttus |
| `backend/app/service.py` | 수정 3곳 | `refresh_all`에 회사 자료 호출 1곳(예외 격리)+`failed_company` 키, `get_ticker_detail`에 `profile`/`snapshot` 2필드, `get_company` 패스스루 |
| `backend/app/api.py` | 수정 2곳 | `GET /tickers/{symbol}/company` 라우트 1개 추가 + `POST /refresh` 1줄(`force_company=symbol is not None`) |
| `backend/tests/conftest.py` | 수정 | `app.sources.*` 전 함수를 AssertionError로 막는 autouse 픽스처(네트워크 0 보장) |
| `backend/tests/test_company.py` | **신규 24케이스** | AC-12~15 + 블록 조립·정규화·캐시 보존 |
| `backend/tests/test_api.py` | 추가 3케이스 | AC-1/2 기존 키 회귀, `/company` 200·404, AC-13 |
| `backend/tests/test_service.py` | 추가 2케이스 | `failed_company` 분리 보고, `profile`/`snapshot` pending 골격 |

`fetchers.py`·`db.py`·`costs.py`·`frontend/**` 미변경(확인: `git status`).

---

## 2. 계약 준수표

### 2.1 `GET /api/tickers/{symbol}` (실응답 2026-08-21 15:48, 포트 8733)

| 계약 필드 | 타입 | AAPL 실값 | 000660 실값 | 일치 |
|---|---|---|---|---|
| 기존 11키 | — | `["candles","cash","cost_rates","currency","dividends","entry_review","fundamentals","history","is_etf","last_refresh","market","name","profile","risk","rules","signal","snapshot","symbol"]` | 동일 | ✅ 삭제·개명 0 |
| `profile.sector` | string\|null | `"Technology"` | `"반도체와반도체장비"`(한글) | ✅ |
| `profile.industry` | string\|null | `"Consumer Electronics"` | `"반도체 제조업"` | ✅ |
| `profile.country` | string\|null | `"United States"` | `"South Korea"` | ✅ |
| `profile.exchange` | string\|null | `"NASDAQ"`(NMS 정규화) | `"KOSPI"` | ✅ |
| `profile.employees` | int\|null | `150000` | `47639` | ✅ |
| `profile.ipo_date` | `YYYY-MM-DD` | `"1980-12-12"` | `"1996-12-26"` | ✅ |
| `profile.website` | URL | `https://www.apple.com` | `http://www.skhynix.com` | ✅ |
| `profile.description` / `_lang` / `_truncated` | — | 1825자 / `"en"` / `false` | 222자 / `"ko"` / `false` | ✅ |
| `profile.source` | string | `"yfinance"` | `"yfinance+daum+fdr"` | ✅ |
| `profile.fetched_at` | ISO | `"2026-08-21T15:48:01"` | `"2026-08-21T15:46:39"` | ✅ |
| `snapshot.perf` 9키 | number\|null | `{"w1":1.98,"m1":-4.93,"m3":2.16,"m6":19.68,"ytd":14.82,"y1":38.25,"y3":79.43,"y5":null,"y10":1104.12}` | `{...,"y3":1384.98,"y5":null,"y10":4781.84}` | ✅ 9키 상시 존재 |
| `snapshot.recommendation_mean` | 1~5(1=강력매수) | `2.11` | `2.0`(네이버 4.00 뒤집음) | ✅ |
| `snapshot.recommendation_scale` | string | `"1=strong_buy..5=strong_sell"` | 동일 | ✅ |
| `snapshot.target_price` | 종목 통화 | `326.3415`(USD) | `3317917`(KRW) | ✅ |
| `snapshot.sources` | string[] | `["yfinance"]` | `["yfinance","naver","daum"]` | ✅ |
| `snapshot.fetched_at` / `status` | ISO / ok\|pending | `"2026-08-21T15:48:07"` / `"ok"` | `"2026-08-21T15:46:45"` / `"ok"` | ✅ |
| `snapshot.*` 84칸 키 | 항상 존재 | 키 68개 상시 존재, 값만 null | 동일 | ✅ |

`fundamentals`(per/pbr/dividend_yield/market_cap)와 `meta`의 `fund:{symbol}`은 그대로 유지 —
`fetch_fundamentals` 미수정.

### 2.2 `GET /api/tickers/{symbol}/company`

| 계약 | AAPL | 000660 | 일치 |
|---|---|---|---|
| `financials.annual[]` | 4건, `{"period":"2022","end_date":"2022-09-30","eps":6.11,"sales":394328000000.0,"shares_outstanding":16325819000.0,"estimate":false}` | 4건, `{"period":"2023","end_date":"2023-12-31","eps":-12517.0,"sales":32765700000000.0,"shares_outstanding":null,"estimate":false}` (억원→원 변환) | ✅ |
| `financials.quarterly[]` | 5건 | 6건(마지막 `estimate:true`) | ✅ |
| `financials.shares_note` | `null` | `"발행주식수 이력은 OpenDART 키 등록 후 표시됩니다."` | ✅ |
| `news.items[]` | 10건 전부 `lang:"en"` | 20건 전부 `lang:"ko"`, `published_at:"2026-08-21T15:43:00"` (KST) | ✅ |
| `ratings.consensus` | `{"recommendation_mean":2.11,"recommendation_label":"매수","target_mean":326.3415,"target_upside_pct":4.83,"analyst_count":40,"as_of":null}` | `{"recommendation_mean":2.0,"recommendation_label":"매수","target_mean":3317917.0,"target_upside_pct":91.79,"analyst_count":40,"as_of":"2026-08-20"}` | ✅ |
| `ratings.changes[]` | 20건, action ∈ `["Upgrade","Downgrade","Reiterated"]` | `[]` | ✅ |
| `ratings.reports[]` | `[]` | 10건 `{"date":"2026-08-20","firm":"한화투자증권","title":"40조원은 시작…","url":"https://m.stock.naver.com/investment/research/company/95791"}` | ✅ |
| `ratings.note` | `null` | 57자 한국어 문구 | ✅ |
| `insiders` | `status:"ok"`, 30건, `{"name":"NEWSTEAD JENNIFER","relation":"General Counsel","date":"2026-08-11","transaction":"Sale","price":307.75,"shares":1439.0,"value":442852.0,"shares_total":null,"url":null}` | `status:"unavailable"`, `items:[]`, note 41자 | ✅ |
| 캐시 없음 → 200 + 전 블록 `pending` | ✅ (`test_company_pending_when_no_cache`) | 동일 | ✅ |
| 없는 종목 → 404 `"ticker not found"` | ✅ | — | ✅ |

---

## 3. 테스트 결과

```
cd backend && .venv/bin/pytest -q
334 passed, 4 deselected, 1 warning in 5.86s
```

네트워크 없이 통과한다. `tests/conftest.py`의 autouse 픽스처 `no_network_sources`가
`app.sources.{yf,naver,daum,krx_desc,dart}`의 모든 함수를 `AssertionError`로 바꿔 놓으므로,
어떤 테스트도 외부에 나가지 못한다(나가면 그 자리에서 실패한다).

신규 테스트 (`tests/test_company.py`, 24케이스):
`test_ratio_to_percent`, `test_debt_to_equity_divided_by_100`, `test_dividend_yield_scale_guard`,
`test_naver_recomm_normalized`, `test_parse_kr_number`, `test_cagr_refuses_sign_flip`,
`test_kr_per_pbr_falls_back_to_naver`, `test_kr_snapshot_fills_required_cells`,
`test_us_snapshot_normalizes_units`, `test_perf_10y_tolerates_first_monthly_bar`,
`test_perf_keys_always_present_and_bounded`, `test_kr_profile_is_korean`,
`test_us_profile_truncates_description`, `test_kr_company_blocks`, `test_us_company_blocks`,
`test_company_pending_when_no_cache`, `test_cache_kept_on_failure`,
`test_failed_block_backs_off_for_30min`, `test_refresh_respects_ttl_and_cap`,
`test_refresh_prefers_holdings_then_watchlist`, `test_crypto_is_skipped`

추가 (`test_api.py`): `test_detail_keeps_existing_keys_and_adds_company`,
`test_company_endpoint_returns_200_when_empty`, `test_detail_never_calls_network`
추가 (`test_service.py`): `test_refresh_reports_company_failures_without_breaking_prices`,
`test_detail_exposes_profile_and_snapshot`

**내 변경과 무관한 실패**: 작업 중 `tests/test_market.py::test_failure_keeps_previous_value_and_backs_off`,
`::test_ttl_skips_fresh_blocks` 2건이 실패한 적이 있다. `app/market.py`·`app/market_fetch.py`는
다른 세션(대시보드 작업)이 같은 시각에 추가한 파일이고 내 변경과 접점이 없다. 최종 실행 시점에는
그쪽에서 고쳐져 334 passed / 0 failed다.

---

## 4. 수용 기준 체크 (BE 해당분)

| # | 결과 | 확인 명령 / 증거 |
|---|---|---|
| AC-1 | **PASS** | `curl -s .../api/tickers/AAPL \| jq 'keys'` → 기존 11키 + `profile`,`snapshot` (§2.1 첫 행). 회귀 테스트 `test_detail_keeps_existing_keys_and_adds_company` |
| AC-2 | **PASS** | `jq '.snapshot.perf \| keys'` → 9개 (`m1,m3,m6,w1,y1,y10,y3,y5,ytd`) |
| AC-3 | **PASS** | AAPL 스냅샷 null 칸 8개(<12): `["eps_next_5y_pct","eps_past_5y_pct","sales_past_5y_pct","earnings_timing","sales_surprise_pct","inst_trans_pct","foreign_own_pct","note"]`. 필수 12칸 전부 non-null — `{"market_cap":4543167856640,"pe":36.37,"eps_ttm":8.56,"roe_pct":148.75,"oper_margin_pct":32.62,"shares_outstanding":14594180000,"beta":1.086,"target_price":326.3415,"recommendation_mean":2.11,"earnings_date":"2026-10-30","ipo_date":"1980-12-12","employees":150000}` |
| AC-4 | **PASS** | `{"market_cap":1263751800000000,"pe":7.71,"pb":4.67,"eps_ttm":224313,"bps":370432,"div_yield":0.17,"roe_pct":92.68,"oper_margin_pct":76.33,"shares":709854891,"beta":2.413,"target_price":3317917,"recomm":2.0,"ipo_date":"1996-12-26","employees":47639,"shorts":[null,null,null]}` — 공매도 3칸 null ✅. **단 `dividend_yield_pct`는 계약에 없던 신규 키다(§5-1)** |
| AC-5 | **PASS** | `jq '{len:(.profile.description\|length), lang:.profile.description_lang}'` → `{"len":222,"lang":"ko"}` (Daum `companySummary`) |
| AC-6 | **PASS** | `{"news_n":20,"langs":["ko"],"annual_n":4,"reports_n":10,"changes":[],"ratings_note_len":57,"insiders_status":"unavailable","insiders_note_len":41}` |
| AC-7 | **PASS** | `{"news_n":10,"changes_n":20,"insiders_n":30,"annual_n":4,"quarterly_n":5}` |
| AC-11 | **PASS** | `cd backend && .venv/bin/pytest -q` → 334 passed. 네트워크 차단은 conftest autouse로 구조적으로 보장 |
| AC-12 | **PASS** | `pytest -q tests/test_company.py -v` — 비율→% / `debtToEquity`÷100 / 배당수익률 스케일 / KR per·pbr 네이버 폴백 / `recommendation_mean` 정규화 5종 전부 존재·통과 |
| AC-13 | **PASS** | `test_detail_never_calls_network` — `app.sources` 전 함수가 `AssertionError`를 던지는 상태에서 `GET /api/tickers/X`·`/company` 둘 다 200 |
| AC-14 | **PASS** | `test_cache_kept_on_failure` — 실패 주입 후 `payload`·`fetched_at` 동일, `error`만 채워지고 `get_snapshot(...)["pe"] == 7.7` 유지 |
| AC-15 | **PASS** | `test_refresh_respects_ttl_and_cap` — 12종목 중 8종목만 갱신, TTL 안인 `T00` 제외. `test_refresh_prefers_holdings_then_watchlist`로 보유>관심>기타 순서 고정 |

AC-8~10, 16~21은 프론트 담당이라 여기서 판정하지 않는다.

### `recommendation_mean` 실측 근거 (스펙 §5.2 요구)

2026-08-21 직접 호출:

| 종목 | 네이버 `recommMean` | 네이버 `priceTargetMean` | 전일 종가 | 상방 | yfinance `recommendationMean` |
|---|---|---|---|---|---|
| 000660 | **4.00** | 3,317,917 | 1,691,000 | +96% | **1.33** |
| 005930 | 4.04 | 491,875 | 271,000 | +81% | — |
| 035420 | 4.00 | 330,565 | 219,500 | +51% | — |
| 003490 | 3.90 | 36,700 | 25,050 | +47% | — |

같은 종목·같은 날 네이버 4.00 ↔ yfinance 1.33이고, 목표주가가 현재가의 2배다.
→ **네이버는 5=강력매수**로 방향이 반대. `company.naver_recomm_to_scale`이 `6 - v`로 뒤집고,
실측값·날짜를 함수 docstring에 남겼다. 단위 테스트 `test_naver_recomm_normalized`로 고정.

---

## 5. 계약 수정 요청

구현으로 덮지 않고 요청으로 남긴다. 전부 **추가**이거나 **데이터가 없어 못 채운 칸**이며,
기존 필드 삭제·개명은 없다.

### 5-1. `snapshot.dividend_yield_pct` (신규 키) — **승인 필요**
AC-4가 000660 스냅샷에 "배당수익률" 값을 요구하는데, §4.3 84칸에는 배당수익률 칸이 없다
(예상 배당/최근 배당/배당락일/배당성장/배당성향뿐). AC를 만족시키려면 필드가 있어야 해서
`snapshot.dividend_yield_pct`(퍼센트 숫자)를 추가했다. 실값: AAPL 0.34, 000660 0.17.
**계약에 이 칸을 넣을지, 아니면 AC-4에서 배당수익률을 빼고 84칸 밖 정보로 볼지** 결정 요청.

### 5-2. `snapshot.note` (신규 키)
`status:"pending"`일 때 사용자 문구를 담는다(`"회사 자료를 아직 받지 못했습니다 — 새로고침을
누르면 지금 가져옵니다."`). §6.3이 요구하는 pending 문구를 BE가 주는 게 4블록 래퍼(`note`)와
같은 방식이라 일관되다고 판단했다. `status:"ok"`면 항상 null.

### 5-3. `api.py` 변경이 라우트 1개가 아니라 라우트 1개 + 1줄
`POST /api/refresh` 한 줄에 `force_company=symbol is not None`을 넘긴다. `refresh_all(conn, symbol)`
안에서 무조건 강제 갱신하게 만들면 **증권사 동기화 경로**(`api.py` `/broker/sync`가 새 편입 종목마다
`refresh_all(conn, symbol)`을 부른다)가 종목 수 × 6콜을 동기로 물게 된다. 그래서 강제 여부를
호출자가 정하도록 했다.

### 5-4. `service.get_company` 패스스루 함수 추가
`api.py`에 비즈니스 로직을 넣지 않는 관례를 지키려고 `service.py`에 3줄짜리 위임 함수를 뒀다
(§8.1은 service 변경을 "호출 1곳 + 2필드"로 제한했다). `api.py`가 `company`를 직접 import하는
쪽을 원하면 그렇게 바꾼다.

### 5-5. `company_cache`에 내부 블록 `perf10y` 1행 추가
스키마 주석의 블록 열거(`profile|snapshot|financials|news|ratings|insiders`)에 없다. perf 10Y는
TTL이 7일인데 snapshot은 12시간이라, snapshot 안에 넣으면 월봉을 12시간마다 다시 받는다.
**화면 응답에는 나가지 않는 내부 캐시**다. 종목당 행이 6→7개가 된다.

### 5-6. 계약대로 채울 수 없는 칸 (구현이 아니라 데이터의 한계)

| 칸 | 상태 | 이유 |
|---|---|---|
| `earnings_timing` | 항상 null | yfinance `calendar`가 BMO/AMC를 주지 않는다. 스펙도 KR은 null로 적었으나 US도 동일 |
| `sales_surprise_pct` | 항상 null | yfinance `earnings_dates`는 EPS 서프라이즈만 준다(매출 컬럼 없음) |
| `inst_trans_pct` | 항상 null | 기관 지분 '변동'은 `institutional_holders` 추가 1콜이 필요. §6.2 콜 예산(종목당 5콜) 안에서 뺐다. KR은 `foreign_own_pct`가 대신 채워진다(51.05) |
| `eps_yoy_ttm_pct` / `sales_yoy_ttm_pct` | 정의 축소 | TTM 대 TTM에는 분기 8개가 필요한데 yfinance는 5~6분기, 네이버는 5분기만 준다. **최근 분기 vs 전년 동기 분기**로 계산했다. 라벨이 "TTM"이면 화면이 사실과 다른 말을 하므로 **FE 라벨을 "EPS 전년동기(분기)"로 고쳐야 한다** |
| `roic_pct` | 데이터 있을 때만 | 실효세율을 손익계산서(`Pretax Income`·`Tax Provision`)에서 뽑아 NOPAT을 만든다. 세율을 상수로 가정하면 그건 계산이 아니라 추측이라, 두 값이 없으면 칸을 비운다 |
| KR `eps_past_3y_pct` / `sales_past_3y_pct` | 채워짐(출처 변경) | 네이버 연간은 실적 3개(=2년 구간)뿐이라 3Y CAGR을 만들 수 없다. yfinance `income_stmt`(KR도 4년)로 채웠다. 2년치를 3년 성장률로 내보내지 않는다 |
| KR `ratings.consensus.analyst_count` | 소스 혼합 | 네이버 `consensusInfo`에 애널리스트 수가 없어 yfinance `numberOfAnalystOpinions`(40)를 쓴다. `recommendation_mean`·`target_mean`·`as_of`는 네이버 |
| `perf.y5` | null | `price_cache`가 1100영업일(≈4.8년)이라 5년 구간을 못 덮는다. 스펙 §4.3 그대로 |

### 5-7. 스펙에 없던 정규화 2건 (데이터가 계약을 어겨서 넣음)
- **`ratings.changes[].action`**: yfinance가 `up/down/main/reit/init` 축약 코드를 준다(실측).
  계약 표기(`Upgrade/Downgrade/Reiterated/Initiated/Resumed/기타`)로 매핑했다.
- **`changes[].from_target == 0.0`**: 야후가 '이전 목표가 없음'을 0으로 준다. 0달러 목표가는
  사실이 아니므로 null로 바꾼다.
- **KR `quick_ratio`/`debt_eq`는 yfinance 값이 있어도 네이버로 덮는다**: yfinance `debtToEquity`는
  차입금 기준이라 국내 공시 부채비율(총부채/자본)과 정의가 다르다(000660 실측 7.08 vs 45.95).
  화면 라벨이 "부채비율"이므로 국내 기준을 쓴다.
- **`financials`에서 EPS·매출·주식수가 전부 빈 기간은 제외**: yfinance 손익계산서의 가장 오래된
  열이 통째로 비는 경우가 있다(AAPL 2021). 남기면 차트에 빈 막대만 생긴다. 그래서 AAPL
  `annual`은 5년이 아니라 4년이다(AC-7 기준 ≥4 충족).

### 5-8. 미검증: OpenDART(2차)
`.env`에 `DART_API_KEY`가 없어 `sources/dart.py`와 KR `insiders`(dart 경로)·`shares_note` 해제
경로는 **실호출로 검증하지 못했다.** 키가 없으면 `available()`이 False이고 KR 내부자는
`unavailable` + 안내 문구로 나간다(이 경로는 검증됨). 키 등록 후 `elestock` 응답 필드명
(`repror`/`isu_exctv_ofcps`/`chnge_qy`/`sp_stock_lmp_cnt`/`rcept_dt`/`rcept_no`)을 실측으로 맞춰야 한다.

### 5-9. 미검증: 전체 갱신 루프의 8종목 상한 (실서버)
`POST /api/refresh`(전체)는 CODEF 자동 잔고 동기화를 함께 태울 수 있어(일 100회 한도)
실서버에서 돌리지 않았다. 상한·TTL·우선순위는 `test_refresh_respects_ttl_and_cap`,
`test_refresh_prefers_holdings_then_watchlist`로 고정했다.

---

## 6. 스키마·마이그레이션

`schema.sql`에 `CREATE TABLE IF NOT EXISTS company_cache (...)`만 추가했다. `db.py`는 **미수정** —
`get_conn`이 연결마다 `executescript(_SCHEMA)`를 돌리므로 기존 DB도 다음 연결에서 표가 생긴다.

**기존 DB에서 업그레이드되는지 확인한 방법**: 사용자의 실제 `backend/mystock.db`(티커 15개,
기존 데이터 보유)에 새 코드를 붙인 임시 서버(8733)를 띄우고 `POST /api/refresh?symbol=...`을
실행한 뒤 직접 조회했다.

```
sqlite> SELECT sql FROM sqlite_master WHERE name='company_cache';
CREATE TABLE company_cache ( symbol TEXT NOT NULL, block TEXT NOT NULL, ... )

sqlite> SELECT symbol, block, source, fetched_at, error IS NULL FROM company_cache;
000660|financials|naver|2026-08-21T15:46:45|1
000660|insiders||2026-08-21T15:46:45|1
000660|news|naver|2026-08-21T15:46:45|1
000660|perf10y|yfinance|2026-08-21T15:44:12|1
000660|profile|yfinance+daum+fdr|2026-08-21T15:46:39|1
000660|ratings|naver|2026-08-21T15:46:45|1
000660|snapshot|yfinance+naver+daum|2026-08-21T15:46:45|1
AAPL|... (동일 7행)
```

- 기존 표(`trades`/`cash_flows`/`price_cache`/…)는 손대지 않았다. 컬럼 추가가 없으므로
  `db.py`의 ALTER 마이그레이션 경로도 건드릴 필요가 없다.
- **구버전 서버 호환 확인**: 이 표가 생긴 뒤에도 옛 코드로 떠 있는 8722가
  `GET /api/tickers/AAPL` → 200을 그대로 반환한다(응답 필드는 추가만 했고 표는 옛 코드가
  읽지 않는다).
- 임시 서버(8733)는 검증 후 종료했다. 8722는 손대지 않았으므로 **화면에서 새 필드를 보려면
  리더가 8722를 재시작해야 한다.**

---

## 7. 남은 이슈

1. **`eps_yoy_ttm_pct` 라벨** — 값이 "TTM 전년동기"가 아니라 "최근 분기 vs 전년 동기 분기"다.
   FE 라벨을 그대로 두면 화면이 사실과 다른 단위를 말한다(§5-6).
2. **`dividend_yield_pct` 승인** — AC-4를 만족시키려 넣은 계약 외 키(§5-1).
3. **OpenDART 경로 미검증** — 키 등록 후 `elestock` 필드명 실측 필요(§5-8).
4. **비공식 API 취약성** — 네이버·다음은 예고 없이 바뀐다. 어댑터 상단에 그 사실과 헤더 요구사항을
   적어 뒀고, 파싱 실패는 블록 단위로 격리되며 이전 캐시가 유지된다(AC-14). 스키마가 바뀌면
   `tests/test_company.py`의 픽스처를 실측으로 다시 맞춰야 한다.
5. **`app/market.py` 병행 작업** — 같은 시각 다른 세션이 `backend/app/market*.py`,
   `tests/test_market.py`를 추가하고 있다. 파일 접점은 없으나 `api.py`(라우터)와
   `tests/conftest.py`는 양쪽이 만질 수 있는 파일이라 커밋 전에 리더가 확인할 것.

---

# v2 반영 (계약 v2 §4 BE 수정 지시 B1~B4)

기준: `_workspace/tickerdetail/21_contract_v2.md`. 승인된 항목(`dividend_yield_pct`,
`force_company`, `perf10y` 내부 행, `eps_yoy_ttm_pct` 필드명 유지, `snapshot.note`,
`service.get_company` 패스스루, action 매핑, `from_target==0`→null, 빈 기간 제외)은 그대로 뒀다.
`app/market*.py`·`tests/test_market.py`는 손대지 않았다.

## v2-1. 변경 파일

| 파일 | 변경 |
|---|---|
| `backend/app/company.py` | B1 `empty_profile()`/`PROFILE_KEYS` 추가, `get_profile`이 pending 골격 반환(반환형 `dict\|None` → `dict`) · B2 `_monthly_close_before()` 분리 후 `y5`도 월봉으로 채움 · B3 `debt_eq`/`quick_ratio` 자릿수 2→4 (US·KR 동일) |
| `backend/tests/test_company.py` | 신규 4케이스 + 기존 3케이스 기대값 갱신 |
| `backend/tests/test_api.py` | `profile.status`/`note` 어서션 추가 |
| `backend/tests/test_service.py` | `profile is None` → pending 골격으로 갱신 |

`schema.sql`·`service.py`·`api.py`·`sources/*`는 v2에서 변경 없음.

## v2-2. 테스트 결과

```
cd backend && .venv/bin/pytest -q
338 passed, 4 deselected, 1 warning in 6.03s
```

(v1 334 → v2 338, 신규 4케이스) — 네트워크 없이 통과. 신규 테스트:

- `test_profile_status_ok_when_cached` (B1)
- `test_perf_y5_uses_monthly_cache` (B2) — 월봉 130개월이면 y5·y10 계산, 21개월이면 y5 null
- `test_kr_debt_eq_is_ratio_not_percent` (B3)
- `test_dividend_yield_stays_in_plausible_range` (B4)

기대값 갱신: `test_kr_per_pbr_falls_back_to_naver`(0.46→0.4595, 1.33→1.3297),
`test_us_snapshot_normalizes_units`(0.78→0.7844, quick 0.812 추가),
`test_company_pending_when_no_cache`(profile null → pending 골격).

## v2-3. B1~B4 증거 (임시 서버 8733, 2026-08-21 · 검증 후 종료. 8722는 건드리지 않음)

### B1 — `profile.status` / `profile.note`

```
$ curl -s .../api/tickers/{AAPL,000660} | jq -c '{status:.profile.status, note:.profile.note, source:.profile.source}'
{"sym":"AAPL","status":"ok","note":null,"source":"yfinance"}
{"sym":"000660","status":"ok","note":null,"source":"yfinance+daum+fdr"}

$ curl -s .../api/tickers/KRW-BTC | jq -c '{status:.profile.status, note:.profile.note, sector:.profile.sector, snapshot_status:.snapshot.status}'
{"status":"pending","note":"회사 자료를 아직 받지 못했습니다 — 새로고침을 누르면 지금 가져옵니다.",
 "sector":null,"snapshot_status":"pending"}
```

**PASS.** 캐시 있으면 `ok`+`note:null`, 없으면 `pending`+문구. 하위 키는 전부 존재하고 값만 null이다.

> **FE에 알림(계약 변경점)**: `profile`이 더 이상 `null`이 아니다. v1에서 `null`이던 자리에
> 이제 `status:"pending"` 골격이 온다. `if (!profile)`로 pending을 판별하던 코드가 있으면
> `profile.status === 'pending'`으로 바꿔야 한다(계약 v2 §2 FE-c·F5가 이미 지시한 방향).

### B2 — `perf.y5`를 `perf10y` 월봉 캐시로 (추가 호출 0)

```
AAPL   {"w1":1.98,"m1":-4.93,"m3":2.16,"m6":19.68,"ytd":14.82,"y1":38.25,"y3":79.43,"y5":110.21,"y10":1104.12}
000660 {"w1":5.17,"m1":-5.46,"m3":-10.87,"m6":82.3,"ytd":165.75,"y1":606.12,"y3":1384.98,"y5":1613.17,"y10":4781.84}
```

**PASS.** 9칸 모두 값이 찼다(v1에서 `y5:null`이던 자리). 외부 호출은 늘지 않았다 —
`company_cache`의 `perf10y` 행(TTL 7일)을 그대로 재사용하고, 그 행이 없을 때만 월봉 1콜을 받는다.
월봉 시리즈가 5년을 못 덮는 신규 상장 종목은 여전히 null(`test_perf_y5_uses_monthly_cache` 후반부).

**주의(정의)**: `w1`~`y3`·`ytd`는 일봉 종가 기준, `y5`·`y10`은 월봉 종가 기준이다. 기준일이
월초로 스냅되므로 같은 기간을 일봉으로 다시 계산하면 소수점 단위 차이가 날 수 있다.
배당 재투자는 어느 쪽도 반영하지 않는다(종가 기준).

### B3 — `debt_eq`·`quick_ratio` 단위 배수 통일 (V1 실측 대조)

```
$ curl -s .../api/tickers/{AAPL,000660} | jq -c '{debt_eq, quick_ratio, current_ratio, lt_debt_eq}'
AAPL    {"debt_eq":0.7844,"quick_ratio":0.812, "current_ratio":1.0,  "lt_debt_eq":1.06}
000660  {"debt_eq":0.4595,"quick_ratio":1.3297,"current_ratio":17.54,"lt_debt_eq":0.12}
```

**PASS.** US·KR 모두 **배수**이고 자릿수 체계가 같다(0.x~1.x). 네이버 원본 `45.95`(%) →
`0.4595`, `132.97`(%) → `1.3297`. 자릿수를 2에서 **4로 올렸다** — 2자리면 45.95%가 `0.46`이 되어
계약이 명시한 `0.4595`와 다른 값이 나가기 때문이다(US도 `0.78`→`0.7844`로 함께 올렸다).

> **발견 1건 — 임의로 고치지 않고 보고한다**: 000660의 `current_ratio`(17.54)는 여전히 yfinance
> 값이고, `quick_ratio`(1.3297, 네이버)와 나란히 놓으면 **당좌비율이 유동비율의 1/13**인 불가능한
> 조합이 된다. 원인은 yfinance의 KR 유동성 지표(quickRatio 15.254 / currentRatio 17.544)가
> 국내 공시 기준과 정의가 다르다는 것으로 보인다. 네이버 `finance/annual`의 행 목록에
> **유동비율이 없어**(매출액·영업이익·당기순이익·지배/비지배주주순이익·영업이익률·순이익률·ROE·
> 부채비율·당좌비율·유보율·EPS·PER·BPS·PBR·주당배당금) 1차 소스로는 대체할 수 없다.
> 계약 §4.3 열2-11은 KR `current_ratio` 출처를 `yf`로 명시하므로 그대로 뒀다.
> **선택지**: (a) 현행 유지 + FE 툴팁에 출처 표기, (b) KR `current_ratio`를 null로 비운다,
> (c) DART 2차에서 유동자산/유동부채로 계산. **판단 요청.**

### B4 — `snapshot.dividend_yield_pct` 스케일 가드

```
$ curl -s .../api/tickers/{AAPL,000660} | jq -c '{snapshot:.snapshot.dividend_yield_pct, fundamentals:.fundamentals.dividend_yield}'
AAPL    {"snapshot":0.34,"fundamentals":0.34}
000660  {"snapshot":0.17,"fundamentals":0.09}
```

**PASS(구현 변경 없음).** 스케일 가드는 `dividend_yield_pct(raw, rate, price)`에 들어 있고,
`test_dividend_yield_scale_guard`(0.34 vs 0.00347 판별)에 더해 **범위 가드**
`test_dividend_yield_stays_in_plausible_range`를 추가했다 — 두 종목 실응답이 `0 ≤ v ≤ 30`(%)
안에 있는지 확인한다. 배당수익률 30% 초과는 현실이 아니라 단위 사고다.

> **FE-a/F1 지시의 근거가 실응답으로 확인됐다**: 000660에서 `snapshot.dividend_yield_pct`는
> **0.17**(네이버 `dividendYieldRatio`, §5.1 퍼센트 정규화 경유)인데
> `fundamentals.dividend_yield`는 **0.09**(yfinance 단독, 정규화 미경유)다. 두 값이 실제로
> 다르므로 FE는 반드시 `snapshot.dividend_yield_pct`를 1순위로 읽어야 한다.

## v2-4. 남은 이슈 (v1 §7에 추가)

6. **`profile`이 null이 아니게 됐다** — FE가 `!profile`로 pending을 판별하면 새 응답에서
   영원히 false다. F5 작업 시 함께 확인 필요(위 B1 알림).
7. **KR `current_ratio` vs `quick_ratio` 정의 불일치** — 위 B3 발견. (a)/(b)/(c) 중 판단 요청.
8. **`y5`·`y10`만 월봉 기준** — 나머지 perf 칸과 기준 봉이 다르다. 화면에서 같은 표에 놓이므로
   FE 툴팁에 "5년·10년은 월봉 종가 기준"을 넣을지 판단 필요.
9. 임시 서버(8733)는 종료했다. **8722는 v2 코드가 아니므로 리더 재시작 후에 V6를 계측해야 한다.**
   DB의 `company_cache`는 8733에서 이미 v2 값(`debt_eq` 4자리·`perf.y5`)으로 갱신돼 있어,
   재시작만 하면 강제 새로고침 없이도 새 값이 서빙된다.

---

# v3 반영 (Phase 4 검수 §5 P1 · D6)

기준: `_workspace/tickerdetail/40_acceptance.md` §5 P1. **BE 필수 수정은 D6 1건뿐**이고
그것만 적용했다. 보류 항목(유동비율·당좌비율 출처 정합성, D6b 제목 절단, DART 2차 실호출)은
건드리지 않았다. `app/market*.py`·`tests/test_market.py`·`frontend/`·git 미변경.

## v3-1. 변경 파일

| 파일 | 변경 |
|---|---|
| `backend/app/company.py` | `import html` + `unescape_text()` 추가. 적용 지점 3곳 — 네이버 뉴스 `title`/`officeName`, yfinance 뉴스 `title`/`source`, 네이버 리포트 `title`/`brokerName` |
| `backend/tests/test_company.py` | `test_news_title_html_entities_unescaped` 1건 추가 + `NAVER_NEWS` 픽스처 제목을 실응답 형태(`&quot;`·`&amp;` 포함)로 교체 |

**적용 지점을 `sources/naver.py`가 아니라 `company.py`로 잡은 이유**: `sources/naver.py`는
원본 JSON을 그대로 돌려주는 어댑터라 제목 필드를 파싱하지 않는다. 파싱은 `build_news`/
`build_ratings`에서 일어나므로, 지시문이 허용한 "조립 지점"에 넣어야 **네이버·yfinance 양쪽
경로가 같은 규칙**을 탄다(yfinance 제목에도 같은 사고가 날 수 있다).

## v3-2. 테스트 결과

```
cd backend && .venv/bin/pytest -q
339 passed, 4 deselected, 1 warning in 7.53s
```

(v2 338 → v3 339). 네트워크 없이 통과 — `conftest.no_network_sources`가 소스 계층을 막는다.

신규 `test_news_title_html_entities_unescaped`:
`unescape_text("&quot;A&quot;") == '"A"'`, `"B &amp; C &#39;D&#39;" → "B & C 'D'"`,
`None → None`, 그리고 조립 결과의 뉴스 20건 + 리포트 10건 제목에
`&quot;`/`&amp;`/`&#39;`가 하나도 없음을 확인한다.

## v3-3. 수정 전후 실응답 (임시 서버 8733 · 검증 후 종료. 8722 미변경)

`before`는 v2 캐시가 서빙되던 시점의 `GET /api/tickers/000660/company`,
`after`는 v3 코드로 강제 갱신한 뒤의 같은 요청이다.

```
BEFORE  엔티티 포함 제목: 20건 중 2건
  &quot;2배보다 3배&quot;…미장 개미 몰린 해외 레버리지 ETF, 거래액 9조원 넘어
  &quot;이게 시총 1·2위 맞아?&quot;…이틀에 한 번꼴 5% 출렁인 '삼전닉스' [증시...

AFTER   엔티티 포함 제목: 0건
  "2배보다 3배"…미장 개미 몰린 해외 레버리지 ETF, 거래액 9조원 넘어
  "이게 시총 1·2위 맞아?"…이틀에 한 번꼴 5% 출렁인 '삼전닉스' [증시...
```

검증 명령(§5 P1이 지정한 것):

```
$ curl -s .../api/tickers/000660/company | jq -r '.news.items[].title' | grep -c '&quot;'
0
$ curl -s .../api/tickers/000660/company | jq -r '.ratings.reports[].title' | grep -c '&quot;\|&amp;\|&#39;'
0
$ curl -s .../api/tickers/AAPL/company    | jq -r '.news.items[].title' | grep -c '&quot;\|&amp;\|&#39;'
0
```

**회귀 없음** — 같은 갱신 뒤 v2 결과가 그대로다:
`{"profile_status":"ok","y5":1613.17,"debt_eq":0.4595,"quick":1.3297,"dy":0.17}`.

> 두 번째 제목 끝의 `[증시...`는 **네이버가 절단해서 보내는 원문**이다(D6b, 보류 판정).
> `html.unescape`와 무관하며 이번 라운드에서 손대지 않았다.

## v3-4. 상태

- `company_cache`는 8733에서 v3 값(엔티티 해제된 제목)으로 이미 갱신돼 있다. **8722는 리더가
  재시작하면 강제 새로고침 없이 새 제목을 서빙한다.**
- 임시 서버(8733)는 종료했고 8722는 살아 있다(`/api/health` 200).
- v1 §7·v2 §v2-4의 남은 이슈(특히 KR `current_ratio` 출처 정합성)는 보류 판정에 따라 그대로 둔다.
