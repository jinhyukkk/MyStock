# 미등록 종목 임시 조회(preview) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 워치리스트에 등록하지 않은 종목도 종목 상세 화면을 열 수 있게 한다.

**Architecture:** `GET /api/tickers/{symbol}`에 `status`·`tracked` 필드를 추가해 `pending → ready` 폴링 계약으로 바꾼다. 미등록 심볼은 새 모듈 `preview.py`가 FastAPI `BackgroundTasks`로 해석·수집하고 `in_watchlist=0` 행을 만든다. 프론트는 두 소비자 페이지가 공유하는 폴링 훅 하나를 쓴다.

**Tech Stack:** Python 3.11 / FastAPI / SQLite(thread-local) / pytest+TestClient, React 19 / TypeScript / Vite

**Spec:** `docs/superpowers/specs/2026-08-22-ticker-preview-design.md`

## Global Constraints

- **DB 연결은 `_conn(request)` 또는 `ThreadLocalDB.conn()`만.** 스레드 간 연결 공유는 프로세스를 죽인다. 백그라운드 작업은 워커 스레드 안에서 자기 연결을 얻는다.
- **응답 필드는 지우거나 이름 바꾸지 않는다. 추가만 한다.** 빌드본이 구버전일 수 있다.
- **API 에러는 `HTTPException(detail=...)`.** 프론트 `api.ts`가 `detail`만 사용자에게 보여준다.
- **주석은 한국어로 "왜"를 쓴다.** "안 그러면 무엇이 깨지는지"까지.
- **pytest는 네트워크 없이 통과해야 한다.** 외부 호출은 전부 monkeypatch.
- **손대지 않는 파일:** `backend/app/schema.sql`, `backend/app/db.py`, `backend/app/service.py`, `backend/app/market*.py`.
- 폴링 간격 `POLL_MS = 2000`, 상한 `MAX_POLLS = 30`, 실패 TTL `FAILURE_TTL_SEC = 300`.
- 실패 메시지 문구(그대로 사용):
  - 해석 실패: `"알 수 없는 심볼입니다 — 종목 코드를 확인하세요."`
  - 수집 예외: `f"조회 실패: {e}"`
  - 폴링 상한: `"수집이 오래 걸립니다 — 다시 시도하세요."`

## 사양에서 바뀐 판단 하나

스펙 작성 뒤 확인한 사실: `service.refresh_all`은 종목별 예외를 `failed_tickers`로 삼키고 예외를 올리지 않는다. 따라서 심볼 해석은 성공했는데 시세만 못 받는 경우 `candles: []`인 행이 남는다.

**이 경우 실패로 만들지 않고 `ready`로 내보낸다.** `TickerDetail.tsx`의 `verdict()`가 이미 `!detail.risk`를 "가격 데이터가 부족해 … 새로고침 후 다시 확인하세요"로 처리하고, 화면의 새로고침 버튼이 그대로 동작한다. 행을 지우려면 `db.py`에 삭제 헬퍼를 더해야 하는데(손대지 않기로 한 파일), 그 값을 치를 만큼 얻는 게 없다.

## 파일 구조

| 파일 | 책임 |
|---|---|
| `backend/app/preview.py` (신규) | 인플라이트 가드, 실패 TTL, 심볼 해석, 백그라운드 수집 job. `service.py`(1307줄)에 넣지 않는 이유는 화면 하나가 거기서 자라면 다른 화면이 같이 흔들리기 때문 |
| `backend/app/api.py` (수정) | `ticker_detail` 계약 확장, `PUT /api/watchlist/{symbol}` |
| `backend/tests/test_preview.py` (신규) | preview 전용 — 순수 단위(가드/TTL) + HTTP 계약 |
| `backend/tests/test_api.py` (수정) | 기존 404 테스트 한 건 |
| `frontend/src/ticker/useTickerDetail.ts` (신규) | 폴링 훅. 소비자가 둘이라 페이지에 복붙하면 두 화면이 갈라진다 |
| `frontend/src/types.ts` (수정) | 응답 유니온 타입 |
| `frontend/src/pages/TickerDetail.tsx` (수정) | 훅 사용, pending 문구, `관심 등록` 버튼 |
| `frontend/src/pages/ticker/Analysis.tsx` (수정) | 훅 사용, 백테스트를 ready 이후로 |
| `frontend/src/components/CommandPalette.tsx` (수정) | 강제 워치리스트 등록 제거 |

---

### Task 1: preview 모듈의 인플라이트·실패 가드

상태 관리만 먼저 만든다. 외부 호출도 DB도 없어서 순수 단위 테스트로 결정적으로 검증된다.

**Files:**
- Create: `backend/app/preview.py`
- Test: `backend/tests/test_preview.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `preview.FAILURE_TTL_SEC: int` (모듈 상수, 테스트에서 monkeypatch)
  - `preview.reset() -> None`
  - `preview._acquire(symbol: str) -> bool`
  - `preview._release(symbol: str) -> None`
  - `preview._fail(symbol: str, message: str) -> None`
  - `preview._recent_failure(symbol: str) -> str | None`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/tests/test_preview.py` 생성:

```python
import pytest

from app import preview


@pytest.fixture(autouse=True)
def clean_preview_state():
    """모듈 레벨 상태는 프로세스 수명 동안 남는다 — 테스트끼리 새게 두면
    앞 테스트의 인플라이트가 뒤 테스트를 pending으로 붙잡는다."""
    preview.reset()
    yield
    preview.reset()


def test_acquire_is_exclusive_until_released():
    assert preview._acquire("005930") is True
    assert preview._acquire("005930") is False
    assert preview._acquire("005930") is False
    preview._release("005930")
    assert preview._acquire("005930") is True


def test_acquire_is_per_symbol():
    assert preview._acquire("005930") is True
    assert preview._acquire("AAPL") is True


def test_failure_is_remembered_then_expires(monkeypatch):
    preview._fail("NOPE", "알 수 없는 심볼입니다 — 종목 코드를 확인하세요.")
    assert preview._recent_failure("NOPE") == "알 수 없는 심볼입니다 — 종목 코드를 확인하세요."
    # TTL이 지나면 잊는다 — 일시적 네트워크 장애 한 번이 영구 실패로 굳으면
    # 사용자가 새로고침을 눌러도 계속 같은 에러만 본다.
    monkeypatch.setattr(preview, "FAILURE_TTL_SEC", 0)
    assert preview._recent_failure("NOPE") is None


def test_unknown_symbol_has_no_failure():
    assert preview._recent_failure("005930") is None
```

- [ ] **Step 2: 실패하는 걸 확인한다**

```bash
cd backend && .venv/bin/pytest tests/test_preview.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.preview'`

- [ ] **Step 3: 최소 구현**

`backend/app/preview.py` 생성:

```python
"""미등록 종목의 임시 조회(preview).

종목 상세는 `tickers` 행이 있어야 열린다. 이 모듈은 행이 없는 심볼을 요청받았을 때
백그라운드에서 해석·수집해 행을 만든다. 요청 경로에서 하지 않는 이유는 두 가지다 —
심볼 해석(`fetchers.search_symbols`)이 캐시 없는 FinanceDataReader 호출이고,
`refresh_all`의 시세·시그널·재무 수집이 수 초 걸린다.

여기서 만든 행은 `in_watchlist=0`이라 `service._active_tickers`의 시간당 갱신 대상에
들어가지 않는다. 한 번 열어본 것만으로 매시간 외부 호출이 늘어나면 안 된다.
"""
import threading
import time

# 일시적 네트워크 장애 한 번이 그 심볼을 영구 실패로 굳히면, 사용자가 새로고침을
# 눌러도 계속 같은 에러만 본다. 5분 뒤에는 다시 시도하게 한다.
FAILURE_TTL_SEC = 300

_lock = threading.Lock()
_inflight: set[str] = set()
_failures: dict[str, tuple[float, str]] = {}   # symbol -> (기록 시각, 메시지)


def reset() -> None:
    """테스트 격리용 — 모듈 레벨 상태는 프로세스 수명 동안 남는다."""
    with _lock:
        _inflight.clear()
        _failures.clear()


def _acquire(symbol: str) -> bool:
    """이 호출이 수집을 시작해야 하면 True.

    프론트가 2초마다 같은 URL을 다시 부르므로, 이게 없으면 폴링 한 번마다
    외부 수집 job이 새로 뜬다."""
    with _lock:
        if symbol in _inflight:
            return False
        _inflight.add(symbol)
        return True


def _release(symbol: str) -> None:
    with _lock:
        _inflight.discard(symbol)


def _fail(symbol: str, message: str) -> None:
    with _lock:
        _failures[symbol] = (time.monotonic(), message)


def _recent_failure(symbol: str) -> str | None:
    with _lock:
        hit = _failures.get(symbol)
        if hit is None:
            return None
        at, message = hit
        if time.monotonic() - at >= FAILURE_TTL_SEC:
            del _failures[symbol]
            return None
        return message
```

- [ ] **Step 4: 통과하는 걸 확인한다**

```bash
cd backend && .venv/bin/pytest tests/test_preview.py -q
```

Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/preview.py backend/tests/test_preview.py
git commit -m "feat: preview 인플라이트·실패 TTL 가드"
```

---

### Task 2: 심볼 해석과 백그라운드 수집 job

**Files:**
- Modify: `backend/app/preview.py`
- Test: `backend/tests/test_preview.py`

**Interfaces:**
- Consumes: Task 1의 `_acquire`/`_release`/`_fail`/`_recent_failure`
- Produces:
  - `preview.poll(symbol: str, bg: fastapi.BackgroundTasks, thread_db) -> dict`
    반환은 `{"status": "pending"|"failed", "symbol": str, ...}`. `failed`일 때만 `message` 키가 붙는다.
  - `preview._resolve(symbol: str) -> dict | None`
  - `preview._job(symbol: str, thread_db) -> None`
  - `thread_db`는 `app.state.db` (`db.ThreadLocalDB`) — `.conn()`으로 호출 스레드의 연결을 준다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/tests/test_preview.py` 끝에 추가:

```python
from app import fetchers

SAMSUNG = {"symbol": "005930", "name": "삼성전자", "market": "KR",
           "is_etf": 0, "yf_symbol": "005930.KS", "currency": "KRW"}


def test_resolve_takes_exact_symbol_match(monkeypatch):
    monkeypatch.setattr(fetchers, "search_symbols", lambda q, conn=None: [SAMSUNG])
    assert preview._resolve("005930") == SAMSUNG


def test_resolve_rejects_partial_match(monkeypatch):
    # 부분 일치를 받아들이면 사용자가 요청하지 않은 종목이 그 URL에 눌러앉는다.
    monkeypatch.setattr(fetchers, "search_symbols", lambda q, conn=None: [SAMSUNG])
    assert preview._resolve("NOPE") is None


def test_resolve_survives_search_failure(monkeypatch):
    def boom(q, conn=None):
        raise RuntimeError("network down")
    monkeypatch.setattr(fetchers, "search_symbols", boom)
    assert preview._resolve("005930") is None
```

- [ ] **Step 2: 실패하는 걸 확인한다**

```bash
cd backend && .venv/bin/pytest tests/test_preview.py -q
```

Expected: FAIL — `AttributeError: module 'app.preview' has no attribute '_resolve'`

- [ ] **Step 3: 최소 구현**

`backend/app/preview.py` 상단 import를 바꾸고:

```python
import threading
import time

from app import db, fetchers, service
```

파일 끝에 추가:

```python
def _resolve(symbol: str) -> dict | None:
    """검색 결과에서 심볼이 **정확히** 일치하는 1건.

    부분 일치를 받아들이면 사용자가 요청하지 않은 종목이 그 URL에 눌러앉는다 —
    `/ticker/00593`이 삼성전자로 열리면 그 화면의 손절가·수량을 믿고 주문하게 된다."""
    try:
        hits = fetchers.search_symbols(symbol)
    except Exception:
        # 해석 실패와 "없는 종목"을 여기서 구분할 방법이 없다. 둘 다 None으로 보내고
        # 실패 TTL이 만료되면 다시 시도하게 한다.
        return None
    for hit in hits:
        if hit.get("symbol") == symbol:
            return hit
    return None


def _job(symbol: str, thread_db) -> None:
    """응답이 나간 뒤 스레드풀 워커에서 돈다."""
    try:
        # 요청 스레드의 연결을 넘겨받아 쓰면 동시 접근으로 프로세스가 죽는다.
        # 이 스레드의 연결을 여기서 직접 얻는다.
        conn = thread_db.conn()
        meta = _resolve(symbol)
        if meta is None:
            _fail(symbol, "알 수 없는 심볼입니다 — 종목 코드를 확인하세요.")
            return
        # in_watchlist=0 — 조회가 워치리스트를 오염시키지 않고, 시간당 전체 갱신
        # 대상(`service._active_tickers`)에도 들어가지 않는다.
        db.upsert_ticker(conn, meta["symbol"], meta["market"], meta["name"],
                         is_etf=meta.get("is_etf", 0), in_watchlist=0,
                         yf_symbol=meta.get("yf_symbol"),
                         currency=meta.get("currency", "KRW"))
        service.refresh_all(conn, symbol)
    except Exception as e:
        _fail(symbol, f"조회 실패: {e}")
    finally:
        # 해제를 빠뜨리면 그 심볼이 프로세스가 살아 있는 동안 영원히 pending으로 굳는다.
        _release(symbol)


def poll(symbol: str, bg, thread_db) -> dict:
    """미등록 심볼에 대한 응답. 첫 호출이 수집을 시작하고, 이후 폴링은 상태만 읽는다."""
    failed = _recent_failure(symbol)
    if failed:
        return {"status": "failed", "symbol": symbol, "message": failed}
    if _acquire(symbol):
        bg.add_task(_job, symbol, thread_db)
    return {"status": "pending", "symbol": symbol}
```

- [ ] **Step 4: 통과하는 걸 확인한다**

```bash
cd backend && .venv/bin/pytest tests/test_preview.py -q
```

Expected: PASS (7 passed)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/preview.py backend/tests/test_preview.py
git commit -m "feat: preview 심볼 해석과 백그라운드 수집 job"
```

---

### Task 3: `GET /api/tickers/{symbol}` 계약 확장

**Files:**
- Modify: `backend/app/api.py:70-76` (`ticker_detail`), import 줄
- Modify: `backend/tests/test_api.py:241-242` (`test_ticker_detail_404`)
- Test: `backend/tests/test_preview.py`

**Interfaces:**
- Consumes: Task 2의 `preview.poll(symbol, bg, thread_db)`
- Produces: `GET /api/tickers/{symbol}` 응답에 `status: "pending"|"ready"|"failed"`, `ready`일 때 `tracked: bool`

**참고 — TestClient의 백그라운드 실행:** Starlette TestClient는 응답을 돌려주기 전에 `BackgroundTasks`를 끝까지 실행한다. 따라서 "첫 GET → pending, 두 번째 GET → ready"가 한 테스트 안에서 결정적으로 검증된다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/tests/test_preview.py` 끝에 추가:

```python
from fastapi.testclient import TestClient

from app import sentiment
from app.main import create_app

FAKE_SENTI = {"vix": 18.0, "vkospi": None, "cnn_fg": 60, "crypto_fg": 50,
              "usdkrw": 1300.0, "failed": []}


@pytest.fixture
def client(tmp_path, ohlcv_up, monkeypatch):
    monkeypatch.setattr(fetchers, "fetch_ohlcv", lambda *a, **k: ohlcv_up)
    monkeypatch.setattr(fetchers, "fetch_fundamentals", lambda *a, **k: None)
    monkeypatch.setattr(fetchers, "search_symbols", lambda q, conn=None: [SAMSUNG])
    monkeypatch.setattr(sentiment, "fetch_sentiment", lambda: dict(FAKE_SENTI))
    app = create_app(db_path=str(tmp_path / "t.db"), refresh_on_start=False)
    with TestClient(app) as c:
        yield c


def test_unregistered_symbol_is_pending_then_ready(client):
    first = client.get("/api/tickers/005930")
    assert first.status_code == 200
    assert first.json() == {"status": "pending", "symbol": "005930"}

    second = client.get("/api/tickers/005930").json()
    assert second["status"] == "ready"
    assert second["tracked"] is False
    # 기존 필드가 그대로 나가야 한다 — 구버전 빌드본도 계속 동작해야 하므로.
    assert len(second["candles"]) > 0
    assert second["signal"]["swing_grade"]
    assert second["cost_rates"]["fee_pct"] >= 0


def test_preview_row_stays_out_of_the_refresh_loop(client):
    client.get("/api/tickers/005930")
    assert client.get("/api/tickers/005930").json()["status"] == "ready"
    # in_watchlist=0 + 미보유라 `_active_tickers`에 안 들어간다.
    # 들어가면 한 번 열어본 종목 수만큼 매시간 외부 호출이 늘어난다.
    assert client.get("/api/dashboard").json()["signals"] == []


def test_unresolvable_symbol_reports_failed(client):
    assert client.get("/api/tickers/NOPE").json()["status"] == "pending"
    out = client.get("/api/tickers/NOPE").json()
    assert out["status"] == "failed"
    assert out["message"] == "알 수 없는 심볼입니다 — 종목 코드를 확인하세요."


def test_registered_ticker_is_ready_and_tracked(client):
    client.post("/api/watchlist", json=SAMSUNG)
    client.post("/api/refresh")
    out = client.get("/api/tickers/005930").json()
    assert out["status"] == "ready"
    assert out["tracked"] is True
```

`backend/tests/test_api.py:241-242`를 이걸로 교체:

```python
def test_ticker_detail_unknown_symbol_reports_failed(client):
    # 404가 아니라 status로 알린다 — 심볼 해석이 네트워크를 타므로 첫 응답 시점에는
    # 그 종목이 없는 건지 아직 수집 전인지 구분할 수 없다.
    assert client.get("/api/tickers/NOPE").json()["status"] == "pending"
    assert client.get("/api/tickers/NOPE").json()["status"] == "failed"
```

- [ ] **Step 2: 실패하는 걸 확인한다**

```bash
cd backend && .venv/bin/pytest tests/test_preview.py tests/test_api.py -q
```

Expected: FAIL — preview 테스트가 `404`를 받고 `assert first.status_code == 200`에서 깨진다

- [ ] **Step 3: 최소 구현**

`backend/app/api.py`의 import 줄을 바꾼다:

```python
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from app import codef, db, fetchers, preview, service
```

`ticker_detail`(70-76줄)을 교체:

```python
@router.get("/tickers/{symbol}")
def ticker_detail(symbol: str, request: Request, bg: BackgroundTasks):
    """미등록 심볼도 연다 — 없으면 백그라운드로 해석·수집하고 pending을 준다.

    404를 주지 않는 이유는 `/company`와 같다. 심볼 해석이 캐시 없는 외부 호출이라
    요청 경로에서 할 수 없고, 그러면 첫 응답 시점에 존재 여부를 아직 모른다."""
    conn = _conn(request)
    t = db.get_ticker(conn, symbol)
    if not t:
        return preview.poll(symbol, bg, request.app.state.db)
    out = service.get_ticker_detail(conn, symbol)
    if out is None:
        raise HTTPException(404, "ticker not found")
    # 추가 필드만 얹는다. 기존 필드를 건드리면 구버전 빌드본이 깨진다.
    return {**out, "status": "ready", "tracked": bool(t["in_watchlist"])}
```

- [ ] **Step 4: 통과하는 걸 확인한다**

```bash
cd backend && .venv/bin/pytest -q
```

