# TickerDetail 프론트엔드 구현 보고서 (Phase 3, FE)

- 스펙: `_workspace/tickerdetail/20_spec.md` (§4.3 84칸, §5 계약, §7 블록 이동, §8.2, §9)
- 범위: `frontend/` 만. `backend/` 무수정. `git add`/`commit` 없음(작업 트리에만 존재).
- **전제**: 백엔드가 아직 `profile`/`snapshot`/`GET /company`를 내보내지 않는다(구현 병행 중).
  계약대로 타입을 먼저 고정하고, 신규 필드는 `?:`/`null` 허용으로 선언해 구버전 응답에서도
  컴파일·렌더가 깨지지 않게 했다. 실데이터 검증은 §5 계약 모양의 **브라우저 런타임 목**
  (`window.fetch` 임시 래핑, 소스 무변경)으로 수행했다 — 커밋 대상 코드에 목은 없다.

## 1. 변경 파일 목록

신규
| 파일 | 요약 |
|---|---|
| `frontend/src/quote/fmt.ts` | 화면 전용 표기 — `abbrNum`(USD `333.70B` / KRW `12.3조`·`4,560억`), `pctText`, `levelPct`, `ratioText`, `intText`, `moneyCell`, `dateText`. `format.ts` 무수정 |
| `frontend/src/quote/fmt.test.ts` | 위 6종 단위 테스트(축약·원화 소수점 금지·null→`—`) |
| `frontend/src/quote/snapshotCells.ts` | finviz 84칸(열1~열6 × 14행) 조립. 라벨·순서는 §4.3 표 그대로, 행 우선으로 엮어 반환 |
| `frontend/src/components/quote/BlockEmpty.tsx` | 4블록 공통 빈 상태/스켈레톤 + `BlockSource`(출처·상대 갱신시각). `status`로 무엇을 그릴지만 고르고 `note`는 그대로 렌더 |
| `frontend/src/components/quote/FinancialsChart.tsx` | recharts 막대 3종(EPS·매출·발행주식수) + 연간/분기 토글 + 추정치 `fillOpacity 0.35` & x축 `(E)` |
| `frontend/src/components/quote/NewsList.tsx` | 날짜가 바뀔 때만 날짜 표기, 같은 날은 시각만 |
| `frontend/src/components/quote/RatingsTable.tsx` | consensus 요약 + `changes` 표 + KR `reports` 대체 표 + `note` 빈 상태 + 1=강력매수 스케일 명시 |
| `frontend/src/components/quote/InsiderTable.tsx` | 9열 표, `.table-cards`로 좁은 화면 카드 접힘(모든 `td`에 `data-label`) |
| `frontend/src/pages/ticker/Analysis.tsx` | §7 이동분 5블록(시그널 근거·백테스트·청산/진입 플랜·커스텀 룰·시그널 히스토리) + `/backtest` 호출 |

수정
| 파일 | 요약 |
|---|---|
| `frontend/src/types.ts` | §5 계약 타입 추가(아래 2절). 기존 타입 변경·삭제 없음 |
| `frontend/src/quote/stats.ts` | `volatility(candles, bars)`(일간 수익률 표준편차 %), `avgTurnover(candles, bars)`(종가×거래량 평균) 추가 |
| `frontend/src/quote/stats.test.ts` | 위 2함수 케이스 5개 추가 |
| `frontend/src/pages/TickerDetail.tsx` | 개요를 finviz 구성으로 재조립: 헤더 → 판정 한 줄(+`분석 →`) → 차트 → 84칸 → 재무 → 뉴스/애널리스트 2:1 → 회사 설명 → 내부자. `/company` 첫 페인트 뒤 지연 로드, `/backtest` 호출 제거 |
| `frontend/src/components/quote/QuoteHeader.tsx` | 섹터·산업·국가·거래소·직원수 텍스트 줄 추가(링크 아님 — 스크리너가 없다) |
| `frontend/src/components/quote/SnapshotTable.tsx` | `SnapCell.sub` 추가(한 칸 두 값: 52주 고가 `126.71 -36.75%`, 변동성 주/월 등) |
| `frontend/src/App.tsx` | `/ticker/:symbol/analysis` 라우트 1개(lazy) |
| `frontend/src/quote.css` | 신규 블록 스타일(`.quote-facts`, `.verdict-link`, `a.quote-tab`, `.block-empty`, `.fin-charts`, `.news-list`, `.company-desc`) |

