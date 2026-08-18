import pytest
from app import broker, db, service


# ── CODEF 응답 파싱 ────────────────────────────────────────────────────────

def _item(**kw):
    base = {"resProductTypeCd": "01", "resItemCode": "005930", "resItemName": "삼성전자",
            "resQuantity": "10", "resAvgPresentAmt": "70,000", "resPresentAmt": "75,000",
            "resPurchaseAmount": "700,000", "resAccountCurrency": "KRW"}
    base.update(kw)
    return base


def test_num_absorbs_broker_formatting():
    """증권사마다 콤마·빈 값·공백이 제각각이다 — 여기서 새면 총자산이 통째로 틀린다."""
    assert broker.num("1,234,567") == 1234567
    assert broker.num("") == 0.0
    assert broker.num(None) == 0.0
    assert broker.num("  -  ") == 0.0
    assert broker.num("-1500.5") == -1500.5


def test_parse_balance_reads_cash_and_holdings():
    data = {"resDepositReceived": "1,000,000", "resDepositReceivedD2": "1,200,000",
            "resDepositReceivedF": "1,400,000",  # 원화환산 — 달러 예수금으로 쓰면 안 된다
            "resDepositReceivedFList": [{"resAmount": "1,000.00", "resAccountCurrency": "USD"}],
            "resItemList": [_item()]}
    out = broker.parse_balance(data, account="1234-5678")
    assert out["cash_krw"] == 1200000  # D+2 우선
    assert out["cash_usd"] == 1000.0   # 환산값(1,400,000)이 아니라 통화별 원금액
    assert out["holdings"] == [{
        "code": "005930", "market": "KR", "currency": "KRW", "name": "삼성전자",
        "quantity": 10.0, "avg_price": 70000.0, "basis_missing": False,
        "account": "1234-5678"}]


def test_parse_balance_falls_back_to_d_when_no_d2():
    out = broker.parse_balance({"resDepositReceived": "500", "resDepositReceivedD2": ""})
    assert out["cash_krw"] == 500


def test_avg_price_derived_from_purchase_amount_when_missing():
    """평균매입가는 필수 항목이 아니다. 0으로 두면 평가액 전액이 이익으로 찍힌다."""
    out = broker.parse_balance({"resItemList": [
        _item(resAvgPresentAmt="", resPurchaseAmount="700,000", resQuantity="10")]})
    assert out["holdings"][0]["avg_price"] == 70000
    assert out["holdings"][0]["basis_missing"] is False


def test_avg_price_missing_falls_back_to_present_price_and_is_flagged():
    """매입금액조차 없으면 현재가로 채우되(손익 0) '평단 모름'을 반드시 남긴다."""
    out = broker.parse_balance({"resItemList": [
        _item(resAvgPresentAmt="", resPurchaseAmount="", resPresentAmt="75,000")]})
    h = out["holdings"][0]
    assert h["avg_price"] == 75000 and h["basis_missing"] is True


def test_non_stock_products_and_zero_quantity_are_skipped():
    out = broker.parse_balance({"resItemList": [
        _item(resProductTypeCd="02", resItemName="펀드"),  # 펀드
        _item(resQuantity="0"),                            # 전량 매도된 잔여 행
    ]})
    assert out["holdings"] == []


def test_kr_code_strips_broker_prefix():
    assert broker.normalize_code("A005930", "01") == "005930"
    assert broker.normalize_code("5930", "01") == "005930"


def test_unmappable_code_is_reported_not_silently_dropped():
    """ISIN처럼 앱 심볼로 확신할 수 없는 코드를 억지로 맞추면 엉뚱한 시세가 붙는다."""
    out = broker.parse_balance({"resItemList": [
        _item(resProductTypeCd="04", resItemCode="US0378331005", resItemName="APPLE",
              resAccountCurrency="USD")]})
    assert out["holdings"] == []
    assert out["unmapped"][0]["raw_code"] == "US0378331005"


