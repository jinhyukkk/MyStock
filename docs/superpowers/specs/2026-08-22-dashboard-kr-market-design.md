# 대시보드 한국 증시 기준 전환 설계 (KR 기본 + US 토글)

작성일: 2026-08-22

## 배경

대시보드(`/`)는 finviz 홈 배치를 따라 만들었고(`638ecce`), 데이터는 전부 미국 시장이다.

```python
# market.py
INDICES = [("S&P 500", "^GSPC"), ("NASDAQ", "^IXIC"), ("DOW", "^DJI")]
HEATMAP_SECTORS = {"TECHNOLOGY": [("NVDA", 48), ...], ...}
```

```tsx
// Dashboard.tsx / IndexChart.tsx
const tone = ups === indices.length ? 'US stocks rose' : ...
const TIMES = ['10AM', '11AM', '12PM', '1PM', '2PM', '3PM', '4PM']
<span>US Large Caps - 1 Day Performance</span>
```

이 앱의 보유·관심 종목은 국내가 중심이다(`tickers.market = KRX`, 6자리 코드). 시장을 먼저
보고 내 종목을 보자는 대시보드의 취지대로라면 먼저 보여야 하는 시장은 한국이다.

## 목표

1. 대시보드 기본 시장을 한국(KOSPI·KOSDAQ)으로 한다.
2. 미국 시장은 토글로 남긴다. 기존 US 블록·코드는 그대로 살아 있어야 한다.
3. 한국 시장에서만 의미 있는 **투자자별 수급(개인·외국인·기관)** 블록을 추가한다.
4. 시장별 데이터는 따로 캐시한다. 한쪽을 보는 동안 다른 쪽 외부 호출이 일어나지 않는다.

**목표가 아닌 것**

- 한글 시장 헤드라인. 네이버 모바일 API에 시장 단위 뉴스 경로를 찾지 못했다(아래 소스 표).
  v1은 야후 `^KS11` 뉴스(영문, 아시아 시황)로 가고 한글 소스는 별도 작업.
- KOSDAQ 히트맵, 업종별 등락 표.
- 샘플 섹션(Breadth·차트패턴·경제/실적 캘린더·인사이더)의 실데이터화. 양쪽 모드 모두 샘플 유지.
- `market_fetch.py`를 `sources/yf.py`로 옮기는 정리. 별도 작업으로 끊는다.

## 확인된 한국 데이터 소스 (2026-08-22 실측)

| 블록 | 소스 | 비고 |
|---|---|---|
| 지수 5분봉 | yfinance `^KS11` `^KQ11` `^KS200` | tz `Asia/Seoul`, 09:00–15:30, 2일치 144봉. 기존 `market_fetch.intraday` 재사용 |
| 지수 현재가·전일비 | 네이버 `GET m.stock.naver.com/api/index/{KOSPI,KOSDAQ,KPI200}/basic` | `closePrice:"6,912.95"` 등 **문자열** |
| 상승/하락/검색상위/시총상위 | 네이버 `GET /api/stocks/{up,down,searchTop,marketValue}/{KOSPI,KOSDAQ}?page=1&pageSize=N` | `itemCode`(6자리), `stockName`, `closePrice`, `fluctuationsRatio`, `accumulatedTradingVolume`, `marketValue`(억원) |
| 투자자 수급 | 네이버 `GET /api/index/{KOSPI,KOSDAQ}/trend` | `{"bizdate":"20260821","personalValue":"-11,652","foreignValue":"-1,760","institutionalValue":"+2,481"}` 억원 |
| 환율·국채 | 네이버 `GET m.stock.naver.com/front-api/marketIndex/productDetail?category={exchange,bond}&reutersCode={FX_USDKRW,KR3YT=RR,KR10YT=RR}` | `{"isSuccess":true,"result":{...}}`. 국내 국채는 야후에 없다 |
| 환율 보조 | yfinance `KRW=X`, `JPY=X`, `^TNX` | `market_fetch.daily_closes` 재사용 |
| 히트맵 | 네이버 `GET /api/stocks/marketValue/KOSPI?page=1&pageSize=100` **1회** | 시총(가중치)·등락률이 한 응답에. 섹터는 상수 매핑 |
| 헤드라인 | yfinance `Ticker("^KS11").news` | 10건, 영문 |

**쓰지 않기로 한 것**

