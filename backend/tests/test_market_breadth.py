"""breadth·패턴 계산 — 합성 시계열만 쓴다(네트워크 없음)."""
import numpy as np
import pandas as pd
import pytest

from app import market_breadth as mb


def _frame(cols: dict[str, list[float]]) -> pd.DataFrame:
    n = max(len(v) for v in cols.values())
    idx = pd.bdate_range(end="2026-08-21", periods=n)
    return pd.DataFrame({k: pd.Series(v, index=idx[-len(v):]) for k, v in cols.items()},
                        index=idx)


def _series(n: int, fn) -> list[float]:
    return [float(fn(i)) for i in range(n)]


def test_breadth_counts_advancing_and_declining():
    df = _frame({"UP": [10, 11], "DOWN": [10, 9], "FLAT": [10, 10]})
    bars = mb.breadth(df)
    up = bars[0]
    assert (up["left_label"], up["left_n"], up["right_n"]) == ("상승", 1, 1)
    # 보합은 좌우 어디에도 안 들어간다 — 분모가 2라 50/50
    assert up["left_pct"] == 50.0 and up["right_pct"] == 50.0


def test_breadth_52w_needs_full_history():
    long_up = _series(300, lambda i: 100 + i)          # 매일 신고가
    short_up = _series(30, lambda i: 100 + i)          # 자료 부족 — 분모에서 빠진다
    bars = mb.breadth(_frame({"LONG": long_up, "SHORT": short_up}))
    hi = next(b for b in bars if b["center"] == "52주")
    assert hi["left_n"] == 1 and hi["right_n"] == 0


def test_breadth_sma_sides():
    above = _series(260, lambda i: 100 + i)            # 우상향 → SMA 위
    below = _series(260, lambda i: 400 - i)            # 우하향 → SMA 아래
    bars = mb.breadth(_frame({"A": above, "B": below}))
    sma50 = next(b for b in bars if b["center"] == "SMA50")
    sma200 = next(b for b in bars if b["center"] == "SMA200")
    assert (sma50["left_n"], sma50["right_n"]) == (1, 1)
    assert (sma200["left_n"], sma200["right_n"]) == (1, 1)


def test_breadth_empty_frame():
    assert mb.breadth(pd.DataFrame()) == []


def _classify(vals: list[float]) -> list[str]:
    return mb._classify(pd.Series(vals, dtype=float))


def test_golden_and_dead_cross():
    # 200일 하락 뒤 급반등 → 단기선이 장기선을 최근에 상향 돌파
    golden = _series(230, lambda i: 300 - i) + _series(25, lambda i: 70 + i * 20)
    assert "golden" in _classify(golden)
    dead = _series(230, lambda i: 100 + i) + _series(25, lambda i: 330 - i * 20)
    assert "dead" in _classify(dead)


def test_high52_and_low52():
    assert "high52" in _classify(_series(260, lambda i: 100 + i))
    assert "low52" in _classify(_series(260, lambda i: 400 - i))


def test_channel_needs_slope_and_fit():
    up = _series(80, lambda i: 100 + i)                        # 곧게 상승
    assert "channel_up" in _classify(up)
    noisy = _series(80, lambda i: 100 + 30 * np.sin(i))        # 기울기 없음
    assert "channel_up" not in _classify(noisy) and "channel_down" not in _classify(noisy)


def test_double_bottom_and_top():
    # W: 100 → 83 → 97 → 83 → 99 (두 번째 바닥에서 돌아선 뒤 끝난다)
    w = [100 - i for i in range(18)] + [83 + i for i in range(15)] + \
        [97 - i for i in range(15)] + [83 + i * 1.2 for i in range(14)]
    assert _classify(w) == ["double_bottom"]
    # M: 82 → 99 → 85 → 99 → 79. 끝이 두 바닥보다 낮아야 M 이고, 그래서 W 로도 안 잡힌다
    m = [82 + i for i in range(18)] + [99 - i for i in range(15)] + \
        [85 + i for i in range(15)] + [99 - i * 1.5 for i in range(14)]
    assert _classify(m) == ["double_top"]


def test_squeeze_detects_narrowing_range():
    wide = [100 + (10 if i % 2 else -10) for i in range(40)]
    calm = [100 + (0.2 if i % 2 else -0.2) for i in range(20)]
    assert "squeeze" in _classify(wide + calm)


def test_patterns_groups_by_signal_and_caps_per_row():
    cols = {f"S{i}": _series(260, lambda j: 100 + j) for i in range(6)}
    rows = mb.patterns(_frame(cols), names={"S0": "가나다"})
    high = next(r for r in rows if r["signal"] == "52주 신고가")
    assert len(high["tickers"]) == mb.PER_PATTERN     # 한 줄에 4개까지
    assert high["tickers"][0] == {"symbol": "S0", "name": "가나다"}
    assert high["icon"] == "▲"


def test_patterns_skips_short_history():
    assert mb.patterns(_frame({"NEW": _series(10, lambda i: 100 + i)})) == []
