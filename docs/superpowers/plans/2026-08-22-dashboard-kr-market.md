# 대시보드 한국 증시 기준 전환 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 대시보드의 기본 시장을 한국(KOSPI·KOSDAQ)으로 바꾸고, 미국 시장은 화면 상단 토글로 남긴다.

**Architecture:** `market.py`를 시장을 모르는 캐시·격리 엔진으로 남기고, 시장별 상수·빌더를 `market_us.py`(기존 코드 이동)와 `market_kr.py`(신규)로 나눈다. 캐시 키는 `"KR:indices"`처럼 시장을 접두로 붙여 시장별로 독립 갱신한다. 한국 데이터는 네이버 모바일 비공식 API(`sources/naver.py`)와 yfinance(`market_fetch.py`)를 섞어 받는다.

**Tech Stack:** FastAPI, pandas, yfinance, requests / React 19 + TypeScript + Vite / pytest, node:test

**Spec:** `docs/superpowers/specs/2026-08-22-dashboard-kr-market-design.md`

## Global Constraints

- 브랜치는 `feature/dashboard-kr`. main 에서 분기했고 스펙 커밋 2개가 이미 올라가 있다.
- **응답 필드는 지우거나 이름을 바꾸지 않는다.** 이 저장소의 규약이다. 이번 작업은 전부 추가다.
- 백엔드 테스트: `cd backend && uv run pytest -q`. 현재 355 passed. **US 동작은 불변이어야 한다.**
- 프론트 검증: `cd frontend && npx tsc -b` (exit 0), `npx oxlint` (경고 0), 단위 테스트는 `npx tsx --test src/quote/*.test.ts` (vitest 아님).
- 외부 호출은 `market_fetch.py`와 `sources/naver.py`에서만 한다. 빌더·엔진은 네트워크를 모른다.
- 네이버 API는 **비공식**이다. `User-Agent` 헤더 필수, 타임아웃 8초, 파싱 실패는 예외로 올려 블록 격리에 맡긴다.
- 실호출 테스트는 `@pytest.mark.smoke`. 기본 실행에서 제외된다(`pyproject.toml`의 `addopts = "-m 'not smoke'"`).
- 주석은 한국어로, "왜"를 쓴다. 커밋 메시지도 한국어 한 줄 + 필요하면 본문.
- 숫자는 JSON 에 실을 수 있어야 한다 — NaN·inf 는 `None` 으로 바꾼다.

---

### Task 1: `market.py`를 시장 무관 엔진으로 + `market_us.py` 추출

기존 US 동작을 그대로 둔 채 구조만 바꾼다. 이 태스크가 끝나면 `market.get_market("US")`가 지금의 `market.get_market()`과 같은 값을 준다.

**Files:**
- Create: `backend/app/market_us.py`
- Modify: `backend/app/market.py` (전면 개편), `backend/app/market_api.py:14-24`
- Test: `backend/tests/test_market.py` (기존 호출을 `"US"`로)

**Interfaces:**
- Produces:
  - `market.MARKETS: dict[str, ModuleType]` — `{"US": market_us}` (Task 3에서 `"KR"` 추가)
  - `market.get_market(market: str, now: float | None = None) -> dict`
  - `market.refresh(market: str, force: bool = False, now: float | None = None) -> None`
  - `market.reset_cache() -> None`
  - `market._pct(last, prev) -> float | None`, `market._chg(last, prev) -> float | None`
  - `market.major_news_from_heatmap(sectors: list[dict], n: int = 16) -> list[dict]`
  - 시장 모듈이 반드시 갖는 것: `SESSION: dict`, `TTL_SEC: dict[str, int]`, `BUILDERS: dict[str, Callable[[], object]]`

- [ ] **Step 1: 기존 테스트를 새 시그니처로 고친다 (실패하는 테스트)**

`backend/tests/test_market.py`에서 `market.get_market(...)`·`market.refresh(...)` 호출에 첫 인자 `"US"`를 넣고, TTL 참조를 시장 모듈로 바꾼다. 아래가 바뀌는 줄 전부다.

```python
# 파일 상단 import
from app import market, market_fetch, market_us

# test_get_market_shape
    m = market.get_market("US", now=1000.0)
    ...
    assert m["market"] == "US"
    assert m["session"]["tz"] == "America/New_York"
    assert m["investors"] == []

# test_block_failure_is_isolated
    m = market.get_market("US", now=1000.0)

# test_failure_keeps_previous_value_and_backs_off
    market.refresh("US", now=1000.0)
    ...
    market.refresh("US", now=1000.0 + market_us.TTL_SEC["indices"] + 1)
    m = market.get_market("US", now=1000.0 + market_us.TTL_SEC["indices"] + 2)
    ...
    market.refresh("US", now=1000.0 + market_us.TTL_SEC["indices"] + 10)

# test_ttl_skips_fresh_blocks
    market.refresh("US", now=1000.0)
    market.refresh("US", now=1000.0 + 60)
    assert calls["n"] == 1
    market.refresh("US", now=1000.0 + market_us.TTL_SEC["headlines"] + 1)
    assert calls["n"] == 2

# test_api_market_endpoint — 그대로 두되 아래 한 줄을 덧붙인다
        assert body["market"] == "US" or body["market"] == "KR"   # Task 4 에서 KR 기본으로 확정
```

여기에 새 테스트 하나를 파일 끝에 더한다.

```python
def test_markets_are_cached_independently(monkeypatch):
    """KR 을 갱신해도 US 빌더는 불리지 않는다 — 안 보는 시장에 외부 호출을 하지 않는다."""
    _ok_fetch(monkeypatch)
    calls = {"n": 0}
    orig = market_us.BUILDERS["indices"]
    def counting():
        calls["n"] += 1
        return orig()
    monkeypatch.setitem(market_us.BUILDERS, "indices", counting)
    market.refresh("US", now=1000.0)
    assert calls["n"] == 1
    # 같은 블록 이름이라도 시장이 다르면 캐시가 따로다
    assert "US:indices" in market._cache.values
```

- [ ] **Step 2: 실패하는 걸 확인한다**

Run: `cd backend && uv run pytest tests/test_market.py -q`
Expected: FAIL — `TypeError: get_market() takes ... ` / `ModuleNotFoundError: No module named 'app.market_us'`

- [ ] **Step 3: `market_us.py`를 만든다**

`backend/app/market.py`의 상수와 `_build_*` 함수를 그대로 옮긴다. 값은 한 글자도 바꾸지 않는다.

```python
"""미국 시장(finviz 구성) 상수와 블록 빌더.

`market.py`가 시장 둘을 다루게 되면서 상수가 두 배가 되어 시장별 파일로 나눴다.
엔진(캐시·TTL·실패 격리)은 `market.py`에 있고 이 파일은 **무엇을 어떻게 받는지**만 안다.
빌더는 예외를 그대로 올린다 — 격리는 엔진 몫이다.
"""
from __future__ import annotations

from app import market_fetch as fetch
from app.market import _chg, _pct

SESSION = {"tz": "America/New_York", "open": "09:30", "close": "16:00"}

TTL_SEC = {
    "indices": 5 * 60,
    "futures": 5 * 60,
    "forex_bonds": 5 * 60,
    "signals_up": 10 * 60,
    "signals_down": 10 * 60,
    "heatmap": 15 * 60,
    "headlines": 15 * 60,
}

INDICES = [("S&P 500", "^GSPC"), ("NASDAQ", "^IXIC"), ("DOW", "^DJI")]
FUTURES = [("Crude Oil", "CL=F", 2), ("Natural Gas", "NG=F", 4), ("Gold", "GC=F", 2),
           ("Dow", "YM=F", 2), ("S&P 500", "ES=F", 2), ("Nasdaq 100", "NQ=F", 2),
           ("Russell 2000", "RTY=F", 2)]
FOREX_BONDS = [("EUR/USD", "EURUSD=X", 4), ("USD/JPY", "JPY=X", 2), ("GBP/USD", "GBPUSD=X", 4),
               ("BTC/USD", "BTC-USD", 2), ("5-Year Treasury", "^FVX", 3),
               ("10-Year Treasury", "^TNX", 3), ("30-Year Treasury", "^TYX", 3)]
SCREENS_UP = [("day_gainers", "Top Gainers", 6), ("small_cap_gainers", "Small Cap Gainers", 5),
              ("most_actives", "Most Active", 4), ("growth_technology_stocks", "Growth Tech", 4)]
SCREENS_DOWN = [("day_losers", "Top Losers", 6), ("most_shorted_stocks", "Most Shorted", 5),
                ("undervalued_large_caps", "Undervalued Large", 4),
                ("aggressive_small_caps", "Aggressive Small", 4)]
HEATMAP_SECTORS: dict[str, list[tuple[str, float]]] = {
    "TECHNOLOGY": [("NVDA", 48), ("MSFT", 36), ("AAPL", 34), ("AVGO", 17), ("ORCL", 7), ("AMD", 5), ("CRM", 3), ("CSCO", 3), ("PLTR", 4), ("MU", 3), ("ADBE", 2), ("NOW", 2), ("INTU", 2), ("QCOM", 2), ("TXN", 2), ("MRVL", 1.5), ("ANET", 1.5), ("AMAT", 1.5), ("LRCX", 1.3), ("KLAC", 1.2), ("IBM", 2)],
    "COMMUNICATION SERVICES": [("GOOGL", 22), ("GOOG", 18), ("META", 17), ("NFLX", 5), ("DIS", 2), ("TMUS", 2), ("VZ", 1.8), ("T", 1.8), ("CMCSA", 1.5)],
    "CONSUMER CYCLICAL": [("AMZN", 24), ("TSLA", 14), ("HD", 4), ("MCD", 2.2), ("BKNG", 2), ("TJX", 1.5), ("LOW", 1.5), ("NKE", 1), ("SBUX", 1), ("ROST", 0.8)],
    "FINANCIAL": [("BRK-B", 11), ("JPM", 9), ("V", 7), ("MA", 6), ("BAC", 4), ("WFC", 3), ("GS", 2.5), ("MS", 2.3), ("AXP", 2), ("C", 1.8), ("SPGI", 1.8), ("BLK", 1.6), ("SCHW", 1.6), ("COIN", 0.9), ("PGR", 1.5), ("ALL", 0.7)],
    "HEALTHCARE": [("LLY", 9), ("JNJ", 5), ("ABBV", 4), ("UNH", 3.5), ("MRK", 2.6), ("ABT", 2.4), ("TMO", 2.2), ("ISRG", 2), ("AMGN", 1.8), ("PFE", 1.6), ("MRNA", 0.4), ("DHR", 1.6), ("GILD", 1.5), ("BSX", 1.5), ("VRTX", 1.3)],
    "INDUSTRIALS": [("GE", 3.2), ("CAT", 2.4), ("RTX", 2.2), ("BA", 1.8), ("HON", 1.6), ("UNP", 1.5), ("ETN", 1.5), ("DE", 1.4), ("LMT", 1.1), ("UBER", 1.8), ("GEV", 1.4), ("HWM", 0.8)],
    "CONSUMER DEFENSIVE": [("WMT", 7), ("COST", 4.5), ("PG", 4), ("KO", 3), ("PEP", 2.2), ("PM", 2.4), ("MDLZ", 1), ("MO", 1), ("CL", 0.8)],
    "ENERGY": [("XOM", 5), ("CVX", 3), ("COP", 1.3), ("EOG", 0.8), ("OKE", 0.6), ("WMB", 0.8)],
    "UTILITIES": [("NEE", 1.6), ("SO", 1), ("DUK", 1), ("CEG", 1), ("VST", 0.8)],
    "REAL ESTATE": [("PLD", 1.1), ("AMT", 0.9), ("WELL", 0.9), ("EQIX", 0.8), ("IRM", 0.4)],
    "BASIC MATERIALS": [("LIN", 2.2), ("SHW", 0.9), ("APD", 0.7), ("ECL", 0.7), ("FCX", 0.7), ("NEM", 0.7)],
}
HEADLINES_SYMBOL = "^GSPC"
HEADLINES_COUNT = 8


def _build_indices() -> list[dict]:
    out = []
    for name, sym in INDICES:
        d = fetch.intraday(sym)
        out.append({"name": name, "symbol": sym, "last": d["last"],
                    "prev_close": d["prev_close"],
                    "change": _chg(d["last"], d["prev_close"]),
                    "change_pct": _pct(d["last"], d["prev_close"]),
                    "candles": d["candles"]})
    return out


def _build_quotes(spec: list[tuple[str, str, int]]) -> list[dict]:
    q = fetch.daily_closes([s for _, s, _ in spec])
    out = []
    for name, sym, dec in spec:
        v = q.get(sym) or {}
        last, prev = v.get("last"), v.get("prev_close")
        out.append({"name": name, "symbol": sym, "last": last, "change": _chg(last, prev),
                    "change_pct": _pct(last, prev), "decimals": dec})
    return out


def _build_signals(spec: list[tuple[str, str, int]]) -> list[dict]:
    out = []
    for screen_name, label, n in spec:
        for row in fetch.screen(screen_name, count=n)[:n]:
            out.append({**row, "name": None, "signal": label})
    return out


def _build_heatmap() -> list[dict]:
    symbols = [s for rows in HEATMAP_SECTORS.values() for s, _ in rows]
    q = fetch.daily_closes(symbols)
    sectors = []
    for name, rows in HEATMAP_SECTORS.items():
        tickers = []
        for sym, w in rows:
            v = q.get(sym) or {}
            tickers.append({"symbol": sym, "name": None, "weight": w,
                            "change_pct": _pct(v.get("last"), v.get("prev_close"))})
        sectors.append({"name": name, "tickers": tickers})
    return sectors


def _build_headlines() -> list[dict]:
    return fetch.news(HEADLINES_SYMBOL, limit=HEADLINES_COUNT)


BUILDERS = {
    "indices": _build_indices,
    "futures": lambda: _build_quotes(FUTURES),
    "forex_bonds": lambda: _build_quotes(FOREX_BONDS),
    "signals_up": lambda: _build_signals(SCREENS_UP),
    "signals_down": lambda: _build_signals(SCREENS_DOWN),
    "heatmap": _build_heatmap,
    "headlines": _build_headlines,
}
```