**손대지 않은 것**: `format.ts`, `theme.css`, `backend/**`, 그리고 다른 세션 소유
(`Dashboard.tsx`, `Layout.tsx`, `SentimentGauge.tsx`, `src/finviz/**`).

## 2. 계약 반영 (`types.ts`)

- 신규: `Profile`, `SnapshotPerf`, `Snapshot`(§4.3 키 전부, 하위 전부 `| null`),
  `CompanyBlock`(공통 래퍼), `FinancialsItem`/`Financials`, `NewsItem`/`News`,
  `RatingsConsensus`/`RatingChange`/`ResearchReport`/`Ratings`, `InsiderItem`/`Insiders`, `Company`.
- `TickerDetail`에 `profile?: Profile | null`, `snapshot?: Snapshot | null` **선택 필드**로 추가.
- `snapshot.recommendation_scale`, `snapshot.sources`, `<block>.status/note/source/fetched_at`까지
  계약대로 받고 화면에 사용한다(스케일 문구·출처·상대 갱신시각 노출).
- KR/US 라벨이 갈리는 열4-4는 `foreign_own_pct`가 있으면 `외국인 지분`, 없으면 `기관 거래`로
  **값 유무**가 고른다(시장 코드 분기 없음, §4.3 지시대로).

## 3. 검증 결과

| 항목 | 결과 |
|---|---|
| `npx tsc -b` | 통과(출력 없음) |
| `npx tsc --noEmit -p tsconfig.app.json` | 통과(0건). 다른 세션 파일 제외 필터(`grep -v "Dashboard\|Layout\|finviz\|theme"`)에서도 0건 |
| `npm run lint`(oxlint) | 무경고. 기존 관례대로 `// eslint-disable-next-line react-hooks/exhaustive-deps` 2곳(심볼 변경 시에만 재요청) |
| `node --test src/quote/stats.test.ts src/quote/fmt.test.ts` | tests 24 / pass 24 / fail 0 |
| 가로 스크롤(1280) | 개요 `documentElement.scrollWidth 1265 = clientWidth 1265`, 분석 동일 → 0 |
| 가로 스크롤(390) | 개요·분석 모두 `scrollWidth 390 = clientWidth 390`, `window.scrollX` 최대 **0** |
| 스냅샷 칸 수 | AAPL·000660 모두 `.snap-cell` **84**개 |
| 390px 스냅샷 | 첫 행 top 동일 칸 수 = **2쌍/행** |
| 내부자 표 390px | `tr` `display:block`, 9칸 전부 `data-label` 표시(카드 접힘), 가로 스크롤 0 |
| DOM 텍스트 `undefined|NaN|null` | 개요(AAPL·000660, 목 있음/없음)·분석 전부 **0건** |
| 콘솔 에러 | 이 화면에서 발생한 것 0건. 남은 에러 2건은 **다른 세션**의 `SentimentGauge.tsx`(삭제됨)·`Layout.tsx` HMR 실패 |

## 4. 수용 기준 체크 (FE 해당분)

