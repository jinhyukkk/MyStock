import pytest
from fastapi.testclient import TestClient
from app import db, fetchers, sentiment
from app.main import create_app, _safe_static_path

FAKE_SENTI = {"vix": 18.0, "vkospi": None, "cnn_fg": 60, "crypto_fg": 50,
              "usdkrw": 1300.0, "failed": []}

@pytest.fixture
def client(tmp_path, ohlcv_up, monkeypatch):
    monkeypatch.setattr(fetchers, "fetch_ohlcv", lambda *a, **k: ohlcv_up)
    monkeypatch.setattr(fetchers, "fetch_fundamentals", lambda *a, **k: None)
    monkeypatch.setattr(fetchers, "search_symbols",
        lambda q, conn=None: [{"symbol": "005930", "name": "삼성전자", "market": "KR",
                               "is_etf": 0, "yf_symbol": "005930.KS", "currency": "KRW"}])
    monkeypatch.setattr(sentiment, "fetch_sentiment", lambda: dict(FAKE_SENTI))
    app = create_app(db_path=str(tmp_path / "t.db"), refresh_on_start=False)
    with TestClient(app) as c:
        yield c

def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}

def test_watchlist_flow(client):
    res = client.post("/api/watchlist", json={"symbol": "005930", "name": "삼성전자",
                                              "market": "KR", "is_etf": 0,
                                              "yf_symbol": "005930.KS", "currency": "KRW"})
    assert res.status_code == 200
    client.post("/api/refresh")
    d = client.get("/api/dashboard").json()
    assert len(d["signals"]) == 1
    assert d["sentiment"]["cnn_fg"] == 60
    assert client.delete("/api/watchlist/005930").status_code == 200

def test_removed_ticker_disappears_from_dashboard(client):
    client.post("/api/watchlist", json={"symbol": "005930", "name": "삼성전자",
                                        "market": "KR", "is_etf": 0,
                                        "yf_symbol": "005930.KS", "currency": "KRW"})
    client.post("/api/refresh")
    d = client.get("/api/dashboard").json()
    assert len(d["signals"]) == 1
    assert client.delete("/api/watchlist/005930").status_code == 200
    d2 = client.get("/api/dashboard").json()
    assert len(d2["signals"]) == 0


def test_held_ticker_stays_after_watchlist_removal(client):
    client.post("/api/watchlist", json={"symbol": "005930", "name": "삼성전자",
                                        "market": "KR", "is_etf": 0,
                                        "yf_symbol": "005930.KS", "currency": "KRW"})
    client.post("/api/refresh")
    client.post("/api/trades", json={"symbol": "005930", "side": "BUY",
                                     "quantity": 10, "price": 70000,
                                     "trade_date": "2026-01-05"})
    client.delete("/api/watchlist/005930")
    d = client.get("/api/dashboard").json()
    assert len(d["signals"]) == 1
    assert d["signals"][0]["is_holding"] is True
    assert d["signals"][0]["in_watchlist"] is False


def test_search(client):
    out = client.get("/api/search", params={"q": "삼성"}).json()
    assert out[0]["symbol"] == "005930"

def test_trades_and_portfolio(client):
    client.post("/api/watchlist", json={"symbol": "005930", "name": "삼성전자",
                                        "market": "KR", "is_etf": 0,
                                        "yf_symbol": "005930.KS", "currency": "KRW"})
    client.post("/api/refresh")
    res = client.post("/api/trades", json={"symbol": "005930", "side": "BUY",
                                           "quantity": 10, "price": 70000,
                                           "trade_date": "2026-01-05"})
    tid = res.json()["id"]
    pf = client.get("/api/portfolio").json()
    assert pf["holdings"][0]["quantity"] == 10
    assert client.delete(f"/api/trades/{tid}").status_code == 200

def test_rules_crud(client):
    client.post("/api/watchlist", json={"symbol": "005930", "name": "삼성전자",
                                        "market": "KR", "is_etf": 0,
                                        "yf_symbol": "005930.KS", "currency": "KRW"})
    rid = client.post("/api/rules", json={"symbol": "005930", "rule_type": "TARGET",
                                          "value": 90000}).json()["id"]
    assert len(client.get("/api/rules").json()) == 1
    assert client.delete(f"/api/rules/{rid}").status_code == 200

def test_ticker_detail_404(client):
    assert client.get("/api/tickers/NOPE").status_code == 404

