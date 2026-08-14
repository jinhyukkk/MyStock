from datetime import date, timedelta
from functools import lru_cache

import pandas as pd
import requests

UPBIT_CANDLES = "https://api.upbit.com/v1/candles/days"
UPBIT_MARKETS = "https://api.upbit.com/v1/market/all"

# 시장별 벤치마크 — (fetch_ohlcv에 넘길 심볼, 표시 라벨). price_cache에는 "BENCH:{market}" 키로 저장.
BENCHMARKS = {"KR": ("KS11", "KOSPI"), "US": ("^GSPC", "S&P500"),
              "CRYPTO": ("KRW-BTC", "BTC")}


def normalize_ohlcv(df: pd.DataFrame, colmap: dict) -> pd.DataFrame:
    out = df.rename(columns=colmap)[["open", "high", "low", "close", "volume"]].copy()
    out.index = pd.to_datetime(out.index)
    out = out.sort_index()
    return out.dropna(subset=["close"]).astype(float)


def parse_upbit_candles(payload: list) -> pd.DataFrame:
    df = pd.DataFrame(payload)
    df.index = pd.to_datetime(df["candle_date_time_kst"].str[:10])
    return normalize_ohlcv(df, {"opening_price": "open", "high_price": "high",
                                "low_price": "low", "trade_price": "close",
                                "candle_acc_trade_volume": "volume"})


def fetch_ohlcv(symbol: str, market: str, yf_symbol: str | None = None,
                days: int = 400) -> pd.DataFrame:
    start = (date.today() - timedelta(days=int(days * 1.6))).isoformat()
    if market == "KR":
        import FinanceDataReader as fdr
        df = fdr.DataReader(symbol, start)
        return normalize_ohlcv(df, {"Open": "open", "High": "high", "Low": "low",
                                    "Close": "close", "Volume": "volume"})
    if market == "US":
        import yfinance as yf
        df = yf.Ticker(yf_symbol or symbol).history(start=start, auto_adjust=True)
        df.index = df.index.tz_localize(None)
        return normalize_ohlcv(df, {"Open": "open", "High": "high", "Low": "low",
                                    "Close": "close", "Volume": "volume"})
    if market == "CRYPTO":
        payload, to = [], None
        while len(payload) < days:
            params = {"market": symbol, "count": 200}
            if to:
                params["to"] = to
            r = requests.get(UPBIT_CANDLES, params=params, timeout=10)
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            new_to = batch[-1]["candle_date_time_utc"]
            if new_to == to:  # 진행 없음 — 상장 초기 도달, 무한 루프 방지
                break
            payload += batch
            to = new_to
        return parse_upbit_candles(payload)
    raise ValueError(f"unknown market: {market}")


def fetch_fundamentals(yf_symbol: str) -> dict | None:
    try:
        import yfinance as yf
        info = yf.Ticker(yf_symbol).info
        dy = info.get("dividendYield")
        return {
            "per": info.get("trailingPE"),
            "pbr": info.get("priceToBook"),
            "dividend_yield": round(dy, 2) if dy is not None else None,
            "market_cap": info.get("marketCap"),
        }
    except Exception:
        return None


@lru_cache(maxsize=1)
def _krx_listing() -> pd.DataFrame:
    import FinanceDataReader as fdr
    df = fdr.StockListing("KRX")[["Code", "Name", "Market"]].dropna()
    df["is_etf"] = 0
    try:
        etf = fdr.StockListing("ETF/KR")[["Symbol", "Name"]].dropna()
        etf = etf.rename(columns={"Symbol": "Code"})
        etf["Market"] = "KOSPI"
        etf["is_etf"] = 1
        df = pd.concat([df, etf], ignore_index=True)
    except Exception:
        pass
    return df


@lru_cache(maxsize=1)
def _upbit_markets() -> list:
    r = requests.get(UPBIT_MARKETS, timeout=10)
    r.raise_for_status()
    return [m for m in r.json() if m["market"].startswith("KRW-")]


def search_symbols(query: str, conn=None) -> list[dict]:
    q = query.strip()
    results = []
    try:
        krx = _krx_listing()
        hit = krx[krx["Name"].str.contains(q, case=False, na=False) |
                  krx["Code"].str.contains(q, na=False)].head(10)
        for _, row in hit.iterrows():
            suffix = ".KQ" if row["Market"] == "KOSDAQ" else ".KS"
            results.append({"symbol": row["Code"], "name": row["Name"], "market": "KR",
                            "is_etf": int(row["is_etf"]),
                            "yf_symbol": row["Code"] + suffix, "currency": "KRW"})
    except Exception:
        pass
    try:
        for m in _upbit_markets():
            if q.lower() in m["korean_name"].lower() or q.upper() in m["market"]:
                results.append({"symbol": m["market"], "name": m["korean_name"],
                                "market": "CRYPTO", "is_etf": 0,
                                "yf_symbol": None, "currency": "KRW"})
        results = results[:20]
    except Exception:
        pass
    if q.isalpha() and q.isupper() and len(q) <= 5:
        try:
            import yfinance as yf
            t = yf.Ticker(q)
            price = t.fast_info.get("lastPrice")
            if price:
                name = (t.info.get("shortName") or q)
                is_etf = 1 if t.info.get("quoteType") == "ETF" else 0
                results.insert(0, {"symbol": q, "name": name, "market": "US",
                                   "is_etf": is_etf, "yf_symbol": q, "currency": "USD"})
        except Exception:
            pass
    return results