| # | 결과 | 증거 |
|---|---|---|
| AC-3 (AAPL 84칸 중 `—` ≤ 12) | **미확인 — 백엔드 대기** | 현 백엔드는 `snapshot`이 없어 실측 `—` 66칸. 계약 모양 목 주입 시 16칸까지 내려감(목의 임의 null 포함) → 값이 오면 채워지는 구조는 확인 |
| AC-4 (000660 필수 14칸 / 공매도 3칸 `—`) | **미확인 — 백엔드 대기** | 목 주입 시 시가총액 `456.8조`·순이익 `12.3조`·목표주가 `320,000`·발행주식수 `7.3억` 표시, 공매도 3칸 `—` 확인 |
| AC-8 (KR 내부자 자리에 `note` 그대로, 빈 표·`undefined` 없음) | **PASS(목)** | 렌더 텍스트: "내부자 거래 / 국내 종목 내부자 거래는 OpenDART 키(무료)를 등록해야 표시됩니다." · `bad: []` |
| AC-9 (개요 `/backtest` 0건, 분석에서만) | **PASS** | 네트워크 로그: 개요 진입 시 `/api/tickers/AAPL`, `/api/tickers/AAPL/company`만. `/backtest`는 `/analysis`에서만 발생 |
| AC-10 (손절 룰 등록·삭제가 분석에서 동작) | **PASS** | `/ticker/AAPL/analysis`에서 "손절가를 룰로 등록" 클릭 → `GET /api/tickers/AAPL`의 `rules` 길이 0→1(`STOP 295.7143`), 삭제 클릭 → 1→0 복귀 |
| AC-16 (tsc + lint 무경고) | **PASS** | 3절 |
| AC-17 (390px 가로 스크롤 0, 두 화면) | **PASS** | `scrollWidth 390 == clientWidth 390`, 최대 `scrollX 0` (개요/분석 각각) |
| AC-18 (390px 2쌍/행 + 내부자 카드) | **PASS** | 3절 계측 |
| AC-19 (캐시 없는 종목에서 4블록 pending, 화면 무손상) | **PASS(현 상태가 곧 증거)** | 백엔드에 `/company`가 없어 요청이 SPA HTML로 떨어지는 상황에서도 4블록이 각각 "회사 자료를 불러오지 못했습니다 — 새로고침 후 다시 확인하세요."(원문은 `title`), 회사 설명은 "…아직 받지 못했습니다 — 새로고침을 누르면 지금 가져옵니다.", 스냅샷 84칸은 `—`로 유지. `undefined/NaN/null` 0건. 백엔드가 `status:"pending"`을 주면 `BlockEmpty`가 BE `note`를 그대로 출력 |
| AC-20 (연간/분기 토글이 실제로 데이터셋 교체, 추정 막대 구분) | **PASS(목)** | 연간 `2022·2023·2024·2025·TTM(E)` → 분기 클릭 후 `2025Q3·2025Q4·2026Q1·2026Q2(E)`로 교체. 추정 막대 `fill-opacity 0.35` vs 실적 `0.9` |
| AC-21 (축약 표기) | **PASS** | 화면 실측: AAPL 시가총액 `3.34T`·내부자 금액 `159.67M`·평균 거래량 `40.9M`, 000660 시가총액 `456.8조`·순이익 `12.3조`. 단위 테스트에 `333.70B`/`92.20M`/`12.3조`/`4,560억` 고정, KRW 억 이하 소수점 금지 assert |

AC-1·2·5·6·7·11~15는 백엔드 소관.

## 5. 계약 불일치

**현재 시점 기준 없음**(백엔드가 아직 신규 필드를 내보내지 않아 실응답 대조 불가).
관측된 사실만 기록한다:

- `GET /api/tickers/AAPL` 실응답 키: `symbol,name,market,currency,is_etf,fundamentals,signal,candles,risk,last_refresh,cost_rates,cash,dividends,history,rules,entry_review` — `profile`·`snapshot` 없음(구현 전).
- `GET /api/tickers/AAPL/company` → 라우트가 없어 **SPA `index.html`(200/HTML)** 이 돌아온다.
  FE는 이 경우 JSON 파싱 실패를 잡아 "불러오지 못했습니다" 상태로 렌더하며, 목업을 소스에 넣지 않았다.

**계약 해석 메모(임의 변경 아님, 확인 요청)**
1. AC-4는 000660 필수 칸에 **배당수익률**을 넣었으나 §4.3의 84칸에는 배당수익률 칸이 없다.
   finviz가 `Dividend TTM 1.02 (0.44%)`로 금액+수익률을 한 칸에 쓰는 것을 따라, `최근 배당(주당)`
   칸의 보조값으로 기존 `fundamentals.dividend_yield`를 붙였다(신규 계약 필드 요구 없음).
2. §4.3 열6 1~9행 성과는 BE 계산이 원칙이나, `snapshot`이 없거나 해당 키가 null인 동안에는
   1주~연초대비를 candles로 계산해 채운다(`perf.w1 ?? perfPct(c,5)`). 1년 이상은 200봉으로
   계산 불가라 BE 값만 쓴다. 화면이 이유 없이 비지 않게 하려는 폴백이며 BE 값이 오면 BE가 이긴다.
3. `profile`에는 `status` 필드가 없어(§5.2) 회사 설명 블록의 "아직 받지 못했습니다" 한 줄만
   FE 문구다. 나머지 4블록 문구는 전부 BE `note`를 그대로 흘린다.

## 6. 보류·질의

- **`abbrNum` KRW 100억 미만은 소수 1자리**(`7.3억`)로 둔다. 정수로 끊으면 발행주식수
  728,002,365주가 `7억`이 되어 자릿수가 하나 사라진다. 시가총액급(≥100억)은 스펙대로
  `4,560억` 정수 표기이며 원 단위 소수점은 어디에도 없다.
