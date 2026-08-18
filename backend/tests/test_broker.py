import urllib.parse
from datetime import datetime, timedelta

import pandas as pd
import pytest
from app import broker, codef, db, service


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


def test_decode_reads_utf8_korean_names():
    """CODEF는 한글을 UTF-8로 퍼센트 인코딩해서 보낸다."""
    body = urllib.parse.quote('{"resItemName": "SK하이닉스"}'.encode("utf-8"))
    assert codef._decode(body) == {"resItemName": "SK하이닉스"}


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


def test_usd_deposit_read_from_misnamed_field():
    """미래에셋은 외화예수금 금액을 resProductType에 담아 준다 — 못 읽으면 통째로 0이 된다."""
    out = broker.parse_balance({"resDepositReceivedFList": [
        {"resProductType": "1,234.56", "resAccountCurrency": "USD"}]})
    assert out["cash_usd"] == 1234.56


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


def test_kr_new_format_code_keeps_letter():
    """신형 코드에서 문자를 떼면 실재하는 다른 종목이 된다 — 엉뚱한 시세로 평가된다."""
    assert broker.normalize_code("0167A0", "01") == "0167A0"
    assert broker.normalize_code("A0167A0", "01") == "0167A0"
    assert broker.normalize_code("0011B0", "01") == "0011B0"
    assert broker.normalize_code("ABCDEF", "01") is None


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


# ── 종합자산 ───────────────────────────────────────────────────────────────

def test_parse_assets_keeps_only_what_stock_balance_misses():
    """종합자산엔 보유종목·외화예수금이 같이 온다 — 그대로 더하면 같은 돈을 두 번 센다."""
    keep, skipped = broker.parse_assets({"resItemList": [
        # 발행어음: 상품유형이 '주식'인데 수량 0, 평가금액만 있다 → 남겨야 한다
        {"resProductTypeCd": "01", "resItemName": "발행어음CMA(개인)",
         "resQuantity": "0", "resValuationAmt": "3,000,000", "resAccountCurrency": "KRW"},
        {"resProductTypeCd": "02", "resItemName": "청년형 펀드",
         "resQuantity": "1000000", "resValuationAmt": "2,000,000", "resAccountCurrency": "KRW"},
        # 아래 셋은 이미 세고 있다
        {"resProductTypeCd": "01", "resItemName": "삼성전자",
         "resQuantity": "5", "resValuationAmt": "400,000", "resAccountCurrency": "KRW"},
        {"resProductTypeCd": "04", "resItemName": "엔비디아",
         "resQuantity": "25", "resValuationAmt": "5,000,000", "resAccountCurrency": "KRW"},
        {"resProductTypeCd": "99", "resItemName": "미국달러",
         "resQuantity": "1000", "resValuationAmt": "1,400,000", "resAccountCurrency": "KRW"},
    ]}, account="1234-5678")
    assert [(r["name"], r["value_krw"], r["type"]) for r in keep] == [
        ("발행어음CMA(개인)", 3000000.0, "현금성 상품"),
        ("청년형 펀드", 2000000.0, "펀드")]
    assert {r["name"] for r in skipped} == {"삼성전자", "엔비디아", "미국달러"}


def test_parse_assets_skips_non_krw_valuation():
    """통화가 원화가 아니면 그대로 더할 수 없다 — 총자산이 환율 배수만큼 어긋난다."""
    keep, skipped = broker.parse_assets({"resItemList": [
        {"resProductTypeCd": "06", "resItemName": "해외채권",
         "resQuantity": "0", "resValuationAmt": "1,000", "resAccountCurrency": "USD"}]})
    assert keep == []
    assert skipped[0]["reason"] == "원화 평가액이 아님"


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