`_build_signals`와 `_build_heatmap`에 `"name": None`이 붙은 것이 유일한 동작 변경이다. 계약상 추가 필드이며 프론트는 `name ?? symbol`로 읽는다.

- [ ] **Step 4: `market.py`를 엔진만 남긴다**

```python
"""시장 데이터 조립 엔진 — 캐시·TTL·실패 격리. **어느 시장인지는 모른다.**

시장별 상수와 빌더는 `market_us.py` / `market_kr.py`에 있고 여기서는 `MARKETS`로만 본다.
규칙:
1. **외부 호출은 시장 모듈의 빌더가 한다.** 엔진은 네트워크를 모른다.
2. **블록별 실패 격리.** 한 블록이 죽어도 나머지는 나간다. 실패한 블록은 이전 값을 유지하고
   `failed`에 이름만 올린다 — 값을 지우면 화면이 "원래 없는 것"과 "이번에 못 받은 것"을
   구분 못 한다.
3. **캐시 키는 `"{market}:{block}"`.** 시장별로 TTL·백오프·백그라운드 갱신이 따로 돈다.
   US 를 아무도 안 보면 US 외부 호출은 일어나지 않는다.
4. **DB 를 쓰지 않는다.** 시장 데이터는 개인 자료가 아니고 재시작 후 다시 받으면 그만이다.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

# 실패한 블록을 바로 다시 때리지 않는다 — 소스가 막힌 날 매 요청마다 재시도하면
# 응답이 블록 수 × 타임아웃만큼 느려진다.
FAIL_BACKOFF_SEC = 3 * 60
MAJOR_NEWS_COUNT = 16
# 시장이 안 주는 블록은 이 기본값으로 나간다 — 프론트가 필드 유무를 분기하지 않게.
EMPTY_BLOCKS = ("indices", "futures", "forex_bonds", "signals_up", "signals_down",
                "heatmap", "headlines", "investors")


def _pct(last, prev) -> float | None:
    if last is None or prev in (None, 0):
        return None
    return round((last / prev - 1) * 100, 2)


def _chg(last, prev) -> float | None:
    if last is None or prev is None:
        return None
    return last - prev


def major_news_from_heatmap(sectors: list[dict], n: int = MAJOR_NEWS_COUNT) -> list[dict]:
    """finviz 'Major News' 는 큰 뉴스가 난 종목의 등락 목록이다. 뉴스 소스 없이도 같은
    목적을 채우는 근사: 대형주 중 |등락| 큰 순. 히트맵 블록을 재사용해 호출이 없다."""
    rows = [t for s in sectors for t in s["tickers"] if t.get("change_pct") is not None]
    rows.sort(key=lambda t: -abs(t["change_pct"]))
    return [{"symbol": t["symbol"], "name": t.get("name"), "change_pct": t["change_pct"]}
            for t in rows[:n]]


# 순환 import 를 피하려고 파일 끝에서 채운다 — 시장 모듈이 `_pct`/`_chg` 를 쓴다.
MARKETS: dict = {}


def _module(market: str):
    m = MARKETS.get(market)
    if m is None:
        raise KeyError(market)
    return m


class _Cache:
    def __init__(self):
        self.lock = threading.Lock()
        self.values: dict[str, object] = {}
        self.fetched_at: dict[str, float] = {}     # 성공 시각(epoch)
        self.attempted_at: dict[str, float] = {}   # 마지막 시도 시각
        self.errors: dict[str, str] = {}
        self.refreshing: set[str] = set()


_cache = _Cache()


def reset_cache():
    """테스트용."""
    global _cache
    _cache = _Cache()


def _key(market: str, block: str) -> str:
    return f"{market}:{block}"


def _is_stale(market: str, block: str, now: float) -> bool:
    ttl = _module(market).TTL_SEC[block]
    return now - _cache.fetched_at.get(_key(market, block), 0) > ttl


def _in_backoff(market: str, block: str, now: float) -> bool:
    k = _key(market, block)
    return k in _cache.errors and now - _cache.attempted_at.get(k, 0) < FAIL_BACKOFF_SEC


def _refresh_block(market: str, block: str, now: float) -> None:
    k = _key(market, block)
    _cache.attempted_at[k] = now
    try:
        value = _module(market).BUILDERS[block]()
    except Exception as e:  # noqa: BLE001 — 어떤 예외든 블록 하나로 격리
        with _cache.lock:
            _cache.errors[k] = f"{type(e).__name__}: {e}"[:200]
        return
    with _cache.lock:
        _cache.values[k] = value
        _cache.fetched_at[k] = now   # 주입된 now 기준 — 테스트가 시계를 돌릴 수 있게
        _cache.errors.pop(k, None)


def refresh(market: str, force: bool = False, now: float | None = None) -> None:
    """그 시장의 낡은 블록만(또는 전부) 순서대로 갱신. 동기 — 호출자가 스레드를 정한다."""
    now = time.time() if now is None else now
    for block in _module(market).BUILDERS:
        if force or (_is_stale(market, block, now) and not _in_backoff(market, block, now)):
            _refresh_block(market, block, now)


def _refresh_in_background(market: str):
    with _cache.lock:
        if market in _cache.refreshing:
            return
        _cache.refreshing.add(market)
    try:
        refresh(market)
    finally:
        with _cache.lock:
            _cache.refreshing.discard(market)


def get_market(market: str, now: float | None = None) -> dict:
    """대시보드 응답. 그 시장의 캐시가 비어 있으면 동기로 채우고(첫 방문 한 번), 이후로는
    낡은 값을 즉시 돌려주면서 백그라운드로 갱신한다(stale-while-revalidate)."""
    now = time.time() if now is None else now
    mod = _module(market)
    blocks = list(mod.BUILDERS)
    if not any(_key(market, b) in _cache.values for b in blocks):
        refresh(market, now=now)
    elif any(_is_stale(market, b, now) and not _in_backoff(market, b, now) for b in blocks):
        threading.Thread(target=_refresh_in_background, args=(market,), daemon=True).start()

    with _cache.lock:
        values = {b: _cache.values.get(_key(market, b)) for b in blocks}
        failed = sorted(k.split(":", 1)[1] for k in _cache.errors if k.startswith(f"{market}:"))
        times = [t for k, t in _cache.fetched_at.items() if k.startswith(f"{market}:")]
    oldest = min(times) if times else None
    heatmap = values.get("heatmap") or []
    out = {b: values.get(b) or [] for b in EMPTY_BLOCKS}
    out.update({
        "market": market,
        "session": mod.SESSION,
        "heatmap": heatmap,
        "major_news": major_news_from_heatmap(heatmap),
        # 블록 중 가장 오래된 성공 시각 — 화면은 이 한 값으로 "기준 n분 전"을 보여준다
        "fetched_at": (datetime.fromtimestamp(oldest).isoformat(timespec="seconds")
                       if oldest else None),
        "failed": failed,
    })
    return out


from app import market_us  # noqa: E402 — 위 정의를 시장 모듈이 import 한다

MARKETS["US"] = market_us
```

`_cache.values`가 시장별이므로 "캐시가 비었나"는 그 시장의 키로 판단한다. `EMPTY_BLOCKS`는 US 응답에도 `investors: []`를 채워 프론트가 필드 유무를 분기하지 않게 한다.

- [ ] **Step 5: `market_api.py`가 새 시그니처를 부르게 한다**

```python
@router.get("/market")
async def get_market():
    return await asyncio.to_thread(market.get_market, "US")


@router.post("/market/refresh")
async def refresh_market():
    await asyncio.to_thread(lambda: market.refresh("US", force=True))
    return await asyncio.to_thread(market.get_market, "US")
```

