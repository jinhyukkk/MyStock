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

def test_realized_round_trip_is_net_of_costs(client):
    """원장 전 구간 — 실제 비용을 입력하면 그 값이, 비우면 추정값이 손익에서 빠진다."""
    client.post("/api/watchlist", json={"symbol": "005930", "name": "삼성전자",
                                        "market": "KR", "is_etf": 0,
                                        "yf_symbol": "005930.KS", "currency": "KRW"})
    client.post("/api/refresh")
    client.post("/api/trades", json={"symbol": "005930", "side": "BUY", "quantity": 10,
                                     "price": 70000, "trade_date": "2026-01-05",
                                     "fee": 100, "tax": 0})
    client.post("/api/trades", json={"symbol": "005930", "side": "SELL", "quantity": 10,
                                     "price": 80000, "trade_date": "2026-02-05",
                                     "fee": 120, "tax": 1200})
    pf = client.get("/api/portfolio").json()
    r = pf["realized"]["entries"][0]
    assert r["buy_price"] == 70010.0                 # 매수 수수료가 평단에 가산
    assert r["cost"] == 1320.0 and r["cost_estimated"] is False
    assert r["pnl"] == r["pnl_gross"] - 1320.0
    assert r["pnl_krw"] == r["pnl"]                  # KRW 종목은 환 손익 없음
    assert r["fx_pnl_krw"] == 0.0
    stats = pf["realized"]["stats"]
    assert stats["cost_krw"] == 1320.0 and stats["cost_estimated"] is False


def test_realized_estimates_costs_when_omitted(client):
    client.post("/api/watchlist", json={"symbol": "005930", "name": "삼성전자",
                                        "market": "KR", "is_etf": 0,
                                        "yf_symbol": "005930.KS", "currency": "KRW"})
    client.post("/api/refresh")
    for side, price in (("BUY", 70000), ("SELL", 80000)):
        client.post("/api/trades", json={"symbol": "005930", "side": side, "quantity": 10,
                                         "price": price, "trade_date": "2026-01-05"})
    stats = client.get("/api/portfolio").json()["realized"]["stats"]
    assert stats["cost_estimated"] is True and stats["cost_krw"] > 0


def _watch_samsung(client):
    client.post("/api/watchlist", json={"symbol": "005930", "name": "삼성전자",
                                        "market": "KR", "is_etf": 0,
                                        "yf_symbol": "005930.KS", "currency": "KRW"})
    client.post("/api/refresh")


def test_oversell_is_rejected(client):
    """ML-14: 통과시키면 수량이 음수가 되며 보유 종목이 조용히 사라진다."""
    _watch_samsung(client)
    client.post("/api/trades", json={"symbol": "005930", "side": "BUY", "quantity": 10,
                                     "price": 70000, "trade_date": "2026-01-05"})
    r = client.post("/api/trades", json={"symbol": "005930", "side": "SELL", "quantity": 11,
                                         "price": 80000, "trade_date": "2026-01-06"})
    assert r.status_code == 400 and "보유 수량" in r.json()["detail"]
    pf = client.get("/api/portfolio").json()
    assert pf["holdings"][0]["quantity"] == 10  # 원장이 그대로 남는다


def test_exact_sell_is_allowed(client):
    _watch_samsung(client)
    client.post("/api/trades", json={"symbol": "005930", "side": "BUY", "quantity": 10,
                                     "price": 70000, "trade_date": "2026-01-05"})
    r = client.post("/api/trades", json={"symbol": "005930", "side": "SELL", "quantity": 10,
                                         "price": 80000, "trade_date": "2026-01-06"})
    assert r.status_code == 200
    assert client.get("/api/portfolio").json()["holdings"] == []


def test_cash_follows_trades(client):
    """예수금이 매매와 연동돼야 총자산이, 나아가 1% 리스크 사이징이 맞는다."""
    _watch_samsung(client)
    client.put("/api/cash", json={"amount": 10_000_000})
    client.post("/api/trades", json={"symbol": "005930", "side": "BUY", "quantity": 10,
                                     "price": 70000, "trade_date": "2026-01-05",
                                     "fee": 105, "tax": 0})
    after_buy = client.get("/api/portfolio").json()["totals"]["cash_krw"]
    assert after_buy == 10_000_000 - (700_000 + 105)
    client.post("/api/trades", json={"symbol": "005930", "side": "SELL", "quantity": 10,
                                     "price": 80000, "trade_date": "2026-01-06",
                                     "fee": 120, "tax": 1200})
    after_sell = client.get("/api/portfolio").json()["totals"]["cash_krw"]
    assert after_sell == after_buy + (800_000 - 120 - 1200)


