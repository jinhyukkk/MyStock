import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

import numpy as np
import pandas as pd
import pytest

@pytest.fixture
def ohlcv_up():
    """300일 완만한 상승 추세 + 노이즈 (결정적)."""
    rng = np.random.default_rng(42)
    n = 300
    close = 100 + np.arange(n) * 0.5 + rng.normal(0, 1.5, n).cumsum() * 0.3
    close = np.maximum(close, 10)
    high = close * (1 + rng.uniform(0.001, 0.02, n))
    low = close * (1 - rng.uniform(0.001, 0.02, n))
    open_ = (high + low) / 2
    volume = rng.uniform(1e5, 3e5, n)
    idx = pd.bdate_range("2025-05-01", periods=n)
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": volume}, index=idx)

@pytest.fixture
def ohlcv_down(ohlcv_up):
    """상승 픽스처를 뒤집은 하락 추세."""
    df = ohlcv_up.copy()
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].values[::-1]
    df[["high", "low"]] = df[["low", "high"]].values  # 뒤집으면 high/low가 바뀜
    return df
