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


def test_exit_plan_reports_r_multiple():
    """+27.91% 보다 +2.1R 이 익절·추격 판단에 직결된다.

    1R은 이 앱이 사이징에 쓰는 리스크 단위(현재가에서 손절선까지 = 2×ATR)로 잰다.
    '평단 − 손절선'으로 재면 수익 중인 포지션(손절선이 평단 위로 올라간 경우)에서
    값이 사라지는데, 익절 판단이 가장 필요한 순간이 바로 그때다.
    """
    # 1R = 130 - 110 = 20, 평단 대비 +30 → +1.5R
    p = portfolio.exit_plan(held=10, avg_price=100.0, close=130.0, stop_price=110.0,
                            market="KR")
    assert p["r_unit"] == 20.0 and p["r_multiple"] == 1.5


def test_r_multiple_is_negative_while_underwater():
    # 1R = 95 - 90 = 5, 평단 대비 -5 → -1R
    p = portfolio.exit_plan(held=10, avg_price=100.0, close=95.0, stop_price=90.0,
                            market="KR")
    assert p["r_multiple"] == -1.0


def test_r_multiple_none_when_stop_at_or_above_price():
    """손절선이 현재가 이상이면 리스크 단위가 0 이하 — 억지로 내지 않는다."""
    p = portfolio.exit_plan(held=10, avg_price=100.0, close=110.0, stop_price=110.0,
                            market="KR")
    assert p["r_multiple"] is None and p["r_unit"] is None


def test_exit_plan_flags_stop_above_average():
    """손절선이 평단 위면 그 손절은 손실 확정이 아니라 이익 확정이다.
    같은 숫자를 붉게 칠하면 좋은 소식이 나쁜 소식으로 읽힌다."""
    p = portfolio.exit_plan(held=10, avg_price=100.0, close=130.0, stop_price=110.0,
                            market="KR")
    assert p["stop_locks_profit"] is True
    assert portfolio.exit_plan(held=10, avg_price=100.0, close=95.0, stop_price=90.0,
                               market="KR")["stop_locks_profit"] is False


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


def test_holdings_carry_krw_value_and_weight():
    """종목 통화로만 표시하면 $150짜리와 ₩10,000짜리의 크기를 나란히 볼 수 없다.
    비중은 총자산(현금 포함) 기준이어야 '이 종목에 얼마나 걸었나'에 답한다."""
    holdings = {"AAPL": {"quantity": 10, "avg_price": 100.0},
                "005930": {"quantity": 10, "avg_price": 50_000.0}}
    tickers = {"AAPL": {"name": "Apple", "market": "US", "currency": "USD"},
               "005930": {"name": "삼성전자", "market": "KR", "currency": "KRW"}}
    out = portfolio.build_portfolio(holdings, {"AAPL": 150.0, "005930": 60_000.0},
                                    tickers, usdkrw=1000.0, cash_krw=1_400_000.0)
    rows = {h["symbol"]: h for h in out["holdings"]}
    assert rows["AAPL"]["value_krw"] == 1_500_000.0   # $1,500 × 1,000
    assert rows["005930"]["value_krw"] == 600_000.0
    # 총자산 = 150만 + 60만 + 현금 140만 = 350만
    assert rows["AAPL"]["weight_pct"] == 42.9
    assert rows["005930"]["weight_pct"] == 17.1


def test_holdings_report_net_proceeds_on_full_exit():
    """'손익 +4.82%'를 본전으로 읽고 청산하면 거래세·수수료 차감 후 실제로는 손실이다.
    지금 전량 팔면 계좌에 얼마가 들어오는지를 화면이 알아야 한다."""
    holdings = {"005930": {"quantity": 10, "avg_price": 50_000.0}}
    tickers = {"005930": {"name": "삼성전자", "market": "KR", "currency": "KRW"}}
    out = portfolio.build_portfolio(holdings, {"005930": 60_000.0}, tickers, usdkrw=None)
    h = out["holdings"][0]
    # 60만원 매도 — 수수료 0.015% + 거래세 0.15% = 990원
    assert h["exit_cost"] == 990.0
    assert h["net_proceeds"] == 599_010.0
    assert h["net_pnl"] == 99_010.0        # 평단 50만 대비 비용 차감 후


