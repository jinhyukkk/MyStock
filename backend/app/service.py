import json
from datetime import datetime

import pandas as pd

from app import db, fetchers, indicators, portfolio, scoring, sentiment


def _active_tickers(conn):
    """워치리스트에 있거나 현재 보유 중인 종목 (보유 종목 + 관심 종목)."""
    holdings = _holdings_map(conn)
    watch = {t["symbol"]: t for t in db.list_tickers(conn, watchlist_only=True)}
    for t in db.list_tickers(conn):
        if t["symbol"] in holdings:
            watch.setdefault(t["symbol"], t)
    return list(watch.values())


def refresh_all(conn) -> dict:
    senti = sentiment.fetch_sentiment()
    db.set_meta(conn, "sentiment", json.dumps(senti))
    failed_tickers = []
    for t in _active_tickers(conn):
        try:
            df = fetchers.fetch_ohlcv(t["symbol"], t["market"],
                                      yf_symbol=t["yf_symbol"], days=400)
            db.save_prices(conn, t["symbol"], df)
            _compute_and_store_signal(conn, t, senti)
            if t["yf_symbol"]:
                fund = fetchers.fetch_fundamentals(t["yf_symbol"])
                if fund:
                    db.set_meta(conn, f"fund:{t['symbol']}", json.dumps(fund))
        except Exception:
            failed_tickers.append(t["symbol"])
    db.set_meta(conn, "last_refresh", datetime.now().isoformat(timespec="seconds"))
    return {"refreshed": True, "failed_sources": senti["failed"],
            "failed_tickers": failed_tickers}


def _compute_and_store_signal(conn, ticker_row, senti):
    df = db.load_prices(conn, ticker_row["symbol"])
    if df.empty:
        return
    enriched = indicators.compute_indicators(df)
    result = scoring.score_ticker(enriched)
    adj_swing, note = sentiment.adjust_score(
        result["swing_score"], ticker_row["market"], senti)
    result["swing_score"] = adj_swing
    result["swing_grade"] = scoring.grade(adj_swing)
    result["context_note"] = note
    date_str = df.index[-1].strftime("%Y-%m-%d")
    db.save_signal(conn, ticker_row["symbol"], date_str,
                   result["swing_score"], result["longterm_score"],
                   result["swing_grade"], json.dumps(result, ensure_ascii=False))


def _latest_close_and_change(conn, symbol):
    df = db.load_prices(conn, symbol, limit=2)
    if df.empty:
        return None, None
    close = float(df.iloc[-1]["close"])
    if len(df) < 2:
        return close, None
    prev = float(df.iloc[-2]["close"])
    return close, round((close / prev - 1) * 100, 2)


def _holdings_map(conn):
    trades = [dict(r) for r in db.list_trades(conn)]
    return portfolio.compute_holdings(trades)


def check_rules(conn, prices: dict, avg_prices: dict) -> list:
    alerts = []
    for r in db.list_rules(conn):
        symbol = r["symbol"]
        close = prices.get(symbol)
        if close is None:
            continue
        t = db.get_ticker(conn, symbol)
        name = t["name"] if t else symbol
        if r["rule_type"] == "TARGET" and close >= r["value"]:
            alerts.append({"symbol": symbol, "name": name, "rule_type": "TARGET",
                           "value": r["value"],
                           "message": f"{name} 목표가 {r['value']:,.0f} 도달 (현재 {close:,.0f})"})
        elif r["rule_type"] == "STOP" and close <= r["value"]:
            alerts.append({"symbol": symbol, "name": name, "rule_type": "STOP",
                           "value": r["value"],
                           "message": f"{name} 손절가 {r['value']:,.0f} 도달 (현재 {close:,.0f})"})
        elif r["rule_type"] == "AVG_PCT":
            avg = avg_prices.get(symbol)
            if not avg:
                continue
            change = (close / avg - 1) * 100
            v = r["value"]
            if (v > 0 and change >= v) or (v < 0 and change <= v):
                alerts.append({"symbol": symbol, "name": name, "rule_type": "AVG_PCT",
                               "value": v,
                               "message": f"{name} 평단 대비 {change:+.1f}% (조건 {v:+.0f}%)"})
    return alerts


