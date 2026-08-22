"""yfinance 어댑터 — 회사 자료용.

`fetchers.fetch_ohlcv`/`fetch_fundamentals`(시세·기존 계약)와 의도적으로 분리했다.
저쪽은 대시보드가 매 갱신마다 부르는 경로라 필드를 늘리면 기존 응답 계약이 흔들린다.

모든 함수는 **plain dict/list**만 돌려준다. pandas 객체를 그대로 넘기면 상위 계층이
NaN·Timestamp를 JSON으로 못 싣고, 테스트 픽스처도 만들 수 없다.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone


def _ticker(yf_symbol: str):
    import yfinance as yf
    return yf.Ticker(yf_symbol)


def _num(v):
    """NaN·inf·pandas 스칼라를 float|None으로. NaN이 JSON에 실리면 프론트에서
    `NaN` 문자열이 화면에 그대로 찍힌다."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _date_str(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(float(v), tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return v.date().isoformat()  # pandas Timestamp / datetime
    except AttributeError:
        pass
    try:
        return v.isoformat()  # date
    except AttributeError:
        return None


def quote_info(yf_symbol: str) -> dict:
    """`info` + 차트 메타 + 실적 캘린더. 프로필·스냅샷이 함께 쓰는 한 덩어리다.

    `firstTradeDateEpochUtc`는 종목에 따라 None으로 오므로(AAPL 실측 2026-08-21)
    상장일은 차트 메타의 `firstTradeDate`로 보강한다 — 이게 없으면 IPO 칸이 항상 빈다.
    """
    t = _ticker(yf_symbol)
    info = dict(t.info or {})
    meta = {}
    try:
        meta = dict(t.history_metadata or {})
    except Exception:
        meta = {}
    cal = {}
    try:
        raw_cal = t.calendar or {}
        for k, v in raw_cal.items():
            if isinstance(v, list):
                cal[k] = [_date_str(x) or x for x in v]
            elif hasattr(v, "isoformat"):
                cal[k] = _date_str(v)
            else:
                cal[k] = _num(v)
    except Exception:
        cal = {}
    return {
        "info": {k: v for k, v in info.items() if not hasattr(v, "shape")},
        "first_trade_date": _date_str(meta.get("firstTradeDate")),
        "calendar": cal,
    }


def estimates(yf_symbol: str) -> dict:
    """EPS 추정치·성장 추정치·실적 서프라이즈. 전부 실패해도 빈 dict로 끝낸다."""
    t = _ticker(yf_symbol)
    out: dict = {"eps_trend": {}, "growth": {}, "earnings": []}
    try:
        df = t.eps_trend
        for period, row in df.iterrows():
            out["eps_trend"][str(period)] = _num(row.get("current"))
    except Exception:
        pass
    try:
        df = t.growth_estimates
        for period, row in df.iterrows():
            out["growth"][str(period)] = _num(row.get("stockTrend"))
    except Exception:
        pass
    try:
        df = t.earnings_dates
        for idx, row in df.iterrows():
            out["earnings"].append({
                "date": _date_str(idx),
                "eps_estimate": _num(row.get("EPS Estimate")),
                "eps_reported": _num(row.get("Reported EPS")),
                "surprise_pct": _num(row.get("Surprise(%)")),
            })
    except Exception:
        pass
    return out


def _stmt_rows(df, keys: list[str]) -> list[dict]:
    rows = []
    if df is None or getattr(df, "empty", True):
        return rows
    for col in df.columns:
        item = {"end_date": _date_str(col)}
        for key in keys:
            item[key] = None
        for label, target in (("Diluted EPS", "eps"), ("Basic EPS", "eps"),
                              ("Total Revenue", "sales"), ("Operating Revenue", "sales"),
                              ("Diluted Average Shares", "shares"),
                              ("Basic Average Shares", "shares"),
                              ("Net Income", "net_income"),
                              ("Operating Income", "operating_income"),
                              ("Pretax Income", "pretax_income"),
                              ("Tax Provision", "tax_provision")):
            if label in df.index and item.get(target) is None:
                item[target] = _num(df.loc[label, col])
        rows.append(item)
    return rows