def test_usd_holding_splits_price_and_fx_contribution():
    """미국주식 비중이 큰 계좌는 원화 손익의 절반이 환일 수 있다 —
    '달러 자산이 잘 버텼다'는 착시 없이 배분을 판단하려면 나눠 봐야 한다."""
    holdings = {"AAPL": {"quantity": 10, "avg_price": 100.0, "avg_fx": 1000.0,
                         "fx_known": True}}
    tickers = {"AAPL": {"name": "Apple", "market": "US", "currency": "USD"}}
    out = portfolio.build_portfolio(holdings, {"AAPL": 120.0}, tickers, usdkrw=1200.0)
    h = out["holdings"][0]
    # 주가 기여 = (120-100)×10 × 현재환율 1200 = 240,000
    assert h["price_pnl_krw"] == 240_000.0
    # 환 기여 = 원금 100×10 × (1200-1000) = 200,000
    assert h["fx_pnl_krw"] == 200_000.0
    assert h["pnl_krw"] == 440_000.0


def test_fx_contribution_is_unknown_without_recorded_buy_rate():
    """매수 환율이 원장에 없으면 매수 시점 환율을 현재 환율로 폴백한다 —
    그 상태의 환 기여 0은 '환 영향이 없었다'가 아니라 '알 수 없다'이다.
    0으로 표기하면 사용자가 환 리스크가 없다고 읽는다."""
    trades = [{"symbol": "AAPL", "side": "BUY", "quantity": 10, "price": 100.0,
               "trade_date": "2026-01-01", "fee": 0.0, "tax": 0.0}]  # fx_rate 미기록
    tickers = {"AAPL": {"name": "Apple", "market": "US", "currency": "USD"}}
    h = portfolio.compute_holdings(trades, tickers, usdkrw=1200.0)["AAPL"]
    assert h["fx_known"] is False

    out = portfolio.build_portfolio({"AAPL": h}, {"AAPL": 120.0}, tickers, usdkrw=1200.0)
    assert out["holdings"][0]["fx_pnl_krw"] is None      # 0이 아니라 미상
    assert out["holdings"][0]["price_pnl_krw"] == 240_000.0


def test_fx_contribution_known_when_every_lot_has_rate():
    trades = [{"symbol": "AAPL", "side": "BUY", "quantity": 10, "price": 100.0,
               "trade_date": "2026-01-01", "fee": 0.0, "tax": 0.0, "fx_rate": 1000.0}]
    tickers = {"AAPL": {"name": "Apple", "market": "US", "currency": "USD"}}
    h = portfolio.compute_holdings(trades, tickers, usdkrw=1200.0)["AAPL"]
    assert h["fx_known"] is True
    out = portfolio.build_portfolio({"AAPL": h}, {"AAPL": 120.0}, tickers, usdkrw=1200.0)
    assert out["holdings"][0]["fx_pnl_krw"] == 200_000.0


def test_krw_holding_has_no_fx_contribution():
    holdings = {"A": {"quantity": 10, "avg_price": 100.0, "avg_fx": 1.0}}
    out = portfolio.build_portfolio(holdings, {"A": 120.0},
                                    {"A": {"market": "KR", "currency": "KRW"}}, usdkrw=1200.0)
    assert out["holdings"][0]["fx_pnl_krw"] == 0.0


def test_holding_weight_is_none_without_price():
    holdings = {"A": {"quantity": 10, "avg_price": 100.0}}
    out = portfolio.build_portfolio(holdings, {}, {"A": {"currency": "KRW"}}, usdkrw=None)
    assert out["holdings"][0]["value_krw"] is None
    assert out["holdings"][0]["weight_pct"] is None


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


def test_clusters_group_highly_correlated_holdings():
    """종목별 비중이 낮아도 상관 0.7+ 로 묶인 종목들은 실질 단일 베팅이다.
    최대 종목 비중만 보면 '집중 없음'으로 읽힌다."""
    import pandas as pd
    idx = pd.date_range("2026-01-01", periods=60)
    a = pd.Series(range(100, 160), index=idx, dtype=float)
    holdings = {"A": {"quantity": 1, "avg_price": 100.0},
                "B": {"quantity": 2, "avg_price": 50.0}}
    closes = {"A": a, "B": a * 0.5}  # 완전 동행 → 상관 1.0
    tickers = {"A": {"name": "가", "currency": "KRW"}, "B": {"name": "나", "currency": "KRW"}}
    out = portfolio.account_risk(holdings, closes, tickers, usdkrw=None, cash_krw=159.0)
    c = out["clusters"][0]
    assert sorted(c["symbols"]) == ["A", "B"]
    assert c["weight_pct"] == 66.6            # 33.3 + 33.3 — 실질 하나의 포지션
    assert out["max_cluster_pct"] == 66.6


