"""자동매매 파이프라인 — 네트워크 없이 plan/execute 전체를 검증한다.

KIS 응답은 가짜 잔고·가짜 클라이언트로 대체한다. 여기서 검증하는 것은
"백테스트와 같은 규칙으로 주문이 만들어지는가"다 — 규칙이 어긋나면
검증한 전략과 실행하는 전략이 달라진다.
"""
import pytest

from app import autotrade, db, engine, kis


@pytest.fixture
def conn(tmp_path):
    c = db.get_conn(str(tmp_path / "t.db"))
    yield c
    c.close()


def _seed(conn, ohlcv, symbol="005930", name="삼성전자"):
    db.upsert_ticker(conn, symbol, "KR", name)
    db.save_prices(conn, symbol, ohlcv)
    autotrade.save_settings(conn, "abs_momentum",
                            {"lookback": 60, "skip": 5, "trend_ma": 30})


def _balance(cash=10_000_000.0, holdings=()):
    return {"cash_krw": cash, "total_eval_krw": cash, "holdings": list(holdings)}


def test_plan_buys_on_enter_signal(conn, ohlcv_up):
    """상승 추세 마지막 봉에서 진입 신호 → 1% 룰 수량의 매수 주문."""
    _seed(conn, ohlcv_up)
    p = autotrade.plan(conn, _balance())
    buys = [o for o in p["orders"] if o["side"] == "BUY"]
    assert len(buys) == 1
    o = buys[0]
    assert o["symbol"] == "005930" and o["reason"] == "enter"
    assert o["qty"] > 0
    assert o["stop"] < o["price_ref"], "손절선이 진입가 위면 사이징이 무의미하다"
    # 수량이 engine.position_size와 같아야 백테스트와 같은 규칙이다
    expected = engine.position_size(10_000_000.0, o["price_ref"], o["stop"], 1.0, "KR")
    assert o["qty"] == int(expected)


def test_plan_skips_buy_when_already_held_in_account(conn, ohlcv_up):
    """계좌에 이미 있는 종목은 다시 사지 않는다 — 수동 보유와 겹치면 비중이 두 배가 된다."""
    _seed(conn, ohlcv_up)
    held = [{"symbol": "005930", "name": "삼성전자", "qty": 10, "avg_price": 100}]
    p = autotrade.plan(conn, _balance(holdings=held))
    assert [o for o in p["orders"] if o["side"] == "BUY"] == []


def test_plan_sells_on_stop_touch(conn, ohlcv_up):
    """어제 저가가 손절선에 닿았으면 매도 — engine의 low<=stop 판정과 동일."""
    _seed(conn, ohlcv_up)
    last_low = float(ohlcv_up["low"].iloc[-1])
    db.upsert_auto_position(conn, "005930", 10, last_low * 1.2,
                            last_low + 1, "2026-01-05")  # 손절선이 저가 위
    held = [{"symbol": "005930", "name": "삼성전자", "qty": 10, "avg_price": 100}]
    p = autotrade.plan(conn, _balance(holdings=held))
    sells = [o for o in p["orders"] if o["side"] == "SELL"]
    assert len(sells) == 1 and sells[0]["reason"] == "stop"
    assert sells[0]["qty"] == 10


def test_plan_sells_on_exit_signal(conn, ohlcv_down):
    """하락 추세(모멘텀<0) 청산 시그널 → exit_signal 매도. 손절선은 멀리 둔다."""
    _seed(conn, ohlcv_down)
    db.upsert_auto_position(conn, "005930", 10, 100.0, 0.01, "2026-01-05")
    held = [{"symbol": "005930", "name": "삼성전자", "qty": 10, "avg_price": 100}]
    p = autotrade.plan(conn, _balance(holdings=held))
    sells = [o for o in p["orders"] if o["side"] == "SELL"]
    assert len(sells) == 1 and sells[0]["reason"] == "exit_signal"


def test_plan_warns_orphan_position_instead_of_selling(conn, ohlcv_up):
    """자동 포지션이 계좌에 없으면(수동 매도 등) 주문 대신 경고 — 팔면 공매도다."""
    _seed(conn, ohlcv_up)
    db.upsert_auto_position(conn, "005930", 10, 100.0, 999999.0, "2026-01-05")
    p = autotrade.plan(conn, _balance(holdings=[]))
    assert [o for o in p["orders"] if o["side"] == "SELL"] == []
    assert any("005930" in w for w in p["warnings"])


def test_plan_respects_cash_gate(conn, ohlcv_up):
    """예수금이 모자라면 진입하지 않는다 — 현금 계좌에서 초과 매수는 미수다."""
    _seed(conn, ohlcv_up)
    p = autotrade.plan(conn, _balance(cash=100.0))
    assert [o for o in p["orders"] if o["side"] == "BUY"] == []


class FakeClient:
    """주문을 기록만 하는 KIS 대역. fail에 담긴 종목은 주문이 실패한다."""

    def __init__(self, balance, fail=()):
        self._balance = balance
        self.sent = []
        self.fail = set(fail)

    def balance(self):
        return self._balance

    def order(self, symbol, side, qty):
        if symbol in self.fail:
            raise kis.KisError("모의 실패")
        self.sent.append((symbol, side, qty))
        return f"ODNO-{len(self.sent)}"


def test_execute_records_position_and_ledger(conn, ohlcv_up):
    """매수 발송 → auto_positions에 손절선과 함께 남고 원장에 sent로 기록된다."""
    _seed(conn, ohlcv_up)
    client = FakeClient(_balance())
    out = autotrade.execute(conn, client)
    assert len(client.sent) == 1
    pos = [dict(r) for r in db.list_auto_positions(conn)]
    assert len(pos) == 1 and pos[0]["symbol"] == "005930" and pos[0]["stop"] > 0
    orders = [dict(r) for r in db.list_auto_orders(conn)]
    assert orders[0]["status"] == "sent" and orders[0]["order_no"] == "ODNO-1"
    assert out["orders"][0]["status"] == "sent"


def test_execute_failure_leaves_no_position(conn, ohlcv_up):
    """주문 실패 시 포지션을 만들면 안 된다 — 존재하지 않는 보유에 손절을 걸게 된다."""
    _seed(conn, ohlcv_up)
    out = autotrade.execute(conn, FakeClient(_balance(), fail={"005930"}))
    assert db.list_auto_positions(conn) == []
    orders = [dict(r) for r in db.list_auto_orders(conn)]
    assert orders[0]["status"] == "failed" and orders[0]["error"]
    assert out["orders"][0]["status"] == "failed"


def test_execute_sell_removes_position(conn, ohlcv_down):
    _seed(conn, ohlcv_down)
    db.upsert_auto_position(conn, "005930", 10, 100.0, 0.01, "2026-01-05")
    held = [{"symbol": "005930", "name": "삼성전자", "qty": 10, "avg_price": 100}]
    autotrade.execute(conn, FakeClient(_balance(holdings=held)))
    assert db.list_auto_positions(conn) == []


def test_settings_roundtrip_and_unknown_preset(conn):
    autotrade.save_settings(conn, "donchian", {"entry_n": 20, "exit_n": 10})
    cfg = autotrade.settings(conn)
    assert cfg["preset"] == "donchian"
    assert cfg["params"]["entry_n"] == 20
    with pytest.raises(ValueError):
        autotrade.save_settings(conn, "없는전략", {})


def test_settings_defaults_when_unset(conn):
    cfg = autotrade.settings(conn)
    assert cfg["preset"] == "abs_momentum"
    assert cfg["params"]["lookback"] == 252
