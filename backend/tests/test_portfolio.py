from app import portfolio


def T(symbol, side, qty, price, d="2026-01-01"):
    """비용을 명시적으로 0으로 둔 체결 — 평단·손익 산술만 검증하는 테스트용."""
    return {"symbol": symbol, "side": side, "quantity": qty, "price": price,
            "trade_date": d, "fee": 0.0, "tax": 0.0}


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


def test_entry_grade_tracked_and_aggregated():
    trades = [dict(T("A", "BUY", 10, 100), grade_at_trade="강력매수", note=None),
              dict(T("A", "BUY", 5, 110), grade_at_trade="중립", note=None),  # 추가 매수는 등급 유지
              dict(T("A", "SELL", 15, 120), grade_at_trade="매도", note="목표가 도달")]
    r = portfolio.realized_pnl(trades)
    assert r[0]["entry_grade"] == "강력매수" and r[0]["note"] == "목표가 도달"
    s = portfolio.realized_stats(r, {"A": {"currency": "KRW"}}, usdkrw=None)
    g = s["by_entry_grade"][0]
    assert g["grade"] == "강력매수" and g["count"] == 1 and g["win_rate"] == 100.0


def test_excluded_lot_still_forms_avg_price_but_flags_realized_entry():
    """평단 맞춤용 보정 로트는 평단에는 그대로 반영되지만, 그 원가로 만든
    실현손익은 실제 체결이 아니므로 basis_adjusted로 표시돼야 한다."""
    trades = [T("A", "BUY", 10, 100),
              dict(T("A", "BUY", 10, 200), exclude_from_stats=1),  # 시트 평단 맞춤 보정
              T("A", "SELL", 20, 160)]
    assert portfolio.compute_holdings(trades[:2])["A"]["avg_price"] == 150
    r = portfolio.realized_pnl(trades)
    assert r[0]["pnl"] == 200 and r[0]["basis_adjusted"] is True


def test_clean_position_is_not_basis_adjusted():
    r = portfolio.realized_pnl([T("A", "BUY", 10, 100), T("A", "SELL", 10, 120)])
    assert r[0]["basis_adjusted"] is False


def test_realized_stats_excludes_basis_adjusted_entries():
    """보정 로트가 섞인 건을 승률에 넣으면 복기 전체가 거짓이 된다 —
    집계에서 빼되, 몇 건을 뺐는지는 화면에 알려야 한다."""
    r = [{"symbol": "A", "pnl": 100, "pnl_pct": 10.0, "basis_adjusted": False},
         {"symbol": "A", "pnl": -50, "pnl_pct": -5.0, "basis_adjusted": False},
         {"symbol": "B", "pnl": 9999, "pnl_pct": 135.0, "basis_adjusted": True}]
    s = portfolio.realized_stats(r, {"A": {"currency": "KRW"}, "B": {"currency": "KRW"}},
                                 usdkrw=None)
    assert s["count"] == 2 and s["excluded_count"] == 1
    assert s["win_rate"] == 50.0 and s["total_pnl_krw"] == 50


def test_realized_stats_uses_trade_fx_rate():
    r = [{"symbol": "AAPL", "pnl": 100, "pnl_pct": 10.0, "fx_rate": 1300.0},
         {"symbol": "AAPL", "pnl": 100, "pnl_pct": 10.0, "fx_rate": None}]  # 과거 행 폴백
    s = portfolio.realized_stats(r, {"AAPL": {"currency": "USD"}}, usdkrw=1400.0)
    assert s["total_pnl_krw"] == 100 * 1300 + 100 * 1400


def test_realized_stats_empty():
    s = portfolio.realized_stats([], {}, usdkrw=None)
    assert s["count"] == 0 and s["win_rate"] is None


KR_T = {"A": {"name": "가", "market": "KR", "currency": "KRW", "is_etf": 0}}
US_T = {"AAPL": {"name": "Apple", "market": "US", "currency": "USD", "is_etf": 0}}


def test_avg_price_includes_buy_fee():
    """평단은 비용 기준 — 수수료를 뺀 평단으로 계산한 수익률은 실제보다 좋게 나온다."""
    h = portfolio.compute_holdings([dict(T("A", "BUY", 10, 100), fee=50.0)], KR_T)
    assert h["A"]["avg_price"] == 105.0  # (1000 + 50) / 10


def test_realized_pnl_is_net_of_fee_and_tax():
    trades = [dict(T("A", "BUY", 10, 100), fee=0.0, tax=0.0),
              dict(T("A", "SELL", 10, 120), fee=20.0, tax=18.0)]
    r = portfolio.realized_pnl(trades, KR_T)[0]
    assert r["pnl_gross"] == 200.0
    assert r["cost"] == 38.0
    assert r["pnl"] == 162.0
    assert r["pnl_pct"] == 16.2


def test_costs_estimated_when_not_recorded():
    """과거 행처럼 수수료 미기록이면 시장 요율로 추정하고 추정 사실을 표시한다."""
    raw = [{k: v for k, v in T("A", side, 10, p).items() if k not in ("fee", "tax")}
           for side, p in (("BUY", 100), ("SELL", 120))]
    r = portfolio.realized_pnl(raw, KR_T)[0]
    assert r["cost_estimated"] is True
    assert r["cost"] > 0 and r["pnl"] < r["pnl_gross"]


