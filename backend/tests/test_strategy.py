import pandas as pd
import pytest

from app import strategy


def _series(values: list[float]) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype=float)


def _frame(closes: list[float]) -> pd.DataFrame:
    """종가만 의미 있는 최소 일봉. 고가·저가는 종가와 같게 둔다."""
    s = _series(closes)
    return pd.DataFrame({"open": s, "high": s, "low": s, "close": s,
                         "volume": 1000.0}, index=s.index)


def test_momentum_skips_recent_window():
    """12-1 모멘텀은 최근 skip일을 제외한다 — 단기 반전이 신호를 오염시킨다.

    lookback=5, skip=2 이면 i 시점 수익률은 close[i-2] / close[i-7] - 1 이다.
    """
    close = _series([100, 110, 120, 130, 140, 150, 160, 170, 180, 190])
    m = strategy.momentum(close, lookback=5, skip=2)
    # i=7: close[5]=150, close[0]=100 → 0.5
    assert m.iloc[7] == pytest.approx(0.5)
    # 앞쪽 lookback+skip 구간은 값이 없다
    assert m.iloc[:7].isna().all()


def test_abs_momentum_enters_on_positive_momentum_above_trend():
    """진입 조건 = 모멘텀 양(+) AND 종가 > 추세선."""
    df = _frame([100 + i for i in range(30)])
    out = strategy.abs_momentum(df, {"lookback": 10, "skip": 2, "trend_ma": 5})
    assert out["enter"].iloc[-1]
    assert not out["exit"].iloc[-1]


def test_abs_momentum_exits_when_momentum_turns_negative():
    """모멘텀이 음(-)으로 돌면 청산 신호."""
    df = _frame([100 + i for i in range(20)] + [120 - 4 * i for i in range(20)])
    out = strategy.abs_momentum(df, {"lookback": 10, "skip": 2, "trend_ma": 5})
    assert out["exit"].iloc[-1]
    assert not out["enter"].iloc[-1]


def test_signals_have_no_lookahead():
    """미래 봉을 붙여도 과거 시그널이 바뀌면 안 된다.

    이게 깨지면 백테스트 전체가 거짓이 된다 — 가장 중요한 테스트다.
    """
    full = _frame([100 + (i % 7) * 3 for i in range(60)])
    out_full = strategy.abs_momentum(full, {"lookback": 10, "skip": 2, "trend_ma": 5})
    cut = full.iloc[:40]
    out_cut = strategy.abs_momentum(cut, {"lookback": 10, "skip": 2, "trend_ma": 5})
    pd.testing.assert_frame_equal(out_full.iloc[:40], out_cut)


def _ohlc(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """(open, high, low, close) 튜플 목록 → 일봉."""
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(
        {"open": [r[0] for r in rows], "high": [r[1] for r in rows],
         "low": [r[2] for r in rows], "close": [r[3] for r in rows],
         "volume": 1000.0}, index=idx)


def test_donchian_enters_on_breakout_of_prior_high():
    """N일 최고가를 넘어서면 진입. 비교 대상은 **어제까지의** 최고가다."""
    rows = [(100, 110, 90, 100)] * 3 + [(100, 116, 95, 115)]
    out = strategy.donchian(_ohlc(rows), {"entry_n": 3, "exit_n": 2})
    assert out["enter"].iloc[3]


def test_donchian_does_not_use_todays_high_in_its_own_breakout():
    """오늘 고가를 오늘 돌파 판정에 넣으면 매일 진입 신호가 뜬다.

    .shift(1) 누락 회귀를 잡는 테스트다.
    """
    rows = [(100, 110, 90, 100), (100, 120, 90, 105),
            (100, 130, 90, 115), (100, 140, 90, 125)]
    out = strategy.donchian(_ohlc(rows), {"entry_n": 2, "exit_n": 2})
    assert not out["enter"].any()


def test_donchian_exits_below_prior_low():
    """M일 최저가를 이탈하면 청산."""
    rows = [(100, 110, 95, 100)] * 3 + [(100, 105, 80, 90)]
    out = strategy.donchian(_ohlc(rows), {"entry_n": 3, "exit_n": 3})
    assert out["exit"].iloc[3]


def test_donchian_registered_in_presets():
    assert "donchian" in strategy.PRESETS
    assert strategy.PRESETS["donchian"]["fn"] is strategy.donchian


def test_both_presets_expose_a_continuous_strength():
    """동시 진입 후보를 자를 때 쓸 연속값. 없으면 엔진이 심볼 이름순으로 자른다.

    - 절대 모멘텀: 모멘텀 값 그 자체
    - 돈치안: 돌파 폭 비율 (종가 − 직전 최고가) / 직전 최고가
    """
    df = _frame([100 + i for i in range(20)])
    mom = strategy.abs_momentum(df, {"lookback": 5, "skip": 2, "trend_ma": 3})
    expected = strategy.momentum(df["close"], 5, 2).fillna(0.0)
    pd.testing.assert_series_equal(mom["strength"], expected, check_names=False)

    rows = [(100, 110, 90, 100)] * 3 + [(100, 116, 95, 115)]
    don = strategy.donchian(_ohlc(rows), {"entry_n": 3, "exit_n": 2})
    # 직전 3일 최고가 110 → (115 − 110) / 110
    assert don["strength"].iloc[3] == pytest.approx(5 / 110)
    # 지표가 안 찬 앞부분은 0 — NaN을 남기면 정렬에서 튄다
    assert don["strength"].iloc[0] == 0.0