def test_us_ticker_maps_through():
    out = broker.parse_balance({"resItemList": [
        _item(resProductTypeCd="04", resItemCode="AAPL", resItemName="APPLE",
              resAccountCurrency="USD", resAvgPresentAmt="180", resQuantity="5")]})
    h = out["holdings"][0]
    assert (h["code"], h["market"], h["currency"]) == ("AAPL", "US", "USD")


def test_merge_combines_accounts_with_quantity_weighted_average():
    a = broker.parse_balance({"resDepositReceived": "1000", "resItemList": [
        _item(resQuantity="10", resAvgPresentAmt="70000")]})
    b = broker.parse_balance({"resDepositReceived": "500", "resItemList": [
        _item(resQuantity="10", resAvgPresentAmt="80000")]})
    m = broker.merge([a, b])
    assert m["cash_krw"] == 1500
    assert m["holdings"][0]["quantity"] == 20
    assert m["holdings"][0]["avg_price"] == 75000


# ── 스냅샷이 원장을 대체하는지 ─────────────────────────────────────────────

@pytest.fixture
def conn(tmp_path):
    c = db.get_conn(str(tmp_path / "t.db"))
    db.upsert_ticker(c, "005930", "KR", "삼성전자")
    yield c
    c.close()


def test_broker_snapshot_overrides_ledger_quantity(conn):
    """원장은 손으로 적는다 — 누락된 체결 하나가 비중·리스크·사이징을 함께 틀어놓는다."""
    db.insert_trade(conn, "005930", "BUY", 10, 70000, "2026-01-02")
    assert service._holdings_map(conn)["005930"]["quantity"] == 10

    db.replace_broker_holdings(conn, [{"symbol": "005930", "quantity": 25,
                                       "avg_price": 68000}], "2026-08-18T09:00:00")
    h = service._holdings_map(conn)["005930"]
    assert (h["quantity"], h["avg_price"], h["source"]) == (25, 68000, "broker")


def test_symbol_sold_at_broker_disappears_from_holdings(conn):
    """증권사에서 이미 전량 매도된 종목이 남으면 화면에 유령 보유가 뜬다."""
    db.insert_trade(conn, "005930", "BUY", 10, 70000, "2026-01-02")
    db.upsert_ticker(conn, "000660", "KR", "SK하이닉스")
    db.replace_broker_holdings(conn, [{"symbol": "000660", "quantity": 3,
                                       "avg_price": 200000}], "2026-08-18T09:00:00")
    holdings = service._holdings_map(conn)
    assert set(holdings) == {"000660"}


def test_empty_snapshot_leaves_ledger_untouched(conn):
    """연동 전(또는 해제 후)에는 원장이 그대로 진실이어야 한다."""
    db.insert_trade(conn, "005930", "BUY", 10, 70000, "2026-01-02")
    db.replace_broker_holdings(conn, [], "2026-08-18T09:00:00")
    assert service._holdings_map(conn)["005930"]["quantity"] == 10


def test_broker_only_symbol_keeps_fx_unknown(conn):
    """원장에 없던 종목은 매수 환율을 알 수 없다 — 0으로 쓰면 '환 영향 없음'이 된다."""
    db.upsert_ticker(conn, "AAPL", "US", "Apple", currency="USD")
    db.replace_broker_holdings(conn, [{"symbol": "AAPL", "quantity": 5,
                                       "avg_price": 180, "currency": "USD"}],
                              "2026-08-18T09:00:00")
    assert service._holdings_map(conn)["AAPL"]["fx_known"] is False


# ── 입출금내역 ─────────────────────────────────────────────────────────────

def _tr(**kw):
    base = {"resAccountTrDate": "20260810", "resAccountTrTime": "093000",
            "resAccountIn": "1,000,000", "resAccountOut": "0",
            "resAccountDesc1": "박진혁", "resAccountDesc2": "이체입금",
            "resAccountDesc3": "", "resAccountDesc4": ""}
    base.update(kw)
    return base


def test_parse_transactions_reads_date_and_amount():
    rows = broker.parse_transactions({"resTrHistoryList": [_tr()]}, account="키움1234")
    assert rows[0]["date"] == "2026-08-10"
    assert rows[0]["amount_in"] == 1000000 and rows[0]["amount_out"] == 0
    assert "이체입금" in rows[0]["desc"]