def test_small_gain_flips_to_loss_after_costs():
    """비용을 반영하면 승패 판정이 뒤집힌다 — gross 승률이 부풀려지는 지점."""
    trades = [dict(T("A", "BUY", 100, 1000), fee=0.0, tax=0.0),
              dict(T("A", "SELL", 100, 1001), fee=15.0, tax=150.0)]
    r = portfolio.realized_pnl(trades, KR_T)
    assert r[0]["pnl_gross"] > 0 and r[0]["pnl"] < 0
    s = portfolio.realized_stats(r, KR_T, usdkrw=None)
    assert s["win_rate"] == 0.0  # net 기준 패


def test_partial_sell_prorates_costs():
    trades = [dict(T("A", "BUY", 10, 100), fee=0.0, tax=0.0),
              dict(T("A", "SELL", 4, 120), fee=10.0, tax=0.0)]
    r = portfolio.realized_pnl(trades, KR_T)[0]
    assert r["quantity"] == 4 and r["cost"] == 10.0


def test_usd_pnl_settles_both_price_and_fx():
    """ML-3: 매도 환율만 쓰면 원금에 붙은 환차손익이 통째로 빠진다."""
    trades = [dict(T("AAPL", "BUY", 100, 200), fx_rate=1300.0, fee=0.0, tax=0.0),
              dict(T("AAPL", "SELL", 100, 220), fx_rate=1400.0, fee=0.0, tax=0.0)]
    r = portfolio.realized_pnl(trades, US_T)[0]
    assert r["buy_fx"] == 1300.0 and r["sell_fx"] == 1400.0
    assert r["pnl_krw"] == 4_800_000.0            # 220*100*1400 - 200*100*1300
    assert r["price_pnl_krw"] == 2_800_000.0      # (220-200)*100*1400
    assert r["fx_pnl_krw"] == 2_000_000.0         # 200*100*(1400-1300)


def test_avg_fx_is_cost_weighted_across_buys():
    trades = [dict(T("AAPL", "BUY", 100, 200), fx_rate=1300.0, fee=0.0, tax=0.0),
              dict(T("AAPL", "BUY", 100, 200), fx_rate=1500.0, fee=0.0, tax=0.0),
              dict(T("AAPL", "SELL", 200, 200), fx_rate=1400.0, fee=0.0, tax=0.0)]
    r = portfolio.realized_pnl(trades, US_T)[0]
    assert r["buy_fx"] == 1400.0  # 동일 금액 매수 → 평균 환율
    assert r["pnl_krw"] == 0.0    # 가격·환율 모두 제자리


def test_realized_stats_prefers_settled_krw_pnl():
    r = portfolio.realized_pnl(
        [dict(T("AAPL", "BUY", 100, 200), fx_rate=1300.0, fee=0.0, tax=0.0),
         dict(T("AAPL", "SELL", 100, 220), fx_rate=1400.0, fee=0.0, tax=0.0)], US_T)
    s = portfolio.realized_stats(r, US_T, usdkrw=1400.0)
    assert s["total_pnl_krw"] == 4_800_000.0
    assert s["fx_pnl_krw"] == 2_000_000.0


def test_open_risk_sums_across_holdings():
    holdings = {"A": {"quantity": 10, "avg_price": 100.0}}
    out = portfolio.open_risk(holdings, {"A": 5.0}, KR_T, usdkrw=None,
                              total_asset_krw=10_000.0)
    # 2×ATR × 10주 = 100 → 총자산 1만의 1%
    assert out["total_risk_krw"] == 100.0 and out["total_risk_pct"] == 1.0
    assert out["over_limit"] is False
    assert out["rows"][0]["symbol"] == "A"


def test_open_risk_flags_over_limit():
    holdings = {"A": {"quantity": 100, "avg_price": 100.0}}
    out = portfolio.open_risk(holdings, {"A": 5.0}, KR_T, usdkrw=None,
                              total_asset_krw=10_000.0)
    assert out["total_risk_pct"] == 10.0 and out["over_limit"] is True


def test_exit_plan_for_losing_position():
    """물린 포지션에서 화면이 알려줘야 하는 것은 '추가 매수 가능 수량'이 아니라
    지금 나가면 얼마를 회수하고 얼마를 확정하는가다."""
    p = portfolio.exit_plan(held=30, avg_price=100.0, close=80.0, stop_price=72.0,
                            market="KR")
    assert p["unrealized_pnl_pct"] == -20.0
    assert p["unrealized_pnl_krw"] == -600.0
    assert p["stop_from_avg_pct"] == -28.0    # 손절선은 평단 대비 -28%
    assert p["risk_to_stop_krw"] == 240.0     # 여기서 손절선까지 추가로 잃는 금액

    third = next(s for s in p["slices"] if s["label"] == "1/3")
    assert third["quantity"] == 10.0
    # 800원 매도 — KR 수수료 0.015% + 거래세 0.15% = 1.32원
    assert third["proceeds_krw"] == 798.68
    assert third["realized_pnl_krw"] == -201.32
    assert [s["label"] for s in p["slices"]] == ["1/3", "1/2", "전량"]


