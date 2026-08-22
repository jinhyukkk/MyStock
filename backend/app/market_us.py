"""미국 시장(finviz 구성) 상수와 블록 빌더.

`market.py`가 시장 둘을 다루게 되면서 상수가 두 배가 되어 시장별 파일로 나눴다.
엔진(캐시·TTL·실패 격리)은 `market.py`에 있고 이 파일은 **무엇을 어떻게 받는지**만 안다.
빌더는 예외를 그대로 올린다 — 격리는 엔진 몫이다.
"""
from __future__ import annotations

from app import market_breadth, market_calendar, market_fetch as fetch, market_history
from app import market_insider
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
    # 일봉·공시 기반 블록은 갱신 비용이 커서 TTL 을 길게(한국판과 같은 기준).
    "breadth": 30 * 60,
    "patterns": 30 * 60,
    "econ": 6 * 60 * 60,
    "earnings": 6 * 60 * 60,
    "insider": 6 * 60 * 60,
}

# 첫 화면을 기다리게 하지 않는 블록 — 종목마다 외부 호출이라 수십 초가 걸린다.
# S&P 500 일봉(24초, 실측 2026-08-22)도 여기 둔다.
SLOW_BLOCKS = ("breadth", "patterns", "earnings", "insider")

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


def _build_breadth() -> dict:
    h = market_history.history("US")
    return {"universe": h["label"], "as_of": h["as_of"],
            "bars": market_breadth.breadth(h["closes"])}


def _build_patterns() -> dict:
    h = market_history.history("US")
    return {"universe": h["label"], "as_of": h["as_of"],
            "rows": market_breadth.patterns(h["closes"], h["names"])}


def _build_earnings() -> dict:
    return market_calendar.earnings(market_history.history("US")["rows"])


def _build_insider() -> dict:
    return market_insider.insider("US", market_history.history("US")["rows"])


BUILDERS = {
    "indices": _build_indices,
    "futures": lambda: _build_quotes(FUTURES),
    "forex_bonds": lambda: _build_quotes(FOREX_BONDS),
    "signals_up": lambda: _build_signals(SCREENS_UP),
    "signals_down": lambda: _build_signals(SCREENS_DOWN),
    "heatmap": _build_heatmap,
    "headlines": _build_headlines,
    "breadth": _build_breadth,
    "patterns": _build_patterns,
    "econ": lambda: market_calendar.econ("US"),
    "earnings": _build_earnings,
    "insider": _build_insider,
}