def financials(yf_symbol: str) -> dict:
    """연간·분기 손익계산서 + 부채 항목(장기부채비율 계산용)."""
    t = _ticker(yf_symbol)
    keys = ["eps", "sales", "shares", "net_income", "operating_income",
            "pretax_income", "tax_provision"]
    out = {"annual": [], "quarterly": [], "balance": {}}
    try:
        out["annual"] = _stmt_rows(t.income_stmt, keys)
    except Exception:
        pass
    try:
        out["quarterly"] = _stmt_rows(t.quarterly_income_stmt, keys)
    except Exception:
        pass
    try:
        bs = t.balance_sheet
        if bs is not None and not bs.empty:
            col = bs.columns[0]
            for label, key in (("Long Term Debt", "long_term_debt"),
                               ("Total Debt", "total_debt"),
                               ("Stockholders Equity", "equity"),
                               ("Total Assets", "total_assets"),
                               ("Invested Capital", "invested_capital")):
                if label in bs.index:
                    out["balance"][key] = _num(bs.loc[label, col])
    except Exception:
        pass
    return out


def news(yf_symbol: str, limit: int = 10) -> list[dict]:
    items = []
    for row in (_ticker(yf_symbol).news or [])[:limit]:
        c = row.get("content") or row
        url = ((c.get("canonicalUrl") or {}).get("url")
               or (c.get("clickThroughUrl") or {}).get("url"))
        if not c.get("title") or not url:
            continue
        items.append({"title": c.get("title"), "url": url,
                      "published_at": c.get("pubDate") or c.get("displayTime"),
                      "source": (c.get("provider") or {}).get("displayName")})
    return items


def upgrades_downgrades(yf_symbol: str, limit: int = 20) -> list[dict]:
    df = _ticker(yf_symbol).upgrades_downgrades
    out = []
    if df is None or df.empty:
        return out
    df = df.sort_index(ascending=False).head(limit)
    for idx, row in df.iterrows():
        out.append({
            "date": _date_str(idx),
            "firm": str(row.get("Firm") or "").strip() or None,
            "action": str(row.get("Action") or "").strip() or None,
            "from_grade": str(row.get("FromGrade") or "").strip() or None,
            "to_grade": str(row.get("ToGrade") or "").strip() or None,
            "from_target": _num(row.get("priorPriceTarget")),
            "to_target": _num(row.get("currentPriceTarget")),
        })
    return out


def insider_transactions(yf_symbol: str, limit: int = 30) -> list[dict]:
    df = _ticker(yf_symbol).insider_transactions
    out = []
    if df is None or df.empty:
        return out
    for _, row in df.head(limit).iterrows():
        out.append({
            "name": str(row.get("Insider") or "").strip() or None,
            "relation": str(row.get("Position") or "").strip() or None,
            "date": _date_str(row.get("Start Date")),
            "transaction": str(row.get("Transaction") or "").strip() or None,
            "text": str(row.get("Text") or "").strip() or None,
            "shares": _num(row.get("Shares")),
            "value": _num(row.get("Value")),
            "url": str(row.get("URL") or "").strip() or None,
        })
    return out


def dividend_history(yf_symbol: str) -> list[dict]:
    """배당 지급 이력 — 배당성장 3/5년 계산용. 없으면 빈 목록."""
    ser = _ticker(yf_symbol).dividends
    out = []
    if ser is None or len(ser) == 0:
        return out
    for idx, amount in ser.items():
        d = _date_str(idx)
        a = _num(amount)
        if d and a:
            out.append({"date": d, "amount": a})
    return out


def monthly_closes(yf_symbol: str, period: str = "10y") -> list[dict]:
    """10년 성과용 월봉. 일봉 1100영업일(≈4.8년)로는 10Y 칸을 만들 수 없다."""
    df = _ticker(yf_symbol).history(period=period, interval="1mo", auto_adjust=True)
    out = []
    if df is None or df.empty:
        return out
    for idx, row in df.iterrows():
        close = _num(row.get("Close"))
        if close is None:
            continue
        out.append({"date": _date_str(idx), "close": close})
    return out