def test_deleting_trade_reverses_cash(client):
    _watch_samsung(client)
    client.put("/api/cash", json={"amount": 10_000_000})
    tid = client.post("/api/trades", json={"symbol": "005930", "side": "BUY", "quantity": 10,
                                           "price": 70000, "trade_date": "2026-01-05",
                                           "fee": 0, "tax": 0}).json()["id"]
    assert client.get("/api/portfolio").json()["totals"]["cash_krw"] == 9_300_000
    client.delete(f"/api/trades/{tid}")
    assert client.get("/api/portfolio").json()["totals"]["cash_krw"] == 10_000_000


def test_correction_lot_is_flagged_and_left_out_of_stats(client):
    """평단 맞춤용 보정 로트는 평단에는 반영되지만 승률·실현손익 집계에는 빠져야 한다.
    가짜 체결가가 통계에 섞이면 복기가 통째로 거짓이 된다."""
    _watch_samsung(client)
    client.post("/api/trades", json={"symbol": "005930", "side": "BUY", "quantity": 10,
                                     "price": 70000, "trade_date": "2026-01-05",
                                     "fee": 0, "tax": 0, "exclude_from_stats": True,
                                     "note": "시트 평단 맞춤 보정 로트"})
    client.post("/api/trades", json={"symbol": "005930", "side": "SELL", "quantity": 10,
                                     "price": 80000, "trade_date": "2026-02-05",
                                     "fee": 0, "tax": 0})
    pf = client.get("/api/portfolio").json()
    assert pf["realized"]["entries"][0]["basis_adjusted"] is True
    stats = pf["realized"]["stats"]
    assert stats["count"] == 0 and stats["excluded_count"] == 1
    # 원장 자체에는 남아 있어야 화면에서 배지를 달 수 있다
    assert client.get("/api/trades").json()[0]["exclude_from_stats"] == 1


def test_trade_response_reports_cash_clamp(client):
    """예수금보다 큰 매수는 예수금을 0으로 자른다 — 그 사실이 응답에 실려야
    화면이 '총자산이 실제보다 작아졌다'를 사용자에게 알릴 수 있다."""
    _watch_samsung(client)
    client.put("/api/cash", json={"amount": 100_000})
    res = client.post("/api/trades", json={"symbol": "005930", "side": "BUY", "quantity": 10,
                                           "price": 70000, "trade_date": "2026-01-05",
                                           "fee": 0, "tax": 0}).json()
    assert res["cash"]["clamped"] is True
    assert res["cash"]["cash_krw"] == 0.0
    assert res["cash"]["applied"] == -100_000.0   # 실제로 빠진 금액
    assert res["cash"]["delta"] == -700_000.0     # 빠졌어야 할 금액


def test_usd_trade_moves_usd_cash_only(client):
    client.post("/api/watchlist", json={"symbol": "AAPL", "name": "Apple", "market": "US",
                                        "is_etf": 0, "yf_symbol": "AAPL", "currency": "USD"})
    client.post("/api/refresh")
    client.put("/api/cash", json={"amount": 5_000_000, "amount_usd": 10_000})
    client.post("/api/trades", json={"symbol": "AAPL", "side": "BUY", "quantity": 10,
                                     "price": 200, "trade_date": "2026-01-05",
                                     "fee": 0, "tax": 0})
    t = client.get("/api/portfolio").json()["totals"]
    assert t["cash_usd"] == 8_000 and t["cash_krw"] == 5_000_000


def test_same_day_trades_replay_in_execution_order(client):
    """ML-14: 같은 날 매도 후 재매수 — 순서가 뒤바뀌면 평단이 잘못 만들어진다."""
    _watch_samsung(client)
    for side, qty, price, at in (("BUY", 10, 70000, "09:10"),
                                 ("SELL", 10, 80000, "10:30"),
                                 ("BUY", 5, 75000, "14:00")):
        r = client.post("/api/trades", json={"symbol": "005930", "side": side,
                                             "quantity": qty, "price": price,
                                             "trade_date": "2026-01-05",
                                             "executed_at": at, "fee": 0, "tax": 0})
        assert r.status_code == 200
    pf = client.get("/api/portfolio").json()
    assert pf["holdings"][0]["quantity"] == 5
    assert pf["holdings"][0]["avg_price"] == 75000  # 재매수분만 남는다
    assert pf["realized"]["stats"]["count"] == 1


