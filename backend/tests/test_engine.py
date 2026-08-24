import pandas as pd
import pytest

from app import engine


def test_position_size_risks_one_percent_of_equity():
    """진입가-손절가 거리가 계좌의 1%가 되도록 수량을 정한다.

    equity 10,000,000 → 리스크 100,000원. 진입 10,000 / 손절 9,000 → 주당 1,000원
    → 100주.
    """
    qty = engine.position_size(10_000_000, entry=10_000, stop=9_000,
                               fx=1.0, market="KR", max_weight=1.0)
    assert qty == 100


def test_position_size_rounds_down_to_lot():
    """국내 주식은 정수 주문만 가능하다. 올림하면 계산해 둔 리스크 한도를 넘는다.

    리스크 100,000 / 주당 950원 = 105.26주 → 105주.
    """
    qty = engine.position_size(10_000_000, entry=10_000, stop=9_050,
                               fx=1.0, market="KR", max_weight=1.0)
    assert qty == 105


def test_position_size_capped_by_max_weight():
    """저변동성 종목은 손절폭이 좁아 1% 룰 수량이 폭발한다 — 비중 상한으로 자른다.

    진입 10,000 / 손절 9,990 → 주당 10원 → 1% 룰로는 10,000주(계좌의 1000%).
    비중 상한 20%면 10,000,000 × 0.2 / 10,000 = 200주.
    """
    qty = engine.position_size(10_000_000, entry=10_000, stop=9_990,
                               fx=1.0, market="KR", max_weight=0.20)
    assert qty == 200


def test_position_size_zero_when_cannot_afford_one_share():
    """한 주도 못 사면 0. 1주로 올려주면 그 1주가 1% 룰을 넘는다."""
    qty = engine.position_size(100_000, entry=10_000_000, stop=9_000_000,
                               fx=1.0, market="KR", max_weight=1.0)
    assert qty == 0


def test_position_size_applies_fx_for_usd():
    """USD 종목의 진입가·손절가는 달러다 — 원화 리스크로 환산해야 수량이 맞는다.

    리스크 100,000원, 주당 손실 $10 × 1,300 = 13,000원 → 7.69주 → 7주.
    """
    qty = engine.position_size(10_000_000, entry=100, stop=90,
                               fx=1_300.0, market="US", max_weight=1.0)
    assert qty == 7


def test_position_size_zero_when_stop_above_entry():
    """손절선이 진입가 위면 손실 정의가 성립하지 않는다 — 0을 돌려준다."""
    qty = engine.position_size(10_000_000, entry=100, stop=110,
                               fx=1.0, market="KR", max_weight=1.0)
    assert qty == 0


