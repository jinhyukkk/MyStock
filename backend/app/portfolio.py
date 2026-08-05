MARKET_LABELS = {"KR": "한국 주식", "US": "미국 주식", "CRYPTO": "암호화폐"}
DEFAULT_USDKRW = 1400.0


def compute_holdings(trades: list) -> dict:
    holdings: dict[str, dict] = {}
    for t in trades:
        s = t["symbol"]
        h = holdings.setdefault(s, {"quantity": 0.0, "avg_price": 0.0})
        if t["side"] == "BUY":
            total_cost = h["avg_price"] * h["quantity"] + t["price"] * t["quantity"]
            h["quantity"] += t["quantity"]
            h["avg_price"] = total_cost / h["quantity"]
        else:
            h["quantity"] -= t["quantity"]
        if h["quantity"] <= 1e-9:
            holdings.pop(s)
    return holdings


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