Task 4 에서 `?market=` 을 붙이고 기본값을 KR 로 바꾼다. 지금은 US 고정으로 두어 이 태스크의 변경 범위를 구조에만 묶는다.

- [ ] **Step 6: 통과하는 걸 확인한다**

Run: `cd backend && uv run pytest -q`
Expected: PASS — 356 passed (기존 355 + 새 테스트 1). `test_market.py`의 US 단언이 전부 그대로 통과해야 한다. 하나라도 값이 달라졌다면 상수를 옮기다 틀린 것이다.

- [ ] **Step 7: 커밋**

```bash
git add backend/app/market.py backend/app/market_us.py backend/app/market_api.py backend/tests/test_market.py
git commit -m "refactor: market.py를 시장 무관 엔진으로 나누고 US 상수를 market_us.py로 옮긴다"
```

---

### Task 2: `sources/naver.py`에 시장 단위 함수 4개

**Files:**
- Modify: `backend/app/sources/naver.py`
- Test: `backend/tests/test_naver_market.py` (신규)

**Interfaces:**
- Consumes: 없음 (외부 API만)
- Produces:
  - `naver._num(v) -> float | None`
  - `naver.index_basic(code: str) -> dict` → `{"last", "prev_close", "change", "change_pct", "traded_at"}`
  - `naver.ranking(kind: str, market: str, n: int) -> list[dict]` → `[{"symbol", "name", "last", "change_pct", "volume", "market_value", "is_etf"}]`
  - `naver.investor_trend(market: str) -> dict` → `{"date", "personal", "foreign", "institution"}`
  - `naver.market_index(category: str, code: str) -> dict` → `{"last", "prev_close", "change", "change_pct", "traded_at"}`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/tests/test_naver_market.py`:

```python
"""네이버 시장 단위 어댑터 — 고정 JSON 픽스처로 파싱만 검증한다.

실호출은 smoke 로 따로 둔다. 비공식 API 라 스키마가 바뀌면 smoke 가 먼저 깨진다.
"""
import pytest

from app.sources import naver


def test_num_parses_naver_strings():
    assert naver._num("281,500") == 281500.0
    assert naver._num("+2,481") == 2481.0
    assert naver._num("-11,652") == -11652.0
    assert naver._num("3.8530") == 3.853
    assert naver._num("N/A") is None
    assert naver._num("") is None
    assert naver._num(None) is None
    assert naver._num(1234) == 1234.0


def test_index_basic(monkeypatch):
    monkeypatch.setattr(naver, "_get", lambda path, params=None: {
        "closePrice": "6,912.95", "compareToPreviousClosePrice": "60.37",
        "fluctuationsRatio": "0.88", "localTradedAt": "2026-08-21T18:59:00+09:00"})
    d = naver.index_basic("KOSPI")
    assert d["last"] == 6912.95
    assert d["change"] == 60.37
    assert d["change_pct"] == 0.88
    # 전일 종가는 응답에 없다 — 현재가에서 등락을 빼서 만든다
    assert d["prev_close"] == pytest.approx(6852.58)
    assert d["traded_at"] == "2026-08-21T18:59:00+09:00"


def test_index_basic_falling_sign(monkeypatch):
    """하락일 때 compareToPreviousClosePrice 에 이미 음수 부호가 온다 —
    fluctuationsType 을 보고 부호를 또 뒤집으면 두 번 뒤집힌다."""
    monkeypatch.setattr(naver, "_get", lambda path, params=None: {
        "closePrice": "6,800.00", "compareToPreviousClosePrice": "-52.95",
        "fluctuationsRatio": "-0.77", "localTradedAt": "2026-08-21T18:59:00+09:00"})
    d = naver.index_basic("KOSPI")
    assert d["change"] == -52.95 and d["change_pct"] == -0.77
    assert d["prev_close"] == pytest.approx(6852.95)


def _ranking_payload():
    return {"stocks": [
        {"itemCode": "005930", "stockName": "삼성전자", "stockEndType": "stock",
         "closePrice": "281,500", "fluctuationsRatio": "3.87",
         "accumulatedTradingVolume": "27,672,192", "marketValue": "16,457,274"},
        {"itemCode": "069500", "stockName": "KODEX 200", "stockEndType": "etf",
         "closePrice": "44,120", "fluctuationsRatio": "-0.35",
         "accumulatedTradingVolume": "1,000,000", "marketValue": "257,848"},
        {"itemCode": "000660", "stockName": "SK하이닉스", "stockEndType": "stock",
         "closePrice": "1,730,000", "fluctuationsRatio": "N/A",
         "accumulatedTradingVolume": "N/A", "marketValue": "12,637,518"},
    ]}


def test_ranking(monkeypatch):
    monkeypatch.setattr(naver, "_get", lambda path, params=None: _ranking_payload())
    rows = naver.ranking("up", "KOSPI", 3)
    assert rows[0] == {"symbol": "005930", "name": "삼성전자", "last": 281500.0,
                       "change_pct": 3.87, "volume": 27672192.0,
                       "market_value": 16457274.0, "is_etf": False}
    assert rows[1]["is_etf"] is True
    # 값이 N/A 인 칸만 None 이 되고 행은 살아남는다
    assert rows[2]["change_pct"] is None and rows[2]["volume"] is None
    assert rows[2]["last"] == 1730000.0


def test_ranking_builds_path(monkeypatch):
    seen = {}
    def fake(path, params=None):
        seen["path"], seen["params"] = path, params
        return _ranking_payload()
    monkeypatch.setattr(naver, "_get", fake)
    naver.ranking("marketValue", "KOSDAQ", 50)
    assert seen["path"] == "/stocks/marketValue/KOSDAQ"
    assert seen["params"] == {"page": 1, "pageSize": 50}


def test_ranking_rejects_unknown_kind():
    with pytest.raises(ValueError):
        naver.ranking("../secret", "KOSPI", 5)


def test_investor_trend(monkeypatch):
    monkeypatch.setattr(naver, "_get", lambda path, params=None: {
        "bizdate": "20260821", "personalValue": "-11,652",
        "foreignValue": "-1,760", "institutionalValue": "+2,481"})
    d = naver.investor_trend("KOSPI")
    assert d == {"date": "2026-08-21", "personal": -11652.0,
                 "foreign": -1760.0, "institution": 2481.0}


def test_market_index(monkeypatch):
    monkeypatch.setattr(naver, "_get_front", lambda path, params=None: {
        "isSuccess": True,
        "result": {"closePrice": "1,388.00", "fluctuations": "-6.80",
                   "fluctuationsRatio": "-0.49",
                   "localTradedAt": "2026-08-22T08:50:38+09:00"}})
    d = naver.market_index("exchange", "FX_USDKRW")
    assert d["last"] == 1388.0 and d["change"] == -6.8 and d["change_pct"] == -0.49
    assert d["prev_close"] == pytest.approx(1394.8)
    assert d["traded_at"] == "2026-08-22T08:50:38+09:00"


def test_market_index_raises_when_not_success(monkeypatch):
    """isSuccess=false 를 그냥 파싱하면 전부 None 인 행이 화면에 남는다 —
    예외로 올려 블록을 failed 로 떨어뜨린다."""
    monkeypatch.setattr(naver, "_get_front", lambda path, params=None:
                        {"isSuccess": False, "message": "nope", "result": None})
    with pytest.raises(ValueError):
        naver.market_index("bond", "KR3YT=RR")


@pytest.mark.smoke
def test_smoke_naver_market_endpoints():
    """비공식 API 스키마 변경 감지용. 기본 실행에서는 제외된다."""
    assert naver.index_basic("KOSPI")["last"] is not None
    rows = naver.ranking("up", "KOSPI", 2)
    assert len(rows) == 2 and rows[0]["symbol"].isalnum()
    assert naver.investor_trend("KOSPI")["date"]
    assert naver.market_index("exchange", "FX_USDKRW")["last"] is not None
    assert naver.market_index("bond", "KR3YT=RR")["last"] is not None
```

- [ ] **Step 2: 실패하는 걸 확인한다**

Run: `cd backend && uv run pytest tests/test_naver_market.py -q`
Expected: FAIL — `AttributeError: module 'app.sources.naver' has no attribute '_num'`

- [ ] **Step 3: 구현한다**

`backend/app/sources/naver.py` 파일 끝에 덧붙인다. 기존 종목 단위 함수(`integration`, `finance`, `news`, `research`)는 건드리지 않는다.

```python
# ── 시장 단위(대시보드) ────────────────────────────────────────────────────────
# 종목 단위 함수들과 달리 여기서는 **숫자로 바꿔서** 돌려준다. 네이버는 "281,500" 처럼
# 콤마가 든 문자열을 주는데, 이걸 그대로 올리면 빌더마다 같은 파싱을 반복하게 된다.

FRONT_BASE = "https://m.stock.naver.com/front-api"
RANKING_KINDS = ("up", "down", "searchTop", "marketValue")