def test_classify_skips_internal_account_transfer():
    """본인 계좌 간 대체는 양쪽 계좌에서 다 잡힌다 — 입출금으로 세면 원금이 양방향으로 부푼다."""
    def one(desc, **kw):
        return broker.classify_flow(broker.parse_transactions(
            {"resTrHistoryList": [_tr(resAccountDesc2=desc, **kw)]})[0])
    assert one("계좌대체입금") is None
    assert one("계좌대체출금", resAccountIn="0", resAccountOut="500,000") is None
    # 예수금을 현금성 상품에 굴리는 스윕도 계좌 밖으로 나간 돈이 아니다
    assert one("CMA 발행어음 중도매도") is None
    assert one("CMA 발행어음 매수", resAccountIn="0", resAccountOut="9,000,000") is None


def test_classify_keeps_transfer_lookalike_wording():
    """'약정'·'장내' 같은 넓은 단어로 거르면 멀쩡한 이체가 조용히 사라진다."""
    def one(desc):
        return broker.classify_flow(broker.parse_transactions(
            {"resTrHistoryList": [_tr(resAccountDesc2=desc)]})[0])
    assert one("이체입금 약정금 정산") == "DEPOSIT"
    assert one("장내이체입금") == "DEPOSIT"
    # 실제로 관측되는 매매 문구는 여전히 걸러진다
    assert one("해외주식매수입고") is None
    assert one("주식매도입금") is None


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


# ── 계좌 목록 관리 ─────────────────────────────────────────────────────────

def _save(conn, org, acct, name=None, pw=None):
    service.broker_select_accounts(conn, [{"organization": org, "account": acct,
                                           "display": f"{org}-{acct}", "name": name,
                                           "account_password": pw}])


def test_saving_accounts_merges_instead_of_replacing(conn, monkeypatch):
    """덮어쓰면 두 번째 증권사를 추가하는 순간 첫 계좌가 조용히 사라진다."""
    monkeypatch.setattr(service.codef, "encrypt", lambda pw: f"enc:{pw}")
    db.set_meta(conn, service.BROKER_CID, "cid")
    _save(conn, "0264", "1111", name="연금저축", pw="1234")
    status = _save(conn, "0240", "2222", name="ISA") or service.broker_status(conn)
    accounts = {a["account"]: a for a in status["accounts"]}
    assert set(accounts) == {"1111", "2222"}
    assert accounts["1111"]["name"] == "연금저축"
    # 재선택에서 비밀번호를 다시 안 넣어도 저장분이 남아야 조회가 계속된다
    _save(conn, "0264", "1111", name="연금저축")
    assert service.broker_accounts(conn)[0]["password_enc"] == "enc:1234"


def test_removing_account_drops_its_snapshot(conn, monkeypatch):
    """뺀 계좌의 보유가 스냅샷에 남으면 유령 보유로 총자산이 부풀어 오른다."""
    db.set_meta(conn, service.BROKER_CID, "cid")
    _save(conn, "0264", "1111")
    _save(conn, "0240", "2222")
    db.replace_broker_holdings(conn, [
        {"symbol": "005930", "name": "삼성전자", "quantity": 10, "avg_price": 70000,
         "account": "0264-1111"},
        {"symbol": "000660", "name": "SK하이닉스", "quantity": 5, "avg_price": 200000,
         "account": "0240-2222"}], "2026-08-18T00:00:00")
    db.set_meta(conn, service.BROKER_OTHER_ASSETS,
                '[{"name":"발행어음","value_krw":1000000,"account":"0264-1111"}]')
    # 재동기화는 CODEF를 타므로 실패시킨다 — 그래도 유령 보유는 남지 않아야 한다
    monkeypatch.setattr(service, "sync_broker",
                        lambda c: (_ for _ in ()).throw(RuntimeError("조회 실패")))

    out = service.broker_remove_account(conn, "1111")
    assert out["resynced"] is False
    assert [a["account"] for a in out["accounts"]] == ["2222"]
    assert [r["account"] for r in db.list_broker_holdings(conn)] == ["0240-2222"]
    assert service.broker_other_assets(conn) == []


