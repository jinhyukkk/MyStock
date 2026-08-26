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


def _seed(conn, ohlcv, symbol="005930", name="삼성전자", bench=True):
    db.upsert_ticker(conn, symbol, "KR", name)
    db.save_prices(conn, symbol, ohlcv)
    autotrade.save_settings(conn, "abs_momentum",
                            {"lookback": 60, "skip": 5, "trend_ma": 30})
    if bench:
        # 레짐 필터가 기본 ON이라 벤치마크가 없으면 진입이 전부 막힌다 —
        # 사이징·주문 규칙을 보는 테스트는 "레짐 통과" 상태에서 돌아야 한다
        _seed_bench(conn, ohlcv)


def _seed_bench(conn, ohlcv):
    """지수 일봉을 종목과 같은 달력에 올린다 — 레짐은 신호일 기준으로 읽힌다."""
    db.save_prices(conn, autotrade.BENCH_SYMBOL, ohlcv)


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
    # 평단을 진입가와 같게 둔다 — 어긋나면 체결가 보정이 먼저 돌아 손절선이 옮겨진다
    held = [{"symbol": "005930", "name": "삼성전자", "qty": 10,
             "avg_price": last_low * 1.2}]
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


# ── 시장 레짐 게이트 ────────────────────────────────────────────────────────
# 워크포워드에서 유효했던 것은 레짐 필터뿐이다(MDD -56%→-28%). 그 필터가
# 실행 경로에 없으면 검증한 구성과 다른 전략이 실계좌에 나간다.

def test_plan_blocks_entries_when_index_is_below_its_moving_average(conn, ohlcv_up, ohlcv_down):
    """지수가 200일선 아래면 신규 진입 0 — 종목 신호가 살아 있어도 막는다."""
    _seed(conn, ohlcv_up, bench=False)
    _seed_bench(conn, ohlcv_down)
    p = autotrade.plan(conn, _balance())
    assert [o for o in p["orders"] if o["side"] == "BUY"] == []
    assert p["regime"]["enabled"] is True and p["regime"]["ok"] is False
    assert any("레짐" in w for w in p["warnings"])


def test_plan_still_exits_while_the_regime_blocks_entries(conn, ohlcv_up, ohlcv_down):
    """하락장에서 못 파는 필터는 리스크 장치가 아니라 족쇄다 — 청산은 그대로 나간다."""
    _seed(conn, ohlcv_up, bench=False)
    _seed_bench(conn, ohlcv_down)
    last_low = float(ohlcv_up["low"].iloc[-1])
    db.upsert_auto_position(conn, "005930", 10, last_low * 1.2,
                            last_low + 1, "2026-01-05")
    held = [{"symbol": "005930", "name": "삼성전자", "qty": 10,
             "avg_price": last_low * 1.2}]
    p = autotrade.plan(conn, _balance(holdings=held))
    sells = [o for o in p["orders"] if o["side"] == "SELL"]
    assert len(sells) == 1 and sells[0]["reason"] == "stop"


def test_plan_blocks_entries_when_the_benchmark_history_is_missing(conn, ohlcv_up):
    """레짐을 판정할 근거가 없으면 막는다 — 근거 없이 사는 쪽이 더 위험하다."""
    _seed(conn, ohlcv_up, bench=False)
    p = autotrade.plan(conn, _balance())
    assert [o for o in p["orders"] if o["side"] == "BUY"] == []
    assert p["regime"]["ok"] is None
    assert any("벤치마크" in w or "지수" in w for w in p["warnings"])


def test_plan_reports_the_regime_numbers_it_judged_on(conn, ohlcv_up):
    """왜 안 샀는지가 화면에서 보여야 한다 — 종가와 200일선을 함께 내보낸다."""
    _seed(conn, ohlcv_up)
    r = autotrade.plan(conn, _balance())["regime"]
    assert r["ok"] is True and r["ma"] == 200
    assert r["bench_close"] > r["bench_ma"]
    assert r["as_of"] == ohlcv_up.index[-1].strftime("%Y-%m-%d")


def test_plan_allows_entries_when_the_regime_filter_is_disabled(conn, ohlcv_up, ohlcv_down):
    """토글을 끄면 진입은 열리되, 그 구성이 검증에서 전패했다는 사실을 경고로 남긴다."""
    _seed(conn, ohlcv_up, bench=False)
    _seed_bench(conn, ohlcv_down)
    autotrade.save_settings(conn, "abs_momentum",
                            {"lookback": 60, "skip": 5, "trend_ma": 30},
                            regime_filter=False)
    p = autotrade.plan(conn, _balance())
    assert len([o for o in p["orders"] if o["side"] == "BUY"]) == 1
    assert p["regime"]["enabled"] is False
    assert any("워크포워드" in w for w in p["warnings"])


def test_regime_filter_defaults_to_on_when_never_configured(conn):
    """기본값이 OFF면 데이터가 반대하는 구성이 계속 기본으로 남는다."""
    assert autotrade.settings(conn)["regime_filter"] is True