def _num(v) -> float | None:
    """'281,500' → 281500.0, '+2,481' → 2481.0, 'N/A'·'' → None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("+", "").strip()
    if not s or s.upper() == "N/A":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _get_front(path: str, params: dict | None = None):
    r = requests.get(f"{FRONT_BASE}{path}", params=params,
                     headers={"User-Agent": UA, "Accept": "application/json"},
                     timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def index_basic(code: str) -> dict:
    """지수 현재가. code: KOSPI | KOSDAQ | KPI200.

    전일 종가는 응답에 없어 `last - change` 로 만든다. 등락 부호는
    `compareToPreviousClosePrice` 에 이미 들어 있으므로 `fluctuationsType` 을 보지 않는다.
    """
    d = _get(f"/index/{code}/basic")
    last = _num(d.get("closePrice"))
    change = _num(d.get("compareToPreviousClosePrice"))
    return {"last": last, "change": change,
            "change_pct": _num(d.get("fluctuationsRatio")),
            "prev_close": None if last is None or change is None else last - change,
            "traded_at": d.get("localTradedAt")}


def ranking(kind: str, market: str, n: int) -> list[dict]:
    """순위 목록. kind: up|down|searchTop|marketValue, market: KOSPI|KOSDAQ.

    `is_etf` 를 같이 준다 — 시총 상위에는 KODEX·TIGER 가 섞여 있고 히트맵은 회사만 그린다.
    ETF 를 여기서 지우지 않는 이유는 시그널 표에서는 보여줘도 되기 때문이다. 거르는 판단은
    부르는 쪽이 한다.
    """
    if kind not in RANKING_KINDS:
        raise ValueError(f"unknown ranking kind: {kind}")
    d = _get(f"/stocks/{kind}/{market}", {"page": 1, "pageSize": n})
    out = []
    for s in (d or {}).get("stocks", []):
        code = s.get("itemCode")
        if not code:
            continue
        out.append({"symbol": code, "name": s.get("stockName"),
                    "last": _num(s.get("closePrice")),
                    "change_pct": _num(s.get("fluctuationsRatio")),
                    "volume": _num(s.get("accumulatedTradingVolume")),
                    "market_value": _num(s.get("marketValue")),
                    "is_etf": s.get("stockEndType") == "etf"})
    return out


def investor_trend(market: str) -> dict:
    """투자자별 순매수(억원). market: KOSPI | KOSDAQ.

    장 마감 후 집계라 `bizdate` 가 전일일 수 있다 — 날짜를 같이 올려 화면이
    "오늘 수급"으로 읽히지 않게 한다.
    """
    d = _get(f"/index/{market}/trend")
    biz = str(d.get("bizdate") or "")
    date = f"{biz[:4]}-{biz[4:6]}-{biz[6:8]}" if len(biz) == 8 else None
    return {"date": date, "personal": _num(d.get("personalValue")),
            "foreign": _num(d.get("foreignValue")),
            "institution": _num(d.get("institutionalValue"))}


def market_index(category: str, code: str) -> dict:
    """환율·국채. category: exchange | bond. code: FX_USDKRW, KR3YT=RR …"""
    d = _get_front("/marketIndex/productDetail",
                   {"category": category, "reutersCode": code})
    if not d.get("isSuccess") or not d.get("result"):
        raise ValueError(f"naver marketIndex failed: {code} {d.get('message')}")
    r = d["result"]
    last = _num(r.get("closePrice"))
    change = _num(r.get("fluctuations"))
    return {"last": last, "change": change,
            "change_pct": _num(r.get("fluctuationsRatio")),
            "prev_close": None if last is None or change is None else last - change,
            "traded_at": r.get("localTradedAt")}
```

- [ ] **Step 4: 통과하는 걸 확인한다**

Run: `cd backend && uv run pytest tests/test_naver_market.py -q`
Expected: PASS — 9 passed, 1 deselected (smoke)

실호출도 한 번 확인한다. Run: `cd backend && uv run pytest tests/test_naver_market.py -m smoke -q`
Expected: PASS (네트워크 필요)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/sources/naver.py backend/tests/test_naver_market.py
git commit -m "feat: 네이버 시장 단위 어댑터 — 지수·순위·수급·환율/국채"
```

---

### Task 3: `market_kr.py` 상수와 빌더

**Files:**
- Create: `backend/app/market_kr.py`
- Modify: `backend/app/market.py` (끝에 `MARKETS["KR"]` 등록)
- Test: `backend/tests/test_market_kr.py` (신규)

**Interfaces:**
- Consumes: Task 2 의 `naver.index_basic/ranking/investor_trend/market_index`, `market_fetch.intraday/daily_closes/news`, Task 1 의 `market._pct/_chg`
- Produces: `market_kr.SESSION/TTL_SEC/BUILDERS/SECTOR_OF/SECTOR_FALLBACK/SIGNALS_UP/SIGNALS_DOWN/FOREX_BONDS`, `market.MARKETS["KR"]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/tests/test_market_kr.py`:

```python
"""market_kr.py — 한국 블록 조립. naver·market_fetch 를 monkeypatch 해 네트워크 없이 돈다."""
import pytest

from app import market, market_fetch, market_kr
from app.sources import naver


@pytest.fixture(autouse=True)
def fresh_cache():
    market.reset_cache()
    yield
    market.reset_cache()


def _ok(monkeypatch):
    monkeypatch.setattr(market_fetch, "intraday", lambda sym: {
        "last": 6900.0, "prev_close": 6850.0,
        "candles": [{"o": 6850, "h": 6960, "l": 6840, "c": 6900, "v": 1000}]})
    monkeypatch.setattr(market_fetch, "daily_closes", lambda syms: {
        s: {"last": 4.5, "prev_close": 4.4} for s in syms})
    monkeypatch.setattr(market_fetch, "news", lambda sym, limit=8: [
        {"title": "kospi headline", "source": "Y", "url": "u",
         "published_at": "2026-08-21T00:00:00Z"}])
    monkeypatch.setattr(naver, "index_basic", lambda code: {
        "last": 6912.95, "prev_close": 6852.58, "change": 60.37,
        "change_pct": 0.88, "traded_at": "2026-08-21T18:59:00+09:00"})
    monkeypatch.setattr(naver, "market_index", lambda cat, code: {
        "last": 1388.0, "prev_close": 1394.8, "change": -6.8,
        "change_pct": -0.49, "traded_at": "2026-08-22T08:50:38+09:00"})
    monkeypatch.setattr(naver, "investor_trend", lambda m: {
        "date": "2026-08-21", "personal": -11652.0,
        "foreign": -1760.0, "institution": 2481.0})
    monkeypatch.setattr(naver, "ranking", lambda kind, mkt, n: [
        {"symbol": "005930", "name": "삼성전자", "last": 281500.0, "change_pct": 3.87,
         "volume": 27672192.0, "market_value": 16457274.0, "is_etf": False},
        {"symbol": "069500", "name": "KODEX 200", "last": 44120.0, "change_pct": -0.35,
         "volume": 1000000.0, "market_value": 257848.0, "is_etf": True},
        {"symbol": "005935", "name": "삼성전자우", "last": 230000.0, "change_pct": 1.2,
         "volume": 500000.0, "market_value": 1660908.0, "is_etf": False},
        {"symbol": "999999", "name": "듣보종목", "last": 1000.0, "change_pct": 0.5,
         "volume": 100.0, "market_value": 50000.0, "is_etf": False},
    ][:n])


def test_kr_indices_use_naver_price_and_yf_candles(monkeypatch):
    _ok(monkeypatch)
    m = market.get_market("KR", now=1000.0)
    assert m["market"] == "KR"
    assert m["session"] == {"tz": "Asia/Seoul", "open": "09:00", "close": "15:30"}
    names = [i["name"] for i in m["indices"]]
    assert names == ["코스피", "코스닥", "코스피 200"]
    i0 = m["indices"][0]
    assert i0["symbol"] == "^KS11"
    assert i0["last"] == 6912.95 and i0["change_pct"] == 0.88   # 가격은 네이버
    assert len(i0["candles"]) == 1                               # 캔들은 yfinance
    assert m["futures"] == []                                    # KR 선물 소스 없음


def test_kr_indices_fall_back_to_candles_when_naver_dies(monkeypatch):
    _ok(monkeypatch)
    def boom(code):
        raise RuntimeError("naver blocked")
    monkeypatch.setattr(naver, "index_basic", boom)
    m = market.get_market("KR", now=1000.0)
    assert "indices" not in m["failed"]              # 블록이 살아야 한다
    assert m["indices"][0]["last"] == 6900.0         # 5분봉에서 계산
    assert m["indices"][0]["change_pct"] == 0.73


def test_kr_indices_fail_when_both_sources_die(monkeypatch):
    _ok(monkeypatch)
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(naver, "index_basic", boom)
    monkeypatch.setattr(market_fetch, "intraday", boom)
    m = market.get_market("KR", now=1000.0)
    assert "indices" in m["failed"] and m["indices"] == []


def test_kr_heatmap_drops_etf_and_preferred(monkeypatch):
    _ok(monkeypatch)
    m = market.get_market("KR", now=1000.0)
    codes = [t["symbol"] for s in m["heatmap"] for t in s["tickers"]]
    assert "005930" in codes
    assert "069500" not in codes      # ETF
    assert "005935" not in codes      # 우선주 (코드가 0 으로 안 끝나고 이름이 '우')
    assert "999999" in codes          # 매핑 없는 종목은 남되


def test_kr_heatmap_unmapped_goes_to_기타(monkeypatch):
    _ok(monkeypatch)
    m = market.get_market("KR", now=1000.0)
    by_sector = {s["name"]: [t["symbol"] for t in s["tickers"]] for s in m["heatmap"]}
    assert "005930" in by_sector["반도체·전자부품"]
    assert "999999" in by_sector[market_kr.SECTOR_FALLBACK]
    # 칸 크기는 시총(억원)
    tk = next(t for s in m["heatmap"] for t in s["tickers"] if t["symbol"] == "005930")
    assert tk["weight"] == 16457274.0 and tk["name"] == "삼성전자"


def test_kr_heatmap_sectors_sorted_by_total_market_value(monkeypatch):
    _ok(monkeypatch)
    m = market.get_market("KR", now=1000.0)
    totals = [sum(t["weight"] for t in s["tickers"]) for s in m["heatmap"]]
    assert totals == sorted(totals, reverse=True)


def test_kr_signals_carry_name_and_label(monkeypatch):
    _ok(monkeypatch)
    m = market.get_market("KR", now=1000.0)
    r = m["signals_up"][0]
    assert r["symbol"] == "005930" and r["name"] == "삼성전자"
    assert r["signal"] == market_kr.SIGNALS_UP[0][2]
    assert {"last", "change_pct", "volume"} <= set(r)


def test_kr_investors(monkeypatch):
    _ok(monkeypatch)
    m = market.get_market("KR", now=1000.0)
    assert [r["market"] for r in m["investors"]] == ["KOSPI", "KOSDAQ"]
    assert m["investors"][0] == {"market": "KOSPI", "date": "2026-08-21",
                                 "personal": -11652.0, "foreign": -1760.0,
                                 "institution": 2481.0}


def test_kr_forex_bonds_mixes_naver_and_yf(monkeypatch):
    _ok(monkeypatch)
    m = market.get_market("KR", now=1000.0)
    names = [r["name"] for r in m["forex_bonds"]]
    assert names == [n for n, _, _, _ in market_kr.FOREX_BONDS]
    usd = m["forex_bonds"][0]
    assert usd["last"] == 1388.0 and usd["decimals"] == 2       # 네이버
    us10 = m["forex_bonds"][-1]
    assert us10["last"] == 4.5 and us10["change_pct"] == 2.27   # yfinance


def test_kr_major_news_uses_names(monkeypatch):
    _ok(monkeypatch)
    m = market.get_market("KR", now=1000.0)
    assert m["major_news"][0]["name"] is not None


def test_sector_map_is_well_formed():
    """수기 매핑이라 오타가 나면 그 종목이 조용히 '기타'로 떨어진다 — 형태를 고정한다."""
    assert len(market_kr.SECTOR_OF) == 87       # 2026-08-22 KOSPI 시총 100 중 ETF·우선주 제외
    for code, sector in market_kr.SECTOR_OF.items():
        assert len(code) == 6, code             # 종목코드는 6자리 (0126Z0 처럼 문자가 섞이기도)
        assert sector.strip() == sector and sector, code
    # 폴백 이름을 실제 섹터로도 쓰면 "매핑 없음"과 "기타 업종"이 한 칸에 섞인다
    assert market_kr.SECTOR_FALLBACK not in set(market_kr.SECTOR_OF.values())
    # 대장주가 빠지면 히트맵 제일 큰 칸이 '기타'가 된다
    for code in ("005930", "000660", "005380", "105560"):
        assert code in market_kr.SECTOR_OF
```

- [ ] **Step 2: 실패하는 걸 확인한다**

Run: `cd backend && uv run pytest tests/test_market_kr.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.market_kr'`

- [ ] **Step 3: `market_kr.py`를 만든다**

```python
"""한국 시장 상수와 블록 빌더.