def _bars(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(
        {"open": [r[0] for r in rows], "high": [r[1] for r in rows],
         "low": [r[2] for r in rows], "close": [r[3] for r in rows]}, index=idx)


def test_resolve_exit_stops_out_when_low_touches_stop():
    """저가가 손절선을 건드리면 그 자리에서 청산."""
    bars = _bars([(100, 105, 98, 102), (102, 106, 88, 95), (95, 99, 94, 97)])
    i, px, reason = engine.resolve_exit(bars, entry_i=0, stop=90.0,
                                        exit_signal=[False, False, False])
    assert (i, px, reason) == (1, 90.0, "stop")


def test_resolve_exit_uses_open_when_gap_below_stop():
    """갭 하락으로 시가가 이미 손절선 아래면 시가 체결.

    손절선 체결을 가정하면 갭 리스크만큼 성과가 낙관적으로 부풀려진다.
    """
    bars = _bars([(100, 105, 98, 102), (85, 88, 84, 86)])
    i, px, reason = engine.resolve_exit(bars, entry_i=0, stop=90.0,
                                        exit_signal=[False, False])
    assert (i, px, reason) == (1, 85.0, "stop")


def test_resolve_exit_on_signal_uses_next_open():
    """청산 신호는 그날 종가에 체결할 수 없다 — 익일 시가다."""
    bars = _bars([(100, 105, 98, 102), (103, 106, 101, 104), (99, 100, 97, 98)])
    i, px, reason = engine.resolve_exit(bars, entry_i=0, stop=50.0,
                                        exit_signal=[False, True, False])
    # 인덱스 1에서 청산 신호 → 인덱스 2 시가 99에 청산
    assert (i, px, reason) == (2, 99.0, "signal")


def test_resolve_exit_falls_back_to_last_close():
    """신호도 손절도 없이 데이터가 끝나면 마지막 종가로 평가 청산."""
    bars = _bars([(100, 105, 98, 102), (102, 106, 101, 104)])
    i, px, reason = engine.resolve_exit(bars, entry_i=0, stop=50.0,
                                        exit_signal=[False, False])
    assert (i, px, reason) == (1, 104.0, "end")


def test_resolve_exit_prefers_stop_when_stop_precedes_signal():
    """손절이 먼저 닿았으면 뒤에 오는 청산 신호는 의미가 없다."""
    bars = _bars([(100, 105, 98, 102), (100, 101, 85, 88), (88, 90, 87, 89)])
    i, px, reason = engine.resolve_exit(bars, entry_i=0, stop=90.0,
                                        exit_signal=[False, True, False])
    assert reason == "stop"
    assert i == 1


def test_metrics_mdd_measures_peak_to_trough():
    """MDD는 최고점 대비 최대 낙폭 — 시작점 대비가 아니다."""
    m = engine.metrics([100.0, 200.0, 150.0, 180.0], trades=[])
    assert m["mdd"] == pytest.approx(-25.0)  # 200 → 150


def test_metrics_win_rate_counts_positive_net_pnl_only():
    """비용 차감 후 손익이 양(+)인 거래만 승. 0원은 승이 아니다."""
    trades = [{"pnl_krw": 100.0}, {"pnl_krw": -50.0}, {"pnl_krw": 0.0}]
    m = engine.metrics([100.0, 110.0], trades=trades)
    assert m["win_rate"] == pytest.approx(33.3, abs=0.1)
    assert m["trade_count"] == 3


def test_metrics_flat_curve_has_zero_mdd_and_cagr():
    m = engine.metrics([1_000.0] * 300, trades=[])
    assert m["mdd"] == 0.0
    assert m["cagr"] == pytest.approx(0.0, abs=1e-9)


def test_metrics_no_trades_leaves_win_rate_none():
    """거래가 0건이면 승률은 0%가 아니라 '없음'이다."""
    m = engine.metrics([100.0, 100.0], trades=[])
    assert m["win_rate"] is None


def _rising(n: int) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = [100.0 + i * 0.5 for i in range(n)]
    return pd.DataFrame({"open": close, "high": [c + 1 for c in close],
                         "low": [c - 1 for c in close], "close": close,
                         "volume": 100_000.0}, index=idx)


def test_run_with_no_signals_returns_flat_equity():
    """신호가 하나도 없으면 자본곡선은 초기자본 평선이고 거래는 0건이다."""
    idx = pd.date_range("2024-01-01", periods=300, freq="D")
    flat = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0,
                         "close": 100.0, "volume": 1000.0}, index=idx)
    out = engine.run({"AAA": flat},
                     {"AAA": {"name": "가", "market": "KR", "currency": "KRW",
                              "is_etf": 0}},
                     preset="abs_momentum",
                     params={"lookback": 20, "skip": 2, "trend_ma": 10},
                     initial_capital_krw=10_000_000.0, fx=1_300.0)
    assert out["trades"] == []
    assert out["metrics"]["trade_count"] == 0
    equities = [p["equity_krw"] for p in out["equity_curve"]]
    assert all(e == pytest.approx(10_000_000.0) for e in equities)


