# 계약 v2 — 구현 보고 2건에 대한 판정 (2026-08-21)

- 대상: `30_backend_report.md` §5 "계약 수정 요청" 7건, `30_frontend_report.md` §5 "계약 해석 메모" 3건
  (+ 두 보고서가 스스로 밝힌 계약 외 결정 6건)
- 기준 계약: `20_spec.md` v1 §4.3 / §5 / §6
- **v2 변경 사유**: 데이터 소스의 실제 한계(항상 null인 칸, 정의가 다른 지표)와 AC-4가 요구하는
  칸이 84칸 안에 없던 설계 누락을 반영한다. **기존 필드 삭제·개명은 없다. 전부 추가 또는 라벨 변경.**
- 검수 제외(브리프 15:35): `Dashboard.tsx`, `Layout.tsx`, `SentimentGauge.tsx`, `theme.css`,
  `frontend/src/finviz/**`, `backend/app/market*.py`, `tests/test_market.py`, `/` 화면.
  두 보고서가 언급한 콘솔 에러·테스트 실패는 전부 이 범위이므로 **판정·검수 대상 아님**.

---

## 0. 판정 요약

| # | 출처 | 항목 | 판정 |
|---|---|---|---|
| 1 | BE | `snapshot.dividend_yield_pct` 추가 | **승인**(계약 정식 필드) + FE 소스 우선순위 지시 |
| 2 | BE | `eps_yoy_ttm_pct` 정의 축소 → FE 라벨 변경 | **승인**(라벨만 변경, 필드명 유지) |
| 3 | BE | `refresh_all`의 `force_company`를 호출자가 결정 | **승인** |
| 4 | BE | `company_cache`에 내부 블록 `perf10y` 1행 | **승인** + `perf.y5` 수정 지시 |
| 5 | BE | KR `quick_ratio`/`debt_eq`는 네이버 우선 | **조건부 승인** — 단위는 계약대로 **배수**(÷100) |
| 6 | BE | 항상 null인 4칸 | **분할 판정**: `earnings_timing` 승인 / `sales_surprise_pct` 승인+칸 축소 / `inst_trans_pct` 승인 / `perf.y5` **거부(수정안)** |
| 7 | BE | OpenDART 경로 실호출 미검증 | **승인**(2차 범위) — 이번 검수 대상에서 제외, 보류 목록으로 |
| a | FE | 배당수익률을 `최근 배당` 칸 보조값으로 표시 | **승인**(위치) + **수정**(소스) |
| b | FE | perf는 `snapshot.perf` 우선·candles 폴백 | **승인**(무수정) |
| c | FE | `profile`에 `status`가 없어 pending 문구를 FE가 생성 | **수정안** — BE가 `profile.status`/`note` 추가 |
| +1 | BE | `snapshot.note`(pending 문구) 추가 | **승인** |
| +2 | BE | `service.get_company` 패스스루 3줄 | **승인**(`api.py`에 로직 금지 관례 준수) |
| +3 | BE | `changes[].action` 축약코드→계약 표기 매핑 | **승인** |
| +4 | BE | `changes[].from_target == 0.0` → null | **승인** |
| +5 | BE | EPS·매출·주식수가 전부 빈 기간 제외 | **승인** |
| +6 | FE | 분석 화면에 등급 배지 2줄 추가 / `3.34T` 축약 / `7.3억` 소수 1자리 | **전부 승인** |

---

## 1. BE 요청 판정

### BE-1 `snapshot.dividend_yield_pct` — 승인 (계약 v2 정식 필드)

AC-4가 요구하는데 84칸에 없던 것은 **내 설계 누락**이다(finviz는 `Dividend TTM 1.02 (0.44%)`처럼
금액 칸 안에 수익률을 괄호로 넣는데, §4.3을 라벨 단위로만 옮기면서 괄호값이 빠졌다).

| 필드 | 타입 | null | 단위 | 신규/기존 |
|---|---|---|---|---|
| `snapshot.dividend_yield_pct` | number\|null | O | %(0.17 = 0.17%) | **신규(v2)** |

- **84칸 구조는 바꾸지 않는다.** 열1-9 `최근 배당(주당)` 칸의 보조값(`snap-value small`)으로 표시한다 — FE-a의 위치 결정을 그대로 채택.
- **소스는 `snapshot.dividend_yield_pct`가 1순위**, `fundamentals.dividend_yield`는 폴백. 이유:
  후자는 `fetch_fundamentals`(yfinance 단독)에서 오고 §5.1의 퍼센트 정규화·스케일 가드를 거치지
  않는다. KR은 yfinance 배당수익률이 비거나 스케일이 다른 사례가 있고, 실제 값은 네이버
  `dividendYieldRatio`(000660 = `0.17%`, 2026-08-21 직접 확인)에서 온다.