가격은 네이버(비공식 모바일 API), 캔들은 yfinance 로 받는다. 네이버에 5분봉이 없고
yfinance 에 국내 국채·투자자 수급이 없어 한쪽으로 통일할 수 없다.

빌더는 예외를 그대로 올린다 — 격리는 `market.py` 몫이다. 예외는 지수 블록으로,
네이버가 죽으면 캔들에서 값을 만들어 블록을 살린다(지수는 화면 최상단이라 빈 칸이 크다).
"""
from __future__ import annotations

import re

from app import market_fetch as fetch
from app.market import _chg, _pct
from app.sources import naver

SESSION = {"tz": "Asia/Seoul", "open": "09:00", "close": "15:30"}

# 미국판과 같은 기준: 장중 지수는 짧게, 구성종목 목록은 길게.
TTL_SEC = {
    "indices": 5 * 60,
    "forex_bonds": 5 * 60,
    "signals_up": 10 * 60,
    "signals_down": 10 * 60,
    "heatmap": 15 * 60,
    "investors": 30 * 60,   # 장 마감 후 하루 한 번 바뀐다
    "headlines": 15 * 60,
}

# (표시명, yfinance 심볼(5분봉), 네이버 코드(가격))
INDICES = [("코스피", "^KS11", "KOSPI"), ("코스닥", "^KQ11", "KOSDAQ"),
           ("코스피 200", "^KS200", "KPI200")]

# (표시명, 소스, 코드, 소수 자릿수). 소스 "yf" 는 market_fetch.daily_closes.
FOREX_BONDS = [("USD/KRW", "exchange", "FX_USDKRW", 2),
               ("JPY(100)/KRW", "exchange", "FX_JPYKRW", 2),
               ("국채 3년", "bond", "KR3YT=RR", 3),
               ("국채 10년", "bond", "KR10YT=RR", 3),
               ("미국채 10년", "yf", "^TNX", 3)]

# (naver ranking kind, 시장, 라벨, 개수)
SIGNALS_UP = [("up", "KOSPI", "상승 상위", 6), ("up", "KOSDAQ", "코스닥 상승", 5),
              ("searchTop", "KOSPI", "검색 상위", 4), ("marketValue", "KOSPI", "시총 상위", 4)]
SIGNALS_DOWN = [("down", "KOSPI", "하락 상위", 6), ("down", "KOSDAQ", "코스닥 하락", 5),
                ("searchTop", "KOSDAQ", "코스닥 검색", 4),
                ("marketValue", "KOSDAQ", "코스닥 시총", 4)]

HEATMAP_MARKET = "KOSPI"
HEATMAP_COUNT = 100          # 네이버 pageSize 상한. 걸러내면 87 종목쯤 남는다(실측 2026-08-22)
INVESTOR_MARKETS = ["KOSPI", "KOSDAQ"]
HEADLINES_SYMBOL = "^KS11"
HEADLINES_COUNT = 8
SECTOR_FALLBACK = "기타"

# 우선주 이름 규칙. 코드가 0 으로 끝나지 않는다는 조건과 **함께** 써야 한다 —
# 이름만 보면 '미래에셋대우'(006800, 보통주) 같은 회사가 걸린다.
_PREFERRED_NAME = re.compile(r"우[A-Z]?$")

# 시총 상위 100 종목의 섹터(2026-08-22 KOSPI 기준 수기 분류). 구성과 가중치는 네이버
# 실시간이고 여기 있는 건 섹터 이름뿐이라 유지 부담이 작다. 없는 코드는 "기타"로 떨어진다 —
# 그 칸이 커지면 매핑을 보탤 때다.
SECTOR_OF: dict[str, str] = {
    # 반도체·전자부품
    "005930": "반도체·전자부품", "000660": "반도체·전자부품", "402340": "반도체·전자부품",
    "009150": "반도체·전자부품", "042700": "반도체·전자부품", "007660": "반도체·전자부품",
    "011070": "반도체·전자부품",
    # 자동차
    "005380": "자동차", "000270": "자동차", "012330": "자동차", "086280": "자동차",
    "161390": "자동차",
    # 2차전지·소재
    "373220": "2차전지·소재", "006400": "2차전지·소재", "051910": "2차전지·소재",
    "003670": "2차전지·소재", "010130": "2차전지·소재", "005490": "2차전지·소재",
    "009830": "2차전지·소재",
    # 바이오·제약
    "207940": "바이오·제약", "068270": "바이오·제약", "0126Z0": "바이오·제약",
    "000100": "바이오·제약", "326030": "바이오·제약",
    # 금융
    "032830": "금융", "105560": "금융", "055550": "금융", "086790": "금융", "000810": "금융",
    "316140": "금융", "138040": "금융", "006800": "금융", "024110": "금융", "005830": "금융",
    "071050": "금융", "323410": "금융", "005940": "금융", "016360": "금융", "039490": "금융",
    # 조선·기계·방산
    "012450": "조선·기계·방산", "329180": "조선·기계·방산", "034020": "조선·기계·방산",
    "042660": "조선·기계·방산", "298040": "조선·기계·방산", "009540": "조선·기계·방산",
    "010140": "조선·기계·방산", "267250": "조선·기계·방산", "079550": "조선·기계·방산",
    "064350": "조선·기계·방산", "272210": "조선·기계·방산", "047810": "조선·기계·방산",
    "443060": "조선·기계·방산", "010120": "조선·기계·방산", "267260": "조선·기계·방산",
    "006260": "조선·기계·방산", "000150": "조선·기계·방산",
    # 인터넷·게임·콘텐츠
    "035420": "인터넷·게임·콘텐츠", "035720": "인터넷·게임·콘텐츠",
    "259960": "인터넷·게임·콘텐츠", "352820": "인터넷·게임·콘텐츠",
    # IT서비스·전자
    "066570": "IT서비스·전자", "018260": "IT서비스·전자", "064400": "IT서비스·전자",
    "307950": "IT서비스·전자",
    # 에너지·화학
    "096770": "에너지·화학", "010950": "에너지·화학", "047050": "에너지·화학",
    # 통신·유틸리티
    "017670": "통신·유틸리티", "030200": "통신·유틸리티", "032640": "통신·유틸리티",
    "015760": "통신·유틸리티",
    # 건설·운송
    "000720": "건설·운송", "028050": "건설·운송", "047040": "건설·운송", "011200": "건설·운송",
    "003490": "건설·운송", "180640": "건설·운송",
    # 소비재·유통
    "033780": "소비재·유통", "003230": "소비재·유통", "090430": "소비재·유통",
    "278470": "소비재·유통", "021240": "소비재·유통",
    # 지주
    "034730": "지주", "003550": "지주", "028260": "지주", "078930": "지주", "000880": "지주",
}


def _is_company(row: dict) -> bool:
    """히트맵에 그릴 대상인가. ETF 는 회사가 아니고, 우선주는 보통주와 같은 회사라
    큰 칸이 둘로 중복된다."""
    if row.get("is_etf"):
        return False
    code, name = row.get("symbol") or "", row.get("name") or ""
    return not (not code.endswith("0") and _PREFERRED_NAME.search(name))


def _build_indices() -> list[dict]:
    out = []
    for name, yf_sym, naver_code in INDICES:
        d = fetch.intraday(yf_sym)      # 실패하면 블록 전체가 실패한다 — 캔들이 없으면 그릴 게 없다
        try:
            q = naver.index_basic(naver_code)
        except Exception:  # noqa: BLE001 — 네이버가 막혀도 캔들로 지수는 그린다
            q = {}
        last = q.get("last") if q.get("last") is not None else d["last"]
        prev = q.get("prev_close") if q.get("prev_close") is not None else d["prev_close"]
        change = q.get("change") if q.get("change") is not None else _chg(last, prev)
        pct = q.get("change_pct") if q.get("change_pct") is not None else _pct(last, prev)
        out.append({"name": name, "symbol": yf_sym, "last": last, "prev_close": prev,
                    "change": change, "change_pct": pct, "candles": d["candles"]})
    return out


def _build_forex_bonds() -> list[dict]:
    yf_syms = [code for _, src, code, _ in FOREX_BONDS if src == "yf"]
    q = fetch.daily_closes(yf_syms) if yf_syms else {}
    out = []
    for name, src, code, dec in FOREX_BONDS:
        if src == "yf":
            v = q.get(code) or {}
            last, prev = v.get("last"), v.get("prev_close")
            row = {"last": last, "change": _chg(last, prev), "change_pct": _pct(last, prev)}
        else:
            row = naver.market_index(src, code)
        out.append({"name": name, "symbol": code, "last": row.get("last"),
                    "change": row.get("change"), "change_pct": row.get("change_pct"),
                    "decimals": dec})
    return out


def _build_signals(spec: list[tuple[str, str, str, int]]) -> list[dict]:
    out = []
    for kind, mkt, label, n in spec:
        for row in naver.ranking(kind, mkt, n)[:n]:
            out.append({"symbol": row["symbol"], "name": row["name"], "last": row["last"],
                        "change_pct": row["change_pct"], "volume": row["volume"],
                        "signal": label})
    return out


def _build_heatmap() -> list[dict]:
    rows = [r for r in naver.ranking("marketValue", HEATMAP_MARKET, HEATMAP_COUNT)
            if _is_company(r)]
    buckets: dict[str, list[dict]] = {}
    for r in rows:
        sector = SECTOR_OF.get(r["symbol"], SECTOR_FALLBACK)
        buckets.setdefault(sector, []).append(
            {"symbol": r["symbol"], "name": r["name"],
             "weight": r["market_value"] or 0.0, "change_pct": r["change_pct"]})
    # 섹터는 시총 합이 큰 것부터 — 트리맵이 큰 덩어리를 왼쪽 위에 놓는다
    return [{"name": s, "tickers": t} for s, t in
            sorted(buckets.items(), key=lambda kv: -sum(x["weight"] for x in kv[1]))]


def _build_investors() -> list[dict]:
    out = []
    for m in INVESTOR_MARKETS:
        d = naver.investor_trend(m)
        out.append({"market": m, **d})
    return out


def _build_headlines() -> list[dict]:
    return fetch.news(HEADLINES_SYMBOL, limit=HEADLINES_COUNT)


BUILDERS = {
    "indices": _build_indices,
    "forex_bonds": _build_forex_bonds,
    "signals_up": lambda: _build_signals(SIGNALS_UP),
    "signals_down": lambda: _build_signals(SIGNALS_DOWN),
    "heatmap": _build_heatmap,
    "investors": _build_investors,
    "headlines": _build_headlines,
}
```

`BUILDERS`에 `futures`가 없다 — 엔진의 `EMPTY_BLOCKS`가 `futures: []`를 채운다.

- [ ] **Step 4: `market.py`에 KR 을 등록한다**

`market.py` 맨 끝을 이렇게 바꾼다.

```python
from app import market_kr, market_us  # noqa: E402 — 위 정의를 시장 모듈이 import 한다

MARKETS["US"] = market_us
MARKETS["KR"] = market_kr
```

- [ ] **Step 5: 통과하는 걸 확인한다**

Run: `cd backend && uv run pytest tests/test_market_kr.py tests/test_market.py -q`
Expected: PASS — KR 12개 + US 기존 전부

- [ ] **Step 6: 커밋**

```bash
git add backend/app/market_kr.py backend/app/market.py backend/tests/test_market_kr.py
git commit -m "feat: 한국 시장 블록 — 지수·순위·히트맵·수급·환율/국채"
```

---

### Task 4: `?market=` 파라미터와 KR 기본값

**Files:**
- Modify: `backend/app/market_api.py`
- Test: `backend/tests/test_market_api.py` (신규)

**Interfaces:**
- Consumes: `market.MARKETS`, `market.get_market`, `market.refresh`
- Produces: `GET /api/market?market=KR|US`, `POST /api/market/refresh?market=KR|US` (둘 다 기본 `KR`)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/tests/test_market_api.py`:

```python
"""/api/market 라우트 — 시장 파라미터와 기본값."""
import pytest
from fastapi.testclient import TestClient

from app import market, market_fetch, market_kr, market_us
from app.main import create_app
from app.sources import naver


@pytest.fixture(autouse=True)
def fresh_cache():
    market.reset_cache()
    yield
    market.reset_cache()


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "t.db"), refresh_on_start=False)
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def stub_sources(monkeypatch):
    monkeypatch.setattr(market_fetch, "intraday", lambda sym: {
        "last": 100.0, "prev_close": 100.0, "candles": []})
    monkeypatch.setattr(market_fetch, "daily_closes", lambda syms: {})
    monkeypatch.setattr(market_fetch, "screen", lambda name, count=10: [])
    monkeypatch.setattr(market_fetch, "news", lambda sym, limit=8: [])
    monkeypatch.setattr(naver, "index_basic", lambda code: {
        "last": 6912.95, "prev_close": 6852.58, "change": 60.37,
        "change_pct": 0.88, "traded_at": None})
    monkeypatch.setattr(naver, "ranking", lambda kind, mkt, n: [])
    monkeypatch.setattr(naver, "market_index", lambda cat, code: {
        "last": 1388.0, "prev_close": 1394.8, "change": -6.8,
        "change_pct": -0.49, "traded_at": None})
    monkeypatch.setattr(naver, "investor_trend", lambda m: {
        "date": "2026-08-21", "personal": 1.0, "foreign": 2.0, "institution": 3.0})


def test_default_market_is_kr(client):
    body = client.get("/api/market").json()
    assert body["market"] == "KR"
    assert body["indices"][0]["symbol"] == "^KS11"
    assert body["session"]["tz"] == "Asia/Seoul"
    assert len(body["investors"]) == 2


def test_us_market_still_works(client):
    body = client.get("/api/market?market=US").json()
    assert body["market"] == "US"
    assert body["indices"][0]["symbol"] == "^GSPC"
    assert body["investors"] == []       # US 는 수급 블록이 없다
    assert body["session"]["tz"] == "America/New_York"


def test_unknown_market_is_400(client):
    r = client.get("/api/market?market=JP")
    assert r.status_code == 400
    assert "market" in r.json()["detail"]


def test_refresh_takes_market(client):
    r = client.post("/api/market/refresh?market=US")
    assert r.status_code == 200 and r.json()["market"] == "US"
    r2 = client.post("/api/market/refresh")
    assert r2.json()["market"] == "KR"
    r3 = client.post("/api/market/refresh?market=JP")
    assert r3.status_code == 400


def test_getting_kr_does_not_fetch_us(client, monkeypatch):
    """KR 만 보는 사용자에게 US 외부 호출이 일어나면 첫 응답이 그만큼 느려진다."""
    calls = {"n": 0}
    orig = market_us.BUILDERS["indices"]
    monkeypatch.setitem(market_us.BUILDERS, "indices",
                        lambda: (calls.__setitem__("n", calls["n"] + 1), orig())[1])
    client.get("/api/market")
    assert calls["n"] == 0
    client.get("/api/market?market=US")
    assert calls["n"] == 1
```

- [ ] **Step 2: 실패하는 걸 확인한다**

Run: `cd backend && uv run pytest tests/test_market_api.py -q`
Expected: FAIL — `assert body["market"] == "KR"` 에서 `"US"` (Task 1 이 US 고정으로 두었으므로)

- [ ] **Step 3: 구현한다**

`backend/app/market_api.py` 전체:

```python
"""대시보드 시장 데이터 라우트. `api.py`와 분리한 이유: 그 파일은 종목 단위 작업이 자주
건드려서 같은 파일을 두 작업이 고치면 충돌한다. DB 를 쓰지 않으므로 `_conn(request)` 도 없다.