def test_uncorrelated_holdings_are_not_clustered():
    """음의 상관이면 묶지 않는다 — 묶어버리면 경고가 늘 켜져 있어 의미를 잃는다."""
    import pandas as pd
    idx = pd.date_range("2026-01-01", periods=60)
    # 서로 반대로 움직이는 일간 수익률 — 단조 상승/하락 계열은 수익률로 보면
    # 둘 다 완만해지는 방향이라 오히려 양의 상관이 나온다
    a, b = [100.0], [100.0]
    for i in range(59):
        step = 0.01 if i % 2 == 0 else -0.01
        a.append(a[-1] * (1 + step))
        b.append(b[-1] * (1 - step))
    holdings = {"A": {"quantity": 1, "avg_price": 100.0},
                "B": {"quantity": 1, "avg_price": 100.0}}
    tickers = {"A": {"name": "가", "currency": "KRW"}, "B": {"name": "나", "currency": "KRW"}}
    out = portfolio.account_risk(holdings, {"A": pd.Series(a, index=idx),
                                            "B": pd.Series(b, index=idx)},
                                 tickers, usdkrw=None)
    assert out["corr"]["matrix"][0][1] < 0   # 픽스처가 실제로 음의 상관인지 먼저 확인
    assert out["clusters"] == []


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


def test_open_risk_uses_registered_stop_over_atr():
    """등록된 손절 룰이 있으면 계좌 리스크도 그 값으로 재야 한다.

    2×ATR은 매일 재계산되지만 알림을 울리는 것은 등록된 룰이다. 계좌 총
    미결 리스크가 사용자가 실제로 지킬 손절선과 다른 값을 쓰면, 화면의
    '총 3.5%'는 어떤 시나리오에서도 실현되지 않는 숫자가 된다.
    """
    holdings = {"A": {"quantity": 10, "avg_price": 100.0}}
    out = portfolio.open_risk(holdings, {"A": 5.0}, KR_T, usdkrw=None,
                              total_asset_krw=10_000.0,
                              prices={"A": 100.0}, stops={"A": 97.0})
    # 2×ATR이면 100이지만 등록 룰(현재가 100 → 손절 97)이면 30
    assert out["total_risk_krw"] == 30.0
    assert out["rows"][0]["stop_source"] == "rule"
    assert out["unregistered_count"] == 0


def test_open_risk_reports_how_many_holdings_lack_a_rule():
    """룰 없는 종목은 2×ATR '가정'이다 — 가정이 몇 건인지 화면이 말해야 한다."""
    holdings = {"A": {"quantity": 10, "avg_price": 100.0},
                "B": {"quantity": 10, "avg_price": 100.0}}
    tickers = {"A": {"name": "가", "currency": "KRW"}, "B": {"name": "나", "currency": "KRW"}}
    out = portfolio.open_risk(holdings, {"A": 5.0, "B": 5.0}, tickers, usdkrw=None,
                              total_asset_krw=10_000.0,
                              prices={"A": 100.0, "B": 100.0}, stops={"A": 97.0})
    assert out["unregistered_count"] == 1
    assert {r["symbol"]: r["stop_source"] for r in out["rows"]} == {"A": "rule", "B": "atr"}


def test_open_risk_treats_profit_locking_stop_as_zero_risk():
    """손절선이 현재가 위면 그 포지션은 더 잃을 것이 없다 — 0으로 잡아야 한다."""
    holdings = {"A": {"quantity": 10, "avg_price": 100.0}}
    out = portfolio.open_risk(holdings, {"A": 5.0}, KR_T, usdkrw=None,
                              total_asset_krw=10_000.0,
                              prices={"A": 100.0}, stops={"A": 105.0})
    assert out["total_risk_krw"] == 0.0