- AC-4의 "배당수익률" 항목은 유효하다 — **판정 기준을 "000660 최근 배당 칸에 `0.17%` 보조값이 보인다"로 구체화**한다.

### BE-2 `eps_yoy_ttm_pct` 정의 축소 — 승인 (라벨만 변경)

TTM 대 TTM에 분기 8개가 필요한데 소스가 5~6분기만 준다는 것은 사실이다. **값을 버리는 것보다
라벨을 정직하게 바꾸는 쪽이 맞다** — "TTM"이라 써 놓고 분기 비교를 보여주면 화면이 단위를 속인다.

| 항목 | v1 | v2 |
|---|---|---|
| 필드명 | `eps_yoy_ttm_pct`, `sales_yoy_ttm_pct` | **유지**(계약 필드 개명 금지) |
| 화면 라벨 | EPS 전년동기 / 매출 전년동기 | **EPS 전년동기(분기)** / **매출 전년동기(분기)** |
| 툴팁(`title`) | — | "최근 분기와 전년 동기 분기의 비교입니다 (TTM 합산이 아님)" |

필드명과 의미가 어긋난 채로 남으므로, BE는 함수 docstring에 정의를 남긴다(이미 했다고 보고됨).

### BE-3 `force_company`를 호출자가 결정 — 승인

`/broker/sync`가 새 편입 종목마다 `refresh_all(conn, symbol)`을 부른다는 지적이 맞다. `refresh_all`
안에서 무조건 강제하면 편입 종목 수 × 6콜을 동기로 물어 CODEF 동기화가 수십 초로 늘어난다.
`api.py`의 1줄(`force_company=symbol is not None`)은 §8.1이 정한 "라우트 1개" 범위를 넘지만,
**대안이 다른 화면(증권사 연동)을 느리게 만드는 것뿐이므로 승인**한다.

- 계약: `POST /api/refresh?symbol=X` → 그 종목 6블록 TTL 무시 강제 갱신(§6.3 그대로).
- 계약: `POST /api/refresh`(전체) → `force_company=False`. TTL·8종목 상한만 따른다.

### BE-4 `company_cache` 내부 블록 `perf10y` — 승인

TTL이 7일 vs 12시간으로 다르니 분리가 맞다. **화면 응답에 나가지 않는 내부 캐시**라 계약 변경이
아니다. `20_spec.md` §6.1의 블록 열거를 `profile|snapshot|financials|news|ratings|insiders|perf10y`로
갱신한다(종목당 7행).

### BE-5 KR `quick_ratio`/`debt_eq` 네이버 우선 — 조건부 승인

정의 근거(yfinance `debtToEquity`는 차입금 기준, 국내 공시 부채비율은 총부채/자본)는 타당하다.
화면 라벨이 "부채비율"인 이상 국내 기준을 쓰는 게 맞다. **단 조건이 하나 있다.**

- **단위는 계약(§4.3 열2-10·12)대로 `배수`다.** 네이버가 주는 `%`(45.95)는 반드시 ÷100(=0.4595)해서
  내보낸다. US는 `0.55`, KR은 `45.95`가 되는 상태가 남으면 **같은 이름·다른 단위**로, 이 프로젝트에서
  실제로 화면을 깨뜨려 온 버그 유형이다.
- 보고서 §5-7의 "000660 실측 7.08 vs 45.95"는 두 값 모두 어느 단위인지 판별할 수 없다 →
  **Phase 4에서 AAPL·000660의 `debt_eq`·`quick_ratio`를 나란히 놓고 실측 대조한다**(§5 검증 항목 V1).

### BE-6 항상 null인 칸 — 분할 판정

