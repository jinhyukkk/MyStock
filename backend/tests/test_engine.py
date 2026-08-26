import numpy as np
import pandas as pd
import pytest

from app import engine, strategy


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
    """동시 보유 노셔널 합 + 진입 비용은 현금(equity)을 넘지 않는다.

    이 픽스처(저변동 _rising)는 MAX_POSITIONS(7)가 아니라 현금 제약이 먼저
    막는다: 비중 상한 20%가 1% 룰보다 먼저 걸려(저변동 → 손절폭이 좁다)
    포지션당 노셔널이 equity의 약 20%다.

    손계산 (초기자본 1억, 진입일 2024-03-07 시가 133원, 왕복비용 0.78%):
      cap_qty  = 1억 × 0.20 / 133 = 150,375.94 → 내림 150,375주
      노셔널   = 150,375 × 133 = 19,999,875원 (자본의 19.999875%)
      진입비용 = 19,999,875 × 0.78% / 2 = 77,999.5원 (편도 = 왕복의 절반)
      1건이 묶는 현금 = 20,077,874.5원
    4건이면 80,311,498원을 써 잔여 현금이 19,688,502원인데 5건째는
    20,077,874.5원이 필요하다 → 막힌다 (5건 × 20,077,874.5 = 100,389,372.5원
    > 1억). 왕복비용 전액을 청산일에 몰아 빼던 옛 코드는 진입 시점에 비용이
    현금을 안 건드려서 5건이 들어갔다 — 다음 날 현금이 마이너스가 되는 조합이다.
    이후 날짜에는 미실현이익이 늘어도 현금 게이트는 실현자본 기준이라 잔여
    현금이 그대로이고, 5건째 수량은 평가자본에 비례해 오히려 더 커진다.
    """
    df = _rising(260)
    frames = {f"S{i}": df.copy() for i in range(12)}
    tickers = {f"S{i}": {"name": f"종목{i}", "market": "KR", "currency": "KRW",
                         "is_etf": 0} for i in range(12)}
    out = engine.run(frames, tickers, preset="abs_momentum",
                     params={"lookback": 60, "skip": 5, "trend_ma": 30},
                     initial_capital_krw=100_000_000.0, fx=1_300.0)
    assert out["max_concurrent"] == 4


def _rising_at(slope: float, n: int = 260) -> pd.DataFrame:
    """기울기만 다른 상승 시리즈 — 모멘텀 강도가 slope에 비례한다.

    abs_momentum(lookback=60, skip=5)의 65번째 봉 모멘텀은
    (100 + 60×slope)/100 − 1 = 0.6 × slope다. 시작가가 같아 진입일도 같다.
    """
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    close = [100.0 + i * slope for i in range(n)]
    return pd.DataFrame({"open": close, "high": [c + 1 for c in close],
                         "low": [c - 1 for c in close], "close": close,
                         "volume": 100_000.0}, index=idx)


