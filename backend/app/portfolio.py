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
    KRW 환산은 현재 환율 근사 (체결 시점 환율은 저장하지 않음)."""
    fx = usdkrw or DEFAULT_USDKRW
    total_krw = 0.0
    for r in realized:
        cur = tickers.get(r["symbol"], {}).get("currency", "KRW")
        total_krw += r["pnl"] * (fx if cur == "USD" else 1.0)
    wins = [r["pnl_pct"] for r in realized if r["pnl"] > 0]
    losses = [r["pnl_pct"] for r in realized if r["pnl"] <= 0]
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses) / len(losses) if losses else None
    payoff = round(avg_win / abs(avg_loss), 2) if avg_win and avg_loss else None
    return {
        "count": len(realized),
        "total_pnl_krw": round(total_krw, 0),
        "win_rate": round(len(wins) / len(realized) * 100, 1) if realized else None,
        "avg_win_pct": round(avg_win, 2) if avg_win is not None else None,
        "avg_loss_pct": round(avg_loss, 2) if avg_loss is not None else None,
        "payoff_ratio": payoff,
    }


def build_portfolio(holdings: dict, prices: dict, tickers: dict, usdkrw) -> dict:
    fx = usdkrw or DEFAULT_USDKRW
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
    totals = {"total_value_krw": round(total_value, 0),
              "total_cost_krw": round(total_cost, 0),
              "total_pnl_krw": round(total_value - total_cost, 0),
              "total_pnl_pct": round((total_value / total_cost - 1) * 100, 2) if total_cost else 0.0}
    allocation = [{"label": k, "value_krw": round(v, 0)} for k, v in
                  sorted(alloc.items(), key=lambda x: -x[1])]
    return {"holdings": rows, "totals": totals, "allocation": allocation}