- 네이버 `/api/stocks/industry`(업종 ~80개 목록)와 `/api/stocks/industry/{no}`(업종 내 종목):
  동작은 하지만 finviz식 섹터 11개로 묶으려면 업종마다 호출해야 해서 80회가 된다.
- 다음(Daum) `api/sectors`, `api/market_index/investors`: 500 응답.
- FinanceDataReader `KRX-DESC`의 `Sector` 열: 값이 "중견기업부/우량기업부" 같은 소속부라
  산업 섹터가 아니다. `KRX`의 `Marcap`은 쓸 수 있지만 네이버 `marketValue`가 같은 호출에
  같이 오므로 필요 없다.

네이버 모바일 API는 **비공식**이다(`sources/naver.py` 머리말과 같은 주의). 브라우저 UA 필수,
스키마 변경·차단 가능. 그래서 블록 격리와 백오프를 기존대로 타고, 실호출 smoke 테스트를 둔다.

## 백엔드

### 모듈 배치

```
backend/app/
  market.py         캐시·TTL·실패 격리·stale-while-revalidate 엔진. 시장을 모른다.
  market_us.py      지금 market.py 에 있는 US 상수·빌더를 그대로 옮긴다 (동작 불변)
  market_kr.py      KR 상수·빌더 (신규)
  market_fetch.py   변경 없음 (yfinance 래퍼)
  sources/naver.py  시장 단위 함수 추가 (아래)
  market_api.py     ?market= 파라미터
```

`market.py`가 245줄에서 상수가 절반이다. 시장이 둘이 되면 상수가 두 배가 되므로 시장별
파일로 나누고, `market.py`에는 엔진만 남긴다.

### `market.py` 엔진 변경

```python
MARKETS = {"US": market_us, "KR": market_kr}   # 각 모듈은 BUILDERS, TTL_SEC, SESSION 을 가진다

def get_market(market: str, now=None) -> dict
def refresh(market: str, force=False, now=None) -> None
```

- 캐시 키를 `"KR:indices"`처럼 `f"{market}:{block}"`으로. `_Cache` 구조는 그대로, 키만 바뀐다.
- `get_market(market)`은 **그 시장의 블록만** 본다. 첫 방문 동기 채움·백그라운드 갱신·백오프
  전부 시장 단위. US를 아무도 안 보면 야후 100종목 일괄 다운로드는 일어나지 않는다.
- `_refreshing` 플래그도 시장별(`refreshing: set[str]`).
- `major_news_from_heatmap`은 시장 무관하므로 엔진에 남긴다.

### `market_kr.py`

```python
SESSION = {"tz": "Asia/Seoul", "open": "09:00", "close": "15:30"}
INDICES = [("코스피", "^KS11", "KOSPI"), ("코스닥", "^KQ11", "KOSDAQ"), ("코스피 200", "^KS200", "KPI200")]
#           표시명      yfinance(5분봉)   네이버 코드(현재가·전일비)
FOREX_BONDS = [("USD/KRW", "exchange", "FX_USDKRW", 2), ("JPY(100)/KRW", "exchange", "FX_JPYKRW", 2),
               ("국채 3년", "bond", "KR3YT=RR", 3), ("국채 10년", "bond", "KR10YT=RR", 3),
               ("미국채 10년", "yf", "^TNX", 3)]
SIGNALS_UP = [("up", "KOSPI", "상승 상위", 6), ("up", "KOSDAQ", "코스닥 상승", 5),
              ("searchTop", "KOSPI", "검색 상위", 4), ("marketValue", "KOSPI", "시총 상위", 4)]
SIGNALS_DOWN = [("down", "KOSPI", "하락 상위", 6), ("down", "KOSDAQ", "코스닥 하락", 5), ...]
HEATMAP_COUNT = 100
SECTOR_OF: dict[str, str] = {"005930": "반도체", "000660": "반도체", "005380": "자동차", ...}
SECTOR_FALLBACK = "기타"
INVESTOR_MARKETS = ["KOSPI", "KOSDAQ"]
HEADLINES_SYMBOL = "^KS11"
```

빌더:

| 블록 | 동작 |
|---|---|
| `indices` | 지수마다 `market_fetch.intraday(yf)`로 캔들, `naver.index_basic(code)`로 `last`·`prev_close`. 네이버가 죽으면 캔들에서 계산(기존 US 방식) |
| `futures` | `[]` 고정 — 소스 없음. 빌더 자체를 두지 않는다 |
| `forex_bonds` | `exchange`/`bond`는 `naver.market_index(category, code)`, `yf`는 `market_fetch.daily_closes` |
| `signals_up/down` | `naver.ranking(kind, market, n)` → `{symbol, name, last, change_pct, volume, signal}` |
| `heatmap` | `naver.ranking("marketValue", "KOSPI", 100)` → ETF·우선주 제외 → `SECTOR_OF.get(code, "기타")`로 묶음. `weight = market_value`(억원). 섹터 순서는 섹터 내 시총 합 내림차순 |
| `investors` | `naver.investor_trend(m)` × `INVESTOR_MARKETS` → `{market, date, personal, foreign, institution}` |
| `headlines` | `market_fetch.news("^KS11", 8)` |

**히트맵에서 걸러내는 것 (실측 2026-08-22로 추가).** 네이버 시총 상위 100에는 ETF 11개
(KODEX 200, TIGER 미국S&P500, KODEX 머니마켓액티브 …)와 우선주 2개(삼성전자우, 현대차2우B)가
섞여 있다. ETF는 회사가 아니고 우선주는 보통주와 같은 회사라 큰 칸이 중복된다.

- ETF: 응답의 `stockEndType == "etf"` — 같은 응답에 있는 값이라 추가 호출이 없다.
- 우선주: **종목코드가 `0`으로 끝나지 않고** 이름이 `우` 또는 `우[A-Z]`로 끝나는 것.
  두 조건을 모두 요구하는 이유는 이름만 보면 `미래에셋대우`(006800, 보통주) 같은 회사가
  걸리기 때문이다. 실측에서 이 규칙은 005935·005387만 걸렀고 006800은 남겼다.

`pageSize=100`을 받아 걸러내면 87종목이 남는다(실측). `pageSize=120`은 응답이 JSON이
아니므로 100이 상한이다. 히트맵에는 87칸이면 충분하고, 개수를 늘리려고 페이지를 더 받지 않는다.

`SECTOR_OF` 수기 매핑에 대하여: US판도 구성종목·비중을 상수로 들고 있다. KR판은 구성과
가중치는 네이버 실시간이고 **섹터 이름만** 상수라 유지 부담이 더 작다. 시총 상위 100개 중
매핑이 없는 종목은 "기타"로 떨어지므로 화면이 깨지지 않고, 그 칸이 커지면 매핑을 보탤 때다.
섹터 분류(예시): 반도체 / 자동차 / 2차전지 / 금융 / 바이오·제약 / 인터넷·플랫폼 / 조선·기계·방산 /
화학·소재·철강 / 유통·소비재 / 통신·유틸리티 / 건설·운송 / 기타.

### `market_us.py`

`market.py`의 `INDICES`~`HEADLINES_COUNT` 상수와 `_build_*` 함수를 그대로 옮긴다.
`SESSION = {"tz": "America/New_York", "open": "09:30", "close": "16:00"}` 추가. `investors` 빌더 없음.

### `sources/naver.py` 추가 함수

모두 **숫자로 변환해서** 돌려준다. `"281,500"` → `281500.0`, `"+2,481"` → `2481.0`,
`"N/A"` → `None`. 변환은 `_num()` 하나에 모은다.

```python
def index_basic(code: str) -> dict          # {last, prev_close, change, change_pct, traded_at}
def ranking(kind: str, market: str, n: int) -> list[dict]
    # kind: up|down|searchTop|marketValue, market: KOSPI|KOSDAQ
    # → [{symbol, name, last, change_pct, volume, market_value, is_etf}]  (market_value 억원)
def investor_trend(market: str) -> dict     # {date: "2026-08-21", personal, foreign, institution}  (억원)
def market_index(category: str, code: str) -> dict   # {last, prev_close, change, change_pct}
```

`market_index` 응답은 `result` 아래 `closePrice`·`fluctuations`·`fluctuationsRatio`(모두 문자열,
실측 2026-08-22: USD `"1,388.00"`/`"-6.80"`/`"-0.49"`, 국채 3년 `"3.8530"`/`"0.0310"`/`"0.81"`).
`prev_close = last - change`로 계산한다. 환율은 `localTradedAt`이 당일 고시 시각(장 밖에서도
갱신), 국채는 전일 마감이다 — `traded_at`도 같이 돌려 화면이 기준 시각을 보일 수 있게 한다.
JPY는 `FX_JPYKRW`가 100엔 기준(`fullName: "일본 JPY 100"`).