- 개요 탭 줄은 `개요·차트·스냅샷·재무·뉴스·회사·내부자` + 마지막 `분석`(링크)이다.
  애널리스트 섹션은 뉴스와 같은 2:1 행에 있어 탭을 따로 두지 않았다(finviz도 같은 행).
- 분석 화면의 시그널 섹션에 **스윙/중장기 등급 배지 2줄**을 추가했다. 개요 스냅샷에서 MyStock
  고유 22칸을 빼면서 등급 배지를 볼 곳이 앱 내 상세 경로에서 사라지기 때문이다(순수 이동에
  더한 유일한 항목).
- 재무 3번째 막대(발행주식수)는 값이 전부 null이면 BE `shares_note`를 그대로 자리에 출력한다.
- 남은 이슈: **다른 세션 파일 오류(제외)** — dev 콘솔의 `SentimentGauge.tsx`(삭제됨)·`Layout.tsx`
  HMR 500/404는 병행 중인 대시보드 작업의 것이다. 내 소유 파일만 필터한 `tsc`는 0건.
- 백엔드가 신규 필드를 내보낸 뒤 AC-3·4·6·7·8·19를 **실데이터로 재계측**해야 한다(현재는 목 기준).

---

# v2 반영 (계약 v2 · FE 수정 지시 F1~F7, 2026-08-21)

기준: `_workspace/tickerdetail/21_contract_v2.md` §3 계약 v2 · §5 FE 수정 지시.
**8722 새 백엔드가 실데이터를 서빙하는 상태에서 5173(dev, 8722 프록시)으로 전 항목 재계측**했다.
목(mock)은 전부 제거됐고 아래 수치는 모두 실응답 기준이다.

## v2-1. 변경 파일

| 파일 | 변경 |
|---|---|
| `frontend/src/types.ts` | 계약 v2 필드 3종 선택 추가: `Snapshot.dividend_yield_pct?`, `Snapshot.note?`, `Profile.status?`/`Profile.note?` (BE가 아직 안 주는 동안도 컴파일·렌더 유지) |
| `frontend/src/quote/snapshotCells.ts` | F1 배당수익률 소스 교체, F2 라벨 2건 + 툴팁 상수 `YOY_NOTE`, F3 서프라이즈 칸 단일화, F6 배수 표기(`x`)와 툴팁 |
| `frontend/src/pages/TickerDetail.tsx` | F5 회사 설명 pending을 `BlockEmpty`+`profile.status/note`로, 스냅샷 하단 문구를 `snapshot.note`로(문구는 BE 소유), 출처 줄은 `relativeTime` 사용 |
| `frontend/src/components/quote/FinancialsChart.tsx` | recharts `ResponsiveContainer` 제거 → 폭 직접 실측(`ResizeObserver`) 후 `BarChart width` 지정 (아래 v2-4 참조) |

## v2-2. F1~F7 증거 (실데이터)

| # | 지시 | 결과 | 증거 |
|---|---|---|---|
| F1 | 배당수익률 소스 `snapshot.dividend_yield_pct ?? fundamentals.dividend_yield` | **완료** | 000660 칸 DOM: `<span class="snap-label">최근 배당(주당)</span><span class="snap-value">3,000<small>0.17%</small></span>` — 지시된 `0.17%` 일치. AAPL은 `1.05` + `0.34%` |
| F2 | 라벨 `EPS/매출 전년동기(분기)` + 툴팁 | **완료** | 000660 칸 텍스트 `EPS 전년동기(분기) +1269.54%`, `매출 전년동기(분기) +256.78%`. 두 칸 `title`="최근 분기와 전년 동기 분기의 비교입니다 (TTM 합산이 아님)" |
| F3 | `EPS 서프라이즈` 단일 값 | **완료** | 000660 `EPS 서프라이즈 +85.24%`(보조값 없음), AAPL `+6.74%`. `sales_surprise_pct`는 타입에만 남기고 렌더 안 함. 84칸 유지 |
| F4 | `earnings_timing` null이면 날짜만 | **완료** | 000660 `실적발표일 2026-10-27`, AAPL `실적발표일 2026-10-30`(둘 다 timing null). DOM 텍스트 `undefined|NaN|null` 0건 |
| F5 | 회사 설명 pending 문구를 BE `note`로 | **완료(BE B1 대기)** | `BlockEmpty`에 `profile.status/note`를 그대로 넘긴다. 현재 응답의 `profile`에는 아직 `status`/`note` 키가 없어(BE 추가 중) pending 폴백 문구가 나간다 — KRW-BTC에서 "회사 자료를 아직 받지 못했습니다 — 새로고침을 누르면 지금 가져옵니다." 확인. **BE가 필드를 붙이면 코드 변경 없이 BE 문구로 바뀐다** |
| F6 | 배수 단위 표기 | **완료** | `당좌비율 1.33x` · `유동비율 17.54x` · `부채비율 0.46x` · `장기부채비율 0.12x`(000660), AAPL `0.81x`/`1.00x`/`0.78x`/`1.06x`. 각 칸 툴팁에 정의 명시(`부채비율`: "총부채 ÷ 자기자본 — 배수(0.46 = 46%)") |
| F7 | 목 제거 후 실백엔드 재계측 | **완료** | v2-3 표 전체가 실데이터 계측 |

