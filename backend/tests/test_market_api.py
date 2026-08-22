"""/api/market 라우트 — 시장 파라미터와 기본값."""
import pytest
from fastapi.testclient import TestClient

from app import market, market_fetch, market_kr, market_us
from app.main import create_app
from app.sources import naver


@pytest.fixture(autouse=True)
def fresh_cache():
    market.reset_cache()
    yield
    market.reset_cache()


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "t.db"), refresh_on_start=False)
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def stub_sources(monkeypatch):
    monkeypatch.setattr(market_fetch, "intraday", lambda sym: {
        "last": 100.0, "prev_close": 100.0, "candles": []})
    monkeypatch.setattr(market_fetch, "daily_closes", lambda syms: {})
    monkeypatch.setattr(market_fetch, "screen", lambda name, count=10: [])
    monkeypatch.setattr(market_fetch, "news", lambda sym, limit=8: [])
    monkeypatch.setattr(naver, "index_basic", lambda code: {
        "last": 6912.95, "prev_close": 6852.58, "change": 60.37,
        "change_pct": 0.88, "traded_at": None})
    monkeypatch.setattr(naver, "ranking", lambda kind, mkt, n: [])
    monkeypatch.setattr(naver, "market_index", lambda cat, code: {
        "last": 1388.0, "prev_close": 1394.8, "change": -6.8,
        "change_pct": -0.49, "traded_at": None})
    monkeypatch.setattr(naver, "investor_trend", lambda m: {
        "date": "2026-08-21", "personal": 1.0, "foreign": 2.0, "institution": 3.0})


def test_default_market_is_kr(client):
    body = client.get("/api/market").json()
    assert body["market"] == "KR"
    assert body["indices"][0]["symbol"] == "^KS11"
    assert body["session"]["tz"] == "Asia/Seoul"
    assert len(body["investors"]) == 2


def test_us_market_still_works(client):
    body = client.get("/api/market?market=US").json()
    assert body["market"] == "US"
    assert body["indices"][0]["symbol"] == "^GSPC"
    assert body["investors"] == []       # US 는 수급 블록이 없다
    assert body["session"]["tz"] == "America/New_York"


def test_unknown_market_is_400(client):
    r = client.get("/api/market?market=JP")
    assert r.status_code == 400
    assert "market" in r.json()["detail"]


def test_refresh_takes_market(client):
    r = client.post("/api/market/refresh?market=US")
    assert r.status_code == 200 and r.json()["market"] == "US"
    r2 = client.post("/api/market/refresh")
    assert r2.json()["market"] == "KR"
    r3 = client.post("/api/market/refresh?market=JP")
    assert r3.status_code == 400


def test_getting_kr_does_not_fetch_us(client, monkeypatch):
    """KR 만 보는 사용자에게 US 외부 호출이 일어나면 첫 응답이 그만큼 느려진다."""
    calls = {"n": 0}
    orig = market_us.BUILDERS["indices"]
    monkeypatch.setitem(market_us.BUILDERS, "indices",
                        lambda: (calls.__setitem__("n", calls["n"] + 1), orig())[1])
    client.get("/api/market")
    assert calls["n"] == 0
    client.get("/api/market?market=US")
    assert calls["n"] == 1
