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


def test_backtest_excess_vs_benchmark(ohlcv_up):
    # 벤치마크 = 종목 자기 자신 → 초과수익률은 0
    out = backtest.backtest_ticker(ohlcv_up, bench=ohlcv_up["close"], bench_label="자기자신")
    assert out["bench_label"] == "자기자신"
    for g in out["grades"]:
        if g["avg_excess5"] is not None:
            assert abs(g["avg_excess5"]) < 0.01
        if g["avg_excess20"] is not None:
            assert abs(g["avg_excess20"]) < 0.01


def test_backtest_no_benchmark_label_none(ohlcv_up):
    out = backtest.backtest_ticker(ohlcv_up)
    assert out["bench_label"] is None
    assert all("avg_excess5" in g for g in out["grades"])


def test_backtest_net_after_cost(ohlcv_up):
    out = backtest.backtest_ticker(ohlcv_up)
    assert out["cost_pct"] == backtest.COST_PCT
    for g in out["grades"]:
        if g["avg_fwd5"] is not None:
            assert g["avg_net5"] == round(g["avg_fwd5"] - backtest.COST_PCT, 2)
