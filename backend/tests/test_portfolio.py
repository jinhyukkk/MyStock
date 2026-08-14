from app import portfolio


def T(symbol, side, qty, price, d="2026-01-01"):
    return {"symbol": symbol, "side": side, "quantity": qty, "price": price, "trade_date": d}


def test_avg_price_weighted():
    h = portfolio.compute_holdings([T("A", "BUY", 10, 100), T("A", "BUY", 10, 200)])
    assert h["A"]["quantity"] == 20 and h["A"]["avg_price"] == 150


def test_sell_keeps_avg_price():
    h = portfolio.compute_holdings([T("A", "BUY", 10, 100), T("A", "SELL", 4, 300)])
    assert h["A"]["quantity"] == 6 and h["A"]["avg_price"] == 100


def test_full_sell_removes_holding():
    h = portfolio.compute_holdings([T("A", "BUY", 10, 100), T("A", "SELL", 10, 120)])
    assert "A" not in h


def test_realized_pnl_avg_cost_basis():
    r = portfolio.realized_pnl([T("A", "BUY", 10, 100), T("A", "BUY", 10, 200),
                                T("A", "SELL", 5, 300)])
    assert len(r) == 1
    assert r[0]["buy_price"] == 150 and r[0]["pnl"] == 750 and r[0]["pnl_pct"] == 100.0


def test_realized_pnl_ignores_sell_without_holding():
    assert portfolio.realized_pnl([T("A", "SELL", 5, 100)]) == []


def test_realized_stats():
    r = [{"symbol": "A", "pnl": 100, "pnl_pct": 10.0},
         {"symbol": "A", "pnl": -50, "pnl_pct": -5.0}]
    s = portfolio.realized_stats(r, {"A": {"currency": "KRW"}}, usdkrw=None)
    assert s["count"] == 2 and s["win_rate"] == 50.0
    assert s["total_pnl_krw"] == 50 and s["payoff_ratio"] == 2.0


def test_realized_stats_empty():
    s = portfolio.realized_stats([], {}, usdkrw=None)
    assert s["count"] == 0 and s["win_rate"] is None


def test_build_portfolio_usd_conversion():
    holdings = {"AAPL": {"quantity": 10, "avg_price": 100.0}}
    tickers = {"AAPL": {"name": "Apple", "market": "US", "currency": "USD"}}
    out = portfolio.build_portfolio(holdings, {"AAPL": 150.0}, tickers, usdkrw=1000.0)
    h = out["holdings"][0]
    assert h["pnl"] == 500.0 and h["pnl_pct"] == 50.0
    assert out["totals"]["total_value_krw"] == 1_500_000.0
    assert out["allocation"][0]["label"] == "미국 주식"


def test_build_portfolio_cash():
    holdings = {"AAPL": {"quantity": 10, "avg_price": 100.0}}
    tickers = {"AAPL": {"name": "Apple", "market": "US", "currency": "USD"}}
    out = portfolio.build_portfolio(holdings, {"AAPL": 150.0}, tickers,
                                    usdkrw=1000.0, cash_krw=500_000.0)
    t = out["totals"]
    assert t["total_asset_krw"] == 2_000_000.0
    assert t["cash_krw"] == 500_000.0 and t["cash_pct"] == 25.0
    assert {"label": "현금", "value_krw": 500_000.0} in out["allocation"]


def test_account_risk():
    import pandas as pd
    idx = pd.date_range("2026-01-01", periods=60)
    a = pd.Series(range(100, 160), index=idx, dtype=float)
    holdings = {"A": {"quantity": 1, "avg_price": 100.0},
                "B": {"quantity": 2, "avg_price": 50.0}}
    closes = {"A": a, "B": a * 0.5}  # 완전 동행 → 상관 1.0
    tickers = {"A": {"name": "가", "currency": "KRW"}, "B": {"name": "나", "currency": "KRW"}}
    out = portfolio.account_risk(holdings, closes, tickers, usdkrw=None, cash_krw=159.0)
    assert out is not None
    # 총자산 = A 159 + B 159 + 현금 159 → 각 종목 33.3%
    assert out["weights"][0]["weight_pct"] == 33.3
    assert out["corr"]["matrix"][0][1] == 1.0
    assert out["mdd_pct"] == 0.0  # 단조 상승 → 낙폭 없음


def test_account_risk_insufficient():
    assert portfolio.account_risk({}, {}, {}, usdkrw=None) is None


def test_build_portfolio_missing_price():
    holdings = {"A": {"quantity": 5, "avg_price": 10.0}}
    tickers = {"A": {"name": "가", "market": "KR", "currency": "KRW"}}
    out = portfolio.build_portfolio(holdings, {}, tickers, usdkrw=None)
    assert out["holdings"][0]["close"] is None  # 가격 없어도 죽지 않음


def test_build_portfolio_default_fx_when_usdkrw_none():
    holdings = {"AAPL": {"quantity": 10, "avg_price": 100.0}}
    tickers = {"AAPL": {"name": "Apple", "market": "US", "currency": "USD"}}
    out = portfolio.build_portfolio(holdings, {"AAPL": 150.0}, tickers, usdkrw=None)
    assert out["totals"]["total_value_krw"] == 150.0 * 10 * 1400.0
