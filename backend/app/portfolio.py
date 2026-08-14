import pandas as pd

MARKET_LABELS = {"KR": "한국 주식", "US": "미국 주식", "CRYPTO": "암호화폐"}
DEFAULT_USDKRW = 1400.0


def _walk_trades(trades: list) -> tuple[dict, list]:
    """매매 내역을 시간순으로 재생해 (현재 보유, 실현손익 원장)을 만든다.
    실현손익은 평단가(이동평균) 기준 — 보유 평단 계산 방식과 일관되게."""
    holdings: dict[str, dict] = {}
    realized: list[dict] = []
    for t in trades:
        s = t["symbol"]
        h = holdings.setdefault(s, {"quantity": 0.0, "avg_price": 0.0})
        if t["side"] == "BUY":
            if h["quantity"] == 0:  # 신규 진입 — 첫 매수 시점 등급이 복기 기준
                h["entry_grade"] = t.get("grade_at_trade")
            total_cost = h["avg_price"] * h["quantity"] + t["price"] * t["quantity"]
            h["quantity"] += t["quantity"]
            h["avg_price"] = total_cost / h["quantity"]
        else:
            qty = min(t["quantity"], h["quantity"])
            if qty > 0 and h["avg_price"] > 0:
                realized.append({
                    "symbol": s, "trade_date": t["trade_date"], "quantity": qty,
                    "buy_price": h["avg_price"], "sell_price": t["price"],
                    "pnl": round((t["price"] - h["avg_price"]) * qty, 4),
                    "pnl_pct": round((t["price"] / h["avg_price"] - 1) * 100, 2),
                    # ponytail: 매도 시점 환율로 전체 손익 환산 — 매수/매도 환율 분리 정산이 필요해지면 평균 매수 환율 추적 추가
                    "fx_rate": t.get("fx_rate"),
                    "entry_grade": h.get("entry_grade"),
                    "note": t.get("note"),
                })
            h["quantity"] -= t["quantity"]
        if h["quantity"] <= 1e-9:
            holdings.pop(s)
    return holdings, realized


def compute_holdings(trades: list) -> dict:
    return _walk_trades(trades)[0]


def realized_pnl(trades: list) -> list[dict]:
    return _walk_trades(trades)[1]


def realized_stats(realized: list, tickers: dict, usdkrw) -> dict:
    """승률·평균 손익비 — 트레이더 자기 복기용 핵심 지표.
    KRW 환산은 매도 체결 시점 환율 우선, 미기록(과거 행)은 현재 환율 폴백."""
    fx = usdkrw or DEFAULT_USDKRW
    total_krw = 0.0
    for r in realized:
        cur = tickers.get(r["symbol"], {}).get("currency", "KRW")
        rate = r.get("fx_rate") or (fx if cur == "USD" else 1.0)
        total_krw += r["pnl"] * rate
    wins = [r["pnl_pct"] for r in realized if r["pnl"] > 0]
    losses = [r["pnl_pct"] for r in realized if r["pnl"] <= 0]
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses) / len(losses) if losses else None
    payoff = round(avg_win / abs(avg_loss), 2) if avg_win and avg_loss else None
    # 진입 등급별 성과 — "시그널 따른 매매 vs 뇌동매매"를 분리해서 본다
    by_grade: dict[str, list] = {}
    for r in realized:
        by_grade.setdefault(r.get("entry_grade") or "미기록", []).append(r)
    grade_stats = [
        {"grade": g, "count": len(rows),
         "win_rate": round(sum(r["pnl"] > 0 for r in rows) / len(rows) * 100, 1),
         "avg_pnl_pct": round(sum(r["pnl_pct"] for r in rows) / len(rows), 2)}
        for g, rows in sorted(by_grade.items(), key=lambda x: -len(x[1]))]
    return {
        "count": len(realized),
        "total_pnl_krw": round(total_krw, 0),
        "win_rate": round(len(wins) / len(realized) * 100, 1) if realized else None,
        "avg_win_pct": round(avg_win, 2) if avg_win is not None else None,
        "avg_loss_pct": round(avg_loss, 2) if avg_loss is not None else None,
        "payoff_ratio": payoff,
        "by_entry_grade": grade_stats,
    }