def test_rules_crud(client):
    client.post("/api/watchlist", json={"symbol": "005930", "name": "삼성전자",
                                        "market": "KR", "is_etf": 0,
                                        "yf_symbol": "005930.KS", "currency": "KRW"})
    rid = client.post("/api/rules", json={"symbol": "005930", "rule_type": "TARGET",
                                          "value": 90000}).json()["id"]
    assert len(client.get("/api/rules").json()) == 1
    assert client.delete(f"/api/rules/{rid}").status_code == 200

def test_ticker_detail_unknown_symbol_reports_failed(client):
    # 404가 아니라 status로 알린다 — 심볼 해석이 네트워크를 타므로 첫 응답 시점에는
    # 그 종목이 없는 건지 아직 수집 전인지 구분할 수 없다.
    assert client.get("/api/tickers/NOPE").json()["status"] == "pending"
    assert client.get("/api/tickers/NOPE").json()["status"] == "failed"

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


def test_index_html_must_revalidate(client):
    """index.html이 캐시되면 배포 후에도 사용자가 옛 프론트를 계속 쓴다.
    해시 붙은 청크는 그대로여도 진입점이 옛 청크를 가리키기 때문이다."""
    res = client.get("/")
    assert "no-cache" in res.headers.get("cache-control", "")


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
    # 평단은 매수 수수료를 포함한 비용 기준 — 체결가보다 근소하게 높다
    assert 70000.0 < held["avg_price"] < 70000.0 * 1.001
    expected = round((held["close"] / held["avg_price"] - 1) * 100, 2)
    assert held["holding_pnl_pct"] == expected
    assert watched["avg_price"] is None and watched["holding_pnl_pct"] is None


# ── 배당 원장 ────────────────────────────────────────────────────────────
def _watch(client, symbol="005930", name="삼성전자", market="KR", currency="KRW"):
    client.post("/api/watchlist", json={"symbol": symbol, "name": name, "market": market,
                                        "is_etf": 0, "yf_symbol": symbol,
                                        "currency": currency})


def test_dividend_credits_cash_net_of_withholding(client):
    """배당을 원장에만 적고 예수금에 넣지 않으면 총자산이 실제보다 작아지고,
    그 총자산을 분모로 쓰는 1% 리스크 사이징이 계속 작은 수량을 제시한다."""
    _watch(client)
    client.put("/api/cash", json={"amount": 1_000_000})
    res = client.post("/api/cash-flows", json={
        "flow_type": "DIVIDEND", "symbol": "005930", "amount": 10000,
        "tax": 1540, "flow_date": "2026-03-15"})
    assert res.status_code == 200
    assert res.json()["cash"]["cash_krw"] == 1_008_460


def test_deleting_a_dividend_reverses_the_cash(client):
    _watch(client)
    client.put("/api/cash", json={"amount": 1_000_000})
    fid = client.post("/api/cash-flows", json={
        "flow_type": "DIVIDEND", "symbol": "005930", "amount": 10000,
        "tax": 1540, "flow_date": "2026-03-15"}).json()["id"]
    client.delete(f"/api/cash-flows/{fid}")
    assert client.get("/api/portfolio").json()["totals"]["cash_krw"] == 1_000_000