def test_run_picks_strongest_candidates_when_slots_run_out():
    """같은 날 후보가 자리보다 많으면 **모멘텀 강도 내림차순**으로 자른다.

    딕셔너리 삽입 순서(= db.list_tickers의 ORDER BY market, name)로 자르면
    결과가 종목 이름에 의존한다 — 종목 하나를 개명해도 CAGR이 바뀐다.

    S0~S4는 기울기가 0.2 → 1.0으로 커지므로 강도도 S0 < … < S4다. 삽입
    순서는 일부러 약한 것부터다. 현금이 4자리분뿐이라(위 테스트의 손계산)
    한 종목이 탈락하는데, 탈락해야 하는 것은 가장 약한 S0다.
    """
    frames = {f"S{i}": _rising_at(0.2 * (i + 1)) for i in range(5)}
    tickers = {f"S{i}": {"name": f"종목{i}", "market": "KR", "currency": "KRW",
                         "is_etf": 0} for i in range(5)}
    out = engine.run(frames, tickers, preset="abs_momentum",
                     params={"lookback": 60, "skip": 5, "trend_ma": 30},
                     initial_capital_krw=100_000_000.0, fx=1_300.0)
    entered = {t["symbol"] for t in out["trades"]}
    assert entered == {"S1", "S2", "S3", "S4"}, \
        "가장 약한 S0이 아니라 이름 뒤쪽 종목이 탈락했다면 정렬이 안 걸린 것이다"


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

    후보 12종목이 같은 날(2024-03-07) 전부 신호를 내는데, 각 포지션이 계좌의
    정확히 1%를 걸므로 그날 6건째까지만 들어간다. 7건째는 6.99% > 6%로 막힌다.
    자본이 충분해 비중 상한(20%)에는 안 걸린다 — 포지션당 노셔널은 5.27%다.

    max_concurrent가 아니라 **같은 날 진입 건수**를 본다. 사이징 기준 자본이
    평가자본(mark-to-market)으로 바뀌면서, 뒤로 갈수록 계좌가 불어나
    기존 리스크 6,000만원의 비중이 6% 아래로 내려간다(평가자본 12억이면 5%).
    그때 7건째가 들어가는 것은 규칙대로다 — 그 시점엔 6% 상한을 안 넘는다.
    max_concurrent를 보면 MAX_POSITIONS(7)를 재게 되어 테스트 이름이 거짓이 된다.
    """
    df = _volatile_rising(260)
    frames = {f"S{i}": df.copy() for i in range(12)}
    tickers = {f"S{i}": {"name": f"종목{i}", "market": "KR", "currency": "KRW",
                         "is_etf": 0} for i in range(12)}
    out = engine.run(frames, tickers, preset="abs_momentum",
                     params={"lookback": 60, "skip": 5, "trend_ma": 30},
                     initial_capital_krw=1_000_000_000.0, fx=1_300.0)
    first_day = min(t["entry_date"] for t in out["trades"])
    same_day = [t for t in out["trades"] if t["entry_date"] == first_day]
    assert len(same_day) == 6
    assert out["max_concurrent"] <= engine.MAX_POSITIONS
    # 사이징 기준이 평가자본이라는 증거 — 나중에 들어간 건은 그 시점 평가자본의
    # 1%를 걸므로, 실현자본(초기 10억)의 1%보다 큰 리스크를 진다. 실현자본으로
    # 계산했다면 리스크가 정확히 10,000,000원(1%) 이하여야 한다.
    late = [t for t in out["trades"] if t["entry_date"] != first_day]
    assert late, "후반부 추가 진입이 없으면 이 단언이 아무것도 확인하지 않는다"
    assert late[0]["qty"] * (late[0]["entry_price"] * 0.20) > 10_000_000


def test_run_deducts_entry_cost_before_the_position_is_closed():
    """비용은 진입·청산 각각 차감한다 — 청산일에 왕복 전액을 몰아 빼지 않는다.

    옛 코드는 보유 기간 내내 자본곡선이 왕복 비용만큼 과대 표시되다가 청산일에
    계단으로 떨어졌고, MDD·샤프가 그 왜곡된 시리즈 위에서 계산됐다.

    진입 직전 날의 자본은 초기자본 그대로여야 하고(아직 아무 일도 없다),
    진입일 자본은 편도 비용(= 왕복의 절반)만큼 낮아야 한다.
    """
    out = engine.run({"AAA": _rising(260)},
                     {"AAA": {"name": "가", "market": "KR", "currency": "KRW",
                              "is_etf": 0}},
                     preset="abs_momentum",
                     params={"lookback": 60, "skip": 5, "trend_ma": 30},
                     initial_capital_krw=10_000_000.0, fx=1_300.0)
    t = out["trades"][0]
    by_date = {c["date"]: c["equity_krw"] for c in out["equity_curve"]}
    dates = [c["date"] for c in out["equity_curve"]]
    entry_i = dates.index(t["entry_date"])
    # 진입일 자본 = 초기자본 − 편도비용 + 당일 평가손익.
    # 진입가 = 그날 시가이고 _rising은 시가 = 종가라 평가손익이 0이다.
    assert by_date[dates[entry_i - 1]] == pytest.approx(10_000_000.0)
    assert by_date[t["entry_date"]] == pytest.approx(
        10_000_000.0 - t["cost_krw"] / 2, abs=1.0)


def test_run_calendar_uses_only_frames_it_actually_ran():
    """30봉 미만으로 걸러진 종목의 날짜가 자본곡선에 패딩되면 안 된다.

    패딩되면 그 날들이 CAGR 분모(거래일수)에 들어가 연율화가 틀어진다.
    """
    long_df = _rising(60)
    # 앞쪽으로 20봉만 있는 종목 — len < 30이라 run이 제외한다
    short_idx = pd.date_range("2023-01-01", periods=20, freq="D")
    short_df = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0,
                             "close": 100.0, "volume": 1000.0}, index=short_idx)
    out = engine.run({"AAA": long_df, "BBB": short_df},
                     {s: {"name": s, "market": "KR", "currency": "KRW", "is_etf": 0}
                      for s in ("AAA", "BBB")},
                     preset="donchian", params={"entry_n": 10, "exit_n": 5},
                     initial_capital_krw=10_000_000.0, fx=1_300.0)
    assert out["universe_size"] == 1
    assert len(out["equity_curve"]) == len(long_df)
    assert out["_used"]["symbols"] == ["AAA"]
    assert out["_used"]["calendar"] == list(long_df.index)


def test_metrics_empty_curve_reports_no_final_equity():
    """유니버스가 비면 '최종자본 0원'이 아니라 '계산할 게 없음'이다.

    0을 내려보내면 화면이 초기자본을 전액 잃은 것처럼 표시한다.
    """
    m = engine.metrics([], [])
    assert m["final_equity_krw"] is None
    assert m["cagr"] is None
    assert m["mdd"] is None
    assert m["trade_count"] == 0


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


def test_buy_and_hold_equal_weights_the_universe():
    """동일가중 매수보유 — 초기자본을 종목 수로 나눠 첫날 사서 끝까지 든다."""
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    up = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0,
                       "close": [100.0, 110.0, 120.0, 130.0, 140.0],
                       "volume": 1000.0}, index=idx)
    flat = pd.DataFrame({"open": 100.0, "high": 100.0, "low": 100.0,
                         "close": 100.0, "volume": 1000.0}, index=idx)
    tickers = {s: {"market": "KR", "currency": "KRW", "is_etf": 0}
               for s in ("A", "B")}
    curve = engine.buy_and_hold({"A": up, "B": flat}, tickers,
                                initial_capital_krw=1_000_000.0,
                                fx=1_300.0, calendar=list(idx))
    # A에 50만(+40%), B에 50만(0%) → 마지막 120만
    assert curve[0]["equity_krw"] == pytest.approx(1_000_000.0)
    assert curve[-1]["equity_krw"] == pytest.approx(1_200_000.0)


def test_buy_and_hold_floors_quantity_and_keeps_the_remainder_as_cash():
    """수량은 내림, 남은 잔돈은 현금 — 첫날 자본은 정확히 초기자본이다."""
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    # 97원은 100만을 나누어떨어지지 않는다 — 내림이 실제로 걸린다.
    # 가격이 움직여야 소수 주수와 내림 주수의 최종 자본이 갈린다 — 평선이면
    # 잔돈과 포지션 가치가 서로 상쇄돼 내림을 빼도 테스트가 통과한다.
    odd = pd.DataFrame({"open": 97.0, "high": 194.0, "low": 97.0,
                        "close": [97.0, 145.5, 194.0], "volume": 1000.0},
                       index=idx)
    tickers = {"A": {"market": "KR", "currency": "KRW", "is_etf": 0}}
    curve = engine.buy_and_hold({"A": odd}, tickers,
                                initial_capital_krw=1_000_000.0,
                                fx=1_300.0, calendar=list(idx))
    # floor(1_000_000/97) = 10309주 × 97 = 999_973원, 잔돈 27원
    assert curve[0]["equity_krw"] == pytest.approx(1_000_000.0)
    # 종가 2배 → 10309 × 194 + 27 = 1_999_973원.
    # 내림을 안 하면 10309.278주 × 194 = 2_000_000원이 나온다
    assert curve[-1]["equity_krw"] == pytest.approx(1_999_973.0, abs=1.0)


def test_buy_and_hold_empty_universe_returns_empty():
    """종목이 없으면 빈 곡선. 화면이 빈 배열을 그대로 처리한다."""
    assert engine.buy_and_hold({}, {}, 1_000_000.0, 1_300.0, []) == []


def test_buy_and_hold_carries_last_close_through_individual_holiday():
    """한 종목만 휴장인 날에도 비교선이 톱니를 만들지 않는다(발견 3 회귀).

    run()의 test_run_marks_holiday_position_without_sawtooth와 같은 구도 —
    BBB는 AAA와 동일한 가격이되 중간 하루가 빠져 있다. calendar는 AAA 덕분에
    그 날짜를 포함하므로, 이월 없이 직전 종가를 안 쓰면 그 날 BBB 몫이 0으로
    빠졌다가 다음 날 되돌아와 스파이크가 생긴다.
    """
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    close = [100.0 + i for i in range(10)]
    aaa = pd.DataFrame({"open": close, "high": close, "low": close,
                        "close": close, "volume": 1000.0}, index=idx)
    gap_date = idx[5]
    bbb = aaa.drop(index=gap_date)
    tickers = {s: {"market": "KR", "currency": "KRW", "is_etf": 0}
               for s in ("AAA", "BBB")}
    curve = engine.buy_and_hold({"AAA": aaa, "BBB": bbb}, tickers,
                                initial_capital_krw=1_000_000.0,
                                fx=1_300.0, calendar=list(idx))
    dates = [c["date"] for c in curve]
    values = [c["equity_krw"] for c in curve]
    gap_str = gap_date.strftime("%Y-%m-%d")
    assert gap_str in dates, "AAA 덕분에 휴장일도 캘린더에는 있어야 한다"
    gi = dates.index(gap_str)
    diffs = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    normal = sorted(diffs)[len(diffs) // 2]
    assert abs(values[gi] - values[gi - 1]) < normal * 5 + 1.0
    assert abs(values[gi + 1] - values[gi]) < normal * 5 + 1.0


# ── 홀드아웃 최적화 ──────────────────────────────────────────────────────────

_KR = {"name": "가", "market": "KR", "currency": "KRW", "is_etf": 0}


def test_run_trade_start_excludes_earlier_trading():
    """trade_start 이전에는 자본곡선 점도, 거래도 없어야 한다.

    시그널은 전체 이력으로 계산되므로 검증 구간 첫 날부터 워밍업이 차 있다 —
    frames를 날짜로 잘라 넘기는 방식이었다면 첫 lookback일은 신호가 비어
    검증이 전략에 불리하게 왜곡된다.
    """
    out = engine.run({"AAA": _rising(260)}, {"AAA": _KR},
                     preset="abs_momentum",
                     params={"lookback": 60, "skip": 5, "trend_ma": 30},
                     initial_capital_krw=10_000_000.0, fx=1_300.0,
                     trade_start=pd.Timestamp("2024-07-01"))
    assert out["equity_curve"][0]["date"] >= "2024-07-01"
    assert out["trades"], "워밍업이 살아 있으면 검증 구간에서도 진입이 나와야 한다"
    assert all(t["entry_date"] >= "2024-07-01" for t in out["trades"])


def test_optimize_splits_by_date_and_sorts_by_valid_sharpe():
    """조합 수 = grid 곱, split은 학습 70%, 정렬은 검증 샤프 내림차순(None 최하)."""
    import math as _math
    grids = [v["grid"] for v in engine.strategy.PRESETS["donchian"]["params"].values()]
    expected = _math.prod(len(g) for g in grids)
    out = engine.optimize({"AAA": _rising(300)}, {"AAA": _KR}, "donchian",
                          initial_capital_krw=10_000_000.0, fx=1_300.0)
    assert out["split_date"] < out["valid_start"]
    assert out["train_days"] == 210 and out["valid_days"] == 90
    assert len(out["results"]) == expected
    for r in out["results"]:
        assert set(r["params"]) == {"entry_n", "exit_n"}
        assert "cagr" in r["train"] and "sharpe" in r["valid"]
    sharpes = [r["valid"]["sharpe"] for r in out["results"]]
    non_null = [s for s in sharpes if s is not None]
    assert non_null == sorted(non_null, reverse=True)
    assert all(s is None for s in sharpes[len(non_null):])


def test_optimize_train_run_cannot_see_validation_prices():
    """학습 지표는 split 이전 데이터만으로 계산돼야 한다 — frames를 절단해
    돌린 결과와 정확히 같아야 검증 구간 누수가 없다."""
    df = _rising(300)
    out = engine.optimize({"AAA": df}, {"AAA": _KR}, "donchian",
                          initial_capital_krw=10_000_000.0, fx=1_300.0)
    split = pd.Timestamp(out["split_date"])
    truncated = engine.run({"AAA": df[df.index <= split]}, {"AAA": _KR},
                           "donchian", out["results"][0]["params"],
                           initial_capital_krw=10_000_000.0, fx=1_300.0)
    assert out["results"][0]["train"] == truncated["metrics"]


def test_optimize_short_history_returns_empty():
    """표본이 너무 짧으면 빈 결과 — 검증 구간 수십 일로는 아무것도 증명 못 한다."""
    out = engine.optimize({"AAA": _rising(60)}, {"AAA": _KR}, "donchian",
                          initial_capital_krw=10_000_000.0, fx=1_300.0)
    assert out["results"] == [] and out["split_date"] is None


def test_optimize_rejects_unknown_preset():
    with pytest.raises(ValueError):
        engine.optimize({}, {}, "없는전략",
                        initial_capital_krw=10_000_000.0, fx=1_300.0)


# ── 멤버십 게이트 · 상장폐지 청산 ─────────────────────────────────────────────

def _trend_frame(n=120, start="2024-01-01"):
    """진입 신호가 확실히 나는 상승 일봉 — 지수 상승이어야 한다.

    등차(+1) 상승은 고가(close+1)가 항상 다음날 종가와 같아져 돈치안 돌파
    (종가 > 직전 고가 최대)가 영원히 안 난다."""
    idx = pd.bdate_range(start, periods=n)
    close = pd.Series([100 * 1.03 ** i for i in range(n)], index=idx)
    return pd.DataFrame({"open": close.values, "high": close.values * 1.01,
                         "low": close.values * 0.99, "close": close.values,
                         "volume": 10_000.0}, index=idx)


def test_membership_gate_blocks_entry_outside_universe():
    """멤버십 False인 날의 진입 신호는 무시된다 — 시점별 유니버스의 핵심."""
    df = _trend_frame()
    tickers = {"S": {"name": "S", "market": "KR", "currency": "KRW", "is_etf": 0}}
    params = {"entry_n": 20, "exit_n": 10}
    base = engine.run({"S": df}, tickers, "donchian", params,
                      initial_capital_krw=1e7, fx=1400.0)
    assert base["metrics"]["trade_count"] > 0  # 게이트 없으면 거래가 난다
    never = {"S": pd.Series(False, index=df.index)}
    gated = engine.run({"S": df}, tickers, "donchian", params,
                       initial_capital_krw=1e7, fx=1400.0, membership=never)
    assert gated["metrics"]["trade_count"] == 0


def test_membership_gate_does_not_force_exit():
    """멤버십 이탈은 청산 사유가 아니다 — 보유는 신호·손절로만 끝난다."""
    df = _trend_frame()
    tickers = {"S": {"name": "S", "market": "KR", "currency": "KRW", "is_etf": 0}}
    params = {"entry_n": 20, "exit_n": 10}
    # 진입 가능 구간을 앞 40일로 제한 — 이후 멤버십 이탈
    mem = pd.Series([i < 40 for i in range(len(df))], index=df.index)
    out = engine.run({"S": df}, tickers, "donchian", params,
                     initial_capital_krw=1e7, fx=1400.0, membership={"S": mem})
    assert out["metrics"]["trade_count"] > 0
    # 상승 추세라 청산 신호·손절이 없다 → 데이터 끝까지 보유(end)여야 한다.
    # 멤버십 이탈(40일째)에 강제 청산됐다면 exit_date가 훨씬 앞이다.
    last = out["trades"][-1]
    assert last["exit_reason"] == "end"
    assert last["exit_date"] == df.index[-1].strftime("%Y-%m-%d")


def test_delisted_symbol_exit_reason():
    """폐지 종목을 데이터 끝까지 들고 있으면 사유가 end가 아니라 delisted."""
    df = _trend_frame(n=80)
    tickers = {"S": {"name": "S", "market": "KR", "currency": "KRW", "is_etf": 0,
                     "delisting_date": df.index[-1].strftime("%Y-%m-%d")}}
    out = engine.run({"S": df}, tickers, "donchian", {"entry_n": 20, "exit_n": 10},
                     initial_capital_krw=1e7, fx=1400.0)
    assert out["metrics"]["trade_count"] > 0
    assert out["trades"][-1]["exit_reason"] == "delisted"


# ── 워크포워드 ────────────────────────────────────────────────────────────────

@pytest.fixture
def tiny_preset(monkeypatch):
    """조합 2개짜리 미니 그리드 — 실제 그리드(15조합)로 돌리면 테스트가 느리다."""
    monkeypatch.setitem(strategy.PRESETS, "tiny", {
        "label": "미니", "kind": strategy.TIMESERIES, "fn": strategy.donchian,
        "params": {
            "entry_n": {"default": 20, "min": 5, "max": 200, "label": "진입",
                        "grid": [10, 20]},
            "exit_n": {"default": 10, "min": 5, "max": 200, "label": "청산",
                       "grid": [5]},
        }})


def _wavy_frames(n=600, n_symbols=3, seed=11):
    """추세가 굽이치는 합성 일봉 — 전 폴드에서 거래가 나게 한다."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n)
    frames, tickers = {}, {}
    for k in range(n_symbols):
        rets = rng.normal(0.0008, 0.02, n) + 0.01 * np.sin(np.arange(n) / 40)
        close = 10_000 * np.exp(np.cumsum(rets))
        df = pd.DataFrame({"open": close, "high": close * 1.015,
                           "low": close * 0.985, "close": close,
                           "volume": 50_000.0}, index=idx)
        frames[f"W{k}"] = df
        tickers[f"W{k}"] = {"name": f"W{k}", "market": "KR", "currency": "KRW",
                            "is_etf": 0}
    return frames, tickers


