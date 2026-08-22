"""대시보드(시장 전체) 외부 시세 호출 — yfinance 얇은 래퍼.

종목상세 세션이 만드는 `app.sources.*`와 같은 역할이지만, 그쪽 작업이 끝나기 전에는
그 패키지를 건드리지 않으려고 따로 둔다. 끝나면 이 파일의 함수들은 `sources/yf.py`로
옮기면 되도록 **시그니처를 단순하게(심볼 in → dict/list out), 상태 없이** 유지한다.

규칙: 여기서는 파싱만 한다. 캐시·TTL·실패 격리는 `market.py` 몫 — 여기에 섞으면
테스트가 yfinance 대신 이 함수들만 monkeypatch 해서 네트워크 없이 돌 수 없다.
"""
from __future__ import annotations

import math

import yfinance as yf


def _f(v) -> float | None:
    """numpy/NaN/None 을 JSON 에 실을 수 있는 float 또는 None 으로."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else x


def intraday(symbol: str) -> dict:
    """당일 5분봉 + 전일 종가. 반환: {last, prev_close, candles:[{o,h,l,c,v}]}.
    전일 종가는 전일 마지막 5분봉 종가로 잡는다 — fast_info 를 또 부르면 지수 3개에
    호출이 배로 늘고, 이 값은 등락 계산에만 쓰여 그 정도 정밀도면 충분하다."""
    t = yf.Ticker(symbol)
    h = t.history(period="2d", interval="5m")
    if h.empty:
        return {"last": None, "prev_close": None, "candles": []}
    days = sorted({d.date() for d in h.index})
    today = h[[d.date() == days[-1] for d in h.index]]
    prev = h[[d.date() == days[-2] for d in h.index]] if len(days) > 1 else None
    candles = [{"o": _f(r.Open), "h": _f(r.High), "l": _f(r.Low), "c": _f(r.Close),
                "v": _f(r.Volume)} for r in today.itertuples()]
    return {"last": _f(today["Close"].iloc[-1]),
            "prev_close": _f(prev["Close"].iloc[-1]) if prev is not None and not prev.empty else None,
            "candles": candles}


def daily_closes(symbols: list[str]) -> dict[str, dict]:
    """여러 심볼의 최근 종가 두 개를 한 번의 요청으로. 반환: {symbol: {last, prev_close}}.
    선물·환율·히트맵(100여 종목)을 심볼마다 부르면 요청이 100번이라 차단당한다 —
    yf.download 는 한 번에 받는다."""
    if not symbols:
        return {}
    df = yf.download(symbols, period="5d", interval="1d", progress=False,
                     auto_adjust=True, group_by="column", threads=True)
    if df is None or df.empty:
        return {}
    close = df["Close"] if "Close" in df.columns else df
    # 단일 심볼이면 Series 로 온다 — 열 이름을 맞춰 DataFrame 으로
    if len(symbols) == 1 and close.ndim == 1:
        close = close.to_frame(symbols[0])
    out: dict[str, dict] = {}
    for s in symbols:
        if s not in close.columns:
            continue
        col = close[s].dropna()
        if col.empty:
            continue
        out[s] = {"last": _f(col.iloc[-1]),
                  "prev_close": _f(col.iloc[-2]) if len(col) > 1 else None}
    return out


def screen(name: str, count: int = 10) -> list[dict]:
    """야후 사전 정의 스크리너(day_gainers, day_losers, most_actives …).
    반환: [{symbol, last, change_pct, volume}]"""
    r = yf.screen(name, count=count)
    out = []
    for q in (r or {}).get("quotes", []):
        if not q.get("symbol"):
            continue
        out.append({"symbol": q["symbol"],
                    "last": _f(q.get("regularMarketPrice")),
                    "change_pct": _f(q.get("regularMarketChangePercent")),
                    "volume": _f(q.get("regularMarketVolume"))})
    return out


def news(symbol: str, limit: int = 8) -> list[dict]:
    """종목/지수 뉴스. 반환: [{title, source, url, published_at}] (ISO8601 UTC 문자열)."""
    items = yf.Ticker(symbol).news or []
    out = []
    for it in items[:limit]:
        c = it.get("content") or it   # yfinance 0.2.5x 는 content 아래, 구버전은 평면
        title = c.get("title")
        if not title:
            continue
        out.append({
            "title": title,
            "source": ((c.get("provider") or {}).get("displayName")
                       or it.get("publisher") or ""),
            "url": ((c.get("canonicalUrl") or {}).get("url")
                    or (c.get("clickThroughUrl") or {}).get("url") or it.get("link") or ""),
            "published_at": c.get("pubDate") or c.get("displayTime") or "",
        })
    return out