def test_assigning_symbol_to_imported_dividend(client):
    """증권사 배당은 적요에 종목이 없어 미지정으로 들어온다 — 나중에 붙일 수 있어야
    종목별 배당수익률에 잡힌다. 금액·통화는 입금 시점 사실이라 바뀌면 안 된다."""
    _watch(client)
    client.put("/api/cash", json={"amount": 1_000_000})
    fid = client.post("/api/cash-flows", json={
        "flow_type": "DEPOSIT", "amount": 5000, "flow_date": "2026-03-15"}).json()["id"]
    cash_before = client.get("/api/portfolio").json()["totals"]["cash_krw"]

    assert client.patch(f"/api/cash-flows/{fid}", json={"symbol": "005930"}).status_code == 200
    row = next(r for r in client.get("/api/cash-flows").json() if r["id"] == fid)
    assert row["symbol"] == "005930"
    assert row["amount"] == 5000 and row["currency"] == "KRW"
    # 귀속만 바뀐 것이므로 예수금은 그대로여야 한다 (두 번 계상 방지)
    assert client.get("/api/portfolio").json()["totals"]["cash_krw"] == cash_before

    # 되돌리기·검증
    assert client.patch(f"/api/cash-flows/{fid}", json={"symbol": ""}).json()["symbol"] is None
    assert client.patch(f"/api/cash-flows/{fid}", json={"symbol": "NOPE"}).status_code == 400
    assert client.patch("/api/cash-flows/99999", json={"symbol": "005930"}).status_code == 404


def test_withdrawal_reduces_cash(client):
    client.put("/api/cash", json={"amount": 1_000_000})
    res = client.post("/api/cash-flows", json={
        "flow_type": "WITHDRAW", "amount": 300_000, "flow_date": "2026-03-15"})
    assert res.json()["cash"]["cash_krw"] == 700_000


def test_dividend_requires_a_symbol(client):
    res = client.post("/api/cash-flows", json={
        "flow_type": "DIVIDEND", "amount": 10000, "flow_date": "2026-03-15"})
    assert res.status_code == 400


def test_withholding_cannot_exceed_gross(client):
    _watch(client)
    res = client.post("/api/cash-flows", json={
        "flow_type": "DIVIDEND", "symbol": "005930", "amount": 1000,
        "tax": 2000, "flow_date": "2026-03-15"})
    assert res.status_code == 400


def test_dividend_currency_follows_the_ticker(client):
    """폼에서 통화를 잘못 고르면 배당 $100이 원화 100원이 된다 —
    통화는 사용자 선택이 아니라 종목이 정한다."""
    _watch(client, "AAPL", "Apple", "US", "USD")
    client.post("/api/refresh")  # 환율 수집 후여야 입금 시점 환율이 고정된다
    client.post("/api/cash-flows", json={
        "flow_type": "DIVIDEND", "symbol": "AAPL", "amount": 100, "currency": "KRW",
        "flow_date": "2026-03-15"})
    row = client.get("/api/cash-flows").json()[0]
    assert row["currency"] == "USD" and row["fx_rate"] == 1300.0


def test_portfolio_reports_dividends_and_total_return(client):
    _watch(client)
    client.post("/api/refresh")
    client.post("/api/trades", json={"symbol": "005930", "side": "BUY",
                                     "quantity": 10, "price": 100.0,
                                     "trade_date": "2025-01-02"})
    client.post("/api/cash-flows", json={
        "flow_type": "DIVIDEND", "symbol": "005930", "amount": 1000,
        "tax": 154, "flow_date": "2026-03-15"})
    pf = client.get("/api/portfolio").json()
    assert pf["dividends"]["total_net_krw"] == 846
    assert pf["dividends"]["by_symbol"][0]["symbol"] == "005930"
    row = next(h for h in pf["holdings"] if h["symbol"] == "005930")
    assert row["dividend_krw"] == 846
    assert row["total_return_krw"] == row["pnl_krw"] + 846

def test_position_rule_target_is_settable(client):
    assert client.get("/api/dashboard").json()["position_rule"]["max"] == 7
    res = client.put("/api/position-rule", json={"min": 3, "max": 6})
    assert res.status_code == 200 and res.json() == {"min": 3, "max": 6}
    assert client.get("/api/dashboard").json()["position_rule"]["min"] == 3

def test_position_rule_rejects_inverted_range(client):
    """min > max면 어떤 개수든 위반이 된다 — 늘 빨간 화면은 곧 무시되는 화면이다."""
    assert client.put("/api/position-rule", json={"min": 8, "max": 3}).status_code == 422
    assert client.put("/api/position-rule", json={"min": 0, "max": 3}).status_code == 422

def test_position_rule_is_readable_without_the_dashboard(client):
    """설정 화면이 현재 목표를 프리필하려고 대시보드 전체를 다시 계산할 이유는 없다."""
    assert client.get("/api/position-rule").json() == {"min": 4, "max": 7}
    client.put("/api/position-rule", json={"min": 2, "max": 5})
    assert client.get("/api/position-rule").json() == {"min": 2, "max": 5}