def test_run_deducts_cost_from_trade_pnl():
    """왕복 비용이 실제로 빠지는지 — 총수익과 순손익이 비용만큼 달라야 한다."""
    out = engine.run({"AAA": _rising(260)},
                     {"AAA": {"name": "가", "market": "KR", "currency": "KRW",
                              "is_etf": 0}},
                     preset="abs_momentum",
                     params={"lookback": 60, "skip": 5, "trend_ma": 30},
                     initial_capital_krw=10_000_000.0, fx=1_300.0)
    assert out["trades"], "상승 추세에서 진입이 한 건도 없으면 시그널이 잘못됐다"
    t = out["trades"][0]
    assert t["cost_krw"] > 0
    gross = (t["exit_price"] - t["entry_price"]) * t["qty"]
    assert t["pnl_krw"] == pytest.approx(gross - t["cost_krw"], abs=1.0)


def test_run_caps_concurrent_notional_at_cash():
    """동시 보유 노셔널 합은 현금(equity)을 넘지 않는다 — MAX_POSITIONS 게이트가 아니다.

    이 픽스처(저변동 _rising)는 MAX_POSITIONS(7)가 아니라 현금 제약이 먼저
    막는다: 비중 상한 20%가 1% 룰보다 먼저 걸려(저변동 → 손절폭이 좁다)
    포지션당 노셔널이 equity의 약 20%다. 현금 계좌라 동시 보유 노셔널 합이
    equity를 넘을 수 없으므로 100% / 20% = 5건에서 막힌다.
    """
    df = _rising(260)
    frames = {f"S{i}": df.copy() for i in range(12)}
    tickers = {f"S{i}": {"name": f"종목{i}", "market": "KR", "currency": "KRW",
                         "is_etf": 0} for i in range(12)}
    out = engine.run(frames, tickers, preset="abs_momentum",
                     params={"lookback": 60, "skip": 5, "trend_ma": 30},
                     initial_capital_krw=100_000_000.0, fx=1_300.0)
    assert out["max_concurrent"] == 5


def _volatile_rising(n: int) -> pd.DataFrame:
    """상승 추세 + 넓은 일중 변동.

    2×ATR이 가격의 5%를 넘어야 1% 룰이 비중 상한(20%)보다 먼저 묶인다
    (조건: 주당 손실 > 가격/20). 일중 ±5%면 2×ATR ≈ 가격의 20%다.
    저변동 fixture(_rising)를 쓰면 비중 상한이 먼저 걸려 이 테스트가 무의미해진다.
    """
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = [100.0 + i * 0.5 for i in range(n)]
    return pd.DataFrame({"open": close,
                         "high": [c * 1.05 for c in close],
                         "low": [c * 0.95 for c in close],
                         "close": close, "volume": 100_000.0}, index=idx)


def test_run_caps_total_account_risk():
    """종목별 1%만 지키면 7종목에서 총 7%가 된다 — 합산 상한 6%가 먼저 막아야 한다.

    각 포지션이 계좌의 정확히 1%를 걸므로 6건째까지만 들어간다.
    MAX_POSITIONS(7)가 아니라 MAX_ACCOUNT_RISK_PCT(6%)가 막는 것을 확인한다.
    """
    df = _volatile_rising(260)
    frames = {f"S{i}": df.copy() for i in range(12)}
    tickers = {f"S{i}": {"name": f"종목{i}", "market": "KR", "currency": "KRW",
                         "is_etf": 0} for i in range(12)}
    out = engine.run(frames, tickers, preset="abs_momentum",
                     params={"lookback": 60, "skip": 5, "trend_ma": 30},
                     initial_capital_krw=1_000_000_000.0, fx=1_300.0)
    # 자본이 충분해 비중 상한에는 안 걸린다 — 막는 것은 총 리스크 6%다
    assert out["max_concurrent"] == 6