def test_removing_last_account_disconnects(conn, monkeypatch):
    """하나뿐인 계좌를 빼면 동기화할 대상이 없다 — 연동 상태로 남겨두면 거짓말이다."""
    db.set_meta(conn, service.BROKER_CID, "cid")
    _save(conn, "0264", "1111")
    out = service.broker_remove_account(conn, "1111")
    assert out["accounts"] == [] and out["connected"] is False
    with pytest.raises(codef.CodefError):
        service.broker_remove_account(conn, "9999")


def test_account_status_counts_its_own_holdings(conn):
    """계좌별 보유 수가 없으면 어느 계좌가 실제로 무엇을 물어오는지 알 수 없다."""
    db.set_meta(conn, service.BROKER_CID, "cid")
    _save(conn, "0264", "1111", name="연금저축")
    db.replace_broker_holdings(conn, [
        {"symbol": "005930", "name": "삼성전자", "quantity": 10, "avg_price": 70000,
         "account": "0264-1111"}], "2026-08-18T00:00:00")
    a = service.broker_status(conn)["accounts"][0]
    assert a["holdings_count"] == 1 and a["name"] == "연금저축"


# ── 알림(텔레그램) 설정 ────────────────────────────────────────────────────

def test_notify_setting_overrides_env_and_can_be_turned_off(conn, monkeypatch):
    """화면에서 껐는데 .env 값으로 알림이 계속 오면 설정을 믿을 수 없게 된다."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "envtok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "env42")
    assert service.notify_status(conn) == {"enabled": True, "token_set": True,
                                           "chat_id": "env42", "source": "env"}
    service.set_notify(conn, "uitok", "ui42")
    assert service.notify_creds(conn) == ("uitok", "ui42")
    st = service.set_notify(conn, "", "")
    assert st["enabled"] is False and service.notify_creds(conn) == ("", "")


def test_notify_test_reports_telegram_reason(conn, monkeypatch):
    """실패 사유를 삼키면 '왜 안 오는지'를 화면에서 영영 못 본다."""
    service.set_notify(conn, "tok", "42")

    class Fail:
        ok = False
        headers = {"content-type": "application/json"}

        def json(self):
            return {"description": "chat not found"}

    monkeypatch.setattr(service.requests, "post", lambda *a, **k: Fail())
    with pytest.raises(RuntimeError, match="chat not found"):
        service.notify_test(conn)

    service.set_notify(conn, "", "")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(ValueError):
        service.notify_test(conn)


def test_account_value_counts_cash_and_other_assets(conn):
    """0종목이어도 발행어음·예수금이 수천만 원인 계좌가 있다 — 종목 수만 세우면
    그 계좌가 '빈 계좌'로 읽히고, 어느 계좌를 뺄지 판단이 통째로 틀어진다."""
    db.set_meta(conn, service.BROKER_CID, "cid")
    _save(conn, "0264", "1111")
    db.set_meta(conn, service.BROKER_ACCOUNT_CASH,
                '{"0264-1111": {"cash_krw": 1000000, "cash_usd": 0}}')
    db.set_meta(conn, service.BROKER_OTHER_ASSETS,
                '[{"name":"발행어음","value_krw":2000000,"account":"0264-1111"}]')
    db.replace_broker_holdings(conn, [
        {"symbol": "005930", "name": "삼성전자", "quantity": 10, "avg_price": 70000,
         "account": "0264-1111"}], "2026-08-18T00:00:00")

    a = service.broker_status(conn)["accounts"][0]
    # 시세가 아직 없는 종목은 평가액에서 빠지므로 부분값임을 알려야 한다
    assert a["value_partial"] is True
    assert a["value_krw"] == 3000000 and a["cash_krw"] == 1000000

    db.save_prices(conn, "005930", pd.DataFrame(
        {"open": [70000], "high": [70000], "low": [70000], "close": [75000],
         "volume": [1]}, index=pd.to_datetime(["2026-08-18"])))
    a = service.broker_status(conn)["accounts"][0]
    assert a["value_partial"] is False and a["value_krw"] == 3750000


def test_sync_failure_surfaces_until_next_success(conn, monkeypatch):
    """자동 갱신은 화면 밖에서 돈다 — 실패를 남기지 않으면 낡은 잔고를 최신으로 믿는다."""
    db.set_meta(conn, service.BROKER_CID, "cid")
    _save(conn, "0264", "1111")
    monkeypatch.setattr(service, "sync_broker",
                        lambda c: (_ for _ in ()).throw(RuntimeError("인증서 만료")))
    monkeypatch.setattr(service.sentiment, "fetch_sentiment",
                        lambda: {"usdkrw": 1400.0, "failed": []})
    monkeypatch.setattr(service.fetchers, "fetch_ohlcv",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("skip")))

    out = service.refresh_all(conn)
    assert out["broker_failed"] == "인증서 만료"
    assert service.get_dashboard(conn)["broker_failed"] == "인증서 만료"
    assert service.broker_status(conn)["last_error"] == "인증서 만료"

    db.set_meta(conn, service.BROKER_LAST_ERROR, "")  # 다음 동기화 성공 시 지워진다
    assert service.get_dashboard(conn)["broker_failed"] is None


# ── CODEF 호출 한도 ────────────────────────────────────────────────────────

def test_auto_sync_budget_scales_with_account_count(conn):
    """계좌가 늘면 한 번의 동기화가 더 많은 호출을 쓴다 — 횟수를 줄여야 한도 안이다."""
    db.set_meta(conn, service.BROKER_CID, "cid")
    for i in range(5):
        _save(conn, "0264", f"111{i}")
    plan = service.auto_sync_plan(conn)
    assert plan["calls_per_sync"] == 10 and plan["times_per_day"] == 6
    # 하루 총 호출이 예비분을 남긴 자동 예산 안이어야 한다
    assert plan["times_per_day"] * plan["calls_per_sync"] <= service.CODEF_AUTO_BUDGET
    assert service.CODEF_AUTO_BUDGET < service.CODEF_DAILY_LIMIT


def test_auto_sync_waits_for_interval_even_after_failure(conn, monkeypatch):
    """실패해도 간격을 지켜야 한다 — 만료된 인증서가 매시간 재시도하면 한도만 태운다."""
    db.set_meta(conn, service.BROKER_CID, "cid")
    _save(conn, "0264", "1111")
    monkeypatch.setattr(service.sentiment, "fetch_sentiment",
                        lambda: {"usdkrw": 1400.0, "failed": []})
    monkeypatch.setattr(service.fetchers, "fetch_ohlcv",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("skip")))
    calls = []
    monkeypatch.setattr(service, "sync_broker",
                        lambda c: calls.append(1) or (_ for _ in ()).throw(RuntimeError("인증서 만료")))

    assert service.should_auto_sync(conn) is True
    service.refresh_all(conn)
    service.refresh_all(conn)  # 바로 다시 갱신해도 잔고는 다시 부르지 않는다
    assert len(calls) == 1 and service.should_auto_sync(conn) is False

    # 간격이 지나면 다시 시도한다
    past = datetime.now() - timedelta(hours=service.auto_sync_plan(conn)["interval_hours"] + 1)
    db.set_meta(conn, service.BROKER_LAST_ATTEMPT, past.isoformat(timespec="seconds"))
    assert service.should_auto_sync(conn) is True


def test_restart_does_not_resync_when_recently_synced(conn):
    """재시작마다 한 번씩 더 부르면, 개발 중 재시작만으로 하루 한도가 사라진다."""
    db.set_meta(conn, service.BROKER_CID, "cid")
    _save(conn, "0264", "1111")
    db.set_meta(conn, service.BROKER_SYNCED_AT,
                datetime.now().isoformat(timespec="seconds"))
    assert service.should_auto_sync(conn) is False
