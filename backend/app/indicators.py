import pandas as pd


def sma(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window).mean()


def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, min_periods=period).mean()
    rs = gain / loss.replace(0, 1e-10)
    return 100 - 100 / (1 + rs)


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


def volume_ratio(volume: pd.Series, window=20) -> pd.Series:
    return volume / volume.shift(1).rolling(window).mean()


def pos_52w(close: pd.Series) -> pd.Series:
    window = min(len(close), 252)
    lo = close.rolling(window, min_periods=60).min()
    hi = close.rolling(window, min_periods=60).max()
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
    out["vol_ratio"] = volume_ratio(df["volume"])
    out["pos_52w"] = pos_52w(df["close"])
    return out