| 칸 | 판정 | 조치 |
|---|---|---|
| `earnings_timing` (US도 null) | **승인** | FE는 `실적발표일` 칸에 날짜만 표시. timing이 오면 뒤에 덧붙인다 |
| `sales_surprise_pct` | **승인 + 칸 축소** | 두 값 칸(`EPS/Sales Surpr.`)에서 절반이 영구히 `—`면 finviz 형식만 흉내 낸 빈 칸이다. 라벨을 **`EPS 서프라이즈`** 단일 값으로 바꾸고 매출 서프라이즈는 표시하지 않는다. 필드는 계약에 남겨 둔다(소스가 생기면 되살린다) |
| `inst_trans_pct` | **승인, 대체 없음** | 기관 지분 '변동'에 1콜 추가는 §6.2 콜 예산 밖이다. US에서 이 칸은 `—`로 남고, AAPL null 8칸은 AC-3 상한(12칸) 안이다. FE의 "값 유무로 라벨 선택"(KR=외국인 지분 51.05 / US=기관 거래 `—`)을 그대로 유지 |
| `perf.y5` | **거부 — 수정안** | `perf10y` 월봉 캐시가 이미 있으므로 **5년 수익률은 추가 호출 0으로 계산된다**. `y3=79.43`·`y10=1104.12`인데 `y5`만 `—`인 화면은 데이터 한계가 아니라 구현 누락으로 보인다. 월봉으로 채운다. 월봉이 5년을 못 덮는 신규 상장 종목만 null |

### BE-7 OpenDART(2차) 실호출 미검증 — 승인, 검수 제외

`.env`에 키가 없는 것은 사실이고, 2차 범위는 원래 "키가 있을 때만"이다.

- **Phase 4 판정 대상에서 제외**한다. 대신 **키 없는 경로만 PASS 조건**: `available()==False`일 때
  KR `insiders.status=="unavailable"` + `note` 비어있지 않음 + `financials.shares_note` 노출(AC-6로 이미 커버).
- `elestock` 응답 필드명 실측 맞춤은 `20_spec.md` §3 보류 목록에 **"DART 2차 경로 실호출 검증"**
  으로 이관한다. 키 등록 시점에 별도 라운드.

### BE 추가 결정 (요청 목록 밖, 보고서에서 확인)

| 항목 | 판정 | 근거 |
|---|---|---|
| `snapshot.note`(pending 문구) | **승인 · 계약 v2 필드** | 4블록 래퍼(`note`)와 같은 방식. 사용자 문구를 BE 한 곳에서 관리하는 원칙에 부합. `status=="ok"`면 null |
| `service.get_company` 패스스루 | **승인** | `api.py`에 비즈니스 로직 금지 관례가 우선. §8.1의 "호출 1곳 + 2필드" 제한보다 코드베이스 관례가 상위 |
| `changes[].action` 축약코드(`up/down/main/reit/init`) 매핑 | **승인** | 계약 표기를 지키는 방향. 매핑 실패값은 `기타` |
| `changes[].from_target == 0.0` → null | **승인** | 0달러 목표가는 사실이 아니다. §5.1 "null은 null로" 준수 |
| EPS·매출·주식수 전부 빈 기간 제외(AAPL annual 5→4) | **승인** | 빈 막대는 정보가 아니다. AC-7(≥4) 충족 |
| KR `financials` 억원→원 변환 | **승인** | §5.1 "종목 통화 원단위" 준수 |
| `recommendation_mean` 뒤집기(네이버 5=강력매수) | **승인 · 검증 완료** | 내가 2026-08-21 직접 확인: `consensusInfo = {"recommMean":"4.00","priceTargetMean":"3,317,917"}`, 같은 날 yfinance 1.33. 목표주가도 네이버 `52주 최고 3,002,000`과 같은 자릿수라 **원 단위 파싱 정상**이다(상방 +96%는 이 데이터셋의 실제 값) |

---

## 2. FE 해석 판정

### FE-a 배당수익률을 `최근 배당` 칸 보조값으로 — 승인(위치) + 수정(소스)

- 위치: **승인.** finviz의 `Dividend TTM 1.02 (0.44%)`와 같은 형태이고 84칸을 흔들지 않는다.
- 소스: **수정.** `fundamentals.dividend_yield` 단독 사용을 금지한다. BE-1 참조 —
  `snapshot.dividend_yield_pct ?? fundamentals?.dividend_yield ?? null`.

### FE-b `snapshot.perf` 우선 · candles 폴백 — 승인 (무수정)

두 값의 정의가 같다(종가 기준 수익률). BE 값이 이긴다는 우선순위도 계약과 일치한다. 캐시가
아직 없는 종목에서 1주~연초대비가 이유 없이 비지 않는 것은 §6.3 "pending에서도 화면이 깨지지
않는다"에 부합한다.

- 단 하나 확인: **연초대비(YTD) 기준일**이 BE(작년 마지막 종가)와 FE(`perfYtdPct`: 작년 마지막
  종가, 없으면 올해 첫 봉)에서 같아야 한다. 폴백과 본값이 다른 숫자를 내면 새로고침 전후로 값이
  튄다 → Phase 4 검증 항목 V2.

