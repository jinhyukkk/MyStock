# 미등록 종목 임시 조회(preview) 설계

작성일: 2026-08-22

## 배경

지금 종목 상세는 `tickers` 테이블에 행이 있는 종목만 열린다.

```python
# service.py:817 get_ticker_detail
t = db.get_ticker(conn, symbol)
if not t:
    return None        # → api.py:70 → 404 "ticker not found"
```

`tickers` 행을 만드는 경로는 `POST /api/watchlist`와 증권사 동기화 둘뿐이다. 결과적으로
**보유 종목 ∪ 워치리스트**만 조회할 수 있다.

프론트에는 이미 우회로가 하나 있다. `CommandPalette.tsx:63`의 `pick()`은 미등록 종목을
고르면 `POST /api/watchlist` → `POST /api/refresh?symbol=` 을 하고 나서 이동한다. 즉
**검색해서 잠깐 본 종목이 전부 워치리스트에 영구 등록된다.** 워치리스트는 "내가 지켜보기로
정한 것"이어야 하는데, "한 번 열어본 것"이 섞여 신호가 죽는다. 게다가 팔레트에서
Enter를 누르면 등록 + 갱신이 끝날 때까지 `종목 추가 중…`으로 멈춰 있다.

## 목표

1. 등록되지 않은 종목도 상세 화면을 열 수 있다.
2. 조회가 워치리스트를 오염시키지 않는다. 관심 등록은 사용자가 명시적으로 누를 때만.
3. 첫 조회의 외부 수집(수 초)이 요청 경로를 막지 않는다.

**목표가 아닌 것**

- 검색 해석기 확장. `fetchers.search_symbols`는 KRX 전종목 + Upbit + "대문자 5자 이하
  영문 티커"만 해석한다. 미국 종목을 회사 이름으로 찾거나 소문자로 치는 건 이번 범위 밖이며,
  별도 작업으로 끊는다.
- 임시 등록분의 정리(GC). 컬럼도 정리 로직도 만들지 않는다. 근거는 아래 "정리하지 않는 이유".
- 표시하는 숫자·계산 로직·대시보드(`market*.py`) 변경.

## 계약

### `GET /api/tickers/{symbol}`

| 상황 | 응답 |
|---|---|
| 등록 종목 (기존) | `200 {"status":"ready", "tracked":true, ...기존 전체 필드}` |
| 미등록 심볼 첫 호출 | `200 {"status":"pending", "symbol":"AAPL"}` + 백그라운드 수집 시작 |
| 수집 중 폴링 | `200 {"status":"pending", "symbol":"AAPL"}` |
| 수집 완료 | `200 {"status":"ready", "tracked":false, ...기존 전체 필드}` |
| 해석/수집 실패 | `200 {"status":"failed", "message":"알 수 없는 심볼입니다"}` |

`status`와 `tracked`는 **추가** 필드다. 기존 필드는 그대로 나가므로 구버전 빌드본도 계속
동작한다(응답 필드는 지우거나 이름 바꾸지 않는다는 규약).

**실패에 404를 쓰지 않는 이유.** 심볼 해석은 `fetchers._krx_listing()`을 타고, 이건 캐시 없는
FinanceDataReader 네트워크 호출이다. 요청 경로에서 부를 수 없으니 해석 자체가 백그라운드로
가야 하고, 그러면 첫 응답 시점에는 그 심볼이 존재하는지 아직 모른다. `api.py:78`의
`/company`가 같은 이유로 이미 `200 + status:"pending"`을 쓰고 있다 — "404를 주면 화면이
'없는 종목'과 '아직 수집 전'을 구분하지 못한다".

### `PUT /api/watchlist/{symbol}` (신규)

이미 존재하는 행의 플래그만 세운다 (`db.set_watchlist(conn, symbol, 1)`).

기존 `POST /api/watchlist`는 `yf_symbol`·`currency`·`is_etf`까지 본문으로 받는다. 임시 등록
시점에 그 행은 이미 정확히 만들어져 있으므로 프론트가 메타데이터를 왕복시킬 이유가 없다.
`DELETE /api/watchlist/{symbol}`와 짝이 맞는다. 행이 없으면 404.

## 백엔드

`service.py`는 이미 1307줄이다. 화면 하나가 여기서 더 자라면 다른 화면이 같이 흔들리므로
**`backend/app/preview.py`** 새 모듈로 뺀다.

### 흐름

```
api.ticker_detail(symbol, bg: BackgroundTasks)
  ├ db.get_ticker 있음 → service.get_ticker_detail + status:"ready", tracked:bool
  └ 없음 → preview.poll(symbol, bg, app.state.db)
        ├ 실패 기록(TTL 내) → {"status":"failed", "message": ...}
        ├ 인플라이트         → {"status":"pending", "symbol": symbol}
        └ 처음              → 인플라이트 등록 + bg.add_task(job)
                            → {"status":"pending", "symbol": symbol}
```