### API 계약 (`market_api.py`)

```
GET  /api/market?market=KR|US          기본 KR
POST /api/market/refresh?market=KR|US  기본 KR
```

`market`이 `MARKETS`에 없으면 `400 {"detail": "unknown market"}`.

응답은 기존 필드를 유지하고 **추가만** 한다.

```jsonc
{
  "market": "KR",
  "session": { "tz": "Asia/Seoul", "open": "09:00", "close": "15:30" },
  "indices": [{ "name": "코스피", "symbol": "^KS11", "last": 6912.95, "prev_close": 6852.58,
                "change": 60.37, "change_pct": 0.88, "candles": [...] }],
  "futures": [],
  "forex_bonds": [{ "name": "USD/KRW", "symbol": "FX_USDKRW", "last": 1390.8, "change": -6.9,
                    "change_pct": -0.49, "decimals": 2 }],
  "signals_up": [{ "symbol": "005930", "name": "삼성전자", "last": 281500, "change_pct": 3.87,
                   "volume": 27672192, "signal": "시총 상위" }],
  "signals_down": [...],
  "heatmap": [{ "name": "반도체", "tickers": [
                 { "symbol": "005930", "name": "삼성전자", "weight": 16457274, "change_pct": 3.87 }] }],
  "major_news": [{ "symbol": "005930", "name": "삼성전자", "change_pct": 3.87 }],
  "headlines": [...],
  "investors": [
    { "market": "KOSPI",  "date": "2026-08-21", "personal": -11652, "foreign": -1760, "institution": 2481 },
    { "market": "KOSDAQ", "date": "2026-08-21", "personal": 6236,   "foreign": -2837, "institution": -3462 }
  ],
  "fetched_at": "2026-08-22T15:01:00",
  "failed": []
}
```

- `name`은 `signals_*`·`heatmap.tickers`·`major_news`에 **추가** 필드. US는 `null`.
- `investors`는 US에서 `[]`. `session`·`market`은 양쪽 모두.
- KR `symbol`은 6자리 코드 = 앱 내부 심볼(`tickers.symbol`). `/ticker/005930` 링크가 바로 맞는다.
  지수·환율의 `symbol`은 소스 코드(`^KS11`, `FX_USDKRW`)이고 링크 대상이 아니다.
- 수급 단위는 억원 부호 있는 정수. 프론트가 `+2,481억`으로 찍는다.

## 프론트

### 상태

- `localStorage["dashboard.market"]` ∈ `"KR" | "US"`, 없으면 `"KR"`.
- `Dashboard.tsx`: `get('/api/market?market=' + market)`. 시장 전환 시 `data`를 비우지 않고
  `busy`만 켠다 — 백엔드 캐시가 있으면 즉시 오고, 없으면 스켈레톤 대신 이전 시장 화면 위에
  "갱신 중…"이 뜬다. 응답의 `market`이 현재 선택과 다르면 버린다(빠르게 두 번 토글했을 때).
- 포커스 복귀 재로드·30초 틱은 그대로.

### 컴포넌트

| 변경 | 내용 |
|---|---|
| `MarketSummary` | 좌측에 `KR │ US` 토글 버튼 두 개. 요약 문장은 `market`으로 분기: `국내 증시 상승 — 코스피 +0.88% · 코스닥 −0.40% · 코스피 200 +1.02%` / 기존 영문 |
| `IndexChart` | `TIMES` 상수 제거. `session.open~close` 사이 정시를 라벨로 생성(KR `10 11 12 13 14 15`, US `10AM…4PM`). `fmtTick`은 지수 크기에 따라 이미 분기 |
| `SignalTable` | 첫 열: `name`이 있으면 이름을 쓰고 `symbol`은 `title`로. 가격 소수점: `market === 'KR' ? 0 : 2` |
| `Heatmap` | 칸 라벨 `name ?? symbol`. 섹터 제목은 데이터의 `name` 그대로 |
| 히트맵 패널 제목 | `KOSPI 대형주 – 1일 등락` / `US Large Caps - 1 Day Performance` |
| `MajorNews` | `name ?? symbol` |
| `QuoteTable` | `futures`가 빈 배열이면 Futures 패널을 그리지 않는다. KR 표 제목 `환율 & 금리` |
| **`InvestorFlows` (신규)** | 지수 차트 줄 바로 아래 한 줄. KOSPI·KOSDAQ 카드 2개, 각각 개인/외국인/기관 순매수를 `+2,481억` 형식, 양수 `up`·음수 `down` 색. 우상단에 `bizdate`. `investors`가 비면(US) 줄 자체를 렌더하지 않는다 |
| `finviz/types.ts` | `name: string \| null` 추가(SignalRow, HeatTicker, MajorNewsRow). `InvestorRow`, `Session`, `MarketData.market/session/investors` 추가 |

