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


def krx_listing() -> list[dict]:
    """KRX 전 종목 스냅샷(FinanceDataReader). 시총 순위·종목명·시장 구분을 여기서 얻는다.
    반환: [{symbol, name, market, marcap, change_pct}] (시총 내림차순).

    네이버 랭킹(pageSize 100 상한)으로는 200 종목 유니버스를 만들 수 없어 fdr 을 쓴다.
    한 번 호출로 2,800여 종목이 오고 0.2초쯤 걸린다(실측 2026-08-22)."""
    import FinanceDataReader as fdr

    df = fdr.StockListing("KRX")
    if df is None or df.empty:
        return []
    df = df.sort_values("Marcap", ascending=False)
    out = []
    for r in df.itertuples():
        code = str(getattr(r, "Code", "") or "")
        if not code:
            continue
        out.append({"symbol": code, "name": getattr(r, "Name", None),
                    "market": getattr(r, "Market", None),
                    "marcap": _f(getattr(r, "Marcap", None)),
                    "change_pct": _f(getattr(r, "ChagesRatio", None))})
    return out


def sp500_listing() -> list[dict]:
    """S&P 500 구성 종목. 반환: [{symbol, name}] (지수 편입 순서 = 알파벳순).
    시총은 안 준다 — 미국 유니버스를 시총 상위 N 으로 자르지 못하는 이유다."""
    import FinanceDataReader as fdr

    df = fdr.StockListing("S&P500")
    if df is None or df.empty:
        return []
    return [{"symbol": str(r.Symbol), "name": getattr(r, "Name", None)}
            for r in df.itertuples() if getattr(r, "Symbol", None)]


def daily_closes_matrix(symbols: list[str], period: str = "1y"):
    """여러 심볼의 일봉 종가 행렬(행=거래일 오름차순, 열=심볼). breadth·차트패턴이 쓴다.

    SMA200 과 52주 신고가를 보려면 1년치가 필요하다 — 그래서 `daily_closes`(최근 2개)와
    따로 둔다. 500 종목 1년치가 한 번의 요청으로 24초쯤(실측 2026-08-22)."""
    import pandas as pd

    if not symbols:
        return pd.DataFrame()
    df = yf.download(symbols, period=period, interval="1d", progress=False,
                     auto_adjust=True, group_by="column", threads=True)
    if df is None or df.empty:
        return pd.DataFrame()
    close = df["Close"] if "Close" in df.columns else df
    if len(symbols) == 1 and close.ndim == 1:
        close = close.to_frame(symbols[0])
    # 전 구간 결측(상장폐지·심볼 오타)인 열은 분모만 늘린다
    return close.dropna(axis=1, how="all")


def earnings_date(symbol: str) -> str | None:
    """다음 실적 발표 예정일(YYYY-MM-DD). 없으면 None.
    yfinance `calendar` 는 종목당 1회 호출이라 부르는 쪽이 개수를 제한해야 한다."""
    cal = yf.Ticker(symbol).calendar or {}
    dates = cal.get("Earnings Date") or []
    if not isinstance(dates, (list, tuple)):
        dates = [dates]
    for d in dates:
        s = getattr(d, "isoformat", lambda: str(d))()
        if s:
            return s[:10]
    return None


def insider_transactions(symbol: str, limit: int = 6) -> list[dict]:
    """내부자 거래(미국). 반환: [{owner, relation, date, transaction, shares, value, price}].

    `Transaction` 열이 비어 오는 행이 많아(실측 2026-08-22 AAPL) 매수/매도 구분과 단가를
    `Text`("Sale at price 307.75 per share.")에서 같이 뽑는다. 방향을 모르는 행을 그대로
    내보내면 화면에서 매수/매도 색이 뒤집혀 보이는 것보다 나쁘다 — 그때는 빈 문자열이다.
    국내 종목은 빈 표가 와서 이 경로를 쓰지 않는다(DART 로 간다)."""
    import re

    df = yf.Ticker(symbol).insider_transactions
    if df is None or getattr(df, "empty", True):
        return []
    out = []
    for row in df.head(limit).to_dict("records"):
        text = str(row.get("Text") or "")
        price = re.search(r"at price\s+([\d,.]+)", text, re.I)
        kind = str(row.get("Transaction") or "").strip()
        if not kind:
            head = text.split(" at ")[0].strip()
            kind = head if len(head) <= 24 else ""
        date = row.get("Start Date")
        out.append({
            "owner": str(row.get("Insider") or ""),
            "relation": str(row.get("Position") or ""),
            "date": str(date)[:10] if date is not None and str(date) != "NaT" else None,
            "transaction": kind,
            "shares": _f(row.get("Shares")),
            "value": _f(row.get("Value")),
            "price": _f(price.group(1).replace(",", "")) if price else None,
            "url": str(row.get("URL") or "") or None,
        })
    return out