`market` 파라미터 기본값이 KR 인 이유: 이 앱의 보유·관심 종목이 국내 중심이라
대시보드를 열었을 때 먼저 봐야 하는 시장이 한국이다.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

from app import market

router = APIRouter(prefix="/api")
DEFAULT_MARKET = "KR"


def _check(name: str) -> str:
    if name not in market.MARKETS:
        raise HTTPException(status_code=400,
                            detail=f"unknown market: {name} "
                                   f"(가능: {', '.join(sorted(market.MARKETS))})")
    return name


@router.get("/market")
async def get_market(market_name: str = Query(DEFAULT_MARKET, alias="market")):
    # 첫 호출은 외부 소스를 동기로 기다린다(수 초). 이벤트 루프를 막지 않도록 스레드로.
    return await asyncio.to_thread(market.get_market, _check(market_name))


@router.post("/market/refresh")
async def refresh_market(market_name: str = Query(DEFAULT_MARKET, alias="market")):
    """TTL 무시하고 그 시장을 전부 다시 받는다 — 화면의 '새로고침' 버튼."""
    name = _check(market_name)
    await asyncio.to_thread(lambda: market.refresh(name, force=True))
    return await asyncio.to_thread(market.get_market, name)
```

- [ ] **Step 4: 기존 테스트의 임시 단언을 확정한다**

`backend/tests/test_market.py`의 `test_api_market_endpoint`에서 Task 1 Step 1 에 넣었던 임시 줄을 지우고 US 를 명시한다.

```python
def test_api_market_endpoint(monkeypatch, tmp_path):
    _ok_fetch(monkeypatch)
    from fastapi.testclient import TestClient
    from app.main import create_app
    app = create_app(db_path=str(tmp_path / "t.db"), refresh_on_start=False)
    with TestClient(app) as c:
        r = c.get("/api/market?market=US")
        assert r.status_code == 200
        body = r.json()
        assert body["indices"][0]["symbol"] == "^GSPC"
        r2 = c.post("/api/market/refresh?market=US")
        assert r2.status_code == 200 and r2.json()["failed"] == []
```

- [ ] **Step 5: 전체 스위트를 돌린다**

Run: `cd backend && uv run pytest -q`
Expected: PASS — 370 남짓, 실패 0

- [ ] **Step 6: 실제 응답을 눈으로 본다**

```bash
cd backend && uv run uvicorn app.main:app --port 8000 &
sleep 20
curl -s 'localhost:8000/api/market' | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['market'], d['session']); print([i['name'] for i in d['indices']]); print([s['name'] for s in d['heatmap']]); print(d['investors']); print('failed:', d['failed'])"
curl -s 'localhost:8000/api/market?market=US' | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['market'], [i['name'] for i in d['indices']], 'failed:', d['failed'])"
curl -s -o /dev/null -w '%{http_code}\n' 'localhost:8000/api/market?market=JP'
kill %1
```

Expected: KR 지수 3개·섹터 목록·수급 2행이 실제 값으로 나오고 `failed`가 비어 있다. US 도 그대로. JP 는 400.
`failed`에 이름이 있으면 그 블록의 네이버 스키마가 바뀐 것이다 — 고치고 나서 다음으로 간다.

- [ ] **Step 7: 커밋**

```bash
git add backend/app/market_api.py backend/tests/test_market_api.py backend/tests/test_market.py
git commit -m "feat: /api/market 에 market 파라미터 — 기본값 KR"
```

---

### Task 5: 프론트 타입과 대시보드 시장 토글

**Files:**
- Modify: `frontend/src/finviz/types.ts`, `frontend/src/pages/Dashboard.tsx`, `frontend/src/finviz/Sections.tsx` (MarketSummary 만), `frontend/src/finviz/finviz.css`
- Test: 없음 (`tsc -b` + 브라우저 실측이 Task 8)

**Interfaces:**
- Consumes: Task 4 의 `GET /api/market?market=`
- Produces:
  - `types.ts`: `MarketName = 'KR' | 'US'`, `Session`, `InvestorRow`, `MarketData.market/session/investors`, `SignalRow.name`, `HeatTicker.name`, `MajorNewsRow.name`
  - `Sections.tsx`: `MarketSummary` 에 `market: MarketName`, `onMarket: (m: MarketName) => void` prop 추가

- [ ] **Step 1: 타입을 추가한다**

`frontend/src/finviz/types.ts`:

```ts
export type MarketName = 'KR' | 'US'
export interface Session { tz: string; open: string; close: string }
export interface InvestorRow {
  market: string
  /** 집계 기준일. 장 마감 후 집계라 오늘이 아닐 수 있다 — 화면에 같이 찍는다 */
  date: string | null
  personal: number | null
  foreign: number | null
  institution: number | null
}
```

`SignalRow`·`HeatTicker`·`MajorNewsRow`에 `name`을 더한다. US 응답은 `null`이라 옵셔널이 아니라 nullable 이다.

```ts
export interface SignalRow {
  symbol: string; name: string | null; last: number | null
  change_pct: number | null; volume: number | null; signal: string
}
export interface HeatTicker { symbol: string; name: string | null; weight: number; change_pct: number | null }
export interface MajorNewsRow { symbol: string; name: string | null; change_pct: number }
```

`MarketData`에 세 줄을 더한다.

```ts
export interface MarketData {
  market: MarketName
  session: Session
  indices: IndexRow[]
  futures: QuoteRow[]
  forex_bonds: QuoteRow[]
  signals_up: SignalRow[]
  signals_down: SignalRow[]
  heatmap: HeatSector[]
  major_news: MajorNewsRow[]
  headlines: Headline[]
  /** 투자자별 순매수(억원). 한국만 채워지고 미국은 빈 배열 */
  investors: InvestorRow[]
  /** 블록 중 가장 오래된 성공 시각(로컬 ISO). null 이면 아직 아무것도 못 받은 상태 */
  fetched_at: string | null
  /** 이번 갱신에 실패한 블록 이름 — 해당 섹션 값은 이전 성공분이거나 비어 있다 */
  failed: string[]
}
```

- [ ] **Step 2: `MarketSummary`에 토글을 단다**

`frontend/src/finviz/Sections.tsx`의 `MarketSummary`를 통째로 바꾼다.

```tsx
export function MarketSummary({ market, onMarket, time, text, stale, failed, busy, onRefresh }: {
  market: MarketName; onMarket: (m: MarketName) => void
  time: string; text: string; stale: boolean; failed: string[]; busy: boolean; onRefresh: () => void
}) {
  return (
    <div className="fv-summary">
      <div className="fv-mkt" role="group" aria-label="시장 선택">
        {(['KR', 'US'] as const).map(m => (
          <button key={m} className={m === market ? 'on' : ''} aria-pressed={m === market}
                  onClick={() => onMarket(m)}>{m}</button>
        ))}
      </div>
      <span className={`fv-summary-time${stale ? ' warn' : ''}`}>{stale && '⚠ '}{time}</span>
      <span className="fv-summary-text">{text}</span>
      {failed.length > 0 && <span className="warn" style={{ fontSize: 12 }}
        title={failed.join(', ')}>일부 갱신 실패 ({failed.length})</span>}
      <button className="ghost" style={{ fontSize: 12, padding: '4px 10px' }}
              onClick={onRefresh} disabled={busy}>{busy ? '갱신 중…' : '새로고침'}</button>
    </div>
  )
}
```

`fv-summary-dot`을 토글로 바꿨다 — 점은 장식이었고 그 자리가 왼쪽 끝이라 토글이 들어갈 자리다.
import 에 `MarketName`을 더한다: `import type { Headline, MajorNewsRow, MarketName, QuoteRow, SignalRow } from './types'`

`frontend/src/finviz/finviz.css`에서 `.fv-summary-dot` 규칙을 지우고 아래를 더한다.

```css
.fv-mkt { display: flex; gap: 2px; flex: none; background: var(--bg-hover); border-radius: 6px; padding: 2px; }
.fv-mkt button {
  border: 0; background: transparent; color: var(--text-dim); font-size: 11px; font-weight: 600;
  padding: 3px 10px; border-radius: 4px; cursor: pointer; letter-spacing: 0.3px;
}
.fv-mkt button.on { background: var(--bg-card); color: var(--text); }
```

- [ ] **Step 3: `Dashboard.tsx`가 시장을 들고 fetch 한다**

상단 import 와 상태·로더를 바꾼다.

```tsx
import type { IndexRow, MarketData, MarketName } from '../finviz/types'

