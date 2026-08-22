"""market.py — 조립·캐시·실패 격리. market_fetch 만 monkeypatch 해서 네트워크 없이 돈다."""
import pytest

from app import market, market_fetch, market_us


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
    m = market.get_market("US", now=1000.0)
    assert m["market"] == "US"
    assert m["session"]["tz"] == "America/New_York"
    assert m["investors"] == []
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
    m = market.get_market("US", now=1000.0)
    assert m["failed"] == ["signals_down", "signals_up"]
    assert m["signals_up"] == [] and m["indices"]          # 다른 블록은 멀쩡


def test_failure_keeps_previous_value_and_backs_off(monkeypatch):
    _ok_fetch(monkeypatch)
    market.refresh("US", now=1000.0)
    calls = {"n": 0}
    def boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("down")
    monkeypatch.setattr(market_fetch, "intraday", boom)
    # TTL 이 지나 재시도 → 실패 → 이전 값 유지 + failed 표기
    market.refresh("US", now=1000.0 + market_us.TTL_SEC["indices"] + 1)
    m = market.get_market("US", now=1000.0 + market_us.TTL_SEC["indices"] + 2)
    assert "indices" in m["failed"] and m["indices"][0]["last"] == 110.0
    # 백오프 안에서는 다시 때리지 않는다
    n = calls["n"]
    market.refresh("US", now=1000.0 + market_us.TTL_SEC["indices"] + 10)
    assert calls["n"] == n


def test_ttl_skips_fresh_blocks(monkeypatch):
    _ok_fetch(monkeypatch)
    calls = {"n": 0}
    orig = market_fetch.news
    def counting(*a, **k):
        calls["n"] += 1
        return orig(*a, **k)
    monkeypatch.setattr(market_fetch, "news", counting)
    market.refresh("US", now=1000.0)
    market.refresh("US", now=1000.0 + 60)
    assert calls["n"] == 1
    market.refresh("US", now=1000.0 + market_us.TTL_SEC["headlines"] + 1)
    assert calls["n"] == 2


def test_cold_cache_ignores_ttl(monkeypatch):
    """콜드 캐시 첫 방문은 TTL 을 안 본다 — `_is_stale` 은 "한 번도 안 받았다"를
    `now - 0 > ttl` 로 판단해서, 시계가 TTL 보다 작으면 그 블록만 빈 채로 남았었다."""
    _ok_fetch(monkeypatch)
    # 주입된 now(1000.0) 보다 훨씬 큰 TTL 을 줘서 예전 버그(=이 블록만 안 채워짐)를 재현한다
    monkeypatch.setitem(market_us.TTL_SEC, "indices", 10**9)
    m = market.get_market("US", now=1000.0)
    assert m["indices"] and m["indices"][0]["last"] == 110.0


def test_cold_cache_backoff_skips_retry(monkeypatch):
    """전 블록이 실패해 캐시가 비면 매 요청이 콜드 캐시 분기로 다시 들어온다 —
    그렇다고 백오프까지 무시하고 재시도하면 블록 수 × 타임아웃만큼 느려진다."""
    calls = {"n": 0}
    def boom(*a, **k):
        calls["n"] += 1
        raise RuntimeError("down")
    monkeypatch.setattr(market_fetch, "intraday", boom)
    monkeypatch.setattr(market_fetch, "daily_closes", boom)
    monkeypatch.setattr(market_fetch, "screen", boom)
    monkeypatch.setattr(market_fetch, "news", boom)
    market.get_market("US", now=1000.0)          # 전 블록 실패 → cache.values 는 여전히 빈 채
    n = calls["n"]
    assert n > 0
    market.get_market("US", now=1000.0 + 1)      # 백오프(3분) 안 — 재시도하면 안 된다
    assert calls["n"] == n


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
        r = c.get("/api/market?market=US")
        assert r.status_code == 200
        body = r.json()
        assert body["indices"][0]["symbol"] == "^GSPC"
        r2 = c.post("/api/market/refresh?market=US")
        assert r2.status_code == 200 and r2.json()["failed"] == []


def test_cache_key_is_market_scoped(monkeypatch):
    """캐시 키가 시장별로 나뉜다 — 안 보는 시장에 외부 호출을 하지 않는다."""
    _ok_fetch(monkeypatch)
    calls = {"n": 0}
    orig = market_us.BUILDERS["indices"]
    def counting():
        calls["n"] += 1
        return orig()
    monkeypatch.setitem(market_us.BUILDERS, "indices", counting)
    market.refresh("US", now=1000.0)
    assert calls["n"] == 1
    # 같은 블록 이름이라도 시장이 다르면 캐시가 따로다
    assert "US:indices" in market._cache.values