def test_overseas_tax_view_nets_gains_and_losses_within_the_year():
    """해외 양도세는 연간 손익을 통산한 뒤 250만원을 공제하고 22%다.

    종목별로 따로 매기면 손실 종목이 세금을 줄여준다는 사실이 사라진다.
    """
    trades = [
        dict(T("AAPL", "BUY", 100, 100), fx_rate=1000.0, fee=0.0, tax=0.0,
             trade_date="2026-01-05"),
        dict(T("AAPL", "SELL", 100, 200), fx_rate=1000.0, fee=0.0, tax=0.0,
             trade_date="2026-03-05"),
    ]
    r = portfolio.realized_pnl(trades, US_T, usdkrw=1000.0)
    tax = portfolio.overseas_tax_view(r, US_T, year=2026)
    assert tax["gain_krw"] == 10_000_000.0          # $10,000 × 1,000원
    assert tax["deduction_krw"] == 2_500_000.0
    assert tax["taxable_krw"] == 7_500_000.0
    assert tax["tax_krw"] == 1_650_000.0            # 750만 × 22%
    assert tax["deduction_left_krw"] == 0.0


def test_overseas_tax_view_reports_remaining_deduction_below_threshold():
    trades = [
        dict(T("AAPL", "BUY", 10, 100), fx_rate=1000.0, fee=0.0, tax=0.0,
             trade_date="2026-01-05"),
        dict(T("AAPL", "SELL", 10, 200), fx_rate=1000.0, fee=0.0, tax=0.0,
             trade_date="2026-03-05"),
    ]
    r = portfolio.realized_pnl(trades, US_T, usdkrw=1000.0)
    tax = portfolio.overseas_tax_view(r, US_T, year=2026)
    assert tax["gain_krw"] == 1_000_000.0
    assert tax["tax_krw"] == 0.0
    assert tax["deduction_left_krw"] == 1_500_000.0


def test_overseas_tax_view_excludes_domestic_trades():
    """국내 상장분은 이 세금의 대상이 아니다 — 섞으면 세액이 부풀려진다."""
    trades = [dict(T("005930", "BUY", 10, 1_000_000), fee=0.0, tax=0.0,
                   trade_date="2026-01-05"),
              dict(T("005930", "SELL", 10, 2_000_000), fee=0.0, tax=0.0,
                   trade_date="2026-03-05")]
    r = portfolio.realized_pnl(trades, KR_T, usdkrw=None)
    tax = portfolio.overseas_tax_view(r, KR_T, year=2026)
    assert tax["gain_krw"] == 0.0 and tax["tax_krw"] == 0.0


def test_overseas_tax_view_ignores_other_years():
    trades = [
        dict(T("AAPL", "BUY", 100, 100), fx_rate=1000.0, fee=0.0, tax=0.0,
             trade_date="2025-01-05"),
        dict(T("AAPL", "SELL", 100, 200), fx_rate=1000.0, fee=0.0, tax=0.0,
             trade_date="2025-03-05"),
    ]
    r = portfolio.realized_pnl(trades, US_T, usdkrw=1000.0)
    assert portfolio.overseas_tax_view(r, US_T, year=2026)["gain_krw"] == 0.0


def test_exit_plan_shows_capital_gains_tax_for_overseas_position():
    """해외 포지션의 '확정 손익'에 5월 양도세가 빠져 있으면 그 돈을 또 쓰게 된다.

    이미 쓴 공제분을 반영한 **한계 세액**이어야 한다 — 올해 아직 이익이 없다면
    250만원까지는 세금이 0이고, 그 사실이 청산 판단을 바꾼다.
    """
    p = portfolio.exit_plan(held=100, avg_price=100.0, close=200.0, stop_price=180.0,
                            market="US", fx=1000.0, taxable_overseas=True,
                            deduction_left_krw=2_500_000.0)
    full = [s for s in p["slices"] if s["label"] == "전량"][0]
    # 차익 $10,000 = ₩10,000,000 (수수료 제외) → 공제 250만 후 750만 × 22%
    assert abs(full["tax_krw"] - 1_650_000) < 20_000
    assert full["realized_pnl_after_tax_krw"] < full["realized_pnl_krw"]
    assert p["taxable_overseas"] is True


def test_exit_plan_has_no_capital_gains_tax_for_domestic_position():
    p = portfolio.exit_plan(held=100, avg_price=100.0, close=200.0, stop_price=180.0,
                            market="KR")
    full = [s for s in p["slices"] if s["label"] == "전량"][0]
    assert full["tax_krw"] == 0.0
    assert full["realized_pnl_after_tax_krw"] == full["realized_pnl_krw"]
    assert p["taxable_overseas"] is False


