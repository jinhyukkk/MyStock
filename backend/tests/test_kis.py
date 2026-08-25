"""KIS 클라이언트 — requests를 가짜로 바꿔 네트워크 없이 검증한다."""
import json

import pytest

from app import db, kis


@pytest.fixture
def conn(tmp_path):
    c = db.get_conn(str(tmp_path / "t.db"))
    yield c
    c.close()


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("KIS_APP_KEY", "k")
    monkeypatch.setenv("KIS_APP_SECRET", "s")
    monkeypatch.setenv("KIS_ACCOUNT", "12345678-01")
    monkeypatch.setenv("KIS_MODE", "paper")


class FakeResp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def test_configured_false_without_keys(monkeypatch):
    for k in ("KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT"):
        monkeypatch.delenv(k, raising=False)
    assert not kis.configured()
    with pytest.raises(kis.KisError):
        kis.Client(None)


def test_account_split(env, conn):
    c = kis.Client(conn)
    assert c.cano == "12345678" and c.prdt == "01"
    assert c.base == kis.DOMAIN["paper"]


def test_token_cached_in_meta(env, conn, monkeypatch):
    """토큰 발급은 분당 1회 제한 — 두 번째 호출은 캐시를 써야 한다."""
    calls = []

    def fake_post(url, **kw):
        calls.append(url)
        return FakeResp({"access_token": "T", "expires_in": 86400})

    monkeypatch.setattr(kis.requests, "post", fake_post)
    c = kis.Client(conn)
    assert c._token() == "T"
    assert c._token() == "T"
    assert len(calls) == 1, "만료 전 재발급은 rate limit에 걸린다"
    assert json.loads(db.get_meta(conn, "kis_token_paper"))["token"] == "T"


def test_order_uses_paper_tr_and_market_price(env, conn, monkeypatch):
    sent = {}

    def fake_post(url, **kw):
        if url.endswith("/oauth2/tokenP"):
            return FakeResp({"access_token": "T", "expires_in": 86400})
        sent.update(url=url, headers=kw["headers"], body=kw["json"])
        return FakeResp({"rt_cd": "0", "output": {"ODNO": "12345"}})

    monkeypatch.setattr(kis.requests, "post", fake_post)
    assert kis.Client(conn).order("005930", "BUY", 3) == "12345"
    assert sent["headers"]["tr_id"] == "VTTC0802U"  # 모의투자 매수 TR
    assert sent["body"]["ORD_DVSN"] == "01" and sent["body"]["ORD_UNPR"] == "0"
    assert sent["body"]["ORD_QTY"] == "3"


def test_order_failure_raises_with_kis_message(env, conn, monkeypatch):
    """HTTP 200이어도 rt_cd가 실패면 예외 — 조용히 넘기면 주문이 안 나갔는데 나간 걸로 기록된다."""
    def fake_post(url, **kw):
        if url.endswith("/oauth2/tokenP"):
            return FakeResp({"access_token": "T", "expires_in": 86400})
        return FakeResp({"rt_cd": "1", "msg1": "잔고 부족"})

    monkeypatch.setattr(kis.requests, "post", fake_post)
    with pytest.raises(kis.KisError, match="잔고 부족"):
        kis.Client(conn).order("005930", "BUY", 3)


def test_balance_parses_holdings_and_cash(env, conn, monkeypatch):
    def fake_post(url, **kw):
        return FakeResp({"access_token": "T", "expires_in": 86400})

    def fake_get(url, **kw):
        return FakeResp({"rt_cd": "0",
                         "output1": [{"pdno": "005930", "prdt_name": "삼성전자",
                                      "hldg_qty": "10", "pchs_avg_pric": "70000"},
                                     {"pdno": "000660", "hldg_qty": "0"}],
                         "output2": [{"dnca_tot_amt": "5000000",
                                      "tot_evlu_amt": "5700000"}]})

    monkeypatch.setattr(kis.requests, "post", fake_post)
    monkeypatch.setattr(kis.requests, "get", fake_get)
    b = kis.Client(conn).balance()
    assert b["cash_krw"] == 5_000_000.0
    assert b["total_eval_krw"] == 5_700_000.0
    # 수량 0(전량 매도 잔재)은 보유로 치지 않는다
    assert [h["symbol"] for h in b["holdings"]] == ["005930"]