def test_walkforward_fold_boundaries(tiny_preset):
    """폴드 검증 구간은 서로 겹치지 않고 시간순이며, 학습은 항상 검증보다 앞."""
    frames, tickers = _wavy_frames()
    out = engine.walkforward(frames, tickers, "tiny",
                             initial_capital_krw=1e7, fx=1400.0, folds=3)
    assert len(out["folds"]) == 3
    prev_end = None
    for f in out["folds"]:
        assert f["train_end"] < f["valid_start"] <= f["valid_end"]
        if prev_end is not None:
            assert f["valid_start"] > prev_end  # 겹침 금지
        prev_end = f["valid_end"]
    # anchored: 학습 끝은 폴드가 갈수록 뒤로 늘어난다
    ends = [f["train_end"] for f in out["folds"]]
    assert ends == sorted(ends)


def test_walkforward_excess_and_summary(tiny_preset):
    """벤치마크를 주면 폴드별 초과수익과 요약 판정이 계산된다."""
    frames, tickers = _wavy_frames()
    bench = next(iter(frames.values())).copy()
    out = engine.walkforward(frames, tickers, "tiny",
                             initial_capital_krw=1e7, fx=1400.0, folds=3,
                             bench_frame=bench)
    for f in out["folds"]:
        assert f["bench_cagr"] is not None
        assert f["excess_pct"] == pytest.approx(
            (f["valid"]["cagr"] or 0) - f["bench_cagr"], abs=0.01)
    s = out["summary"]
    assert s["total_folds"] == 3
    assert 0 <= s["positive_folds"] <= 3
    assert s["median_excess_pct"] is not None
    assert s["param_stability"]["distinct_combos"] >= 1


