import pandas as pd

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
    out = backtest.backtest_ticker(ohlcv_up, bench=ohlcv_up[["open", "close"]],
                                   bench_label="자기자신")
    assert out["bench_label"] == "자기자신"
    for g in out["grades"]:
        # 손절이 걸린 표본은 종목만 조기 청산되므로 초과수익이 음(-)으로 남는다
        if g["avg_excess5"] is not None and g["stop_rate5"] == 0.0:
            assert abs(g["avg_excess5"]) < 0.01


def test_backtest_accepts_close_only_benchmark(ohlcv_up):
    out = backtest.backtest_ticker(ohlcv_up, bench=ohlcv_up["close"], bench_label="종가만")
    assert out["bench_label"] == "종가만"
    assert any(g.get("avg_excess5") is not None for g in out["grades"])


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


def test_win_rate_is_net_of_cost(ohlcv_up):
    """ML-6: 승률은 사용자가 사이즈를 키울 때 쓰는 숫자다 — gross면 부풀려진다."""
    out = backtest.backtest_ticker(ohlcv_up)
    seen_gap = False
    for g in out["grades"]:
        for h in (5, 20):
            if g[f"win{h}"] is None:
                continue
            assert g[f"win{h}"] <= g[f"win{h}_gross"]
            seen_gap = seen_gap or g[f"win{h}"] < g[f"win{h}_gross"]
    assert seen_gap


def test_zero_occurrence_grades_are_reported(ohlcv_up):
    out = backtest.backtest_ticker(ohlcv_up)
    observed = {g["grade"] for g in out["grades"]}
    assert set(out["missing_grades"]) == set(backtest.GRADE_ORDER) - observed
    assert out["version"] == backtest.VERSION


# ── ML-9: 익일 시가 진입 ────────────────────────────────────────────────

def _flat_frame(n=300, close=100.0, open_=None, low=None):
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({"open": open_ if open_ is not None else close,
                         "high": close * 1.001, "low": low if low is not None else close * 0.999,
                         "close": close, "volume": 1e5}, index=idx)


def test_entry_uses_next_day_open_not_signal_close(monkeypatch):
    """신호를 만든 종가에 그 종가로 체결하는 건 실제로 낼 수 없는 주문이다."""
    df = _flat_frame()
    # 종가는 100 고정, 시가만 101 → 익일 시가 진입이면 수익률이 음(-)으로 나온다
    df["open"] = 101.0
    df["high"] = 101.5
    df["low"] = 99.0
    monkeypatch.setattr(backtest.scoring, "score_ticker",
                        lambda d: {"swing_grade": "중립", "longterm_grade": "중립"})
    out = backtest.backtest_ticker(df)
    g = next(g for g in out["grades"] if g["grade"] == "중립")
    # 진입 101 → 청산 100 = -0.99%. 종가 진입이었다면 0.00%.
    assert g["avg_fwd5"] == round((100 / 101 - 1) * 100, 2)
    assert out["entry_rule"].startswith("신호 다음 거래일 시가")


# ── ML-8: 2×ATR 손절 이식 ──────────────────────────────────────────────

def test_stop_loss_caps_downside_and_is_reported(monkeypatch):
    """앱이 손절을 권장하는데 백테스트가 무조건 보유면 사용자는 그 수익률을 못 받는다."""
    n = 300
    idx = pd.bdate_range("2025-01-01", periods=n)
    close = pd.Series(100.0, index=idx)
    low = pd.Series(100.0, index=idx)
    # 마지막 구간에서만 깊게 흔들었다가 제자리로 마감 — 보유는 0%, 손절은 손실 확정
    low.iloc[-40:] = 80.0
    df = pd.DataFrame({"open": close, "high": close * 1.001, "low": low,
                       "close": close, "volume": 1e5}, index=idx)
    monkeypatch.setattr(backtest.scoring, "score_ticker",
                        lambda d: {"swing_grade": "중립", "longterm_grade": "중립"})
    out = backtest.backtest_ticker(df)
    g = next(g for g in out["grades"] if g["grade"] == "중립")
    assert g["stop_rate5"] > 0                     # 손절이 실제로 걸렸다
    assert g["avg_fwd5"] < g["avg_hold5"]          # 손절 적용 수익률이 더 낮다
    assert out["stop_atr_mult"] == backtest.STOP_ATR_MULT