부수: 스냅샷 표 아래 pending 문구도 `snapshot.note`(BE 문구)를 그대로 쓴다 — KRW-BTC에서
"회사 자료를 아직 받지 못했습니다 — 새로고침을 누르면 지금 가져옵니다." 렌더 확인.

## v2-3. 실데이터 AC 재계측 (목 없음)

| # | 결과 | 실측 |
|---|---|---|
| AC-3 | **PASS** | AAPL 84칸 중 `—` **4칸**(기관 거래 / EPS 성장(5년 추정) / EPS·매출 성장 과거 5Y 보조값) ≤ 12. 요구 12칸 전부 값 있음: 시가총액 `4.54T` · PER `36.37` · EPS(TTM) `8.56` · ROE `148.75%` · 영업이익률 `32.62%` · 발행주식수 `14.59B` · 베타 `1.09` · 목표주가 `326.34(+4.83%)` · 컨센서스 의견 `2.11` · 실적발표일 `2026-10-30` · 상장일 `1980-12-12` · 직원수 `150,000` |
| AC-4 | **PASS** | 000660 요구 14칸 전부 값 있음: 시가총액 `1263.8조` · PER `7.71` · PBR `4.67` · EPS(TTM) `224,313` · BPS `370,432` · 배당수익률 `0.17%`(최근 배당 칸 보조값, v2 판정 기준) · ROE `92.68%` · 영업이익률 `76.33%` · 발행주식수 `7.1억` · 베타 `2.41` · 목표주가 `3,317,917(+91.79%)` · 컨센서스 의견 `2.00` · 상장일 `1996-12-26` · 직원수 `47,639`. 공매도 3칸(`공매도 비율/상환일수/잔고`) 전부 `—`. 총 `—` 8칸 |
| AC-6 | **PASS** | 000660: 뉴스 `.news-item` **20건**(전부 한국어, 출처 naver) · 재무 annual **4개**(2023·2024·2025·2026(E)) · 리포트 표 **10행** · `ratings.changes` 표 미출력(0건) + note 문장 렌더 · 내부자 `unavailable` note 렌더 |
| AC-7 | **PASS** | AAPL: 뉴스 **10건** · 등급 변경 표 **20행** · 내부자 표 **30행** · 재무 annual **4개**(2022~2025) · quarterly **5개**(2025Q2~2026Q2, 토글로 교체 확인) |
| AC-8 | **PASS** | 000660 내부자 자리 텍스트: "국내 종목 내부자 거래는 OpenDART 키(무료)를 등록해야 표시됩니다." 빈 표 없음. 페이지 DOM 텍스트 `undefined\|NaN\|null` **0건** |
| AC-9 | **PASS** | 실서버 네트워크 로그: 개요 진입 = `/api/tickers/000660` + `/api/tickers/000660/company`만(개발 StrictMode로 detail 2회). `/backtest`는 `/analysis` 방문 시에만 |
| AC-19 | **PASS** | 캐시 없는 종목 **KRW-BTC**(BE 실응답 `snapshot.status="pending"`, 4블록 전부 `pending`): 스냅샷 84칸 유지, 4블록 + 회사 설명 + 스냅샷 하단이 모두 BE `note` 문장, 가로 스크롤 0, `undefined\|NaN\|null` 0건 |
| AC-16 | **PASS** | `npx tsc -b` OK, `npm run lint` 무경고, `node --test src/quote/{stats,fmt}.test.ts` 24/24 |
| AC-17 | **PASS** | 1280px: 개요(AAPL·000660)·분석(AAPL·000660) 전부 `scrollWidth 1280 == clientWidth`, `scrollX` 최대 0. 390px: 같은 4개 화면 `scrollWidth 390 == clientWidth 390`, `scrollX` 최대 0 |
| AC-18 | **PASS** | 390px 스냅샷 2쌍/행(첫 행 동일 `top` 칸 2개), 내부자 표 `tr display:block`(카드), 가로 스크롤 0 |
| AC-20 | **PASS** | AAPL 연간 3차트×4막대=12개 → `분기` 클릭 시 x축 `2025Q2…2026Q2`로 교체. 000660은 연간 4번째가 컨센서스라 `2026(E)` 라벨 + `fill-opacity 0.35`(실적 막대 `0.9`) |
| AC-21 | **PASS** | AAPL 시가총액 `4.54T`·매출 `394.33B`·발행주식수 `14.59B`, 000660 시가총액 `1263.8조`·매출 `32.8조`·발행주식수 `7.1억`. KRW 원 단위 소수점 없음 |

