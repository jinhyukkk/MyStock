import json
from datetime import datetime

import pandas as pd

from app import backtest, db, fetchers, indicators, portfolio, scoring, sentiment

BACKTEST_DAYS = 1100  # 약 3년 — 한 국면짜리 400일 검증은 상승장 착시를 못 거른다


def _active_tickers(conn):
    """워치리스트에 있거나 현재 보유 중인 종목 (보유 종목 + 관심 종목)."""
    holdings = _holdings_map(conn)
    watch = {t["symbol"]: t for t in db.list_tickers(conn, watchlist_only=True)}
    for t in db.list_tickers(conn):
        if t["symbol"] in holdings:
            watch.setdefault(t["symbol"], t)
    return list(watch.values())


def refresh_all(conn, symbol: str | None = None) -> dict:
    """symbol 지정 시 해당 종목만 갱신 — 종목 추가 직후 전체 갱신(수 초) 대신 사용."""
    if symbol is None:
        senti = sentiment.fetch_sentiment()
        db.set_meta(conn, "sentiment", json.dumps(senti))
        targets = _active_tickers(conn)
    else:
        senti = get_sentiment_view(conn)  # 심리지표는 저장분 재사용
        t = db.get_ticker(conn, symbol)
        targets = [t] if t else []
    failed_tickers = []
    for t in targets:
        try:
            df = fetchers.fetch_ohlcv(t["symbol"], t["market"],
                                      yf_symbol=t["yf_symbol"], days=BACKTEST_DAYS)
            db.save_prices(conn, t["symbol"], df)
            _compute_and_store_signal(conn, t, senti)
            if t["yf_symbol"]:
                fund = fetchers.fetch_fundamentals(t["yf_symbol"])
                if fund:
                    db.set_meta(conn, f"fund:{t['symbol']}", json.dumps(fund))
        except Exception:
            failed_tickers.append(t["symbol"])
    if symbol is None:
        for market in {t["market"] for t in targets}:
            try:
                _refresh_benchmark(conn, market)
            except Exception:
                failed_tickers.append(f"BENCH:{market}")
    if symbol is None:  # 단일 갱신은 전체 기준 시각을 건드리지 않는다
        db.set_meta(conn, "last_refresh", datetime.now().isoformat(timespec="seconds"))
    return {"refreshed": True, "failed_sources": senti.get("failed", []),
            "failed_tickers": failed_tickers}


def _compute_and_store_signal(conn, ticker_row, senti):
    df = db.load_prices(conn, ticker_row["symbol"])
    if df.empty:
        return
    enriched = indicators.compute_indicators(df)
    result = scoring.score_ticker(enriched)
    result["context_note"] = sentiment.context_note(
        result["swing_score"], ticker_row["market"], senti)
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


def get_portfolio_view(conn) -> dict:
    holdings = _holdings_map(conn)
    prices = {}
    for s in holdings:
        close, _ = _latest_close_and_change(conn, s)
        if close is not None:
            prices[s] = close
    tickers_map = {t["symbol"]: dict(t) for t in db.list_tickers(conn)}
    fx = get_sentiment_view(conn).get("usdkrw")
    pf = portfolio.build_portfolio(holdings, prices, tickers_map, fx)
    trades = [dict(r) for r in db.list_trades(conn)]
    realized = portfolio.realized_pnl(trades)
    pf["realized"] = {"entries": realized[::-1][:50],
                      "stats": portfolio.realized_stats(realized, tickers_map, fx)}
    return pf


def _risk_block(conn, enriched: pd.DataFrame, currency: str) -> dict | None:
    """ATR 기반 손절 제안 + 계좌 1% 리스크 포지션 사이징 + 종목 MDD."""
    last = enriched.iloc[-1]
    atr = last.get("atr14")
    if atr is None or pd.isna(atr) or not atr:
        return None
    close = float(last["close"])
    atr = float(atr)
    stop = close - 2 * atr
    senti = get_sentiment_view(conn)
    fx = (senti.get("usdkrw") or portfolio.DEFAULT_USDKRW) if currency == "USD" else 1.0
    total = get_portfolio_view(conn)["totals"]["total_value_krw"]
    risk_krw = total * 0.01
    return {
        "atr": round(atr, 4),
        "atr_pct": round(atr / close * 100, 2),
        "stop_price": round(stop, 4),
        "stop_pct": round((stop / close - 1) * 100, 2),
        "mdd_pct": round(indicators.max_drawdown_pct(enriched["close"]), 2),
        # 계좌 총액의 1%만 잃도록 2×ATR 손절 기준 수량 (총액 없으면 None)
        "position_size_1pct": round(risk_krw / (2 * atr * fx), 4) if total > 0 else None,
        "risk_budget_krw": round(risk_krw, 0) if total > 0 else None,
    }


def _refresh_benchmark(conn, market):
    bench_symbol, _ = fetchers.BENCHMARKS[market]
    bdf = fetchers.fetch_ohlcv(bench_symbol, market, yf_symbol=bench_symbol,
                               days=BACKTEST_DAYS)
    db.save_prices(conn, f"BENCH:{market}", bdf)


def get_backtest(conn, symbol) -> dict | None:
    df = db.load_prices(conn, symbol, limit=BACKTEST_DAYS)
    if df.empty:
        return None
    last_date = df.index[-1].strftime("%Y-%m-%d")
    cached = db.get_meta(conn, f"backtest:{symbol}")
    if cached:
        obj = json.loads(cached)
        if obj.get("end") == last_date and "cost_pct" in obj:
            return obj
    t = db.get_ticker(conn, symbol)
    bench, bench_label = None, None
    if t and t["market"] in fetchers.BENCHMARKS:
        bench_label = fetchers.BENCHMARKS[t["market"]][1]
        bdf = db.load_prices(conn, f"BENCH:{t['market']}", limit=BACKTEST_DAYS)
        # 미수집이거나 종목 데이터보다 짧으면(초과수익 구간 불일치) 1회 재수집
        if bdf.empty or bdf.index[0] > df.index[0]:
            try:
                _refresh_benchmark(conn, t["market"])
                bdf = db.load_prices(conn, f"BENCH:{t['market']}", limit=BACKTEST_DAYS)
            except Exception:
                pass
        bench = bdf["close"] if not bdf.empty else None
    result = backtest.backtest_ticker(df, bench=bench, bench_label=bench_label)
    if result:
        db.set_meta(conn, f"backtest:{symbol}", json.dumps(result, ensure_ascii=False))
    return result


def get_ticker_detail(conn, symbol) -> dict | None:
    t = db.get_ticker(conn, symbol)
    if not t:
        return None
    df = db.load_prices(conn, symbol)
    candles = []
    risk = None
    if not df.empty:
        full = indicators.compute_indicators(df)
        risk = _risk_block(conn, full, t["currency"])
        enriched = full.tail(200)
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
        "signal": signal, "candles": candles, "risk": risk,
        "history": [{"date": r["date"], "swing_score": r["swing_score"],
                     "longterm_score": r["longterm_score"], "grade": r["grade"]}
                    for r in db.load_signal_history(conn, symbol)],
        "rules": [dict(r) for r in db.list_rules(conn, symbol)],
    }