def test_holding_flags_basis_adjusted_lots():
    """평단 맞춤 보정 로트가 원가에 섞이면 평단·평가손익·R·손절선이 전부
    그 위에 서게 된다. 실현손익 집계에서 빼는 것만으로는 부족하고, 보유 중인
    종목의 숫자도 실거래 산물이 아니라는 사실을 화면이 말해야 한다."""
    trades = [dict(T("A", "BUY", 10, 100), exclude_from_stats=1),
              dict(T("A", "BUY", 10, 120))]
    h = portfolio.compute_holdings(trades, KR_T)
    out = portfolio.build_portfolio(h, {"A": 130.0}, KR_T, usdkrw=None)
    assert out["holdings"][0]["basis_adjusted"] is True


def test_holding_without_adjusted_lots_is_not_flagged():
    h = portfolio.compute_holdings([dict(T("A", "BUY", 10, 100))], KR_T)
    out = portfolio.build_portfolio(h, {"A": 130.0}, KR_T, usdkrw=None)
    assert out["holdings"][0]["basis_adjusted"] is False


def test_basis_adjusted_lot_is_recognized_from_note():
    """체크박스가 생기기 전에 임포트된 보정 로트는 플래그가 0이고 메모에만 남아 있다.

    플래그만 보면 이 계좌에서는 경고가 영원히 뜨지 않는다 — 원장을 고치지 않고
    메모의 표식으로도 같은 사실을 읽어낸다.
    """
    trades = [dict(T("A", "BUY", 10, 100), note="증명서 임포트 (시트 평단 맞춤 보정 로트) / ISA"),
              dict(T("A", "BUY", 10, 120))]
    out = portfolio.build_portfolio(portfolio.compute_holdings(trades, KR_T),
                                    {"A": 130.0}, KR_T, usdkrw=None)
    assert out["holdings"][0]["basis_adjusted"] is True


def test_ordinary_note_does_not_mark_a_lot_as_adjusted():
    trades = [dict(T("A", "BUY", 10, 100), note="추세 눌림목 진입")]
    out = portfolio.build_portfolio(portfolio.compute_holdings(trades, KR_T),
                                    {"A": 130.0}, KR_T, usdkrw=None)
    assert out["holdings"][0]["basis_adjusted"] is False


# ── 배당 ─────────────────────────────────────────────────────────────────
def F(symbol, amount, d="2026-03-15", tax=0.0, currency="KRW", fx=None,
      flow_type="DIVIDEND"):
    return {"flow_type": flow_type, "symbol": symbol, "amount": amount, "tax": tax,
            "flow_date": d, "currency": currency, "fx_rate": fx, "note": None}


def test_dividend_view_nets_withholding_tax():
    """배당은 세전 금액이 아니라 원천징수 후 들어온 돈이 실제 수익이다."""
    v = portfolio.dividend_view([F("A", 10000, tax=1540)], KR_T, year=2026)
    assert v["total_gross_krw"] == 10000 and v["total_tax_krw"] == 1540
    assert v["total_net_krw"] == 8460


def test_dividend_view_converts_usd_at_payment_fx():
    """입금 시점 환율이 있으면 그것을 쓴다 — 지금 환율로 환산하면
    작년에 받은 배당이 오늘 환율 변동만으로 늘었다 줄었다 한다."""
    v = portfolio.dividend_view([F("AAPL", 100, tax=15, currency="USD", fx=1300.0)],
                                US_T, usdkrw=1500.0, year=2026)
    assert v["total_net_krw"] == 85 * 1300


def test_dividend_view_falls_back_to_current_fx_when_unrecorded():
    v = portfolio.dividend_view([F("AAPL", 100, currency="USD")], US_T,
                                usdkrw=1400.0, year=2026)
    assert v["total_net_krw"] == 100 * 1400
    assert v["fx_estimated"] is True


def test_dividend_view_separates_this_year_from_lifetime():
    """올해 배당수익률과 누적 배당은 다른 숫자다 — 합치면 보유 기간이 긴
    종목이 무조건 높은 수익률로 보인다."""
    v = portfolio.dividend_view([F("A", 1000, d="2025-03-15"),
                                 F("A", 2000, d="2026-03-15")], KR_T, year=2026)
    assert v["total_net_krw"] == 3000 and v["ytd_net_krw"] == 2000


