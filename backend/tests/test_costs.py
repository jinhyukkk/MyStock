from app import costs


def test_kr_stock_roundtrip_includes_transfer_tax():
    buy = costs.estimate("KR", "BUY", 1_000_000, is_etf=0)
    sell = costs.estimate("KR", "SELL", 1_000_000, is_etf=0)
    assert buy["fee"] == 150 and buy["tax"] == 0  # 매수엔 세금 없음
    assert sell["fee"] == 150 and sell["tax"] == 1500  # 증권거래세 0.15%
    assert costs.roundtrip_pct("KR", is_etf=0) == 0.18


def test_kr_etf_exempt_from_transfer_tax():
    assert costs.estimate("KR", "SELL", 1_000_000, is_etf=1)["tax"] == 0
    assert costs.roundtrip_pct("KR", is_etf=1) < costs.roundtrip_pct("KR", is_etf=0)


def test_us_and_crypto_rates_differ_from_kr():
    us = costs.roundtrip_pct("US")
    crypto = costs.roundtrip_pct("CRYPTO")
    assert crypto < us  # 업비트 왕복이 미국 주식보다 싸다
    assert us != costs.roundtrip_pct("KR", is_etf=0)


def test_spread_grows_as_liquidity_falls():
    """ML-15: 유동성 낮은 소형주는 호가 스프레드만으로 0.3%p를 넘긴다."""
    liquid = costs.spread_pct(500e8)
    mid = costs.spread_pct(50e8)
    thin = costs.spread_pct(0.5e8)
    assert liquid < mid < thin
    assert costs.spread_pct(None) > 0  # 거래대금 미상이면 중간 가정


def test_backtest_cost_differs_by_market():
    """단일 0.3%p는 업비트에 과대, 국내 소형주에 과소였다."""
    crypto = costs.backtest_cost_pct("CRYPTO", avg_turnover_krw=500e8)
    kr_small = costs.backtest_cost_pct("KR", avg_turnover_krw=0.5e8)
    assert crypto < 0.3 < kr_small
    # 같은 시장이라도 유동성이 낮으면 더 비싸다
    assert costs.backtest_cost_pct("KR", avg_turnover_krw=500e8) < kr_small


def test_backtest_cost_includes_fees_and_spread():
    market, turnover = "KR", 50e8
    assert costs.backtest_cost_pct(market, 0, turnover) == round(
        costs.roundtrip_pct(market, 0) + costs.spread_pct(turnover), 4)


def test_unknown_market_falls_back_without_raising():
    out = costs.estimate("XX", "SELL", 1_000_000)
    assert out["fee"] >= 0 and out["tax"] >= 0