Expected: PASS — 전체 스위트 통과 (기존 테스트 포함)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/api.py backend/tests/test_preview.py backend/tests/test_api.py
git commit -m "feat: 미등록 종목도 종목 상세를 연다 (pending 폴링 계약)"
```

---

### Task 4: `PUT /api/watchlist/{symbol}`

임시 조회 중인 종목을 사용자가 명시적으로 관심 등록할 때 쓴다. 행은 이미 정확히 만들어져 있으므로 플래그만 세운다 — 프론트가 `yf_symbol`·`currency`를 왕복시킬 이유가 없다.

**Files:**
- Modify: `backend/app/api.py` (`remove_watch` 바로 위)
- Test: `backend/tests/test_preview.py`

**Interfaces:**
- Consumes: Task 3의 `tracked` 필드
- Produces: `PUT /api/watchlist/{symbol}` → `{"ok": True}` / 행이 없으면 404 `"ticker not found"`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/tests/test_preview.py` 끝에 추가:

```python
def test_track_flips_preview_row_into_watchlist(client):
    client.get("/api/tickers/005930")
    assert client.get("/api/tickers/005930").json()["tracked"] is False

    assert client.put("/api/watchlist/005930").status_code == 200
    assert client.get("/api/tickers/005930").json()["tracked"] is True
    # 등록했으니 이제 대시보드(=시간당 갱신 대상)에도 나타난다.
    assert len(client.get("/api/dashboard").json()["signals"]) == 1


def test_track_unknown_symbol_is_404(client):
    assert client.put("/api/watchlist/NOPE").status_code == 404
```

- [ ] **Step 2: 실패하는 걸 확인한다**

```bash
cd backend && .venv/bin/pytest tests/test_preview.py -q
```

Expected: FAIL — `assert 405 == 200` (PUT 라우트 없음)

- [ ] **Step 3: 최소 구현**

`backend/app/api.py`의 `remove_watch` 바로 위에 추가:

```python
@router.put("/watchlist/{symbol}")
def track_watch(symbol: str, request: Request):
    """이미 있는 행의 플래그만 세운다.

    `POST /api/watchlist`는 yf_symbol·currency까지 본문으로 받는데, 임시 조회로 만들어진
    행은 그 값이 이미 정확하다. 프론트가 메타데이터를 되돌려 보내면 틀릴 여지만 생긴다."""
    conn = _conn(request)
    if not db.get_ticker(conn, symbol):
        raise HTTPException(404, "ticker not found")
    db.set_watchlist(conn, symbol, 1)
    return {"ok": True}
```

- [ ] **Step 4: 통과하는 걸 확인한다**

```bash
cd backend && .venv/bin/pytest -q
```

Expected: PASS — 전체 스위트 통과

- [ ] **Step 5: 커밋**

```bash
git add backend/app/api.py backend/tests/test_preview.py
git commit -m "feat: PUT /api/watchlist/{symbol} — 조회 중인 종목을 관심 등록"
```

---

### Task 5: 프론트 타입과 폴링 훅

**Files:**
- Modify: `frontend/src/types.ts` (`TickerDetail` 인터페이스 아래)
- Create: `frontend/src/ticker/useTickerDetail.ts`

**Interfaces:**
- Consumes: Task 3·4의 응답 계약
- Produces:
  - `types.ts`: `TickerDetailReady = TickerDetail & { status: 'ready'; tracked: boolean }`, `TickerDetailResponse` 유니온
  - `useTickerDetail(symbol: string | undefined) → { detail: TickerDetailReady | null, status: DetailStatus, error: string | null, loadedAt: number, reload: () => void }`
  - `DetailStatus = 'loading' | 'pending' | 'ready' | 'failed'`

프론트 단위 테스트는 없다 — `tsc -b` + `lint`가 게이트이고, 동작은 Task 8에서 브라우저로 실측한다.

- [ ] **Step 1: 타입을 추가한다**

`frontend/src/types.ts`의 `TickerDetail` 인터페이스 닫는 중괄호 바로 뒤에 추가:

```ts
/** `GET /api/tickers/{symbol}` 응답.
 *
 *  미등록 종목은 백그라운드 수집이 끝날 때까지 pending이 온다. 실패에 404가 아니라
 *  status를 쓰는 이유는 백엔드 주석 참고 — 첫 응답 시점엔 '없는 종목'인지
 *  '아직 수집 전'인지 구분할 수 없다. */
export type TickerDetailReady = TickerDetail & { status: 'ready'; tracked: boolean }
export type TickerDetailResponse =
  | { status: 'pending'; symbol: string }
  | { status: 'failed'; symbol: string; message: string }
  | TickerDetailReady
```

- [ ] **Step 2: 훅을 만든다**

`frontend/src/ticker/useTickerDetail.ts` 생성:

```ts
import { useCallback, useEffect, useRef, useState } from 'react'
import { get } from '../api'
import type { TickerDetailReady, TickerDetailResponse } from '../types'

const POLL_MS = 2000
/** 60초. 상한이 없으면 백엔드가 조용히 죽었을 때 탭이 영원히 2초마다 요청을 쏜다. */
const MAX_POLLS = 30

export type DetailStatus = 'loading' | 'pending' | 'ready' | 'failed'

/** 종목 상세를 받되, 미등록 종목이면 수집이 끝날 때까지 폴링한다.
 *
 *  소비자가 개요(TickerDetail)와 분석(Analysis) 둘이라 훅으로 뽑았다. 페이지마다
 *  폴링을 복붙하면 상한·정리 규칙이 갈라지고 한쪽만 고쳐지는 일이 생긴다. */
export function useTickerDetail(symbol: string | undefined) {
  const [detail, setDetail] = useState<TickerDetailReady | null>(null)
  const [status, setStatus] = useState<DetailStatus>('loading')
  const [error, setError] = useState<string | null>(null)
  const [loadedAt, setLoadedAt] = useState(Date.now())
  // 심볼이 바뀌면 세대를 올린다. 없으면 A→B로 이동하는 중에 도착한 A의 응답이
  // B 화면을 덮어쓴다.
  const gen = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const run = useCallback((mine: number, tries: number) => {
    if (!symbol) return
    get<TickerDetailResponse>(`/api/tickers/${symbol}`).then(res => {
      if (gen.current !== mine) return
      // status가 없는 응답은 구버전 백엔드다 — 그때는 200이면 곧 완성본이었다.
      const s: DetailStatus = (res as Partial<{ status: DetailStatus }>).status ?? 'ready'
      if (s === 'pending') {
        if (tries + 1 >= MAX_POLLS) {
          setStatus('failed')
          setError('수집이 오래 걸립니다 — 다시 시도하세요.')
          return
        }
        setStatus('pending')
        timer.current = setTimeout(() => run(mine, tries + 1), POLL_MS)
        return
      }
      if (s === 'failed') {
        setStatus('failed')
        setError((res as { message: string }).message)
        return
      }
      setDetail(res as TickerDetailReady)
      setStatus('ready')
      setError(null)
      setLoadedAt(Date.now())
    }).catch(e => {
      if (gen.current !== mine) return
      setStatus('failed')
      setError(String(e))
    })
  }, [symbol])

  const reload = useCallback(() => {
    if (timer.current) clearTimeout(timer.current)
    gen.current += 1
    setStatus('loading')
    setError(null)
    run(gen.current, 0)
  }, [run])

  useEffect(() => {
    gen.current += 1
    const mine = gen.current
    setDetail(null)
    setStatus('loading')
    setError(null)
    run(mine, 0)
    return () => {
      // 언마운트·심볼 변경 시 예약된 폴링을 끊지 않으면 떠난 화면이 계속 요청을 쏜다.
      if (timer.current) clearTimeout(timer.current)
    }
  }, [symbol, run])

  return { detail, status, error, loadedAt, reload }
}
```

- [ ] **Step 3: 타입·린트를 통과하는지 본다**

```bash
cd frontend && npx tsc -b && npm run lint
```

Expected: 에러 없음

- [ ] **Step 4: 커밋**

```bash
git add frontend/src/types.ts frontend/src/ticker/useTickerDetail.ts
git commit -m "feat: 종목 상세 폴링 훅과 응답 유니온 타입"
```

---

### Task 6: 종목 개요 화면에 훅 적용

**Files:**
- Modify: `frontend/src/pages/TickerDetail.tsx:75-115` (상태·load·useEffect), `:130-142` (에러/스켈레톤 분기), 헤더 영역

**Interfaces:**
- Consumes: Task 5의 `useTickerDetail`, Task 4의 `PUT /api/watchlist/{symbol}`
- Produces: 없음 (화면)

- [ ] **Step 1: 상태와 로딩을 훅으로 바꾼다**

`const [detail, setDetail] = useState<Detail | null>(null)` / `const [error, setError] = useState…` / `const [now, setNow] = useState(Date.now())` / `const load = () => get<Detail>(…)` 를 지우고 다음으로 바꾼다:

```ts
  const { detail, status, error, loadedAt, reload } = useTickerDetail(symbol)
  const now = loadedAt
```

import에 추가:

```ts
import { useTickerDetail } from '../ticker/useTickerDetail'
import { put } from '../api'
```

`refresh()`의 `await load()`를 `reload()`로 바꾼다. 에러는 훅의 `error`가 아니라 별도 상태로 받는다 — 훅의 `error`는 "상세를 못 받았다"는 뜻이고, 이건 "버튼 동작이 실패했다"는 다른 사실이다:

```ts
  const [actionError, setActionError] = useState<string | null>(null)

  const refresh = async () => {
    setBusy(true); setActionError(null)
    try { await post(`/api/refresh?symbol=${encodeURIComponent(symbol!)}`); reload(); await loadCompany() }
    catch (e) { setActionError(String(e)) }
    finally { setBusy(false) }
  }
```

심볼 변경 `useEffect`에서 `load()` 호출을 지운다 (훅이 한다):