## v2-4. 구현 중 발견해 고친 것 (FE 자체 결함)

**recharts `ResponsiveContainer`가 폭 0에서 마운트되면 영구히 0으로 굳는다.**
회사 자료는 첫 페인트 뒤 로드되므로, 그 순간 컨테이너가 폭 0(숨은 탭·비활성 프리뷰 등)이면
막대가 끝내 그려지지 않았다(AAPL 재무 3칸 전부 빈 상태로 관측, 이후 창 크기를 바꿔도 복구 안 됨).
`ResponsiveContainer`를 걷어내고 `ResizeObserver`로 폭을 직접 재서 `BarChart width`에 넘기도록 바꿨다.
같은 조건에서 재계측: AAPL 12막대 / 000660 8막대 + shares_note 정상 렌더, 폭 0→값 전환에서도 복구된다.
(이 프로젝트에서 recharts가 조용히 안 그리는 사례는 `AllocationDonut.tsx` 주석에도 남아 있다.)

## v2-5. 계약 불일치 · BE 확인 요청

1. **`current_ratio`(유동비율) 단위가 US/KR에서 다르다.** 실측 AAPL `1.0` vs 000660 `17.54`.
   `debt_eq`(0.7844 vs 0.4595)와 `quick_ratio`(0.812 vs 1.3297)는 v2 §4-B3대로 **배수로 통일**됐지만
   유동비율만 자릿수 체계가 다르다(SK하이닉스 유동비율은 배수로 2~3 수준이라 17.54는 어느 단위로도
   설명되지 않는다). 계약 §4.3 열2-11은 `유동비율(배)` = **배수**다. **BE 확인 요청**(V1의 확장).
   FE는 계약대로 배수로 표기하며 값 변환을 하지 않는다.
2. `profile.status`/`profile.note`(v2 §4-B1)는 아직 응답에 없다 — FE는 폴백 경로로 정상 동작하며,
   필드가 붙으면 코드 변경 없이 BE 문구가 나간다. **BE 대기**.
3. `snapshot.perf.y5`는 채워졌다(AAPL `110.21`, 000660 `1613.17`) — B2 반영 확인.
4. `sales_surprise_pct`는 계약에 남아 있으나 실응답 항상 null이고, v2 §5-F3에 따라 렌더하지 않는다.

## v2-6. 남은 이슈

- 회사 설명 블록에서 `profile.status === 'ok'`인데 `description`이 null인 종목은
  "이 종목은 회사 설명이 제공되지 않습니다."(FE 문구)가 나간다. BE가 이 경우에도 `note`를 주면
  그쪽이 우선한다.
- KRW-BTC 등 회사 자료 자체가 성립하지 않는 자산(암호화폐)도 `pending`으로 표시된다 —
  "아직 못 받음"과 "원래 없음"의 구분은 BE `status`(`unavailable`) 소관이라 FE에서 분기하지 않았다.
- **내가 만들지 않은 작업 트리 변경**: `frontend/src/api.ts`(200인데 JSON이 아니면 "백엔드 구버전"
  메시지로 바꾸는 `json()` 헬퍼)는 다른 세션이 넣은 것이다. 내 코드와 충돌하지 않으며,
  `/company`가 SPA 폴백으로 떨어지던 상황의 오류 문구를 개선한다 — 되돌리지 않았다.

