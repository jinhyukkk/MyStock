import numpy as np
import pandas as pd
from app import indicators as ind

def test_sma_basic():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    out = ind.sma(s, 3)
    assert np.isnan(out.iloc[1])
    assert out.iloc[2] == 2.0 and out.iloc[4] == 4.0

def test_rsi_extremes():
    up = pd.Series(np.arange(1, 40, dtype=float))     # 계속 상승
    down = pd.Series(np.arange(40, 1, -1, dtype=float))  # 계속 하락
    assert ind.rsi(up).iloc[-1] > 95
    assert ind.rsi(down).iloc[-1] < 5

def test_rsi_range(ohlcv_up):
    r = ind.rsi(ohlcv_up["close"]).dropna()
    assert ((r >= 0) & (r <= 100)).all()

def test_rsi_flat_series_is_neutral():
    flat = pd.Series([100.0] * 30)
    assert ind.rsi(flat).iloc[-1] == 50.0

def test_macd_shape(ohlcv_up):
    out = ind.macd(ohlcv_up["close"])
    assert list(out.columns) == ["macd", "macd_signal", "macd_hist"]
    tail = out.dropna().tail(5)
    assert np.allclose(tail["macd_hist"], tail["macd"] - tail["macd_signal"])

def test_bollinger_order(ohlcv_up):
    out = ind.bollinger(ohlcv_up["close"]).dropna()
    assert (out["bb_upper"] >= out["bb_mid"]).all()
    assert (out["bb_mid"] >= out["bb_lower"]).all()

def test_stochastic_range(ohlcv_up):
    out = ind.stochastic(ohlcv_up["high"], ohlcv_up["low"], ohlcv_up["close"]).dropna()
    assert ((out >= 0) & (out <= 100)).all().all()

def test_volume_ratio(ohlcv_up):
    v = ohlcv_up["volume"].copy()
    v.iloc[-1] = v.iloc[-21:-1].mean() * 3
    assert abs(ind.volume_ratio(v).iloc[-1] - 3.0) < 0.01

def test_pos_52w(ohlcv_up):
    p = ind.pos_52w(ohlcv_up["close"]).dropna()
    assert ((p >= 0) & (p <= 1)).all()
    assert p.iloc[-1] > 0.5  # 상승 추세면 상단

def test_compute_indicators_columns(ohlcv_up):
    out = ind.compute_indicators(ohlcv_up)
    for col in ["sma20", "sma60", "sma120", "rsi", "macd", "macd_signal",
                "macd_hist", "bb_mid", "bb_upper", "bb_lower",
                "stoch_k", "stoch_d", "vol_ratio", "pos_52w"]:
        assert col in out.columns
    assert len(out) == len(ohlcv_up)
