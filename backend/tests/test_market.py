"""market.py — 조립·캐시·실패 격리. market_fetch 만 monkeypatch 해서 네트워크 없이 돈다."""
import pytest

from app import market, market_fetch


@pytest.fixture(autouse=True)
def fresh_cache():
    market.reset_cache()
    yield
    market.reset_cache()


def _ok_fetch(monkeypatch):
    monkeypatch.setattr(market_fetch, "intraday", lambda sym: {
        "last": 110.0, "prev_close": 100.0,
        "candles": [{"o": 100, "h": 112, "l": 99, "c": 110, "v": 1000}]})
    monkeypatch.setattr(market_fetch, "daily_closes", lambda syms: {
        s: {"last": 50.0 + i, "prev_close": 50.0} for i, s in enumerate(syms)})
    monkeypatch.setattr(market_fetch, "screen", lambda name, count=10: [
        {"symbol": f"{name[:3].upper()}{i}", "last": 1.0, "change_pct": 5.0 - i, "volume": 1e6}
        for i in range(count + 2)])
    monkeypatch.setattr(market_fetch, "news", lambda sym, limit=8: [
        {"title": "headline", "source": "X", "url": "u", "published_at": "2026-08-21T00:00:00Z"}])


def test_get_market_shape(monkeypatch):
    _ok_fetch(monkeypatch)
    m = market.get_market(now=1000.0)
    assert [i["name"] for i in m["indices"]] == ["S&P 500", "NASDAQ", "DOW"]
    assert m["indices"][0]["change_pct"] == 10.0 and m["indices"][0]["change"] == 10.0
    assert len(m["futures"]) == 7 and len(m["forex_bonds"]) == 7
    assert m["futures"][0]["decimals"] == 2 and m["futures"][0]["change_pct"] == 0.0
    # 스크리너는 요청 개수만큼만 자르고 라벨을 붙인다
    assert m["signals_up"][0]["signal"] == "Top Gainers"
    assert sum(r["signal"] == "Top Gainers" for r in m["signals_up"]) == 6
    assert m["heatmap"][0]["name"] == "TECHNOLOGY"
    assert {"symbol", "weight", "change_pct"} <= set(m["heatmap"][0]["tickers"][0])
    # major_news 는 히트맵에서 |등락| 큰 순 16개
    assert len(m["major_news"]) == 16
    pcts = [abs(r["change_pct"]) for r in m["major_news"]]
    assert pcts == sorted(pcts, reverse=True)
    assert m["headlines"][0]["title"] == "headline"
    assert m["failed"] == [] and m["fetched_at"]


def test_block_failure_is_isolated(monkeypatch):
    _ok_fetch(monkeypatch)
    def boom(*a, **k):
        raise RuntimeError("yahoo down")
    monkeypatch.setattr(market_fetch, "screen", boom)
    m = market.get_market(now=1000.0)
    assert m["failed"] == ["signals_down", "signals_up"]
    assert m["signals_up"] == [] and m["indices"]          # 다른 블록은 멀쩡


def test_failure_keeps_previous_value_and_backs_off(monkeypatch):
    _ok_fetch(monkeypatch)
    market.refresh(now=1000.0)
    calls = {"n": 0}
    def boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("down")
    monkeypatch.setattr(market_fetch, "intraday", boom)
    # TTL 이 지나 재시도 → 실패 → 이전 값 유지 + failed 표기
    market.refresh(now=1000.0 + market.TTL_SEC["indices"] + 1)
    m = market.get_market(now=1000.0 + market.TTL_SEC["indices"] + 2)
    assert "indices" in m["failed"] and m["indices"][0]["last"] == 110.0
    # 백오프 안에서는 다시 때리지 않는다
    n = calls["n"]
    market.refresh(now=1000.0 + market.TTL_SEC["indices"] + 10)
    assert calls["n"] == n


def test_ttl_skips_fresh_blocks(monkeypatch):
    _ok_fetch(monkeypatch)
    calls = {"n": 0}
    orig = market_fetch.news
    def counting(*a, **k):
        calls["n"] += 1
        return orig(*a, **k)
    monkeypatch.setattr(market_fetch, "news", counting)
    market.refresh(now=1000.0)
    market.refresh(now=1000.0 + 60)
    assert calls["n"] == 1
    market.refresh(now=1000.0 + market.TTL_SEC["headlines"] + 1)
    assert calls["n"] == 2


def test_pct_handles_missing():
    assert market._pct(None, 100) is None
    assert market._pct(100, None) is None
    assert market._pct(100, 0) is None
    assert market._pct(101, 100) == 1.0


def test_api_market_endpoint(monkeypatch, tmp_path):
    _ok_fetch(monkeypatch)
    from fastapi.testclient import TestClient
    from app.main import create_app
    app = create_app(db_path=str(tmp_path / "t.db"), refresh_on_start=False)
    with TestClient(app) as c:
        r = c.get("/api/market")
        assert r.status_code == 200
        body = r.json()
        assert body["indices"][0]["symbol"] == "^GSPC"
        r2 = c.post("/api/market/refresh")
        assert r2.status_code == 200 and r2.json()["failed"] == []
