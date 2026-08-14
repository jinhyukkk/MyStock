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

def test_fetch_ohlcv_crypto_pages_when_days_gt_200(monkeypatch):
    page1 = [
        {"candle_date_time_kst": "2025-06-10T09:00:00", "candle_date_time_utc": "2025-06-10T00:00:00",
         "opening_price": 100.0, "high_price": 110.0, "low_price": 90.0, "trade_price": 105.0,
         "candle_acc_trade_volume": 10.0},
        {"candle_date_time_kst": "2025-06-09T09:00:00", "candle_date_time_utc": "2025-06-09T00:00:00",
         "opening_price": 99.0, "high_price": 108.0, "low_price": 89.0, "trade_price": 104.0,
         "candle_acc_trade_volume": 9.0},
    ]
    page2 = [
        {"candle_date_time_kst": "2025-06-01T09:00:00", "candle_date_time_utc": "2025-06-01T00:00:00",
         "opening_price": 80.0, "high_price": 85.0, "low_price": 75.0, "trade_price": 82.0,
         "candle_acc_trade_volume": 5.0},
        {"candle_date_time_kst": "2025-05-31T09:00:00", "candle_date_time_utc": "2025-05-31T00:00:00",
         "opening_price": 78.0, "high_price": 83.0, "low_price": 74.0, "trade_price": 80.0,
         "candle_acc_trade_volume": 4.0},
    ]

    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return list(self._payload)

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        if params is not None and "to" in params:
            return FakeResponse(page2)
        return FakeResponse(page1)

    monkeypatch.setattr(fetchers.requests, "get", fake_get)

    df = fetchers.fetch_ohlcv("KRW-BTC", "CRYPTO", days=250)

    # 2페이지 수집 + 진행 없음 감지로 종료 (마지막 호출은 page2 반복 → 중단)
    assert len(calls) == 3
    assert calls[1]["to"] == page1[-1]["candle_date_time_utc"]
    assert len(df) == len(page1) + len(page2)

def test_fetch_fundamentals_zero_dividend_yield_is_not_none(monkeypatch):
    import sys
    import types

    class FakeTicker:
        def __init__(self, symbol):
            self.info = {"trailingPE": 10.0, "priceToBook": 1.0,
                        "dividendYield": 0.0, "marketCap": 123}

    fake_yf = types.ModuleType("yfinance")
    fake_yf.Ticker = FakeTicker
    monkeypatch.setitem(sys.modules, "yfinance", fake_yf)

    result = fetchers.fetch_fundamentals("AAPL")
    assert result["dividend_yield"] == 0.0

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