```ts
  useEffect(() => { setCompany(null) }, [symbol])
```

회사 자료 로드는 ready 이후로 좁힌다 — pending 중에 부르면 `/company`가 404를 준다:

```ts
  useEffect(() => {
    if (status !== 'ready' || !detail) return
    const t = setTimeout(loadCompany, 0)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, detail?.symbol])
```

- [ ] **Step 2: 화면 상태 3가지를 나눈다**

기존 `if (error) return (…)` / `if (!detail) return (…)` 블록을 교체:

```tsx
  if (status === 'failed') return (
    <div className="card">
      <div style={{ color: 'var(--sell)' }}>{error ?? '불러오기 실패'}</div>
      <button style={{ marginTop: 10 }} onClick={reload}>다시 시도</button>
    </div>
  )
  if (!detail) return (
    <div className="grid">
      {/* pending은 "멈춘 것"이 아니라 "받는 중"이다 — 구분해 주지 않으면
          사용자가 새로고침을 반복하며 같은 수집을 기다린다 */}
      {status === 'pending' &&
        <div className="quote-note">시세를 받아오는 중…</div>}
      <div className="card skeleton" style={{ minHeight: 80 }} />
      <div className="card skeleton" style={{ minHeight: 380 }} />
      <div className="card skeleton" style={{ minHeight: 240 }} />
    </div>
  )
```

- [ ] **Step 3: `관심 등록` 버튼을 헤더에 단다**

`refresh` 함수 아래에 추가:

```ts
  /** 조회만 하던 종목을 워치리스트로 올린다. 여기서만 등록된다 —
   *  검색해서 열어본 것이 저절로 워치리스트에 쌓이면 "지켜보기로 정한 것"이 무의미해진다. */
  const track = async () => {
    setBusy(true); setActionError(null)
    try { await put(`/api/watchlist/${encodeURIComponent(symbol!)}`); reload() }
    catch (e) { setActionError(String(e)) }
    finally { setBusy(false) }
  }
```

`QuoteHeader` 옆 버튼 묶음(새로고침 버튼이 있는 곳)에 추가:

```tsx
  {!detail.tracked &&
    <button onClick={track} disabled={busy} title="워치리스트에 추가">관심 등록</button>}
```

그 버튼 묶음 바로 아래에 동작 실패를 표시한다 — 조용히 실패하면 사용자는 등록됐다고 믿는다:

```tsx
  {actionError &&
    <div className="quote-note" style={{ color: 'var(--sell)' }}>{actionError}</div>}
```

- [ ] **Step 4: 타입·린트를 확인한다**

```bash
cd frontend && npx tsc -b && npm run lint
```

Expected: 에러 없음

- [ ] **Step 5: 커밋**

```bash
git add frontend/src/pages/TickerDetail.tsx
git commit -m "feat: 종목 개요에 수집 대기 상태와 관심 등록 버튼"
```

---

### Task 7: 분석 화면에 훅 적용

**Files:**
- Modify: `frontend/src/pages/ticker/Analysis.tsx:38-72`

**Interfaces:**
- Consumes: Task 5의 `useTickerDetail`
- Produces: 없음 (화면)

- [ ] **Step 1: 상태와 로딩을 훅으로 바꾼다**

`const [detail, setDetail] = …` / `const [error, setError] = …` / `const [now, setNow] = …` / `const load = () => get<Detail>(…)` 를 지우고:

```ts
  const { detail, status, error, loadedAt, reload } = useTickerDetail(symbol)
  const now = loadedAt
```

import에 추가:

```ts
import { useTickerDetail } from '../../ticker/useTickerDetail'
```

- [ ] **Step 2: 백테스트를 ready 이후로 미룬다**

`useEffect(() => { load(); setBacktest(null); loadBacktest() }, [symbol])` 를 교체:

```ts
  // `/backtest`는 tickers 행이 없으면 404다. pending 중에 쏘면 수집이 끝나기도 전에
  // 백테스트 블록이 에러로 굳는다 — ready가 된 뒤에만 부른다.
  useEffect(() => { setBacktest(null) }, [symbol])
  useEffect(() => {
    if (status !== 'ready') return
    loadBacktest()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, symbol])
```

`refresh()`도 개요 화면과 같은 이유로 별도 에러 상태를 쓴다:

```ts
  const [actionError, setActionError] = useState<string | null>(null)

  const refresh = async () => {
    setBusy(true); setActionError(null)
    try { await post(`/api/refresh?symbol=${encodeURIComponent(symbol!)}`); reload(); await loadBacktest() }
    catch (e) { setActionError(String(e)) }
    finally { setBusy(false) }
  }
```

- [ ] **Step 3: 화면 상태를 나눈다**

`Analysis.tsx`의 기존 에러/스켈레톤 분기를 교체한다:

```tsx
  if (status === 'failed') return (
    <div className="card">
      <div style={{ color: 'var(--sell)' }}>{error ?? '불러오기 실패'}</div>
      <button style={{ marginTop: 10 }} onClick={reload}>다시 시도</button>
    </div>
  )
  if (!detail) return (
    <div className="grid">
      {/* pending은 "멈춘 것"이 아니라 "받는 중"이다 — 구분해 주지 않으면
          사용자가 새로고침을 반복하며 같은 수집을 기다린다 */}
      {status === 'pending' &&
        <div className="quote-note">시세를 받아오는 중…</div>}
      <div className="card skeleton" style={{ minHeight: 80 }} />
      <div className="card skeleton" style={{ minHeight: 380 }} />
      <div className="card skeleton" style={{ minHeight: 240 }} />
    </div>
  )
```

버튼 묶음 아래에 동작 실패를 표시한다:

```tsx
  {actionError &&
    <div className="quote-note" style={{ color: 'var(--sell)' }}>{actionError}</div>}
```

- [ ] **Step 4: 타입·린트를 확인한다**

```bash
cd frontend && npx tsc -b && npm run lint
```

Expected: 에러 없음

- [ ] **Step 5: 커밋**

```bash
git add frontend/src/pages/ticker/Analysis.tsx
git commit -m "feat: 분석 화면도 폴링 훅을 쓰고 백테스트를 ready 이후로"
```

---

### Task 8: 팔레트의 강제 등록 제거 + 브라우저 실측

**Files:**
- Modify: `frontend/src/components/CommandPalette.tsx:62-75` (`pick`), `busy` 상태와 placeholder

**Interfaces:**
- Consumes: Task 3의 pending 계약 (등록 없이 이동해도 상세가 열린다)
- Produces: 없음

- [ ] **Step 1: `pick`에서 등록·갱신을 뺀다**

```ts
  /** 등록하지 않고 바로 연다 — 상세 화면이 알아서 수집한다.
   *  여기서 워치리스트에 넣으면 "한 번 열어본 것"과 "지켜보기로 정한 것"이 섞인다. */
  const pick = (it: Item) => {
    setOpen(false)
    navigate(`/ticker/${it.symbol}`)
  }
```

`const [busy, setBusy] = useState(false)` 와 `post` import를 지운다 (다른 곳에서 안 쓰면). 입력 필드의 `disabled={busy}` 와 `placeholder={busy ? '종목 추가 중…' : '종목 이름 또는 심볼 검색'}` 를 다음으로 바꾼다:

```tsx
        <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)}
               onKeyDown={onInputKey}
               placeholder="종목 이름 또는 심볼 검색" />
```

`pick`이 더 이상 async가 아니므로 `if (busy) return` 도 지운다. `busy`를 쓰는 다른 자리가 남아 있으면 lint가 잡는다.

- [ ] **Step 2: 타입·린트를 확인한다**

```bash
cd frontend && npx tsc -b && npm run lint
```

Expected: 에러 없음

- [ ] **Step 3: 백엔드 전체 스위트를 돌린다**

```bash
cd backend && .venv/bin/pytest -q
```

Expected: 전부 통과

- [ ] **Step 4: 브라우저로 실측한다**

`preview_start`로 `mystock`(8722, 백엔드)과 `mystock-frontend`(5173) 를 띄운다. 5173에서 확인할 것:

1. **미등록 종목 URL 직접 입력** — 워치리스트에 없는 종목 코드로 `/ticker/{code}`를 연다.
   스켈레톤 + `시세를 받아오는 중…` → 실제 화면으로 전환되는지 본다.
2. **Network 탭** — `/api/tickers/{code}` 요청이 2초 간격으로 나가다 `status:"ready"`에서
   **멈추는지** 확인한다. 멈추지 않으면 훅의 조기 반환이 잘못된 것이다.
3. **`관심 등록` 버튼** — 누르면 버튼이 사라지고, `/watchlist` 화면에 그 종목이 나타난다.
4. **팔레트** — `Cmd+K`로 종목을 검색해 Enter. `종목 추가 중…` 대기 없이 즉시 이동하고,
   워치리스트에는 **추가되지 않는지** 확인한다.
5. **분석 탭** — 미등록 종목의 `/ticker/{code}/analysis`를 직접 열어 백테스트 블록이
   404 에러가 아니라 정상 렌더되는지 본다.
6. **없는 심볼** — `/ticker/ZZZZZZ`를 열어 `알 수 없는 심볼입니다 — 종목 코드를 확인하세요.`
   가 뜨고 폴링이 멈추는지 본다.

- [ ] **Step 5: 커밋**

```bash
git add frontend/src/components/CommandPalette.tsx
git commit -m "feat: 팔레트에서 종목을 열어도 워치리스트에 등록되지 않는다"
```

---

## 검증 요약

| 게이트 | 명령 |
|---|---|
| 백엔드 | `cd backend && .venv/bin/pytest -q` |
| 프론트 타입·린트 | `cd frontend && npx tsc -b && npm run lint` |
| 실측 | 5173에서 Task 8 Step 4의 6항목 |
| 빌드본 갱신 | `cd frontend && npm run build` (8722가 서빙하는 것) |