### FE-c `profile`에 `status`가 없다 — 수정안 (BE가 필드 추가)

FE 지적이 맞다. §5.2에서 `snapshot`에만 `status`를 두고 `profile`에 빠뜨렸다. 사용자 문구가
BE(4블록+snapshot)와 FE(회사 설명)로 갈라지면, 나중에 문구를 고칠 때 한 곳을 빠뜨린다.

| 필드 | 타입 | null | 신규/기존 |
|---|---|---|---|
| `profile.status` | `"ok"`\|`"pending"` | X | **신규(v2)** |
| `profile.note` | string\|null | O | **신규(v2)** — `pending`이면 필수, `ok`면 null |

FE는 `profile.note`가 오면 그것을 쓰고, 없으면 현행 문구로 폴백한다(구버전 백엔드 호환).

### FE 추가 결정 — 전부 승인

| 항목 | 판정 | 근거 |
|---|---|---|
| 분석 화면에 스윙/중장기 등급 배지 2줄 추가 | **승인** | 개요 스냅샷에서 MyStock 22칸을 빼면서 등급 배지를 볼 곳이 사라졌다. §7 "삭제가 아니라 이동" 취지 안 |
| `abbrNum`이 `3.34T`(조 달러) 사용 | **승인 · AC-21 해석 확장** | finviz도 `T`를 쓴다. `4543.17B`보다 정확히 읽힌다. AC-21 판정 문구에 `T` 허용을 명시 |
| KRW 100억 미만 소수 1자리(`7.3억`) | **승인** | 정수 절단이 발행주식수의 자릿수를 지운다는 근거가 타당. **원 단위 소수점 금지 규칙은 그대로**(≥100억은 `4,560억` 정수) |
| 개요 탭 구성(애널리스트 탭 없음, 마지막 `분석` 링크) | **승인** | finviz도 뉴스/애널리스트가 같은 행 |
| 재무 3번째 막대가 전부 null이면 `shares_note` 출력 | **승인** | §4.2 KR 1차 빈 상태 규칙 그대로 |

---

## 3. 계약 v2 변경분 (추가 필드 4개 · 라벨 3건)

**추가 필드** — 전부 신규, 삭제·개명 0:

| 필드 | 타입 | null | 단위 | 소유 |
|---|---|---|---|---|
| `snapshot.dividend_yield_pct` | number\|null | O | %(0.17) | BE |
| `snapshot.note` | string\|null | O | — | BE |
| `profile.status` | `"ok"`\|`"pending"` | X | — | BE |
| `profile.note` | string\|null | O | — | BE |

**라벨 변경** (FE, 계약 필드 불변):

| 필드 | v1 라벨 | v2 라벨 |
|---|---|---|
| `eps_yoy_ttm_pct` | EPS 전년동기 | EPS 전년동기(분기) |
| `sales_yoy_ttm_pct` | 매출 전년동기 | 매출 전년동기(분기) |
| `eps_surprise_pct`(+`sales_surprise_pct`) | 서프라이즈(EPS/매출) | EPS 서프라이즈 (단일 값) |

**단위 재확인**: `debt_eq`·`quick_ratio`는 **배수**(US·KR 동일). `*_pct`는 전부 퍼센트 숫자.

---

## 4. BE 수정 지시

> 담당: `backend-engineer`. 범위 `backend/` 만.

**B1. `profile`에 `status`·`note` 추가** (FE-c)
`snapshot`과 동일 규칙. 캐시가 없으면 `status:"pending"` + `note:"회사 자료를 아직 받지 못했습니다 —
새로고침을 누르면 지금 가져옵니다."`, 있으면 `status:"ok"` + `note:null`.
검증: `curl -s .../api/tickers/{새종목} | jq '.profile.status, .profile.note'`.

**B2. `snapshot.perf.y5`를 `perf10y` 월봉 캐시로 채운다** (BE-6)
추가 외부 호출 0. 월봉 시리즈가 5년을 못 덮는 종목만 null. `y3`·`y10`이 있는데 `y5`만 `—`인
상태를 없앤다. 단위 테스트에 "월봉 60개월 시리즈에서 y5가 계산된다" 케이스 추가.
검증: `curl -s .../api/tickers/AAPL | jq '.snapshot.perf.y5'` → 숫자.

