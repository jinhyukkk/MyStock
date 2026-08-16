import pandas as pd


def sma(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window).mean()


def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, min_periods=period).mean()
    rs = gain / loss.replace(0, 1e-10)
    out = 100 - 100 / (1 + rs)
    # Handle flat series: when both gain and loss are ~0, RSI should be neutral (50)
    mask = (gain < 1e-12) & (loss < 1e-12)
    out[mask & out.notna()] = 50.0
    return out


def macd(s: pd.Series, fast=12, slow=26, signal=9) -> pd.DataFrame:
    line = s.ewm(span=fast, min_periods=fast).mean() - s.ewm(span=slow, min_periods=slow).mean()
    sig = line.ewm(span=signal, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig})


def bollinger(s: pd.Series, window=20, k=2) -> pd.DataFrame:
    mid = s.rolling(window).mean()
    std = s.rolling(window).std()
    return pd.DataFrame({"bb_mid": mid, "bb_upper": mid + k * std, "bb_lower": mid - k * std})


def stochastic(high, low, close, k_period=14, d_period=3, smooth=3) -> pd.DataFrame:
    lowest = low.rolling(k_period).min()
    highest = high.rolling(k_period).max()
    raw_k = 100 * (close - lowest) / (highest - lowest).replace(0, 1e-10)
    k = raw_k.rolling(smooth).mean()
    d = k.rolling(d_period).mean()
    return pd.DataFrame({"stoch_k": k, "stoch_d": d})


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period).mean()


def max_drawdown_pct(close: pd.Series) -> float:
    """기간 내 최대 낙폭(%). 항상 0 이하."""
    return float(((close / close.cummax()) - 1).min() * 100)


def volume_ratio(volume: pd.Series, window=20) -> pd.Series:
    return volume / volume.shift(1).rolling(window).mean()


def pos_52w(close: pd.Series, high: pd.Series | None = None,
            low: pd.Series | None = None) -> pd.Series:
    """52주 범위 내 현재 종가의 위치 (0=저점, 1=고점).

    범위는 고가/저가 기준이다 — "52주 신고가"는 장중 고가로 정의되므로, 종가
    rolling만 쓰면 실제 범위보다 좁게 잡혀 위치가 과대·과소 계상된다.
    (고저가가 없으면 종가로 폴백)
    """
    window = min(len(close), 252)
    lo = (low if low is not None else close).rolling(window, min_periods=60).min()
    hi = (high if high is not None else close).rolling(window, min_periods=60).max()
    return ((close - lo) / (hi - lo).replace(0, 1e-10)).clip(0, 1)


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["sma20"] = sma(df["close"], 20)
    out["sma60"] = sma(df["close"], 60)
    out["sma120"] = sma(df["close"], 120)
    out["rsi"] = rsi(df["close"])
    out = out.join(macd(df["close"]))
    out = out.join(bollinger(df["close"]))
    out = out.join(stochastic(df["high"], df["low"], df["close"]))
    out["atr14"] = atr(df["high"], df["low"], df["close"])
    out["vol_ratio"] = volume_ratio(df["volume"])
    out["pos_52w"] = pos_52w(df["close"], df["high"], df["low"])
    return out