def test_ticker_detail_ok(client):
    client.post("/api/watchlist", json={"symbol": "005930", "name": "삼성전자",
                                        "market": "KR", "is_etf": 0,
                                        "yf_symbol": "005930.KS", "currency": "KRW"})
    client.post("/api/refresh")
    detail = client.get("/api/tickers/005930").json()
    assert detail["signal"]["swing_grade"]
    assert len(detail["candles"]) > 0


@pytest.fixture
def fake_dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa-index</html>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    secret = tmp_path / "secret.txt"
    secret.write_text("top-secret, must never be served")
    return dist


def test_safe_static_path_blocks_traversal(fake_dist):
    assert _safe_static_path(fake_dist, "../secret.txt") is None
    assert _safe_static_path(fake_dist, "../../etc/passwd") is None
    assert _safe_static_path(fake_dist, "..%2f..%2fsecret.txt") is None


def test_safe_static_path_rejects_missing_or_empty(fake_dist):
    assert _safe_static_path(fake_dist, "") is None
    assert _safe_static_path(fake_dist, "nope.html") is None


def test_safe_static_path_allows_real_file(fake_dist):
    result = _safe_static_path(fake_dist, "assets/app.js")
    assert result == (fake_dist / "assets" / "app.js").resolve()


def test_set_cash_with_usd(client):
    r = client.put("/api/cash", json={"amount": 300000, "amount_usd": 200})
    assert r.status_code == 200
    assert r.json() == {"cash_krw": 300000.0, "cash_usd": 200.0}
    client.post("/api/refresh")  # 센티먼트 갱신 → usdkrw=1300 반영
    t = client.get("/api/portfolio").json()["totals"]
    assert t["cash_krw"] == 300000.0 and t["cash_usd"] == 200.0
    assert t["cash_usd_krw"] == 200 * 1300.0  # FAKE_SENTI usdkrw=1300


def test_set_cash_krw_only_keeps_usd(client):
    client.put("/api/cash", json={"amount": 100, "amount_usd": 50})
    r = client.put("/api/cash", json={"amount": 999})  # 하위호환: USD 미전송 → 유지
    assert r.json() == {"cash_krw": 999.0, "cash_usd": 50.0}


def test_set_cash_usd_only_keeps_krw(client):
    """KRW 미전송 = '변경 없음'. 프론트 빈 입력이 원화 예수금을 0으로 날리던 버그 방지."""
    client.put("/api/cash", json={"amount": 700000, "amount_usd": 50})
    r = client.put("/api/cash", json={"amount_usd": 300})
    assert r.json() == {"cash_krw": 700000.0, "cash_usd": 300.0}


def test_set_cash_empty_body_changes_nothing(client):
    client.put("/api/cash", json={"amount": 700000, "amount_usd": 50})
    r = client.put("/api/cash", json={})
    assert r.json() == {"cash_krw": 700000.0, "cash_usd": 50.0}


def test_set_cash_zero_is_explicit(client):
    """0은 '비웠다'는 명시적 의사 — None(미전송)과 구분되어야 한다."""
    client.put("/api/cash", json={"amount": 700000})
    r = client.put("/api/cash", json={"amount": 0})
    assert r.json()["cash_krw"] == 0.0


def _add_two_tickers(client):
    for sym, name in [("005930", "삼성전자"), ("000660", "SK하이닉스")]:
        client.post("/api/watchlist", json={"symbol": sym, "name": name, "market": "KR",
                                            "is_etf": 0, "yf_symbol": f"{sym}.KS",
                                            "currency": "KRW"})
    client.post("/api/refresh")


def test_dashboard_lists_holdings_first(client):
    """보유 종목이 시그널 표 상단에 오지 않으면 '보유 중 매도 신호'를 놓친다."""
    _add_two_tickers(client)
    client.post("/api/trades", json={"symbol": "000660", "side": "BUY", "quantity": 10,
                                     "price": 70000, "trade_date": "2026-01-05"})
    signals = client.get("/api/dashboard").json()["signals"]
    assert [s["is_holding"] for s in signals] == [True, False]


def test_dashboard_signal_carries_avg_price(client):
    _add_two_tickers(client)
    client.post("/api/trades", json={"symbol": "000660", "side": "BUY", "quantity": 10,
                                     "price": 70000, "trade_date": "2026-01-05"})
    by_symbol = {s["symbol"]: s for s in client.get("/api/dashboard").json()["signals"]}
    held, watched = by_symbol["000660"], by_symbol["005930"]
    assert held["avg_price"] == 70000.0
    expected = round((held["close"] / 70000 - 1) * 100, 2)
    assert held["holding_pnl_pct"] == expected
    assert watched["avg_price"] is None and watched["holding_pnl_pct"] is None
