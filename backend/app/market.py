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
        # 첫 방문은 TTL 을 따지지 않고 채운다 — `_is_stale` 은 "한 번도 안 받았다"를
        # `now - 0 > ttl` 로 판단해서, 주입된 시계가 TTL 보다 작으면 그 블록이 빈 채 남는다.
        # 백오프는 지킨다: 전 블록이 실패한 시장은 매 요청이 여기로 다시 들어오는데,
        # 그때 재시도까지 하면 응답이 블록 수 × 타임아웃만큼 느려진다.
        for b in blocks:
            if not _in_backoff(market, b, now):
                _refresh_block(market, b, now)
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


from app import market_kr, market_us  # noqa: E402 — 위 정의를 시장 모듈이 import 한다

MARKETS["US"] = market_us
MARKETS["KR"] = market_kr