def test_ext_key_is_stable_across_refetch_but_unique_per_duplicate_row():
    """같은 기간을 다시 조회해도 키가 같아야 중복 적재가 안 되고, 같은 날 같은 금액이
    두 번 들어온 경우는 서로 달라야 두 번째 입금이 누락되지 않는다."""
    data = {"resTrHistoryList": [_tr(), _tr()]}
    first = [r["ext_key"] for r in broker.parse_transactions(data, account="A")]
    second = [r["ext_key"] for r in broker.parse_transactions(data, account="A")]
    assert first == second
    assert first[0] != first[1]


def test_transactions_skip_rows_without_amount_or_date():
    rows = broker.parse_transactions({"resTrHistoryList": [
        _tr(resAccountTrDate="합계"),
        _tr(resAccountIn="0", resAccountOut="0"),
    ]})
    assert rows == []


def test_classify_skips_trade_settlement():
    """매매 대금까지 현금흐름으로 넣으면 원장과 겹쳐 같은 돈이 두 번 계상된다."""
    rows = broker.parse_transactions({"resTrHistoryList": [
        _tr(resAccountDesc2="주식매수", resAccountIn="0", resAccountOut="700,000")]})
    assert broker.classify_flow(rows[0]) is None


def test_classify_deposit_withdraw_dividend_interest():
    def one(**kw):
        return broker.classify_flow(broker.parse_transactions(
            {"resTrHistoryList": [_tr(**kw)]})[0])
    assert one() == "DEPOSIT"
    assert one(resAccountIn="0", resAccountOut="500,000") == "WITHDRAW"
    assert one(resAccountDesc3="배당금 삼성전자") == "DIVIDEND"
    assert one(resAccountDesc3="예탁금이용료") == "INTEREST"


def test_flow_import_is_idempotent_and_matches_dividend_symbol(conn, monkeypatch):
    """재조회는 중복을 만들지 않아야 하고, 배당은 종목에 붙어야 배당수익률에 잡힌다."""
    db.set_meta(conn, service.BROKER_CID, "cid")
    db.set_meta(conn, service.BROKER_ACCOUNTS,
                '[{"organization":"0264","account":"1234","display":"키움1234"}]')
    payload = {"resTrHistoryList": [
        _tr(),
        _tr(resAccountTrTime="100000", resAccountIn="14,000",
            resAccountDesc3="배당금 삼성전자"),
        _tr(resAccountTrTime="110000", resAccountIn="0", resAccountOut="700,000",
            resAccountDesc2="주식매수"),
    ]}
    monkeypatch.setattr(service.codef, "transactions", lambda *a, **k: [payload])

    out = service.sync_broker_flows(conn)
    assert out["added"] == {"DEPOSIT": 1, "WITHDRAW": 0, "DIVIDEND": 1, "INTEREST": 0}
    assert out["skipped_trades"] == 1
    div = [dict(r) for r in db.list_cash_flows(conn, flow_type="DIVIDEND")]
    assert div[0]["symbol"] == "005930" and div[0]["amount"] == 14000

    again = service.sync_broker_flows(conn)
    assert again["total_added"] == 0 and again["duplicates"] == 2
    assert len(db.list_cash_flows(conn)) == 2


def test_flow_import_does_not_touch_cash(conn, monkeypatch):
    """예수금은 잔고조회가 덮어쓰는 값이다 — 여기서 더하면 이중 반영된다."""
    db.set_meta(conn, service.BROKER_CID, "cid")
    db.set_meta(conn, service.BROKER_ACCOUNTS,
                '[{"organization":"0264","account":"1234"}]')
    db.set_meta(conn, "cash_krw", "5000000")
    monkeypatch.setattr(service.codef, "transactions",
                        lambda *a, **k: [{"resTrHistoryList": [_tr()]}])
    service.sync_broker_flows(conn)
    assert service.get_cash_krw(conn) == 5000000