def test_walkforward_stitched_curve_is_continuous(tiny_preset):
    """연결 곡선은 날짜가 단조 증가하고 폴드 경계에서 자본이 이어진다."""
    frames, tickers = _wavy_frames()
    out = engine.walkforward(frames, tickers, "tiny",
                             initial_capital_krw=1e7, fx=1400.0, folds=3)
    curve = out["stitched_curve"]
    dates = [c["date"] for c in curve]
    assert dates == sorted(dates) and len(set(dates)) == len(dates)
    # 첫 점은 초기자본 근처에서 출발한다(첫 폴드는 배율 1)
    assert curve[0]["equity_krw"] == pytest.approx(1e7, rel=0.2)
    assert out["stitched_metrics"]["cagr"] is not None


def test_walkforward_progress_callback(tiny_preset):
    frames, tickers = _wavy_frames(n=400)
    calls = []
    engine.walkforward(frames, tickers, "tiny", initial_capital_krw=1e7,
                       fx=1400.0, folds=2,
                       progress_cb=lambda done, total: calls.append((done, total)))
    assert calls and calls[-1][0] == calls[-1][1]  # 마지막엔 done == total


# ── 시장 레짐 필터 ────────────────────────────────────────────────────────────

def test_regime_filter_blocks_entry_when_off():
    """레짐 False인 날의 진입 신호는 무시된다 — 하락장 신규 진입 차단."""
    df = _trend_frame()
    tickers = {"S": {"name": "S", "market": "KR", "currency": "KRW", "is_etf": 0}}
    params = {"entry_n": 20, "exit_n": 10}
    off = pd.Series(False, index=df.index)
    out = engine.run({"S": df}, tickers, "donchian", params,
                     initial_capital_krw=1e7, fx=1400.0, regime=off)
    assert out["metrics"]["trade_count"] == 0