def build_portfolio(holdings: dict, prices: dict, tickers: dict, usdkrw,
                    cash_krw: float = 0.0, cash_usd: float = 0.0) -> dict:
    fx = usdkrw or DEFAULT_USDKRW
    cash_usd_krw = cash_usd * fx
    cash_total_krw = cash_krw + cash_usd_krw
    rows, alloc = [], {}
    total_value = total_cost = 0.0
    for symbol, h in holdings.items():
        info = tickers.get(symbol, {})
        currency = info.get("currency", "KRW")
        close = prices.get(symbol)
        rate = fx if currency == "USD" else 1.0
        value = pnl = pnl_pct = None
        if close is not None:
            value = close * h["quantity"]
            pnl = (close - h["avg_price"]) * h["quantity"]
            pnl_pct = round((close / h["avg_price"] - 1) * 100, 2) if h["avg_price"] else None
            total_value += value * rate
            total_cost += h["avg_price"] * h["quantity"] * rate
            label = MARKET_LABELS.get(info.get("market"), "기타")
            alloc[label] = alloc.get(label, 0.0) + value * rate
        rows.append({"symbol": symbol, "name": info.get("name", symbol),
                     "market": info.get("market"), "currency": currency,
                     "quantity": h["quantity"], "avg_price": h["avg_price"],
                     "close": close, "value": value, "pnl": pnl, "pnl_pct": pnl_pct})
    total_asset = total_value + cash_total_krw
    totals = {"total_value_krw": round(total_value, 0),
              "total_cost_krw": round(total_cost, 0),
              "total_pnl_krw": round(total_value - total_cost, 0),
              "total_pnl_pct": round((total_value / total_cost - 1) * 100, 2) if total_cost else 0.0,
              "cash_krw": round(cash_krw, 0),
              "cash_usd": round(cash_usd, 2),
              "cash_usd_krw": round(cash_usd_krw, 0),
              "total_asset_krw": round(total_asset, 0),
              "cash_pct": round(cash_total_krw / total_asset * 100, 1) if total_asset else 0.0}
    allocation = [{"label": k, "value_krw": round(v, 0)} for k, v in
                  sorted(alloc.items(), key=lambda x: -x[1])]
    if cash_total_krw > 0:
        allocation.append({"label": "현금", "value_krw": round(cash_total_krw, 0)})
    return {"holdings": rows, "totals": totals, "allocation": allocation}


def account_risk(holdings: dict, closes: dict, tickers: dict, usdkrw,
                 cash_krw: float = 0.0) -> dict | None:
    """계좌 단위 리스크 — 종목 비중(집중도), 상관계수, 변동성/MDD.
    현재 보유 수량을 과거 종가에 그대로 적용한 근사이며 환율은 현재 값 고정."""
    fx = usdkrw or DEFAULT_USDKRW
    series = {s: closes[s] for s in holdings
              if s in closes and closes[s] is not None and len(closes[s]) > 1}
    if not series:
        return None
    frame = pd.DataFrame(series).ffill().dropna()
    if len(frame) < 20:
        return None
    rates = {s: (fx if tickers.get(s, {}).get("currency") == "USD" else 1.0)
             for s in frame.columns}
    qty = {s: holdings[s]["quantity"] for s in frame.columns}
    port = sum(frame[s] * qty[s] * rates[s] for s in frame.columns)
    rets = port.pct_change().dropna()
    mdd = float(((port / port.cummax()) - 1).min() * 100)

    last_vals = {s: float(frame[s].iloc[-1]) * qty[s] * rates[s] for s in frame.columns}
    total_asset = sum(last_vals.values()) + max(cash_krw, 0.0)
    weights = sorted(
        [{"symbol": s, "name": tickers.get(s, {}).get("name", s),
          "weight_pct": round(v / total_asset * 100, 1)} for s, v in last_vals.items()],
        key=lambda w: -w["weight_pct"])

    corr = None
    if len(frame.columns) >= 2:
        m = frame.pct_change().corr()
        symbols = list(m.columns)
        corr = {"symbols": symbols,
                "names": [tickers.get(s, {}).get("name", s) for s in symbols],
                "matrix": [[round(float(m.iloc[i, j]), 2) for j in range(len(symbols))]
                           for i in range(len(symbols))]}
    return {
        "days": len(frame),
        "weights": weights,
        "max_weight_pct": weights[0]["weight_pct"] if weights else None,
        "volatility_pct": round(float(rets.std() * (252 ** 0.5) * 100), 1),
        "mdd_pct": round(mdd, 2),
        "corr": corr,
    }