def _rising_then_crash(n_rise: int = 260, n_crash: int = 10) -> pd.DataFrame:
    """상승 후 급락 — 손절 청산·음수 손익 경로를 실제로 태워 본다.

    지금까지의 run 픽스처는 전부 단조 상승이라 stop 청산과 음수 pnl이 한 번도
    실행되지 않았다. rolling 지표는 과거만 보므로 뒤에 급락을 붙여도 진입
    시점의 신호는 그대로다.
    """
    up = _rising(n_rise)
    idx = pd.date_range(up.index[-1] + pd.Timedelta(days=1), periods=n_crash, freq="D")
    crash_close = [up["close"].iloc[-1] * (0.5 ** (i + 1)) for i in range(n_crash)]
    down = pd.DataFrame({"open": crash_close, "high": [c * 1.01 for c in crash_close],
                         "low": [c * 0.5 for c in crash_close], "close": crash_close,
                         "volume": 100_000.0}, index=idx)
    return pd.concat([up, down])


def test_run_stops_out_with_negative_pnl_on_crash():
    """급락으로 손절에 닿으면 exit_reason이 stop이고 pnl_krw는 음수다."""
    out = engine.run({"AAA": _rising_then_crash()},
                     {"AAA": {"name": "가", "market": "KR", "currency": "KRW",
                              "is_etf": 0}},
                     preset="abs_momentum",
                     params={"lookback": 60, "skip": 5, "trend_ma": 30},
                     initial_capital_krw=10_000_000.0, fx=1_300.0)
    assert out["trades"], "급락 전 진입이 한 건도 없으면 픽스처가 잘못됐다"
    t = out["trades"][0]
    assert t["exit_reason"] == "stop"
    assert t["pnl_krw"] < 0


def test_run_marks_holiday_position_without_sawtooth():
    """일부 종목만 휴장인 날에도 자본곡선이 톱니를 만들지 않는다(발견 1 회귀).

    BBB는 AAA와 동일한 가격이되 중간 하루가 빠져 있다(개별 휴장). calendar는
    AAA 덕분에 그 날짜를 포함하므로, 옛 버그(day not in df.index → 평가손익
    0)라면 그 날 BBB의 누적 미실현손익이 통째로 사라졌다가 다음 날 되돌아와
    큰 스파이크가 생긴다. 고친 코드는 직전 종가(last_mark)를 이어받아 그 날
    변화가 다른 날들과 비슷한 크기여야 한다.
    """
    aaa = _rising(260)
    gap_date = aaa.index[150]
    bbb = aaa.drop(index=gap_date)
    tickers = {"AAA": {"name": "가", "market": "KR", "currency": "KRW", "is_etf": 0},
               "BBB": {"name": "나", "market": "KR", "currency": "KRW", "is_etf": 0}}
    out = engine.run({"AAA": aaa, "BBB": bbb}, tickers, preset="abs_momentum",
                     params={"lookback": 20, "skip": 2, "trend_ma": 10},
                     initial_capital_krw=10_000_000.0, fx=1_300.0)
    dates = [c["date"] for c in out["equity_curve"]]
    values = [c["equity_krw"] for c in out["equity_curve"]]
    gap_str = gap_date.strftime("%Y-%m-%d")
    assert gap_str in dates, "AAA 덕분에 휴장일도 캘린더에는 있어야 한다"
    gi = dates.index(gap_str)
    assert 0 < gi < len(values) - 1
    diffs = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    normal = sorted(diffs)[len(diffs) // 2]  # 중앙값 — 평상시 하루 변화 크기
    diff_in = abs(values[gi] - values[gi - 1])
    diff_out = abs(values[gi + 1] - values[gi])
    # 옛 버그는 BBB의 누적 미실현손익 전체가 스파이크로 나타난다 —
    # 평상시 하루 변화의 수십 배 규모. 고친 코드는 평상시와 비슷해야 한다.
    assert diff_in < normal * 5 + 1.0
    assert diff_out < normal * 5 + 1.0


def test_run_rejects_unknown_preset():
    """알 수 없는 전략은 ValueError — API 계층이 400으로 바꿔 준다."""
    with pytest.raises(ValueError):
        engine.run({}, {}, preset="없는전략", params={},
                   initial_capital_krw=1_000_000.0, fx=1_300.0)