def test_exit_plan_applies_fx_to_usd_position():
    p = portfolio.exit_plan(held=10, avg_price=100.0, close=150.0, stop_price=140.0,
                            market="US", fx=1000.0)
    assert p["unrealized_pnl_krw"] == 500_000.0
    assert p["slices"][-1]["label"] == "전량" and p["slices"][-1]["quantity"] == 10.0


def test_exit_plan_none_without_holding():
    assert portfolio.exit_plan(held=0, avg_price=100.0, close=80.0,
                               stop_price=72.0, market="KR") is None


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


def test_build_portfolio_cash_usd():
    holdings = {"AAPL": {"quantity": 10, "avg_price": 100.0}}
    tickers = {"AAPL": {"name": "Apple", "market": "US", "currency": "USD"}}
    out = portfolio.build_portfolio(holdings, {"AAPL": 150.0}, tickers,
                                    usdkrw=1000.0, cash_krw=300_000.0, cash_usd=200.0)
    t = out["totals"]
    assert t["cash_usd"] == 200.0
    assert t["cash_usd_krw"] == 200_000.0
    assert t["cash_krw"] == 300_000.0
    assert t["total_asset_krw"] == 2_000_000.0  # 주식 150만 + 현금 50만
    assert t["cash_pct"] == 25.0
    assert {"label": "현금", "value_krw": 500_000.0} in out["allocation"]


def test_total_pnl_pct_of_asset_uses_total_asset_denominator():
    """평가손익률의 분모는 투자원금이다 — 현금 비중이 크면 총자산 대비와 크게 벌어진다.

    이 두 값을 구분하지 않으면 현금 70% 계좌에서 하루 손실을 3배로 체감하고
    멀쩡한 포지션을 조기 청산하게 된다.
    """
    holdings = {"AAPL": {"quantity": 10, "avg_price": 100.0}}
    tickers = {"AAPL": {"name": "Apple", "market": "US", "currency": "USD"}}
    out = portfolio.build_portfolio(holdings, {"AAPL": 150.0}, tickers,
                                    usdkrw=1000.0, cash_krw=3_500_000.0)
    t = out["totals"]
    assert t["total_pnl_krw"] == 500_000.0
    assert t["total_pnl_pct"] == 50.0          # 투자원금 100만 대비
    assert t["total_pnl_pct_of_asset"] == 10.0  # 총자산 500만 대비


def test_total_pnl_pct_of_asset_is_zero_without_assets():
    assert portfolio.build_portfolio({}, {}, {}, usdkrw=None)["totals"][
        "total_pnl_pct_of_asset"] == 0.0


def test_build_portfolio_cash_usd_default_fx():
    out = portfolio.build_portfolio({}, {}, {}, usdkrw=None, cash_usd=100.0)
    assert out["totals"]["cash_usd_krw"] == 100.0 * portfolio.DEFAULT_USDKRW


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


def test_account_risk_uses_trading_day_intersection():
    """ML-11: 합집합+ffill이면 주말 행에서 주식 수익률이 0으로 채워져 변동성이 눌린다."""
    import pandas as pd
    stock_idx = pd.bdate_range("2026-01-01", periods=60)          # 주식 — 거래일만
    coin_idx = pd.date_range("2026-01-01", periods=84)            # 코인 — 365일
    rng = [1.0, -1.0] * 42
    stock = pd.Series([100 * (1 + 0.01 * rng[i]) ** i for i in range(60)], index=stock_idx)
    coin = pd.Series([50.0 + i for i in range(84)], index=coin_idx)
    holdings = {"S": {"quantity": 1, "avg_price": 100.0},
                "C": {"quantity": 1, "avg_price": 50.0}}
    tickers = {"S": {"name": "주식", "currency": "KRW"}, "C": {"name": "코인", "currency": "KRW"}}
    out = portfolio.account_risk(holdings, {"S": stock, "C": coin}, tickers, usdkrw=None)
    assert out["days"] == len(stock_idx)  # 교집합 = 주식 거래일
    # 주말이 빠졌으므로 연간 관측 수는 365가 아니라 250 부근
    assert 240 <= out["periods_per_year"] <= 270
    assert out["mdd_note"] and "소급" in out["mdd_note"]
    assert str(out["days"]) in out["calendar_note"]


def test_account_risk_crypto_only_annualizes_on_365():
    """코인 단독 계좌는 365일 자산 — √252로 연율화하면 약 20% 과소 계상된다."""
    import pandas as pd
    idx = pd.date_range("2026-01-01", periods=200)
    s = pd.Series([100.0 + i for i in range(200)], index=idx)
    out = portfolio.account_risk({"C": {"quantity": 1, "avg_price": 100.0}},
                                 {"C": s}, {"C": {"name": "코인", "currency": "KRW"}},
                                 usdkrw=None)
    assert 350 <= out["periods_per_year"] <= 370


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