def test_regime_filter_carries_last_value_on_bench_holiday():
    """벤치마크 휴장일은 직전 레짐을 이어받는다 — 빈 날을 False로 치면
    벤치 휴장일마다 진입이 통째로 막힌다."""
    df = _trend_frame()
    tickers = {"S": {"name": "S", "market": "KR", "currency": "KRW", "is_etf": 0}}
    params = {"entry_n": 20, "exit_n": 10}
    # 벤치 캘린더에서 종목 거래일 일부가 빠진 레짐(전부 True)
    sparse = pd.Series(True, index=df.index[::2])
    out = engine.run({"S": df}, tickers, "donchian", params,
                     initial_capital_krw=1e7, fx=1400.0, regime=sparse)
    base = engine.run({"S": df}, tickers, "donchian", params,
                      initial_capital_krw=1e7, fx=1400.0)
    assert out["metrics"]["trade_count"] == base["metrics"]["trade_count"]


# ── 횡단면 프리셋 통합 ──────────────────────────────────────────────────────

def _xs_universe(n_symbols=10, n_days=400, seed=11):
    """추세 세기가 종목마다 다른 합성 일봉 — 랭킹이 갈리도록."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n_days)
    frames, tickers = {}, {}
    for k in range(n_symbols):
        drift = 0.0002 + k * 0.0002
        close = 10_000 * np.exp(np.cumsum(rng.normal(drift, 0.015, n_days)))
        spread = np.abs(rng.normal(0, 0.01, n_days)) * close
        frames[f"X{k:02d}"] = pd.DataFrame(
            {"open": close, "high": close + spread, "low": close - spread,
             "close": close, "volume": 1e6}, index=idx)
        tickers[f"X{k:02d}"] = {"name": f"X{k:02d}", "market": "KR",
                                "currency": "KRW", "is_etf": 0}
    return frames, tickers


def test_run_supports_a_cross_sectional_preset():
    """횡단면 프리셋으로도 자본곡선과 거래가 나온다."""
    frames, tickers = _xs_universe()
    out = engine.run(frames, tickers, "xs_momentum",
                     {"lookback": 126, "skip": 21, "enter_pct": 20, "exit_pct": 50},
                     initial_capital_krw=10_000_000.0, fx=1300.0)
    assert out["equity_curve"], "자본곡선이 비면 신호가 전혀 안 붙은 것이다"
    assert out["trades"], "거래 0건 결과는 회귀를 못 잡는다"
    assert out["metrics"]["cagr"] is not None
    assert out["universe_size"] == 10


def test_cross_sectional_signals_stay_aligned_with_suspended_bars():
    """거래정지(NaN 행)가 섞여도 신호가 한 칸씩 밀리지 않는다.

    밀리면 예외 없이 틀린 자본곡선이 나오므로, 여기서 잡지 못하면 어디서도
    잡히지 않는다. NaN 행을 심은 종목의 진입가가 그 종목 실제 시가여야 한다.
    """
    frames, tickers = _xs_universe()
    victim = "X09"  # 모멘텀 1위 — 반드시 매수 후보에 든다
    f = frames[victim].copy()
    f.iloc[200:205, :4] = float("nan")  # OHLC만 NaN (거래정지)
    frames[victim] = f
    out = engine.run(frames, tickers, "xs_momentum",
                     {"lookback": 126, "skip": 21, "enter_pct": 30, "exit_pct": 60},
                     initial_capital_krw=10_000_000.0, fx=1300.0)
    valid_opens = set(f["open"].dropna().round(4))
    for t in out["trades"]:
        if t["symbol"] == victim:
            assert t["entry_price"] in valid_opens, \
                "진입가가 그 종목의 실제 시가가 아니면 신호가 밀린 것이다"


def test_cross_sectional_membership_restricts_the_ranking_denominator():
    """멤버십이 랭킹 분모에 반영된다 — 비멤버는 진입하지 않는다."""
    frames, tickers = _xs_universe()
    members = {"X00", "X01", "X02", "X03"}
    membership = {s: pd.Series(s in members, index=df.index)
                  for s, df in frames.items()}
    out = engine.run(frames, tickers, "xs_momentum",
                     {"lookback": 126, "skip": 21, "enter_pct": 30, "exit_pct": 60},
                     initial_capital_krw=10_000_000.0, fx=1300.0,
                     membership=membership)
    traded = {t["symbol"] for t in out["trades"]}
    assert traded, "멤버 안에서는 거래가 나와야 한다"
    assert traded <= members, f"비멤버가 진입했다: {traded - members}"