**B3. `debt_eq`·`quick_ratio` 단위를 배수로 통일** (BE-5)
네이버 `%`값은 ÷100. AAPL과 000660의 두 값을 나란히 출력해 자릿수 체계가 같은지 **직접 확인해
보고**한다. 단위 테스트 `test_kr_debt_eq_is_ratio_not_percent`(네이버 45.95 입력 → 0.4595 출력) 추가.
검증: `curl -s .../api/tickers/{AAPL,000660} | jq '{debt_eq:.snapshot.debt_eq, quick:.snapshot.quick_ratio}'`.

**B4. `snapshot.dividend_yield_pct`를 계약 v2 정식 필드로 유지** (BE-1)
구현 변경 없음. 0~30 범위 스케일 가드 테스트를 이 필드에도 적용했는지 확인만 하고 보고에 한 줄 남긴다.

**B5. 없음** — BE-2·3·4·7 및 추가 결정 6건은 현 구현 그대로 승인이다. `eps_yoy_ttm_pct` 필드명은
바꾸지 않는다(라벨은 FE 몫).

---

## 5. FE 수정 지시

> 담당: `frontend-engineer`. 범위 `frontend/` 만. 검수 제외 파일(대시보드·Layout·finviz·theme.css)은 **건드리지 않는다**.

**F1. 배당수익률 소스 교체** (FE-a)
`최근 배당(주당)` 칸의 보조값을
`snapshot?.dividend_yield_pct ?? detail.fundamentals?.dividend_yield ?? null` 순서로 읽는다.
검증: 000660에서 `0.17%`가 보인다(네이버 `dividendYieldRatio` 실측값).

**F2. 라벨 2건 변경 + 툴팁** (BE-2)
`EPS 전년동기` → `EPS 전년동기(분기)`, `매출 전년동기` → `매출 전년동기(분기)`.
두 칸의 `title`에 "최근 분기와 전년 동기 분기의 비교입니다 (TTM 합산이 아님)".

**F3. 서프라이즈 칸 축소** (BE-6)
`서프라이즈(EPS/매출)` 두 값 칸 → `EPS 서프라이즈` 단일 값. `sales_surprise_pct`는 렌더하지 않는다
(타입에는 남긴다). 84칸 총수는 그대로.

**F4. 실적발표일 칸** — `earnings_timing`이 null이면 날짜만 표시. `"null"`/`"undefined"` 문자열이
붙지 않는지 000660·AAPL 양쪽에서 확인.

**F5. 회사 설명 pending 문구를 BE `note`로** (FE-c)
`profile.status === 'pending'`이면 `profile.note`를 그대로 렌더, `note`가 없으면 현행 FE 문구 폴백
(구버전 백엔드 호환). `BlockEmpty`를 재사용한다.

**F6. 단위 라벨 확인** — `부채비율`·`당좌비율` 칸이 배수 표기임을 라벨 또는 툴팁에서 알 수 있게 한다
(`0.46` 옆에 아무 단위가 없으면 사용자가 46%로도, 0.46%로도 읽는다).

**F7. 목(mock) 제거 상태에서 실백엔드 재계측** — AC-3·4·6·7·8·19를 8722(빌드본) 재시작 후 실데이터로
다시 측정해 보고한다. 현재 보고의 "PASS(목)"은 Phase 4에서 인정하지 않는다.

---

## 6. Phase 4로 넘기는 검증 항목 (판정이 아니라 계측)

| # | 항목 | 방법 |
|---|---|---|
| V1 | `debt_eq`·`quick_ratio`가 US/KR에서 같은 단위(배수)인가 | AAPL·000660 `jq` 나란히 대조 |
| V2 | `perf.ytd`의 BE 값과 FE 폴백 값이 같은 기준일을 쓰는가 | 캐시 있는 종목에서 BE 값, `snapshot`을 지운 상태에서 FE 폴백 값 비교 |
| V3 | 84칸 라벨·순서가 `20_spec.md` §4.3과 완전히 일치하는가 | DOM `.snap-label` 84개 텍스트를 스펙 표와 대조 |
| V4 | 실응답 키 ↔ `types.ts` 인터페이스 교차표 | `curl \| jq 'paths'` vs `types.ts` — 이름 같고 타입 다른 필드(`"12.5"` vs `12.5`), BE가 null 주는데 FE가 non-null 선언한 필드 |
| V5 | `refresh_all`(전체)의 8종목 상한 | 실서버 미검증(CODEF 한도) → **"실행 미검증"으로 표기**하고 단위 테스트 결과로 판정 |
| V6 | 8722 빌드본이 신규 필드를 실제로 서빙하는가 | 리더가 재시작한 뒤 `curl` — 재시작 전 계측은 무효 |