# --- 종목상세 회사 자료 (tickerdetail) ------------------------------------------

DETAIL_KEYS = ["fundamentals", "signal", "candles", "risk", "cost_rates", "cash",
               "dividends", "history", "rules", "entry_review", "last_refresh"]


def _add_and_refresh(client):
    client.post("/api/watchlist", json={"symbol": "005930", "name": "삼성전자",
                                        "market": "KR", "is_etf": 0,
                                        "yf_symbol": "005930.KS", "currency": "KRW"})
    client.post("/api/refresh")


def test_detail_keeps_existing_keys_and_adds_company(client):
    """AC-1/AC-2 — 기존 11개 키는 하나도 사라지지 않고 profile·snapshot만 추가된다.
    빌드본이 구버전일 수 있으므로 필드 제거·개명은 곧 화면 파손이다."""
    _add_and_refresh(client)
    d = client.get("/api/tickers/005930").json()
    for key in DETAIL_KEYS:
        assert key in d, key
    assert "profile" in d and "snapshot" in d
    # 계약 v2 B1 — 캐시가 없어도 profile은 null이 아니라 pending 골격 + 안내 문구다.
    # null이면 화면이 문구를 스스로 지어내고, 그 문구가 BE의 4블록 문구와 갈라진다.
    assert d["profile"]["status"] == "pending"
    assert d["profile"]["note"]
    assert set(d["snapshot"]["perf"]) == {"w1", "m1", "m3", "m6", "ytd",
                                          "y1", "y3", "y5", "y10"}
    assert d["snapshot"]["recommendation_scale"] == "1=strong_buy..5=strong_sell"


def test_company_endpoint_returns_200_when_empty(client):
    """캐시가 비어도 200 + 전 블록 pending. 404를 주면 화면이 '없는 종목'과 못 가른다."""
    _add_and_refresh(client)
    res = client.get("/api/tickers/005930/company")
    assert res.status_code == 200
    body = res.json()
    assert body["symbol"] == "005930"
    for block in ("financials", "news", "ratings", "insiders"):
        assert body[block]["status"] in ("ok", "pending", "unavailable")
    assert client.get("/api/tickers/NOPE/company").status_code == 404


def test_detail_never_calls_network(client):
    """AC-13 — `app.sources` 전 모듈이 AssertionError를 던지는 상태(conftest 기본)에서도
    종목상세·회사 자료 요청은 200이어야 한다. 요청 경로에 외부 호출이 남아 있으면 여기서
    깨진다 — 실제로는 화면이 yfinance 응답을 3초 기다리는 상태다."""
    import app.sources.daum, app.sources.naver, app.sources.yf
    with pytest.raises(AssertionError):
        app.sources.yf.quote_info("AAPL")
    with pytest.raises(AssertionError):
        app.sources.naver.integration("005930")
    with pytest.raises(AssertionError):
        app.sources.daum.quote("005930")
    _add_and_refresh(client)
    assert client.get("/api/tickers/005930").status_code == 200
    assert client.get("/api/tickers/005930/company").status_code == 200


def test_strategy_presets_lists_both_strategies(client):
    """화면이 파라미터 입력칸을 그리려면 각 전략의 파라미터 메타가 필요하다."""
    r = client.get("/api/strategy/presets")
    assert r.status_code == 200
    body = r.json()
    assert {p["key"] for p in body} == {"abs_momentum", "donchian", "xs_momentum"}
    mom = next(p for p in body if p["key"] == "abs_momentum")
    assert mom["label"] == "절대 모멘텀"
    assert mom["params"]["lookback"]["default"] == 252