### 백그라운드 job

`BackgroundTasks`에 등록한 동기 함수는 응답이 나간 뒤 스레드풀 워커에서 돈다.

1. `thread_local_db.conn()`으로 **그 스레드의 연결**을 얻는다. 요청 스레드의 연결을 넘겨받아
   쓰면 동시 접근으로 프로세스가 죽는다(`main.py` 주석).
2. `fetchers.search_symbols(symbol)` 결과에서 `symbol`이 정확히 일치하는 1건을 고른다.
   없으면 실패 기록 후 종료.
3. `db.upsert_ticker(..., in_watchlist=0)`
4. `service.refresh_all(conn, symbol)` — OHLCV, 시그널, fundamentals. `force_company=False`라
   회사 자료 6블록은 TTL 캐시 경로로 뒤따라온다.
5. `finally`에서 인플라이트 해제. 해제를 빠뜨리면 그 심볼이 영구히 pending으로 굳는다.

### 상태 보관

모듈 레벨 dict + `threading.Lock`. **DB에 남기지 않는다.**

- 인플라이트: 2초 폴링이 매번 job을 재시작하는 것만 막으면 된다. 프로세스가 재시작되면
  다음 폴링이 알아서 다시 시작하므로 영속성이 필요 없다.
- 실패 기록: **TTL 5분**. 만료시키지 않으면 일시적 네트워크 장애 한 번이 그 심볼을 영구
  실패로 굳혀, 사용자가 새로고침을 눌러도 계속 같은 에러만 본다. TTL은 모듈 상수로 두어
  테스트에서 monkeypatch할 수 있게 한다.

### 갱신 루프에 얹지 않는다

`service._active_tickers`는 워치리스트 ∪ 보유만 고른다. 임시 등록분은 `in_watchlist=0` +
미보유라 시간당 전체 갱신 대상에서 자동으로 빠진다. **`_active_tickers`는 손대지 않는다** —
여기에 임시 등록분을 넣으면 한 번 열어본 종목 수만큼 매시간 외부 호출이 늘어난다.

### 정리하지 않는 이유

임시 등록분은 `tickers` 1행 + `price_cache` 최대 400행 + `signal_history` 소량 + `company_cache`
몇 행을 남긴다. 주기 갱신 비용은 0이고, 로컬 단일 사용자 SQLite에서 이 크기는 문제가 되는
지점이 멀다. 반대로 GC를 넣으려면 `last_viewed_at` 컬럼 + 마이그레이션 + `trades`/`cash_flows`/
`custom_rules` 참조 검사 + 4개 테이블 연쇄 삭제가 붙는다. 지금 값을 치르지 않는다.
나중에 실제로 커지면 그때 기준을 정한다.

부수 효과로 **재조회가 즉시 뜬다** — 한 번 본 종목은 캐시가 살아 있어 두 번째 방문부터
pending이 없다.

## 프론트엔드

### 폴링 훅

`/api/tickers/{symbol}` 소비자가 둘이다 — `pages/TickerDetail.tsx:86`과
`pages/ticker/Analysis.tsx:51`. 양쪽에 폴링을 복붙하면 두 화면이 갈라지므로
**`frontend/src/ticker/useTickerDetail.ts`** 훅 하나로 뽑고 둘이 같이 쓴다.

```ts
useTickerDetail(symbol) → { detail, status, error, reload }
//   status: 'loading' | 'pending' | 'ready' | 'failed'
```

- `status === 'pending'`이면 **2초** 뒤 같은 URL 재요청. `ready`/`failed`면 멈춘다.
- **상한 30회(60초).** 넘으면 `failed` + "수집이 오래 걸립니다 — 다시 시도하세요."
  상한이 없으면 백엔드가 조용히 죽었을 때 탭이 영원히 2초마다 요청을 쏜다.
- 심볼 변경·언마운트 시 타이머를 정리하고 늦게 온 응답을 무시한다. 없으면 A→B로 이동하는
  중에 도착한 A의 응답이 B 화면을 덮어쓴다.

### 의존 호출의 순서

`/company`와 `/backtest`는 `db.get_ticker`가 없으면 404다. 지금 `Analysis.tsx:71`은 `load()`와
`loadBacktest()`를 같이 쏘는데, pending 중이면 백테스트가 404로 죽는다. **두 호출 모두
`status === 'ready'` 이후에만 발화**하도록 바꾼다. `TickerDetail.tsx`의 `loadCompany`는 이미
`detail` 도착 후에 걸려 있어 조건만 `status === 'ready'`로 좁힌다.