def test_dividend_view_groups_by_symbol_sorted_by_size():
    v = portfolio.dividend_view([F("A", 1000), F("AAPL", 10, currency="USD", fx=1400.0),
                                 F("A", 500)], {**KR_T, **US_T}, year=2026)
    by = v["by_symbol"]
    assert [r["symbol"] for r in by] == ["AAPL", "A"]
    assert by[1]["net_krw"] == 1500 and by[1]["count"] == 2


def test_dividend_view_ignores_non_dividend_flows():
    """입출금은 현금흐름이지 수익이 아니다 — 같은 표에 합산하면
    입금액이 배당수익률로 둔갑한다."""
    v = portfolio.dividend_view([F("A", 1000), F(None, 5_000_000, flow_type="DEPOSIT")],
                                KR_T, year=2026)
    assert v["total_net_krw"] == 1000 and v["count"] == 1


def test_dividend_yield_on_cost_uses_this_year_only():
    v = portfolio.dividend_view([F("A", 1000, d="2025-03-15"), F("A", 3000)],
                                KR_T, year=2026, cost_krw={"A": 100_000})
    assert v["by_symbol"][0]["yield_on_cost_pct"] == 3.0
    assert v["yield_on_cost_pct"] == 3.0


def test_dividend_yield_is_withheld_when_position_changed_midyear():
    """중간에 사고 판 종목의 '올해 배당 ÷ 현재 원가'는 수익률이 아니다."""
    v = portfolio.dividend_view([F("A", 3000)], KR_T, year=2026,
                                cost_krw={"A": 100_000}, traded_this_year={"A"})
    assert v["by_symbol"][0]["yield_on_cost_pct"] is None
    assert v["by_symbol"][0]["position_changed"] is True


def test_dividend_yield_none_for_closed_position():
    v = portfolio.dividend_view([F("A", 3000)], KR_T, year=2026, cost_krw={})
    assert v["by_symbol"][0]["yield_on_cost_pct"] is None
    assert v["by_symbol"][0]["held"] is False


def test_total_return_adds_dividends_to_unrealized_pnl():
    """주가만 보면 -5%인 커버드콜이 배당까지 더하면 플러스일 수 있다.
    배당을 세지 않는 화면은 그 포지션을 팔라고 말하는 것과 같다."""
    h = portfolio.compute_holdings([T("A", "BUY", 10, 100)], KR_T)
    out = portfolio.build_portfolio(h, {"A": 95.0}, KR_T, usdkrw=None,
                                    dividends={"A": 200.0})
    row = out["holdings"][0]
    assert row["pnl_krw"] == -50 and row["dividend_krw"] == 200
    assert row["total_return_krw"] == 150 and row["total_return_pct"] == 15.0
    assert out["totals"]["dividend_krw"] == 200
    assert out["totals"]["total_return_krw"] == 150


def test_total_return_is_null_without_dividends():
    """배당이 0인 종목에 '총수익률'을 따로 세우면 같은 숫자가 두 번 나온다."""
    h = portfolio.compute_holdings([T("A", "BUY", 10, 100)], KR_T)
    row = portfolio.build_portfolio(h, {"A": 95.0}, KR_T, usdkrw=None)["holdings"][0]
    assert row["dividend_krw"] == 0.0 and row["total_return_krw"] is None


def test_account_yield_excludes_the_symbols_it_refused_to_score():
    """종목마다 '기간 불일치'라며 수익률을 감춰놓고 그 종목들로 계좌 수익률을
    내면, 화면이 한쪽에서 못 낸다고 말한 숫자를 다른 쪽에서 합계로 내놓게 된다."""
    v = portfolio.dividend_view([F("A", 3000), F("AAPL", 10, currency="USD", fx=1000.0)],
                                {**KR_T, **US_T}, year=2026,
                                cost_krw={"A": 100_000, "AAPL": 500_000},
                                traded_this_year={"AAPL"})
    assert v["yield_on_cost_pct"] == 3.0  # A만으로 계산 — AAPL은 분자·분모에서 함께 빠진다
    assert v["yield_basis_krw"] == 100_000 and v["yield_partial"] is True


def test_account_yield_is_null_when_no_symbol_can_be_scored():
    v = portfolio.dividend_view([F("A", 3000)], KR_T, year=2026,
                                cost_krw={"A": 100_000}, traded_this_year={"A"})
    assert v["yield_on_cost_pct"] is None