첫 로드 안내 문구("야후 파이낸스에서 … 10초쯤")는 시장별로: KR은 "네이버·야후에서 지수와
순위를 받아오느라 몇 초 걸립니다".

### 숫자 표기

- KR 가격: 정수, 천 단위 콤마. `decimals` 필드가 이미 있으므로 `forex_bonds`는 그대로,
  시그널·히트맵은 `market`으로 분기.
- 거래량은 기존 `vol()`(M/K) 유지 — 한국도 "27.67M 주"는 읽힌다. 억/만 변환은 하지 않는다.
- 수급: `Intl.NumberFormat('ko-KR')` + `억` 접미, 부호 항상 표시.

## 실패 처리

- 블록 단위 격리·이전 값 유지·3분 백오프·`failed` 목록은 엔진이 시장 키로 그대로 수행한다.
- 네이버 한 엔드포인트가 죽으면 그 블록만 `failed`. 예: `index_basic` 실패 시 `indices`
  빌더는 캔들에서 `last`/`prev_close`를 계산해 블록을 살린다(캔들도 없으면 블록 실패).
- 수급은 장 마감 후 집계라 `bizdate`가 전일일 수 있다. 날짜를 같이 보내고 화면에 찍는다 —
  "오늘 수급"으로 읽히지 않게.
- 네이버 응답 문자열 파싱 실패(`ValueError`)는 `_num()`이 `None`으로 흡수한다. 블록 전체를
  죽이지 않는다.

## 테스트

- `tests/test_market.py`: 기존 단언을 `market="US"`로 고쳐 그대로 통과시킨다 — US 동작 불변 증명.
- `tests/test_market_kr.py` (신규): `sources.naver`·`market_fetch`를 monkeypatch.
  - 응답 형태·`name` 필드·`session`·`investors` 2행.
  - 히트맵: 매핑된 코드는 해당 섹터, 없는 코드는 "기타", `weight`가 `market_value`.
  - `index_basic` 실패 시 캔들로 폴백, 캔들도 없으면 `failed`에 `indices`.
  - 수급 부호(`"+2,481"` → `2481`, `"-11,652"` → `-11652`).
- `tests/test_market_cache.py` 또는 기존 파일에 추가: KR 갱신이 US 캐시를 건드리지 않고,
  `get_market("US")` 전에는 US 빌더가 호출되지 않는다.
- `tests/test_market_api.py`: `?market=` 기본값 KR, `XX` → 400, `refresh?market=US`.
- `tests/test_naver_market.py`: `_num()` 변환표, 각 함수의 응답 파싱(고정 JSON 픽스처).
  `@pytest.mark.smoke`로 실호출 1개씩(`index_basic("KOSPI")`, `ranking("up","KOSPI",2)`,
  `investor_trend("KOSPI")`, `market_index("exchange","FX_USDKRW")`) — 스키마 변경 감지용.
- 프론트: `tsc -b`·`oxlint` + 브라우저 실측(KR 기본 로드, US 토글, 다시 KR — 네트워크 탭에서
  `?market=` 확인, 수급 패널 부호·색, 히트맵 한글 라벨, 시간축 `10…15`).

## 구현 순서 (계획서가 쪼갤 단위)

1. `market_us.py` 추출 + `market.py` 시장 키 엔진화 — 기존 테스트가 `market="US"`로 그대로 통과
2. `sources/naver.py` 시장 함수 4개 + `_num`
3. `market_kr.py` 빌더 + `test_market_kr.py`
4. `market_api.py` `?market=` + 400
5. 프론트 타입 + `Dashboard` 토글·fetch
6. `IndexChart` 시간축·`SignalTable`/`Heatmap`/`MajorNews` 이름 표시
7. `InvestorFlows` 패널
8. 브라우저 실측