---

# v3 반영 (Phase 4 검수 · FE 수정 지시 F-a~F-h, 2026-08-22)

기준: `_workspace/tickerdetail/40_acceptance.md` §5 "FE 수정 지시 — 이번 라운드 필수".
필수 7건(D1·D3·D4·D7·D8·D11·D12) + P2 1건(D5 툴팁, §2.2에서 "현행 유지 + 툴팁 출처 표기"로 확정)
적용. 보류 항목(R1·R3·D9·D10·D13·뉴스 절단·`quote/cells.ts` 삭제)은 손대지 않았다.
검증은 5173(dev, 8722 프록시) 실데이터 · AAPL/000660 · 1280px/390px.

## v3-1. 변경 파일

| 파일 | 변경 |
|---|---|
| `frontend/src/quote/fmt.ts` | F-b: 조 단위 `toLocaleString('ko-KR', {min/maxFractionDigits:1})` — `1263.8조` → `1,263.8조` |
| `frontend/src/quote/fmt.test.ts` | F-b 케이스 추가(`1_263_751_800_000_000 → '1,263.8조'`) |
| `frontend/src/quote/snapshotCells.ts` | F-a: `abbrNum('USD', avgVolume(…))` → `abbr(…)`(종목 통화) / F-f: 3·5년 결합 칸 3개를 3년 단일 값으로 축소(`배당성장 3년`·`EPS 성장(3년)`·`매출 성장(3년)`) / F-h: 당좌·유동비율 툴팁에 출처 체계 명시 |
| `frontend/src/components/quote/SnapshotTable.tsx` | F-c: 값과 보조값 사이 구분자 `· ` 삽입 |
| `frontend/src/components/quote/QuoteHeader.tsx` | F-d: `cur()` → `quote/fmt.ts`의 `moneyCell()` + 통화기호 접두(부호는 기호 앞). `format.ts` 무수정 |
| `frontend/src/components/quote/BlockEmpty.tsx` | F-e①: `block.source`가 없으면 `BlockSource`가 `null` 반환(시각만 뜨는 줄 제거) |
| `frontend/src/pages/TickerDetail.tsx` | F-e②: 회사 설명 `<small>`에 `· {relativeTime(profile.fetched_at, now)}` 추가 |
| `frontend/src/quote.css` | F-g: 390px 탭 줄 처리(아래 v3-3) + 640px 이하 스냅샷 라벨·값 줄바꿈 허용 |

## v3-2. F-a~F-h 증거 (실데이터 DOM)

| # | 지시 | 결과 | 실측 |
|---|---|---|---|
| F-a (D3, AC-21) | 평균 거래량을 종목 통화로 축약 | **완료** | 000660 `평균 거래량(20) 573만`(M 사라짐, 같은 열 `발행주식수 7.1억`과 단위 체계 일치) / AAPL `53.05M` |
| F-b (D4, AC-21) | 조 단위 천단위 구분 | **완료** | 000660 `시가총액 1,263.8조` · `기업가치(EV) 1,161.9조` · `순이익(TTM) 162.0조`. 단위 테스트 24/24 |
| F-c (D1) | 값·보조값 구분자 | **완료** | `ATR (14) 172,043 · 9.94%`(지시 문구와 동일) · `52주 고가 2,987,000 · -42.08%` · `최근 배당(주당) 3,000 · 0.17%` · `변동성(주/월) 7.15% · 9.57%` · `목표주가 3,317,917 · +91.79%` |
| F-d (D8) | 헤더 자릿수 통일 | **완료** | AAPL 헤더 `$309.35` ↔ 스냅샷 `현재가 309.35`(전일 종가 `311.30`) 자릿수 동일. 등락 `-$1.95 (-0.63%)` — 부호가 기호 앞. KRW는 `₩1,730,000` ↔ `현재가 1,730,000`(원 단위 소수점 없음) |
| F-e (D7) | 출처 없는 시각 줄 제거 + 회사 설명 시각 | **완료** | 000660 블록 헤더 4줄 전부 `출처: …` 접두(`출처: naver · 1분 전` ×3, 회사 설명 `출처: yfinance+daum+fdr · 1분 전`). `unavailable`인 내부자 블록은 source가 null이라 줄 자체가 사라짐(이전엔 `3분 전`만 떴다). AAPL 회사 설명 `출처: yfinance · 1분 전 · 영문 원문` |
| F-f (D11/R2) | 3/5년 결합 칸 축소 | **완료** | `배당성장 3년 +26.50%` · `EPS 성장(3년) +165.07%` · `매출 성장(3년) +29.61%`(보조값 제거). **84칸 유지**(AAPL·000660 모두 `.snap-cell` 84). 390px `.snap-label` 말줄임 **0칸**(AAPL·000660) |
| F-g (D12) | 390px 탭 줄 | **완료(방식 변경, 아래)** | 390px에서 탭 줄 2행 wrap, `분석` 탭 `right = 66 ≤ innerWidth 390`. `/analysis`의 `← 개요` 탭도 `right = 79` |
| F-h (D5) | 두 비율 출처 툴팁 | **완료** | `당좌비율` title="유동자산(재고 제외) ÷ 유동부채 — 배수. 국내 종목은 국내 공시 기준(네이버)", `유동비율` title="유동자산 ÷ 유동부채 — 배수. yfinance 기준(국내 종목도 동일)" |