### 화면 상태

| status | 화면 |
|---|---|
| `loading` | 첫 요청이 아직 안 돌아온 상태. 기존 스켈레톤 3장 그대로 (문구 없음) |
| `pending` | 기존 스켈레톤 3장 + "시세를 받아오는 중…" 한 줄. 지금은 `!detail`이면 무조건 스켈레톤이라 사용자가 멈춘 건지 받는 중인지 구분하지 못한다 |
| `failed` | 기존 에러 카드 + 응답의 `message` + `다시 시도` |
| `ready && !tracked` | 헤더에 `관심 등록` 버튼 → `PUT /api/watchlist/{symbol}` → `reload()` |

### CommandPalette

`components/CommandPalette.tsx`의 `pick()`에서 `POST /api/watchlist`와 `POST /api/refresh`
호출, 그리고 `busy` 상태를 통째로 제거하고 `navigate`만 남긴다. `종목 추가 중…` 플레이스홀더도
같이 사라진다. Enter가 즉시 반응하고, 워치리스트에는 사용자가 명시적으로 등록한 것만 남는다.

## 테스트

pytest는 네트워크 없이 통과해야 하므로 `fetchers.search_symbols`와 `service.refresh_all`을
monkeypatch한다. TestClient는 `BackgroundTasks`를 응답 뒤 동기 실행하므로 **"첫 GET → pending,
두 번째 GET → ready"** 가 한 테스트 안에서 검증된다.

`backend/tests/test_preview.py` (신규):

| 테스트 | 검증 |
|---|---|
| 미등록 심볼 첫 GET | `200`, `status == "pending"` |
| 수집 후 재GET | `status == "ready"`, `tracked is False`, 기존 필드(`candles`·`cost_rates` 등) 존재 |
| 임시 등록분 DB 상태 | `in_watchlist == 0`, `service._active_tickers()`에 포함되지 않음 |
| 해석 실패 | `status == "failed"` + `message` |
| 폴링 3회 연타 | job 호출 카운터가 1 (인플라이트 가드) |
| 실패 TTL 만료 | 만료 후 다시 `pending`으로 job 재시작 |
| 등록 종목 회귀 | `005930` → `status == "ready"`, `tracked is True` |
| `PUT /api/watchlist/{symbol}` | `in_watchlist == 1`, 이후 `tracked is True`. 없는 심볼은 404 |

**수정할 기존 테스트**: `tests/test_api.py:242`의
`assert client.get("/api/tickers/NOPE").status_code == 404` → pending/failed 2단계로.
계약 변경의 유일한 회귀 지점이다.

프론트는 `npx tsc -b` + `npm run lint`, 그리고 5173에서 브라우저 실측 — 미등록 심볼 URL을
직접 입력해 스켈레톤 → 렌더 전환을 확인하고, Network 탭에서 폴링이 2초 간격으로 나가다
`ready`에서 **멈추는지** 본다.

## 변경 범위

| 파일 | 변경 |
|---|---|
| `backend/app/preview.py` | 신규 — 인플라이트 가드, 심볼 해석, 백그라운드 job |
| `backend/app/api.py` | `ticker_detail`에 `BackgroundTasks` + `status`/`tracked`, `PUT /api/watchlist/{symbol}` |
| `backend/tests/test_preview.py` | 신규 |
| `backend/tests/test_api.py` | `NOPE` 404 테스트 수정 |
| `frontend/src/ticker/useTickerDetail.ts` | 신규 — 폴링 훅 |
| `frontend/src/pages/TickerDetail.tsx` | 훅 사용, pending 문구, `관심 등록` 버튼 |
| `frontend/src/pages/ticker/Analysis.tsx` | 훅 사용, 백테스트를 ready 이후로 |
| `frontend/src/components/CommandPalette.tsx` | 강제 등록 제거 |
| `frontend/src/types.ts` | `status`·`tracked` 필드 |

`schema.sql`·`db.py`·`service.py`·`_active_tickers`는 손대지 않는다. 대시보드 쪽
`market*.py`도 무관하다.

## 열린 위험

- **첫 조회 60초 상한이 짧을 수 있다.** `refresh_all`은 OHLCV + 시그널 + fundamentals를
  순차로 받는다. 미국 종목에서 yfinance가 느린 날 상한에 걸리면 사용자는 `failed`를 본다.
  실측 후 상한을 조정한다. 데이터는 이미 저장돼 있으므로 `다시 시도`는 즉시 성공한다.
- **검색 해석기의 좁은 커버리지가 그대로 남는다.** URL로 `/ticker/aapl`(소문자)을 열면
  `failed`가 뜬다. 범위 밖으로 끊은 항목이며, 별도 작업으로 다룬다.