def test_strategy_backtest_returns_curve_and_metrics(client):
    """종목·가격을 실제로 심고 돌린다 — 빈 DB로는 엔진을 들어내도 통과한다.

    빈 유니버스에서는 curve가 []라 키 존재만 보는 단언이 전부 통과하면서
    "curve and metrics"라는 이름이 검증하는 게 아무것도 없어진다.
    세 곡선이 같은 달력 위에 서는지(발견 3·4)까지 여기서 함께 막는다.
    """
    _add_and_refresh(client)
    r = client.post("/api/strategy/backtest",
                    json={"preset": "abs_momentum",
                          "params": {"lookback": 60, "skip": 5, "trend_ma": 30},
                          "initial_capital_krw": 10_000_000})
    assert r.status_code == 200
    body = r.json()
    assert set(body["metrics"]) >= {"cagr", "mdd", "sharpe", "win_rate",
                                    "trade_count", "final_equity_krw",
                                    "excess_vs_bench", "bench_cagr"}
    assert body["universe_size"] == 1
    assert len(body["equity_curve"]) > 0
    # 비교선은 전략과 같은 달력 위에 서야 한다 — 길이가 갈라지면 차트가
    # 에러 없이 조용히 날짜를 어긋나게 그린다
    assert len(body["buy_and_hold"]) == len(body["equity_curve"])
    assert len(body["benchmark"]) == len(body["equity_curve"])
    assert body["metrics"]["final_equity_krw"] is not None
    assert body["metrics"]["excess_vs_bench"] == pytest.approx(
        body["metrics"]["cagr"] - body["metrics"]["bench_cagr"], abs=0.01)
    # 유니버스 편향 경고는 화면이 문구를 지어내지 않도록 서버가 내려준다
    assert body["universe_warning"]
    assert body["fx_note"]


def test_strategy_backtest_empty_universe_has_no_final_equity(client):
    """종목이 하나도 없으면 최종자본은 0원이 아니라 '없음'이다.

    0을 내려보내면 지표 카드가 초기자본을 전액 잃은 것처럼 표시한다.
    """
    body = client.post("/api/strategy/backtest",
                       json={"preset": "abs_momentum"}).json()
    assert body["equity_curve"] == []
    assert body["metrics"]["final_equity_krw"] is None
    assert body["metrics"]["cagr"] is None
    assert body["metrics"]["excess_vs_bench"] is None


def test_strategy_backtest_rejects_unknown_preset(client):
    """알 수 없는 전략은 500이 아니라 400이어야 화면에 원인이 남는다."""
    r = client.post("/api/strategy/backtest", json={"preset": "없는전략"})
    assert r.status_code == 400


def test_strategy_backtest_fills_missing_params_with_defaults(client):
    """화면이 일부 파라미터만 보내도 나머지는 기본값으로 채운다."""
    r = client.post("/api/strategy/backtest",
                    json={"preset": "donchian", "params": {"entry_n": 20}})
    assert r.status_code == 200
    assert r.json()["params"] == {"entry_n": 20, "exit_n": 20}