const MARKET_KEY = 'dashboard.market'
function initialMarket(): MarketName {
  const v = localStorage.getItem(MARKET_KEY)
  return v === 'US' ? 'US' : 'KR'      // 기본은 한국. 알 수 없는 값도 KR 로 떨어진다
}

/** 지수 등락으로 만든 한 줄 요약. 뉴스 요약 소스가 없어 문장을 지어내지 않고 숫자만 나열한다. */
function summaryText(indices: IndexRow[], market: MarketName): string {
  const shown = indices.filter(i => i.change_pct !== null)
  if (shown.length === 0) return '지수 데이터를 아직 받지 못했습니다'
  const parts = shown.map(i => `${i.name} ${i.change_pct! > 0 ? '+' : ''}${i.change_pct!.toFixed(2)}%`)
  const ups = shown.filter(i => i.change_pct! > 0).length
  const tone = market === 'KR'
    ? (ups === shown.length ? '국내 증시 상승' : ups === 0 ? '국내 증시 하락' : '국내 증시 혼조')
    : (ups === shown.length ? 'US stocks rose' : ups === 0 ? 'US stocks fell' : 'US stocks mixed')
  return `${tone} — ${parts.join(' · ')}`
}
```

컴포넌트 본문:

```tsx
  const [market, setMarket] = useState<MarketName>(initialMarket)
  const [data, setData] = useState<MarketData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [now, setNow] = useState(Date.now())

  const load = useCallback(() => get<MarketData>(`/api/market?market=${market}`)
    // 빠르게 두 번 토글하면 먼저 쏜 응답이 나중에 올 수 있다 — 지금 시장이 아니면 버린다
    .then(d => { if (d.market === market) { setData(d); setError(null); setNow(Date.now()) } })
    .catch(e => setError(String(e))), [market])
  useEffect(() => { load() }, [load])

  const pickMarket = (m: MarketName) => {
    if (m === market) return
    localStorage.setItem(MARKET_KEY, m)
    setBusy(true)
    setMarket(m)          // load 가 market 에 걸려 있어 이 한 줄로 다시 받는다
  }
  // 전환 요청이 끝나면(또는 실패하면) busy 를 내린다. data 를 지우지 않는 이유는
  // 스켈레톤으로 되돌아가면 화면이 통째로 깜빡이기 때문 — 이전 시장을 두고 위에서 갱신한다.
  useEffect(() => { setBusy(false) }, [data, error])
```

`refresh`도 시장을 붙인다.

```tsx
  const refresh = async () => {
    setBusy(true)
    try { setData(await post<MarketData>(`/api/market/refresh?market=${market}`)); setNow(Date.now()) }
    catch (e) { setError(String(e)) }
    finally { setBusy(false) }
  }
```

첫 로드 안내 문구:

```tsx
      <div className="fv-dim" style={{ textAlign: 'center', fontSize: 12 }}>
        {market === 'KR'
          ? '첫 로드는 네이버·야후에서 지수와 순위 100여 종목을 받아오느라 몇 초 걸립니다.'
          : '첫 로드는 야후 파이낸스에서 지수·스크리너·100여 종목을 받아오느라 10초쯤 걸립니다.'}</div>
```

`MarketSummary` 호출:

```tsx
      <MarketSummary market={market} onMarket={pickMarket}
                     time={`기준 ${relativeTime(data.fetched_at, now)}`}
                     text={summaryText(data.indices, market)}
                     stale={stale} failed={data.failed} busy={busy} onRefresh={refresh} />
```

Futures 표는 빈 배열이면 숨긴다 — 마지막 `fv-row quotes` 블록을 바꾼다.

```tsx
      <div className="fv-row quotes" style={data.futures.length === 0 ? { gridTemplateColumns: '1fr' } : undefined}>
        {data.futures.length > 0 && <QuoteTable title="Futures" rows={data.futures} />}
        <QuoteTable title={market === 'KR' ? '환율 & 금리' : 'Forex & Bonds'} rows={data.forex_bonds} />
      </div>
```

히트맵 패널 제목:

```tsx
          <div className="fv-panel-title"><span>
            {market === 'KR' ? 'KOSPI 대형주 – 1일 등락' : 'US Large Caps - 1 Day Performance'}</span></div>
