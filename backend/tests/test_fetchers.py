import pandas as pd
import pytest
from app import fetchers

def test_normalize_ohlcv_renames_and_sorts():
    df = pd.DataFrame({"Open": [2, 1], "High": [3, 2], "Low": [1, 0.5],
                       "Close": [2.5, 1.5], "Volume": [10, 20]},
                      index=pd.to_datetime(["2026-01-02", "2026-01-01"]))
    out = fetchers.normalize_ohlcv(df, {"Open": "open", "High": "high", "Low": "low",
                                        "Close": "close", "Volume": "volume"})
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert out.index[0] < out.index[1]

def test_parse_upbit_candles():
    payload = [
        {"candle_date_time_kst": "2026-01-02T09:00:00", "opening_price": 100.0,
         "high_price": 110.0, "low_price": 90.0, "trade_price": 105.0,
         "candle_acc_trade_volume": 12.5},
        {"candle_date_time_kst": "2026-01-01T09:00:00", "opening_price": 95.0,
         "high_price": 101.0, "low_price": 94.0, "trade_price": 100.0,
         "candle_acc_trade_volume": 10.0},
    ]
    out = fetchers.parse_upbit_candles(payload)
    assert len(out) == 2
    assert out.index[0].strftime("%Y-%m-%d") == "2026-01-01"  # 오름차순
    assert out.iloc[1]["close"] == 105.0

def test_fetch_ohlcv_unknown_market():
    with pytest.raises(ValueError):
        fetchers.fetch_ohlcv("X", "LONDON")

@pytest.mark.smoke
def test_smoke_fetch_kr():
    df = fetchers.fetch_ohlcv("005930", "KR", days=30)
    assert len(df) > 10 and "close" in df.columns

@pytest.mark.smoke
def test_smoke_fetch_us():
    df = fetchers.fetch_ohlcv("AAPL", "US", yf_symbol="AAPL", days=30)
    assert len(df) > 10

@pytest.mark.smoke
def test_smoke_fetch_crypto():
    df = fetchers.fetch_ohlcv("KRW-BTC", "CRYPTO", days=30)
    assert len(df) > 10

@pytest.mark.smoke
def test_smoke_search():
    assert any(r["symbol"] == "005930" for r in fetchers.search_symbols("삼성전자"))
    assert any(r["market"] == "CRYPTO" for r in fetchers.search_symbols("비트코인"))
