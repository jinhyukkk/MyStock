"""대시보드(finviz 구성) 시장 데이터 조립 + 인메모리 캐시.

`company.py`가 "한 종목"을 조립한다면 이 모듈은 "시장 전체"를 조립한다. 규칙도 같다:
1. **외부 호출은 `market_fetch`에서만.** 여기서 yfinance 를 직접 부르지 않는다.
2. **블록별 실패 격리.** 스크리너가 죽어도 지수 차트는 나가야 한다. 실패한 블록은
   이전 값을 유지하고 `failed`에 이름만 올린다 — 값을 지우면 화면이 "원래 없는 것"과
   "이번에 못 받은 것"을 구분 못 한다.
3. **DB 를 쓰지 않는다.** 시장 데이터는 개인 자료가 아니고 재시작 후 다시 받으면 그만이라
   스레드-로컬 DB 규칙(main.py)에 엮일 이유가 없다. 프로세스 메모리 + 락으로 충분.

응답 블록: indices, futures, forex_bonds, signals_up, signals_down, heatmap, major_news,
headlines. 단위: 가격은 해당 자산 단위 숫자, 등락은 퍼센트 숫자(`_pct`), 거래량은 주 수.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from app import market_fetch as fetch

# 블록별 TTL(초). 장중 지수 차트는 짧게, 구성종목 히트맵은 길게 — 전부 같은 주기면
# 100종목 일괄 다운로드를 5분마다 하게 된다.
TTL_SEC = {
    "indices": 5 * 60,
    "futures": 5 * 60,
    "forex_bonds": 5 * 60,
    "signals_up": 10 * 60,
    "signals_down": 10 * 60,
    "heatmap": 15 * 60,
    "headlines": 15 * 60,
}
# 실패한 블록을 바로 다시 때리지 않는다 — 야후가 막힌 날 매 요청마다 재시도하면
# 응답이 블록 수 × 타임아웃만큼 느려진다.
FAIL_BACKOFF_SEC = 3 * 60

INDICES = [("S&P 500", "^GSPC"), ("NASDAQ", "^IXIC"), ("DOW", "^DJI")]
FUTURES = [("Crude Oil", "CL=F", 2), ("Natural Gas", "NG=F", 4), ("Gold", "GC=F", 2),
           ("Dow", "YM=F", 2), ("S&P 500", "ES=F", 2), ("Nasdaq 100", "NQ=F", 2),
           ("Russell 2000", "RTY=F", 2)]
FOREX_BONDS = [("EUR/USD", "EURUSD=X", 4), ("USD/JPY", "JPY=X", 2), ("GBP/USD", "GBPUSD=X", 4),
               ("BTC/USD", "BTC-USD", 2), ("5-Year Treasury", "^FVX", 3),
               ("10-Year Treasury", "^TNX", 3), ("30-Year Treasury", "^TYX", 3)]
# finviz 좌측 표(상승 계열)·우측 표(하락 계열)에 대응하는 야후 사전 정의 스크리너.
# New High/Overbought/Unusual Volume 같은 finviz 고유 시그널은 야후에 없다 — 있는 것만 쓴다.
SCREENS_UP = [("day_gainers", "Top Gainers", 6), ("small_cap_gainers", "Small Cap Gainers", 5),
              ("most_actives", "Most Active", 4), ("growth_technology_stocks", "Growth Tech", 4)]
SCREENS_DOWN = [("day_losers", "Top Losers", 6), ("most_shorted_stocks", "Most Shorted", 5),
                ("undervalued_large_caps", "Undervalued Large", 4),
                ("aggressive_small_caps", "Aggressive Small", 4)]
# 히트맵 구성종목(섹터, 심볼, 시총 비중 근사). 야후에 S&P500 구성종목 API 가 없어 대형주
# 위주로 고정한다. 비중은 칸 크기에만 쓰이므로 근사치로 충분 — 등락은 실시간으로 받는다.
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
MAJOR_NEWS_COUNT = 16
HEADLINES_SYMBOL = "^GSPC"
HEADLINES_COUNT = 8


def _pct(last, prev) -> float | None:
    if last is None or prev in (None, 0):
        return None
    return round((last / prev - 1) * 100, 2)


def _chg(last, prev) -> float | None:
    if last is None or prev is None:
        return None
    return last - prev


# ── 블록별 빌더 (예외는 그대로 올린다 — 격리는 _refresh_block 이 한다) ──────────────

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
            out.append({**row, "signal": label})
    return out


def _build_heatmap() -> list[dict]:
    symbols = [s for rows in HEATMAP_SECTORS.values() for s, _ in rows]
    q = fetch.daily_closes(symbols)
    sectors = []
    for name, rows in HEATMAP_SECTORS.items():
        tickers = []
        for sym, w in rows:
            v = q.get(sym) or {}
            tickers.append({"symbol": sym, "weight": w,
                            "change_pct": _pct(v.get("last"), v.get("prev_close"))})
        sectors.append({"name": name, "tickers": tickers})
    return sectors


def _build_headlines() -> list[dict]:
    return fetch.news(HEADLINES_SYMBOL, limit=HEADLINES_COUNT)


def major_news_from_heatmap(sectors: list[dict], n: int = MAJOR_NEWS_COUNT) -> list[dict]:
    """finviz 'Major News' 는 큰 뉴스가 난 종목의 등락 목록이다. 뉴스 소스 없이도 같은
    목적을 채우는 근사: 대형주 중 |등락| 큰 순. 히트맵 블록을 그대로 재사용해 호출이 없다."""
    rows = [t for s in sectors for t in s["tickers"] if t.get("change_pct") is not None]
    rows.sort(key=lambda t: -abs(t["change_pct"]))
    return [{"symbol": t["symbol"], "change_pct": t["change_pct"]} for t in rows[:n]]


BUILDERS = {
    "indices": _build_indices,
    "futures": lambda: _build_quotes(FUTURES),
    "forex_bonds": lambda: _build_quotes(FOREX_BONDS),
    "signals_up": lambda: _build_signals(SCREENS_UP),
    "signals_down": lambda: _build_signals(SCREENS_DOWN),
    "heatmap": _build_heatmap,
    "headlines": _build_headlines,
}


# ── 캐시 ──────────────────────────────────────────────────────────────────────

class _Cache:
    def __init__(self):
        self.lock = threading.Lock()
        self.values: dict[str, object] = {}
        self.fetched_at: dict[str, float] = {}     # 성공 시각(epoch)
        self.attempted_at: dict[str, float] = {}   # 마지막 시도 시각
        self.errors: dict[str, str] = {}
        self.refreshing = False


_cache = _Cache()


def reset_cache():
    """테스트용."""
    global _cache
    _cache = _Cache()


def _is_stale(block: str, now: float) -> bool:
    return now - _cache.fetched_at.get(block, 0) > TTL_SEC[block]


def _in_backoff(block: str, now: float) -> bool:
    return (block in _cache.errors
            and now - _cache.attempted_at.get(block, 0) < FAIL_BACKOFF_SEC)


def _refresh_block(block: str, now: float) -> None:
    _cache.attempted_at[block] = now
    try:
        value = BUILDERS[block]()
    except Exception as e:  # noqa: BLE001 — 어떤 예외든 블록 하나로 격리
        with _cache.lock:
            _cache.errors[block] = f"{type(e).__name__}: {e}"[:200]
        return
    with _cache.lock:
        _cache.values[block] = value
        _cache.fetched_at[block] = now   # 주입된 now 기준 — 테스트가 시계를 돌릴 수 있게
        _cache.errors.pop(block, None)


def refresh(force: bool = False, now: float | None = None) -> None:
    """낡은 블록만(또는 전부) 순서대로 갱신. 동기 — 호출자가 스레드를 정한다."""
    now = time.time() if now is None else now
    for block in BUILDERS:
        if force or (_is_stale(block, now) and not _in_backoff(block, now)):
            _refresh_block(block, now)


def _refresh_in_background():
    with _cache.lock:
        if _cache.refreshing:
            return
        _cache.refreshing = True
    try:
        refresh()
    finally:
        with _cache.lock:
            _cache.refreshing = False


def get_market(now: float | None = None) -> dict:
    """대시보드 응답. 캐시가 비어 있으면 동기로 채우고(첫 방문 한 번), 이후로는 낡은 값을
    즉시 돌려주면서 백그라운드로 갱신한다(stale-while-revalidate) — 장중 5분마다 누군가
    새로고침할 때 화면이 야후 응답 시간만큼 멈추지 않게."""
    now = time.time() if now is None else now
    if not _cache.values:
        refresh(now=now)
    elif any(_is_stale(b, now) and not _in_backoff(b, now) for b in BUILDERS):
        threading.Thread(target=_refresh_in_background, daemon=True).start()

    with _cache.lock:
        values = dict(_cache.values)
        failed = sorted(_cache.errors)
        oldest = min(_cache.fetched_at.values()) if _cache.fetched_at else None
    heatmap = values.get("heatmap") or []
    return {
        "indices": values.get("indices") or [],
        "futures": values.get("futures") or [],
        "forex_bonds": values.get("forex_bonds") or [],
        "signals_up": values.get("signals_up") or [],
        "signals_down": values.get("signals_down") or [],
        "heatmap": heatmap,
        "major_news": major_news_from_heatmap(heatmap),
        "headlines": values.get("headlines") or [],
        # 블록 중 가장 오래된 성공 시각 — 화면은 이 한 값으로 "기준 n분 전"을 보여준다
        "fetched_at": (datetime.fromtimestamp(oldest).isoformat(timespec="seconds")
                       if oldest else None),
        "failed": failed,
    }