def test_gap_down_fills_at_open_not_at_stop():
    """갭 하락에서 손절선 체결을 가정하면 갭 리스크만큼 성과가 부풀려진다."""
    o = [100.0, 100.0, 60.0, 100.0]
    lo = [100.0, 100.0, 55.0, 100.0]
    c = [100.0, 100.0, 100.0, 100.0]
    px, stopped = backtest._exit_price(o, c, lo, c, 1, 3, stop=95.0)
    assert stopped is True and px == 60.0  # 손절선 95가 아니라 갭 시가 60


def test_no_stop_touch_exits_at_horizon_close():
    o = [100.0] * 4
    lo = [99.0] * 4
    c = [100.0, 101.0, 102.0, 103.0]
    px, stopped = backtest._exit_price(o, c, lo, c, 1, 3, stop=95.0)
    assert stopped is False and px == 103.0


# ── ML-7 / ML-10: 에피소드·신뢰구간·표본 게이팅 ───────────────────────

def test_episodes_collapse_overlapping_signals():
    assert backtest._episodes([1, 2, 3, 4, 5], 20) == 1
    assert backtest._episodes([0, 20, 40], 20) == 3
    assert backtest._episodes([0, 19, 20], 20) == 2
    assert backtest._episodes([], 20) == 0


def test_episodes_are_fewer_than_signal_days(ohlcv_up):
    out = backtest.backtest_ticker(ohlcv_up)
    for g in out["grades"]:
        assert g["episodes20"] <= g["n"]
    assert any(g["episodes20"] < g["n"] for g in out["grades"])


def test_standard_error_uses_episodes_not_signal_days(ohlcv_up):
    """중첩 보정을 안 하면 표준오차가 실제보다 작게 나와 우위가 있어 보인다."""
    import math
    out = backtest.backtest_ticker(ohlcv_up)
    g = max((g for g in out["grades"] if g["se20"] is not None), key=lambda x: x["n"])
    naive = g["se20"] * math.sqrt(g["episodes20"]) / math.sqrt(g["n"])
    assert g["se20"] > naive  # 에피소드 기준이 더 보수적(큰 값)


def test_small_sample_is_flagged_insufficient(ohlcv_up):
    out = backtest.backtest_ticker(ohlcv_up)
    assert out["min_episodes"] == backtest.MIN_EPISODES
    for g in out["grades"]:
        assert g["insufficient20"] == (g["episodes20"] < backtest.MIN_EPISODES)


# ── ML-12: 중장기 등급 검증 ────────────────────────────────────────────

def test_max_episodes_exposes_unverifiable_horizons(ohlcv_up):
    """긴 구간은 관측 기간이 물리적 상한을 만든다 — '더 쌓이면 채워진다'가 아니다."""
    out = backtest.backtest_ticker(ohlcv_up)
    assert out["max_episodes"]["120"] < out["max_episodes"]["5"]
    for g in out["longterm_grades"]:
        assert g["episodes120"] <= out["max_episodes"]["120"]
    # 이 픽스처(300일)로 120일 비중첩 표본은 하한에 도달할 수 없다
    assert out["max_episodes"]["120"] < backtest.MIN_EPISODES


def test_longterm_grades_are_backtested(ohlcv_up):
    """검증된 신호와 검증 안 된 신호가 같은 무게로 놓이면 사용자는 구분하지 못한다."""
    out = backtest.backtest_ticker(ohlcv_up)
    assert out["long_horizons"] == [60, 120]
    assert out["longterm_grades"]
    for g in out["longterm_grades"]:
        assert g["grade"] in backtest.GRADE_ORDER
        assert "episodes60" in g and "insufficient120" in g
    observed = {g["grade"] for g in out["longterm_grades"]}
    assert set(out["missing_longterm_grades"]) == set(backtest.GRADE_ORDER) - observed
