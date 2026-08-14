import json
import pytest
from app import db, service, fetchers, sentiment

FAKE_SENTI = {"vix": 20.0, "vkospi": None, "cnn_fg": 40, "crypto_fg": 55,
              "usdkrw": 1300.0, "failed": ["vkospi"]}

@pytest.fixture
def conn(tmp_path, ohlcv_up, monkeypatch):
    c = db.get_conn(str(tmp_path / "t.db"))
    db.upsert_ticker(c, "005930", "KR", "삼성전자", in_watchlist=1, yf_symbol="005930.KS")
    db.upsert_ticker(c, "AAPL", "US", "Apple", in_watchlist=1, yf_symbol="AAPL", currency="USD")
    monkeypatch.setattr(fetchers, "fetch_ohlcv", lambda *a, **k: ohlcv_up)
    monkeypatch.setattr(fetchers, "fetch_fundamentals", lambda *a, **k: {"per": 15.0})
    monkeypatch.setattr(sentiment, "fetch_sentiment", lambda: dict(FAKE_SENTI))
    yield c
    c.close()

def test_refresh_all_stores_signals(conn):
    out = service.refresh_all(conn)
    assert out["refreshed"] is True
    assert db.get_latest_signal(conn, "005930") is not None
    assert db.get_meta(conn, "last_refresh")
    assert json.loads(db.get_meta(conn, "sentiment"))["cnn_fg"] == 40

def test_refresh_survives_single_ticker_failure(conn, monkeypatch):
    orig = fetchers.fetch_ohlcv
    monkeypatch.setattr(fetchers, "fetch_ohlcv",
        lambda symbol, market, **k: (_ for _ in ()).throw(RuntimeError("down"))
        if symbol == "AAPL" else orig(symbol, market, **k))
    out = service.refresh_all(conn)
    assert "AAPL" in out["failed_tickers"]
    assert db.get_latest_signal(conn, "005930") is not None

def test_dashboard_shape(conn):
    service.refresh_all(conn)
    d = service.get_dashboard(conn)
    assert d["sentiment"]["cnn_fg_label"] == "공포"
    assert len(d["signals"]) == 2
    s = d["signals"][0]
    for key in ["symbol", "name", "market", "close", "change_pct", "swing_score",
                "swing_grade", "longterm_score", "longterm_grade",
                "grade_changed", "is_holding"]:
        assert key in s
    assert d["last_refresh"]

def test_summary_tags_shortened_and_ranked():
    details = {"indicator_scores": [
        {"name": "RSI", "score": 80, "reason": "RSI 28 — 과매도 구간 (반등 가능성)"},
        {"name": "MACD", "score": -40,
         "reason": "MACD 히스토그램 음(-) — 하락 모멘텀 유지 ⚠ 상승 추세 중 조정 신호 — 신뢰도 반감"},
        {"name": "거래량", "score": 0, "reason": "거래량 평균 수준 (100%)"},
        {"name": "볼린저밴드", "score": 30, "reason": "볼린저밴드 하단 근접"},
        {"name": "스토캐스틱", "score": 40, "reason": "스토캐스틱 15 — 과매도권"},
        {"name": "이평선 배열", "score": 70, "reason": "주가 > 60일선 > 120일선 — 중장기 정배열"},
    ]}
    tags = service.summary_tags(details)
    assert len(tags) == 3  # 0점 제외, |score| 상위 3개만
    assert tags[0] == {"label": "RSI: 과매도 구간", "score": 80, "warn": False}
    assert tags[1]["label"] == "이평선 배열: 중장기 정배열"
    assert tags[2]["warn"] is True  # 국면 반감 경고 분리
    assert service.summary_tags({}) == []  # 과거 데이터 폴백


def test_dashboard_includes_summary_tags(conn):
    service.refresh_all(conn)
    d = service.get_dashboard(conn)
    for s in d["signals"]:
        assert isinstance(s["summary_tags"], list) and len(s["summary_tags"]) <= 3


def test_rule_alerts(conn):
    service.refresh_all(conn)
    close = db.load_prices(conn, "005930").iloc[-1]["close"]
    db.insert_rule(conn, "005930", "TARGET", close * 0.9)   # 이미 도달
    db.insert_rule(conn, "005930", "STOP", close * 0.5)     # 미도달
    d = service.get_dashboard(conn)
    assert len(d["rule_alerts"]) == 1
    assert d["rule_alerts"][0]["rule_type"] == "TARGET"

def test_signal_includes_in_watchlist_flag(conn):
    service.refresh_all(conn)
    d = service.get_dashboard(conn)
    for s in d["signals"]:
        assert "in_watchlist" in s
    assert all(s["in_watchlist"] for s in d["signals"])


def test_removed_ticker_drops_from_dashboard(conn):
    service.refresh_all(conn)
    db.remove_from_watchlist(conn, "AAPL")
    d = service.get_dashboard(conn)
    symbols = [s["symbol"] for s in d["signals"]]
    assert "AAPL" not in symbols
    assert "005930" in symbols


def test_removed_ticker_not_polled_on_refresh(conn, monkeypatch):
    service.refresh_all(conn)
    db.remove_from_watchlist(conn, "AAPL")
    calls = []
    orig = fetchers.fetch_ohlcv

    def track(symbol, market, **k):
        calls.append(symbol)
        return orig(symbol, market, **k)

    monkeypatch.setattr(fetchers, "fetch_ohlcv", track)
    service.refresh_all(conn)
    assert "AAPL" not in calls
    assert "005930" in calls


def test_held_but_removed_ticker_still_in_dashboard(conn):
    service.refresh_all(conn)
    db.remove_from_watchlist(conn, "AAPL")
    db.insert_trade(conn, "AAPL", "BUY", 1, 100, "2026-01-01")
    d = service.get_dashboard(conn)
    aapl = next(s for s in d["signals"] if s["symbol"] == "AAPL")
    assert aapl["is_holding"] is True
    assert aapl["in_watchlist"] is False


def test_ticker_detail(conn):
    service.refresh_all(conn)
    detail = service.get_ticker_detail(conn, "005930")
    assert detail["name"] == "삼성전자"
    assert len(detail["candles"]) <= 200
    assert {"date", "open", "close", "sma20", "rsi", "macd"} <= set(detail["candles"][-1])
    assert detail["signal"]["swing_grade"]
    assert detail["fundamentals"] == {"per": 15.0}
    assert service.get_ticker_detail(conn, "NOPE") is None


def test_notify_telegram_dedupes_per_day(conn, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    sent = []

    class OK:
        def raise_for_status(self):
            pass

    monkeypatch.setattr(service.requests, "post",
                        lambda url, json=None, timeout=None: sent.append(json) or OK())
    alerts = [{"symbol": "005930", "rule_type": "TARGET", "value": 100.0,
               "message": "삼성전자 목표가 100 도달"}]
    service._notify_telegram(conn, alerts)
    service._notify_telegram(conn, alerts)  # 같은 날 재호출 → 발송 안 함
    assert len(sent) == 1
    assert "삼성전자" in sent[0]["text"] and sent[0]["chat_id"] == "42"


def test_notify_telegram_noop_without_config(conn, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr(service.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("호출되면 안 됨")))
    service._notify_telegram(conn, [{"symbol": "A", "rule_type": "STOP", "value": 1,
                                     "message": "m"}])