```

- [ ] **Step 4: 타입·린트를 확인한다**

Run: `cd frontend && npx tsc -b && npx oxlint`
Expected: `tsc` exit 0, oxlint 경고 0. `name` 필드를 아직 안 읽는 컴포넌트가 있어도 nullable 추가라 타입은 통과한다.

- [ ] **Step 5: 커밋**

```bash
git add frontend/src/finviz/types.ts frontend/src/finviz/Sections.tsx frontend/src/finviz/finviz.css frontend/src/pages/Dashboard.tsx
git commit -m "feat: 대시보드에 KR/US 시장 토글 — 기본 한국"
```

---

### Task 6: 한글 종목명·시간축·소수점

**Files:**
- Modify: `frontend/src/finviz/Sections.tsx`, `frontend/src/finviz/Heatmap.tsx`, `frontend/src/finviz/IndexChart.tsx`, `frontend/src/pages/Dashboard.tsx`

**Interfaces:**
- Consumes: Task 5 의 `SignalRow.name`, `HeatTicker.name`, `MajorNewsRow.name`, `MarketData.session`
- Produces: `SignalTable`·`MajorNews` 에 `krw?: boolean` prop, `Heatmap` 에 변경 없음(데이터만 읽음), `IndexChart` 에 `session: Session` prop

- [ ] **Step 1: 시그널 표가 이름을 보여주고 KR 은 소수점을 뗀다**

`Sections.tsx`의 `SignalTable`:

```tsx
export function SignalTable({ rows, gear, krw }: { rows: SignalRow[]; gear?: boolean; krw?: boolean }) {
  return (
    <Panel gear={gear}>
      <table className="fv-table">
        <thead><tr><th>{krw ? '종목' : 'Ticker'}</th><th>{krw ? '현재가' : 'Last'}</th>
          <th>Change %</th><th>{krw ? '거래량' : 'Volume'}</th><th className="l">Signal</th></tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={5} className="c fv-dim">순위 응답 없음</td></tr>}
          {rows.map((r, i) => (
            <tr key={i}>
              <td><span className="fv-logo" aria-hidden>{(r.name ?? r.symbol)[0]}</span>
                <Link to={`/ticker/${r.symbol}`} className="fv-tk" title={r.symbol}>{r.name ?? r.symbol}</Link></td>
              <td className="n">{num(r.last, krw ? 0 : 2)}</td>
              <td className={`n ${sign(r.change_pct)}`}>{pct(r.change_pct)}</td>
              <td className="n">{vol(r.volume)}</td>
              <td className="l"><span className="fv-signal">{r.signal}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}
```

`T` 컴포넌트는 심볼만 받으므로 여기서는 `Link`를 직접 쓴다. 한글 이름은 길어서 넘칠 수 있으니 CSS 를 더한다 (`finviz.css`):

```css
/* 한글 종목명은 영문 티커보다 길다 — 칸을 넘기지 말고 자른다 */
.fv-table td .fv-tk { display: inline-block; max-width: 130px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; vertical-align: bottom; }
```

`MajorNews`도 같게:

```tsx
export function MajorNews({ rows }: { rows: MajorNewsRow[] }) {
  return (
    <Panel>
      <div className="fv-panel-title" title="대형주 중 당일 등락이 큰 순">Major Movers</div>
      <div className="fv-major">
        {rows.length === 0 && <div className="fv-major-row fv-dim">—</div>}
        {rows.map(r => (
          <div key={r.symbol} className="fv-major-row">
            <Link to={`/ticker/${r.symbol}`} className="fv-tk" title={r.symbol}>{r.name ?? r.symbol}</Link>
            <span className={`fv-badge ${sign(r.change_pct)}`}>{pct(r.change_pct)}</span>
          </div>
        ))}
      </div>
    </Panel>
  )
}
```

- [ ] **Step 2: 히트맵 칸이 이름을 보여준다**

`Heatmap.tsx:88-99`의 `Link` 블록만 바꾼다. `key`와 링크 대상(`/ticker/${t.symbol}`)은 `symbol` 그대로다 — 이름은 바뀔 수 있고 코드는 안 바뀐다.

이 파일에는 이미 칸 크기에 따라 글자 크기를 줄이는 `font` 단계가 있다(`size > 90 ? 22 : … : 0`). 한글 이름은 3~6자라 영문 티커보다 넓어서, 글자가 작아지는 칸(`font < 11`)에서는 이름 대신 코드를 쓴다.

```tsx
                return (
                  <Link key={t.symbol} to={`/ticker/${t.symbol}`} className="fv-cell"
                        title={`${t.name ? t.name + ' ' : ''}${t.symbol} ${t.change_pct === null ? '—' : (t.change_pct > 0 ? '+' : '') + t.change_pct.toFixed(2) + '%'}`}
                        style={{ left: pct(c.x, inner.w), top: pct(c.y, inner.h),
                                 width: pct(c.w, inner.w), height: pct(c.h, inner.h),
                                 background: color(t.change_pct), fontSize: font }}>
                    {font > 0 && <>
                      {/* 한글 이름은 영문 티커보다 넓다 — 글자가 작아지는 칸에서는 코드가 낫다 */}
                      <span className="fv-cell-t">{font >= 11 ? (t.name ?? t.symbol) : t.symbol}</span>
                      {font >= 11 && t.change_pct !== null && <span className="fv-cell-c">
                        {t.change_pct > 0 ? '+' : ''}{t.change_pct.toFixed(2)}%</span>}
                    </>}
                  </Link>
                )
```

`.fv-cell-t`가 넘치지 않게 `finviz.css`에 한 줄 더한다.

```css
.fv-cell-t { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
```

- [ ] **Step 3: 지수 차트 시간축을 세션에서 만든다**

`IndexChart.tsx`에서 `const TIMES = [...]` 상수를 지우고 prop 으로 받은 세션에서 만든다.

```tsx
import type { IndexRow, Session } from './types'

/** 장 시작~마감 사이 정시 라벨. 미국은 10AM…4PM, 한국은 10…15.
 *  상수로 박아두면 한국 장(09:00–15:30)에 4PM 이 찍힌다. */
function hourLabels(s: Session): string[] {
  const h0 = Number(s.open.slice(0, 2)), h1 = Number(s.close.slice(0, 2))
  const us = s.tz.startsWith('America')
  const out: string[] = []
  for (let h = h0 + 1; h <= h1; h++) {
    out.push(us ? `${h % 12 === 0 ? 12 : h % 12}${h < 12 ? 'AM' : 'PM'}` : String(h))
  }
  return out
}

export default function IndexChart({ data, asOf, session }:
  { data: IndexRow; asOf: string | null; session: Session }) {
  const TIMES = hourLabels(session)
  // ... 나머지는 그대로 ...
```

날짜 라벨 로케일도 시장에 맞춘다.

```tsx
  const dateLabel = asOf
    ? new Date(asOf).toLocaleDateString(session.tz.startsWith('Asia') ? 'ko-KR' : 'en-US',
        { month: 'short', day: 'numeric' })
    : ''
```

`Dashboard.tsx`의 호출부:

```tsx
        {data.indices.map(i => <IndexChart key={i.symbol} data={i} asOf={data.fetched_at} session={data.session} />)}
```

- [ ] **Step 4: 시그널 표에 `krw`를 넘긴다**

`Dashboard.tsx`:

```tsx
        <SignalTable rows={data.signals_up} krw={market === 'KR'} />
        <SignalTable rows={data.signals_down} gear krw={market === 'KR'} />
```

- [ ] **Step 5: 타입·린트를 확인한다**

Run: `cd frontend && npx tsc -b && npx oxlint`
Expected: exit 0, 경고 0

- [ ] **Step 6: 커밋**

```bash
git add frontend/src/finviz frontend/src/pages/Dashboard.tsx
git commit -m "feat: 대시보드가 한글 종목명과 한국 장 시간축을 쓴다"
```

---

### Task 7: 투자자 수급 패널

**Files:**
- Modify: `frontend/src/finviz/Sections.tsx`, `frontend/src/finviz/finviz.css`, `frontend/src/pages/Dashboard.tsx`

**Interfaces:**
- Consumes: Task 5 의 `InvestorRow`
- Produces: `Sections.tsx` 의 `export function InvestorFlows({ rows }: { rows: InvestorRow[] })`

- [ ] **Step 1: 컴포넌트를 만든다**

`Sections.tsx`에 더한다. import 에 `InvestorRow`를 넣는다.

```tsx
/** 순매수 금액(억원). 부호를 항상 붙인다 — 수급은 방향이 값보다 먼저 읽혀야 한다. */
const flow = (v: number | null) =>
  v === null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toLocaleString('ko-KR')}억`

/** 투자자별 순매수. 한국 시장에서 "누가 사고 누가 팔았나"는 지수 등락만큼 자주 보는 값이고
 *  finviz 에는 대응 블록이 없어 새로 만든다. 집계 기준일을 같이 찍는 이유: 장 마감 후
 *  집계라 장중에는 전일 값이 보이는데, 날짜가 없으면 오늘 수급으로 읽힌다. */
export function InvestorFlows({ rows }: { rows: InvestorRow[] }) {
  return (
    <>
      {rows.map(r => (
        <Panel key={r.market} className="fv-flow">
          <div className="fv-panel-title">
            <span>{r.market} 투자자 순매수</span>
            <span className="fv-dim" style={{ fontWeight: 400 }}>{r.date ?? '기준일 미상'}</span>
          </div>
          <div className="fv-flow-row">
            {([['개인', r.personal], ['외국인', r.foreign], ['기관', r.institution]] as const).map(
              ([label, v]) => (
                <div key={label}>
                  <p className="fv-dim">{label}</p>
                  <p className={`fv-flow-v ${sign(v)}`}>{flow(v)}</p>
                </div>
              ))}
          </div>
        </Panel>
      ))}
    </>
  )
}
```

`fv-panel-title`이 `span` 두 개를 양끝으로 벌리는지 확인하고, 아니면 아래 CSS 로 맞춘다.

`finviz.css`:

```css
.fv-row.flows { grid-template-columns: repeat(2, 1fr); }
.fv-flow .fv-panel-title { display: flex; justify-content: space-between; align-items: baseline; }
.fv-flow-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; padding: 10px 12px 12px; }
.fv-flow-row p { margin: 0; font-size: 11px; }
.fv-flow-v { font-size: 15px; font-weight: 700; margin-top: 3px !important; font-variant-numeric: tabular-nums; }
.fv-flow-v.up { color: var(--buy); }
.fv-flow-v.down { color: var(--sell); }
```

`--buy`/`--sell` 은 `theme.css`에 이미 있는 변수다(`Sections.tsx`의 `fv-row-buy`가 쓰고 있다).

- [ ] **Step 2: 대시보드에 끼운다**

`Dashboard.tsx`의 import 에 `InvestorFlows`를 더하고, 지수 차트 줄 바로 아래에 넣는다.

```tsx
      <div className="fv-row charts">
        {data.indices.map(i => <IndexChart key={i.symbol} data={i} asOf={data.fetched_at} session={data.session} />)}
      </div>

      {data.investors.length > 0 && (
        <div className="fv-row flows"><InvestorFlows rows={data.investors} /></div>
      )}
```

US 는 `investors`가 빈 배열이라 줄 자체가 렌더되지 않는다.

- [ ] **Step 3: 타입·린트를 확인한다**

Run: `cd frontend && npx tsc -b && npx oxlint`
Expected: exit 0, 경고 0

- [ ] **Step 4: 커밋**

```bash
git add frontend/src/finviz/Sections.tsx frontend/src/finviz/finviz.css frontend/src/pages/Dashboard.tsx
git commit -m "feat: 투자자별 순매수 패널 — 한국 시장에만"
```

---

### Task 8: 브라우저 실측과 마무리

**Files:** 없음 (확인만, 문제가 나오면 해당 파일 수정)

- [ ] **Step 1: 백엔드·프론트를 띄운다**

```bash
cd backend && uv run uvicorn app.main:app --port 8000 &
cd frontend && npm run dev &
```

- [ ] **Step 2: KR 기본 화면을 확인한다**

`http://localhost:5173/` 를 연다. 확인 목록:

1. 상단 토글이 `KR`에 켜져 있다.
2. 지수 카드 3개가 코스피·코스닥·코스피 200 이고 캔들이 그려진다.
3. 지수 차트 시간축이 `10 11 12 13 14 15` (`4PM`이 아니다).
4. 수급 패널 2개(KOSPI·KOSDAQ)가 지수 아래에 있고, 개인/외국인/기관 값의 부호와 색이 맞는다. 기준일이 찍혀 있다.
5. 시그널 표가 한글 종목명이고 현재가에 소수점이 없다. 이름을 누르면 `/ticker/005930` 으로 간다.
6. 히트맵 제목이 `KOSPI 대형주 – 1일 등락`, 칸에 KODEX·TIGER 가 없고 삼성전자우가 없다.
7. 맨 아래에 Futures 표가 없고 `환율 & 금리` 한 표만 있다.
8. 요약 문장이 `국내 증시 …` 로 시작한다.
9. 콘솔에 에러가 없다.

- [ ] **Step 3: US 토글을 확인한다**

`US`를 누른다.

1. 지수가 S&P 500·NASDAQ·DOW 로 바뀌고 시간축이 `10AM…4PM` 이다.
2. 수급 패널 줄이 사라진다.
3. Futures 표가 다시 나온다.
4. 요약 문장이 `US stocks …` 다.
5. 네트워크 탭에 `/api/market?market=US` 가 찍힌다.
6. 새로고침(F5) 하면 US 로 남아 있다 (localStorage).

- [ ] **Step 4: 되돌리고 경계를 본다**

1. `KR`로 되돌린다 — 두 번째부터는 캐시라 즉시 나온다.
2. `KR`↔`US`를 빠르게 5번 눌러도 지수 이름과 토글 상태가 어긋나지 않는다(늦게 온 응답 버리기).
3. 브라우저 폭을 390px 로 줄여 수급 패널과 시그널 표가 가로로 넘치지 않는지 본다. 넘치면 `finviz.css`에 미디어 쿼리를 더한다.

- [ ] **Step 5: 전체 검증**

```bash
cd backend && uv run pytest -q
cd frontend && npx tsc -b && npx oxlint && npx tsx --test src/quote/*.test.ts
```

Expected: pytest 실패 0, tsc exit 0, oxlint 경고 0, node:test 24 pass

- [ ] **Step 6: smoke 로 네이버 스키마를 한 번 더 확인한다**

Run: `cd backend && uv run pytest -m smoke tests/test_naver_market.py -q`
Expected: PASS

- [ ] **Step 7: 커밋**

실측에서 고친 게 있으면 커밋한다. 없으면 건너뛴다.

```bash
git add -A
git commit -m "fix: 브라우저 실측에서 나온 배치 문제를 고친다"
```

---

## 검증 요약

| 무엇 | 어떻게 |
|---|---|
| US 동작 불변 | `test_market.py` 기존 단언이 `market="US"`로 전부 통과 |
| KR 블록 조립 | `test_market_kr.py` — 지수 폴백, ETF·우선주 제외, 기타 섹터, 수급, 환율/국채 |
| 네이버 파싱 | `test_naver_market.py` — 픽스처 파싱 + smoke 실호출 |
| 시장 분리 | `test_market_api.py::test_getting_kr_does_not_fetch_us` |
| 기본값 KR | `test_market_api.py::test_default_market_is_kr` |
| 화면 | Task 8 실측 목록 |
