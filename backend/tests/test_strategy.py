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