def get_sentiment_view(conn) -> dict:
    raw = db.get_meta(conn, "sentiment")
    senti = json.loads(raw) if raw else {"vix": None, "vkospi": None,
                                         "cnn_fg": None, "crypto_fg": None,
                                         "usdkrw": None, "failed": []}
    senti["cnn_fg_label"] = sentiment.fg_label(senti.get("cnn_fg"))
    senti["crypto_fg_label"] = sentiment.fg_label(senti.get("crypto_fg"))
    return senti


def get_dashboard(conn) -> dict:
    senti = get_sentiment_view(conn)
    holdings = _holdings_map(conn)
    active = _active_tickers(conn)
    prices, signals = {}, []
    for t in active:
        close, change = _latest_close_and_change(conn, t["symbol"])
        if close is not None:
            prices[t["symbol"]] = close
        sig = db.get_latest_signal(conn, t["symbol"])
        if not sig:
            continue
        details = json.loads(sig["details"]) if sig["details"] else {}
        prev_grade = db.get_prev_grade(conn, t["symbol"])
        signals.append({
            "symbol": t["symbol"], "name": t["name"], "market": t["market"],
            "currency": t["currency"], "close": close, "change_pct": change,
            "swing_score": sig["swing_score"], "swing_grade": sig["grade"],
            "longterm_score": sig["longterm_score"],
            "longterm_grade": scoring.grade(sig["longterm_score"]),
            "grade_changed": prev_grade is not None and prev_grade != sig["grade"],
            "is_holding": t["symbol"] in holdings,
            "in_watchlist": bool(t["in_watchlist"]),
            "context_note": details.get("context_note"),
            "summary": details.get("summary"),
        })
    signals.sort(key=lambda s: -abs(s["swing_score"]))
    tickers_map = {t["symbol"]: dict(t) for t in active}
    pf = portfolio.build_portfolio(holdings, prices, tickers_map, senti.get("usdkrw"))
    avg_prices = {s: h["avg_price"] for s, h in holdings.items()}
    return {
        "sentiment": senti,
        "portfolio_summary": {**pf["totals"], "holdings_count": len(holdings)},
        "signals": signals,
        "rule_alerts": check_rules(conn, prices, avg_prices),
        "last_refresh": db.get_meta(conn, "last_refresh"),
        "failed_sources": senti.get("failed", []),
    }


def get_ticker_detail(conn, symbol) -> dict | None:
    t = db.get_ticker(conn, symbol)
    if not t:
        return None
    df = db.load_prices(conn, symbol)
    candles = []
    if not df.empty:
        enriched = indicators.compute_indicators(df).tail(200)
        enriched = enriched.astype(object).where(pd.notna(enriched), None)
        for idx, row in enriched.iterrows():
            candles.append({"date": idx.strftime("%Y-%m-%d"), **{
                k: (round(row[k], 4) if row[k] is not None else None)
                for k in ["open", "high", "low", "close", "volume", "sma20", "sma60",
                          "sma120", "bb_upper", "bb_lower", "rsi", "macd",
                          "macd_signal", "macd_hist"]}})
    sig = db.get_latest_signal(conn, symbol)
    signal = json.loads(sig["details"]) if sig and sig["details"] else None
    fund_raw = db.get_meta(conn, f"fund:{symbol}")
    return {
        "symbol": symbol, "name": t["name"], "market": t["market"],
        "currency": t["currency"], "is_etf": t["is_etf"],
        "fundamentals": json.loads(fund_raw) if fund_raw else None,
        "signal": signal, "candles": candles,
        "history": [{"date": r["date"], "swing_score": r["swing_score"],
                     "longterm_score": r["longterm_score"], "grade": r["grade"]}
                    for r in db.load_signal_history(conn, symbol)],
        "rules": [dict(r) for r in db.list_rules(conn, symbol)],
    }
