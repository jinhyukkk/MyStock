"""네이버 시장 단위 어댑터 — 고정 JSON 픽스처로 파싱만 검증한다.

실호출은 smoke 로 따로 둔다. 비공식 API 라 스키마가 바뀌면 smoke 가 먼저 깨진다.
"""
import pytest

from app.sources import naver


def test_num_parses_naver_strings():
    assert naver._num("281,500") == 281500.0
    assert naver._num("+2,481") == 2481.0
    assert naver._num("-11,652") == -11652.0
    assert naver._num("3.8530") == 3.853
    assert naver._num("N/A") is None
    assert naver._num("") is None
    assert naver._num(None) is None
    assert naver._num(1234) == 1234.0


def test_index_basic(monkeypatch):
    monkeypatch.setattr(naver, "_get", lambda path, params=None: {
        "closePrice": "6,912.95", "compareToPreviousClosePrice": "60.37",
        "fluctuationsRatio": "0.88", "localTradedAt": "2026-08-21T18:59:00+09:00"})
    d = naver.index_basic("KOSPI")
    assert d["last"] == 6912.95
    assert d["change"] == 60.37
    assert d["change_pct"] == 0.88
    # 전일 종가는 응답에 없다 — 현재가에서 등락을 빼서 만든다
    assert d["prev_close"] == pytest.approx(6852.58)
    assert d["traded_at"] == "2026-08-21T18:59:00+09:00"


def test_index_basic_falling_sign(monkeypatch):
    """하락일 때 compareToPreviousClosePrice 에 이미 음수 부호가 온다 —
    fluctuationsType 을 보고 부호를 또 뒤집으면 두 번 뒤집힌다."""
    monkeypatch.setattr(naver, "_get", lambda path, params=None: {
        "closePrice": "6,800.00", "compareToPreviousClosePrice": "-52.95",
        "fluctuationsRatio": "-0.77", "localTradedAt": "2026-08-21T18:59:00+09:00"})
    d = naver.index_basic("KOSPI")
    assert d["change"] == -52.95 and d["change_pct"] == -0.77
    assert d["prev_close"] == pytest.approx(6852.95)


def _ranking_payload():
    return {"stocks": [
        {"itemCode": "005930", "stockName": "삼성전자", "stockEndType": "stock",
         "closePrice": "281,500", "fluctuationsRatio": "3.87",
         "accumulatedTradingVolume": "27,672,192", "marketValue": "16,457,274"},
        {"itemCode": "069500", "stockName": "KODEX 200", "stockEndType": "etf",
         "closePrice": "44,120", "fluctuationsRatio": "-0.35",
         "accumulatedTradingVolume": "1,000,000", "marketValue": "257,848"},
        {"itemCode": "000660", "stockName": "SK하이닉스", "stockEndType": "stock",
         "closePrice": "1,730,000", "fluctuationsRatio": "N/A",
         "accumulatedTradingVolume": "N/A", "marketValue": "12,637,518"},
    ]}


def test_ranking(monkeypatch):
    monkeypatch.setattr(naver, "_get", lambda path, params=None: _ranking_payload())
    rows = naver.ranking("up", "KOSPI", 3)
    assert rows[0] == {"symbol": "005930", "name": "삼성전자", "last": 281500.0,
                       "change_pct": 3.87, "volume": 27672192.0,
                       "market_value": 16457274.0, "is_etf": False}
    assert rows[1]["is_etf"] is True
    # 값이 N/A 인 칸만 None 이 되고 행은 살아남는다
    assert rows[2]["change_pct"] is None and rows[2]["volume"] is None
    assert rows[2]["last"] == 1730000.0


def test_ranking_builds_path(monkeypatch):
    seen = {}
    def fake(path, params=None):
        seen["path"], seen["params"] = path, params
        return _ranking_payload()
    monkeypatch.setattr(naver, "_get", fake)
    naver.ranking("marketValue", "KOSDAQ", 50)
    assert seen["path"] == "/stocks/marketValue/KOSDAQ"
    assert seen["params"] == {"page": 1, "pageSize": 50}


def test_ranking_rejects_unknown_kind():
    with pytest.raises(ValueError):
        naver.ranking("../secret", "KOSPI", 5)


def test_investor_trend(monkeypatch):
    monkeypatch.setattr(naver, "_get", lambda path, params=None: {
        "bizdate": "20260821", "personalValue": "-11,652",
        "foreignValue": "-1,760", "institutionalValue": "+2,481"})
    d = naver.investor_trend("KOSPI")
    assert d == {"date": "2026-08-21", "personal": -11652.0,
                 "foreign": -1760.0, "institution": 2481.0}


def test_market_index(monkeypatch):
    monkeypatch.setattr(naver, "_get_front", lambda path, params=None: {
        "isSuccess": True,
        "result": {"closePrice": "1,388.00", "fluctuations": "-6.80",
                   "fluctuationsRatio": "-0.49",
                   "localTradedAt": "2026-08-22T08:50:38+09:00"}})
    d = naver.market_index("exchange", "FX_USDKRW")
    assert d["last"] == 1388.0 and d["change"] == -6.8 and d["change_pct"] == -0.49
    assert d["prev_close"] == pytest.approx(1394.8)
    assert d["traded_at"] == "2026-08-22T08:50:38+09:00"


def test_market_index_raises_when_not_success(monkeypatch):
    """isSuccess=false 를 그냥 파싱하면 전부 None 인 행이 화면에 남는다 —
    예외로 올려 블록을 failed 로 떨어뜨린다."""
    monkeypatch.setattr(naver, "_get_front", lambda path, params=None:
                        {"isSuccess": False, "message": "nope", "result": None})
    with pytest.raises(ValueError):
        naver.market_index("bond", "KR3YT=RR")


@pytest.mark.smoke
def test_smoke_naver_market_endpoints():
    """비공식 API 스키마 변경 감지용. 기본 실행에서는 제외된다."""
    assert naver.index_basic("KOSPI")["last"] is not None
    rows = naver.ranking("up", "KOSPI", 2)
    assert len(rows) == 2 and rows[0]["symbol"].isalnum()
    assert naver.investor_trend("KOSPI")["date"]
    assert naver.market_index("exchange", "FX_USDKRW")["last"] is not None
    assert naver.market_index("bond", "KR3YT=RR")["last"] is not None