def test_regime_filter_setting_roundtrips(conn):
    autotrade.save_settings(conn, "donchian", {"entry_n": 20}, regime_filter=False)
    assert autotrade.settings(conn)["regime_filter"] is False
    autotrade.save_settings(conn, "donchian", {"entry_n": 20}, regime_filter=True)
    assert autotrade.settings(conn)["regime_filter"] is True


# ── 유니버스 불일치 고지 ────────────────────────────────────────────────────

def test_plan_always_discloses_the_universe_mismatch(conn, ohlcv_up):
    """실행 모집단은 관심종목, 검증은 krx300 — 성과의 큰 몫이 이 차이에서 나왔다."""
    _seed(conn, ohlcv_up)
    p = autotrade.plan(conn, _balance())
    assert p["universe"] == {"kind": "watchlist", "size": 1}
    assert any("krx300" in w for w in p["warnings"])


# ── 체결가 보정 ────────────────────────────────────────────────────────────
# entry_price는 주문 시점 직전 종가 근사였다 — 실체결(시가)과 벌어지면
# 손절선이 그만큼 어긋나 1% 룰의 1%가 1%가 아니게 된다.

def test_plan_reconciles_entry_price_from_the_account_average(conn, ohlcv_up):
    """계좌 평단과 다르면 진입가를 평단으로 고치고 손절폭을 유지한 채 손절선을 옮긴다."""
    _seed(conn, ohlcv_up)
    db.upsert_auto_position(conn, "005930", 10, 100.0, 90.0, "2026-01-05")
    held = [{"symbol": "005930", "name": "삼성전자", "qty": 10, "avg_price": 104.0}]
    p = autotrade.plan(conn, _balance(holdings=held))
    pos = [dict(r) for r in db.list_auto_positions(conn)][0]
    assert pos["entry_price"] == pytest.approx(104.0)
    # 손절폭 10(=100−90)은 진입 시점 2×ATR이다 — 오늘 ATR로 다시 계산하면
    # 계산해 둔 리스크 한도가 사후에 바뀐다
    assert pos["entry_price"] - pos["stop"] == pytest.approx(10.0)
    assert any("보정" in w for w in p["warnings"])


def test_plan_reconciles_the_fill_only_once(conn, ohlcv_up):
    """부분매도·추가매수로 평단이 움직여도 재보정하지 않는다 — 그 평단은 진입 체결가가 아니다."""
    _seed(conn, ohlcv_up)
    db.upsert_auto_position(conn, "005930", 10, 100.0, 90.0, "2026-01-05")
    held = [{"symbol": "005930", "name": "삼성전자", "qty": 10, "avg_price": 104.0}]
    autotrade.plan(conn, _balance(holdings=held))
    held[0]["avg_price"] = 130.0
    p = autotrade.plan(conn, _balance(holdings=held))
    pos = [dict(r) for r in db.list_auto_positions(conn)][0]
    assert pos["entry_price"] == pytest.approx(104.0)
    assert not any("보정" in w for w in p["warnings"])


def test_plan_leaves_the_entry_price_alone_when_it_already_matches(conn, ohlcv_up):
    """오차가 없으면 손대지 않는다 — 의미 없는 보정 경고로 화면을 채우지 않는다."""
    _seed(conn, ohlcv_up)
    db.upsert_auto_position(conn, "005930", 10, 100.0, 90.0, "2026-01-05")
    held = [{"symbol": "005930", "name": "삼성전자", "qty": 10, "avg_price": 100.02}]
    p = autotrade.plan(conn, _balance(holdings=held))
    pos = [dict(r) for r in db.list_auto_positions(conn)][0]
    assert pos["entry_price"] == pytest.approx(100.0)
    assert not any("보정" in w for w in p["warnings"])


def test_stop_judgement_uses_the_reconciled_stop(conn, ohlcv_up):
    """보정이 청산 판정보다 먼저여야 백테스트와 같은 손절이 된다.

    보정 전 손절선은 어제 저가 아래(발동 안 함), 보정 후에는 저가 위(발동)다.
    보정을 청산 뒤에 두면 이 손절이 하루 늦게 나간다.
    """
    _seed(conn, ohlcv_up)
    last_low = float(ohlcv_up["low"].iloc[-1])
    db.upsert_auto_position(conn, "005930", 10, last_low * 0.5,
                            last_low * 0.4, "2026-01-05")
    # 평단을 크게 올리면 손절폭(0.1×low)이 그대로 따라 올라가 저가를 넘어선다
    held = [{"symbol": "005930", "name": "삼성전자", "qty": 10,
             "avg_price": last_low * 1.2}]
    p = autotrade.plan(conn, _balance(holdings=held))
    sells = [o for o in p["orders"] if o["side"] == "SELL"]
    assert len(sells) == 1 and sells[0]["reason"] == "stop"
