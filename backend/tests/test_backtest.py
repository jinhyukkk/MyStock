from app import backtest


def test_backtest_uptrend(ohlcv_up):
    out = backtest.backtest_ticker(ohlcv_up)
    assert out is not None
    assert out["samples"] > 50
    assert out["start"] < out["end"]
    total_n = sum(g["n"] for g in out["grades"])
    assert total_n == out["samples"]
    for g in out["grades"]:
        assert g["grade"] in backtest.GRADE_ORDER
        if g["avg_fwd5"] is not None:
            assert -100 <= g["avg_fwd5"] <= 100
        if g["win5"] is not None:
            assert 0 <= g["win5"] <= 100


def test_backtest_insufficient_data(ohlcv_up):
    assert backtest.backtest_ticker(ohlcv_up.head(100)) is None