def test_strategy_optimize_returns_ranked_results(client):
    """종목을 심고 최적화를 돌리면 학습/검증 지표가 함께 내려온다."""
    _add_and_refresh(client)
    r = client.post("/api/strategy/optimize", json={"preset": "donchian"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"split_date", "train_days", "valid_days",
                         "results", "universe_warning", "note"}
    if body["results"]:  # 시드 데이터가 120일 미만이면 빈 결과도 정상
        first = body["results"][0]
        assert set(first) == {"params", "train", "valid"}


def test_strategy_optimize_rejects_unknown_preset(client):
    r = client.post("/api/strategy/optimize", json={"preset": "없는전략"})
    assert r.status_code == 400


def test_autotrade_status_without_keys(client, monkeypatch):
    """KIS 키가 없어도 상태 화면은 떠야 한다 — 설정 안내를 보여줄 곳이 이 화면이다."""
    for k in ("KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT", "KIS_MODE"):
        monkeypatch.delenv(k, raising=False)
    r = client.get("/api/autotrade/status")
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert body["mode"] == "paper"  # KIS_MODE 미설정 기본값은 모의투자다
    assert body["settings"]["preset"] in ("abs_momentum", "donchian")
    assert body["positions"] == [] and body["orders"] == []


def test_autotrade_plan_without_keys_is_400(client, monkeypatch):
    for k in ("KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT", "KIS_MODE"):
        monkeypatch.delenv(k, raising=False)
    r = client.post("/api/autotrade/plan")
    assert r.status_code == 400
    assert "KIS" in r.json()["detail"]


def test_autotrade_execute_requires_confirm(client):
    """confirm 없는 실행은 무조건 400 — 실수 클릭 한 번이 실제 주문이 되면 안 된다."""
    assert client.post("/api/autotrade/execute", json={}).status_code == 400


def test_autotrade_settings_roundtrip(client):
    r = client.put("/api/autotrade/settings",
                   json={"preset": "donchian", "params": {"entry_n": 40}})
    assert r.status_code == 200
    s = client.get("/api/autotrade/status").json()["settings"]
    assert s["preset"] == "donchian" and s["params"]["entry_n"] == 40
    assert client.put("/api/autotrade/settings",
                      json={"preset": "없는전략"}).status_code == 400


def test_autotrade_settings_carry_the_regime_filter(client):
    """레짐 필터는 화면에서 끌 수 있어야 하고, 안 보내면 ON이 기본이다."""
    client.put("/api/autotrade/settings",
               json={"preset": "donchian", "regime_filter": False})
    s = client.get("/api/autotrade/status").json()["settings"]
    assert s["regime_filter"] is False
    client.put("/api/autotrade/settings", json={"preset": "donchian"})
    s = client.get("/api/autotrade/status").json()["settings"]
    assert s["regime_filter"] is True


# ── 워크포워드 · 유니버스 API ─────────────────────────────────────────────────

def _poll_job(client, url, tries=200):
    import time
    for _ in range(tries):
        st = client.get(url).json()
        if st["status"] != "running":
            return st
        time.sleep(0.02)
    raise AssertionError("잡이 끝나지 않습니다")


def test_walkforward_rejects_unknown_preset(client):
    r = client.post("/api/strategy/walkforward", json={"preset": "없는전략"})
    assert r.status_code == 400


def test_walkforward_unknown_job_404(client):
    assert client.get("/api/strategy/walkforward/없는잡").status_code == 404


def test_walkforward_empty_universe_completes(client):
    """종목이 없어도 잡은 error가 아니라 빈 결과로 끝나야 한다 —
    watchlist가 비어 있는 신규 설치에서 500이 나면 안 된다."""
    r = client.post("/api/strategy/walkforward",
                    json={"preset": "donchian", "universe": "watchlist"})
    assert r.status_code == 200
    st = _poll_job(client, f"/api/strategy/walkforward/{r.json()['job_id']}")
    assert st["status"] == "done"
    assert st["result"]["folds"] == []


def test_walkforward_krx300_without_collection_errors(client):
    """수집 전 krx300 요청은 안내 메시지가 담긴 error로 끝난다."""
    r = client.post("/api/strategy/walkforward",
                    json={"preset": "donchian", "universe": "krx300"})
    st = _poll_job(client, f"/api/strategy/walkforward/{r.json()['job_id']}")
    assert st["status"] == "error"
    assert "수집" in st["error"]


def test_universe_status_empty(client):
    r = client.get("/api/universe/status")
    assert r.status_code == 200
    body = r.json()
    assert body["symbols"] == 0 and body["delisted_count"] == 0


def test_optimize_response_carries_regime_warning(client, monkeypatch):
    """optimize는 유지하되 레짐 경고가 붙는다 — 기존 필드는 그대로."""
    from app import service as svc
    monkeypatch.setattr(svc, "_strategy_universe", lambda conn: ({}, {}, 1400.0))
    r = client.post("/api/strategy/optimize", json={"preset": "donchian"})
    assert r.status_code == 200
    assert any("워크포워드" in w for w in r.json()["warnings"])


def test_walkforward_regime_filter_needs_benchmark(client):
    """벤치마크 이력이 없는 상태의 레짐 필터 요청은 안내가 담긴 error."""
    r = client.post("/api/strategy/walkforward",
                    json={"preset": "donchian", "regime_filter": True})
    st = _poll_job(client, f"/api/strategy/walkforward/{r.json()['job_id']}")
    assert st["status"] == "error" and "벤치마크" in st["error"]


def test_strategy_presets_declare_autotrade_capability(client):
    """화면이 자동매매 드롭다운에서 횡단면을 걸러낼 수 있어야 한다."""
    presets = {p["key"]: p for p in client.get("/api/strategy/presets").json()}
    assert presets["abs_momentum"]["autotrade_capable"] is True
    assert presets["abs_momentum"]["kind"] == "timeseries"
    assert presets["xs_momentum"]["autotrade_capable"] is False
    assert presets["xs_momentum"]["kind"] == "cross_sectional"
    # 기존 필드는 그대로 — 빌드본이 구버전일 수 있다
    assert presets["xs_momentum"]["label"] and presets["xs_momentum"]["params"]