## v3-3. 지시와 다르게 구현한 것 (1건, 사유 명시)

**F-g**: 지시는 `.quote-tabs`에 `mask-image` 페이드(잘렸다는 어포던스)였으나, **≤720px에서
탭 줄을 `flex-wrap: wrap`으로 감싸 전부 보이게** 했다.

- 이유: `분석` 탭은 손절 룰 등록·삭제·백테스트로 가는 **앱 유일의 입구**다(AC-10). 잘렸다는
  신호만 주면 여전히 스크롤이라는 추가 동작을 요구한다. 리더의 검증 조건도
  "`분석` 탭 `getBoundingClientRect().right <= innerWidth`"였고, 페이드로는 이 조건을 만족할 수 없다.
- 비용: 390px에서 탭 영역 높이 +28px(1행 → 2행). 721px 이상은 기존 1행·가로 스크롤 그대로.
- 페이드가 더 낫다고 판단되면 CSS 6줄을 되돌리면 된다(`quote.css`의 `@media (max-width: 720px)` 블록).

## v3-4. 지시에 없지만 F-f 검증 조건을 맞추려 추가한 CSS 1건

F-f의 검증 기준은 "390px에서 `.snap-label` 말줄임 0칸"이었는데, 라벨을 줄인 뒤에도
`52주 고가`·`EPS 전년동기(분기)` 2칸이 여전히 말줄임됐다(한 칸 폭 170px, 값이 길다).
`@media (max-width: 640px)`에서만 `.snap-label`·`.snap-value`의 줄바꿈을 허용했다.

- 결과: 390px 말줄임 **0칸**(AAPL·000660), 스냅샷 표 높이 1102 → 1131px(+29px).
- 1280px는 영향 없음: 84칸 전부 셀 높이 26px 단일값(줄바꿈 0), 6쌍/행 유지.

## v3-5. v3 재계측 (실데이터, 목 없음)

| 항목 | 1280px | 390px |
|---|---|---|
| 개요 AAPL | `scrollWidth 1265 = clientWidth`, `scrollX` 0, 84칸, 6쌍/행, 라벨 말줄임 0 | `390 = 390`, `scrollX` 0, 84칸, 2쌍/행, 말줄임 0 |
| 개요 000660 | 동일 | 동일 |
| 분석 AAPL / 000660 | `scrollX` 0 | `scrollX` 0, `← 개요` 탭 `right 79` |
| DOM `undefined\|NaN\|null` | 0건(4경로) | 0건(4경로) |
| tsc / lint / node --test | `tsc -b` 종료 0 · oxlint 무경고 · 24/24 pass | — |

AC 영향: **AC-21 FAIL 2건 해소**(`573만`·`1,263.8조`), AC-3·4·17·18은 위 계측에서 유지 확인.
AC-16 유지. 나머지 AC는 이번 변경의 영향권 밖이다.

## v3-6. 부수 확인

- v2에서 "계약 불일치"로 올렸던 **000660 `current_ratio` 17.54**는 이번 실응답에서 `2.59x`로
  정상화됐다(BE 수정 확인). 화면은 계약대로 배수 표기를 유지한다.
- `frontend/src/api.ts`(다른 세션), `format.ts`, `theme.css`, `Dashboard.tsx`, `Layout.tsx`,
  `finviz/**`는 이번 라운드에도 건드리지 않았다.
