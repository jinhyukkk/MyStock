"""대시보드의 실데이터 블록 — breadth·패턴·경제지표·실적·인사이더.

유니버스와 일봉은 conftest 의 `fake_market_universe` 가 합성값으로 바꿔 놓는다.
여기서 보는 것은 **블록이 화면에 나갈 모양**과 **키 없는 소스의 안내**다.
"""
from datetime import date, timedelta

import pytest

from app import market, market_calendar, market_fetch, market_insider
from app.sources import dart, ecos, fred


@pytest.fixture(autouse=True)
def fresh_cache():
    market.reset_cache()
    yield
    market.reset_cache()


@pytest.fixture(autouse=True)
def stub_kr_sources(monkeypatch):
    """KR 대시보드의 네이버 블록 — 여기서 볼 대상이 아니라 최소값으로 채운다."""
    from app.sources import naver
    monkeypatch.setattr(market_fetch, "intraday",
                        lambda sym: {"last": 1.0, "prev_close": 1.0, "candles": []})
    monkeypatch.setattr(market_fetch, "daily_closes", lambda syms: {})
    monkeypatch.setattr(market_fetch, "news", lambda sym, limit=8: [])
    monkeypatch.setattr(naver, "index_basic", lambda code: {})
    monkeypatch.setattr(naver, "market_index", lambda cat, code: {})
    monkeypatch.setattr(naver, "ranking", lambda kind, mkt, n: [])
    monkeypatch.setattr(naver, "investor_trend",
                        lambda m: {"date": None, "personal": None, "foreign": None,
                                   "institution": None})


def _kr(monkeypatch, now=1000.0):
    # 백그라운드 갱신이 응답을 만드는 도중에 느린 블록을 채우면 검증이 흔들린다
    monkeypatch.setattr(market, "_refresh_in_background", lambda m: None)
    return market.get_market("KR", now=now)


def test_breadth_block_carries_universe_label(monkeypatch):
    m = _kr(monkeypatch)
    assert m["breadth"]["universe"] == "코스피·코스닥 시총 200"
    assert m["breadth"]["as_of"] == "2026-08-21"
    # 합성 일봉이 우상향이라 세 종목 모두 상승·SMA 위
    assert m["breadth"]["bars"][0]["left_n"] == 3
    assert {b["center"] for b in m["breadth"]["bars"]} == {None, "52주", "SMA50", "SMA200"}


def test_patterns_block_lists_detected_signals(monkeypatch):
    m = _kr(monkeypatch)
    rows = m["patterns"]["rows"]
    assert rows and all({"signal", "icon", "tickers"} <= set(r) for r in rows)
    assert m["patterns"]["universe"] == "코스피·코스닥 시총 200"
    # 종목 칸은 화면 링크에 쓰는 6자리 코드여야 한다(`005930.KS` 면 클릭이 깨진다)
    assert rows[0]["tickers"][0]["symbol"] == "005930"


def test_slow_blocks_are_empty_on_first_visit(monkeypatch):
    """실적·인사이더는 종목마다 외부 호출이라 첫 화면을 붙잡지 않는다."""
    m = _kr(monkeypatch)
    assert m["earnings"] == {} and m["insider"] == {}
    assert m["breadth"]["bars"]          # 반대로 일봉 기반 블록은 첫 화면에 나온다


def test_slow_blocks_fill_in_on_refresh(monkeypatch):
    _kr(monkeypatch)
    market.refresh("KR", force=True, now=2000.0)
    m = _kr(monkeypatch, now=2000.0)
    assert m["earnings"]["status"] == "ok"
    assert m["insider"]["status"] == "unavailable"   # DART 키 없음(conftest)


def test_econ_kr_without_key_explains_why(monkeypatch):
    m = _kr(monkeypatch)
    assert m["econ"]["status"] == "unavailable"
    assert "ECOS_API_KEY" in m["econ"]["note"] and m["econ"]["rows"] == []


def test_econ_kr_picks_key_indicators(monkeypatch):
    monkeypatch.setattr(ecos, "available", lambda: True)
    monkeypatch.setattr(ecos, "key_statistics", lambda: [
        {"category": "통화", "name": "M2(평잔)", "value": "4000", "unit": "십억원", "period": "202606"},
        {"category": "금리", "name": "한국은행 기준금리", "value": "2.5", "unit": "연%", "period": "20260814"},
        {"category": "물가", "name": "소비자물가지수", "value": "116.2", "unit": "2020=100", "period": "202607"},
    ])
    out = market_calendar.econ("KR")
    assert out["status"] == "ok" and out["kind"] == "indicator"
    # 키워드 순서(기준금리 → 소비자물가 → …)가 ECOS 응답 순서보다 앞선다
    assert [r["name"] for r in out["rows"]][:2] == ["한국은행 기준금리", "소비자물가지수"]
    assert out["rows"][0]["date"] == "2026-08-14"     # CYCLE 8자리 → 날짜
    assert out["rows"][1]["date"] == "2026-07"        # 6자리 → 월


def test_econ_us_lists_release_schedule(monkeypatch):
    monkeypatch.setattr(fred, "available", lambda: True)
    monkeypatch.setattr(fred, "release_dates", lambda **k: [
        {"date": "2026-08-24", "name": "Advance Monthly Retail Sales"}])
    out = market_calendar.econ("US")
    assert out["kind"] == "release"
    # 예상치·실제치는 무료 소스에 없다 — 칸을 지어내지 않고 비운다
    assert out["rows"][0] == {"date": "2026-08-24", "name": "Advance Monthly Retail Sales",
                              "value": None, "unit": None}


def test_earnings_groups_by_date_and_skips_far_future(monkeypatch):
    today = date(2026, 8, 22)
    when = {"A": today + timedelta(days=2), "B": today + timedelta(days=2),
            "C": today + timedelta(days=200), "D": today - timedelta(days=5)}
    monkeypatch.setattr(market_fetch, "earnings_date",
                        lambda sym: when[sym].isoformat())
    rows = [{"symbol": s, "name": s, "yf": s} for s in ("A", "B", "C", "D")]
    out = market_calendar.earnings(rows, today=today)
    assert out["scope"] == "상위 4종목"
    # 지난 발표(D)와 반년 뒤(C)는 빠지고, 같은 날 둘은 한 줄로 묶인다
    assert len(out["rows"]) == 1
    assert [t["symbol"] for t in out["rows"][0]["tickers"]] == ["A", "B"]


def test_earnings_keeps_only_nearest_dates(monkeypatch):
    today = date(2026, 8, 22)
    monkeypatch.setattr(market_fetch, "earnings_date",
                        lambda sym: (today + timedelta(days=int(sym))).isoformat())
    rows = [{"symbol": str(i), "name": str(i), "yf": str(i)} for i in range(1, 12)]
    out = market_calendar.earnings(rows, today=today)
    assert len(out["rows"]) == market_calendar.EARNINGS_DATES
    assert out["rows"][0]["date"] == (today + timedelta(days=1)).isoformat()


def test_earnings_survives_one_broken_symbol(monkeypatch):
    today = date(2026, 8, 22)

    def flaky(sym):
        if sym == "A":
            raise RuntimeError("yahoo down")
        return (today + timedelta(days=1)).isoformat()

    monkeypatch.setattr(market_fetch, "earnings_date", flaky)
    rows = [{"symbol": s, "name": s, "yf": s} for s in ("A", "B")]
    out = market_calendar.earnings(rows, today=today)
    assert [t["symbol"] for t in out["rows"][0]["tickers"]] == ["B"]


def test_insider_us_sorts_latest_and_top():
    rows = [{"symbol": "AAPL", "name": "Apple", "yf": "AAPL"}]
    out = market_insider.insider("US", rows)
    assert out["status"] == "ok" and out["top_label"] == "거래대금 상위"
    assert out["latest"][0]["symbol"] == "AAPL" and out["latest"][0]["price"] == 50.0
    # 유니버스 전체가 아니라 상위 N 만 훑었다는 사실이 화면까지 가야 한다
    assert out["scope"] == "상위 1종목"


def test_insider_kr_uses_dart_and_has_no_price(monkeypatch):
    monkeypatch.setattr(dart, "available", lambda: True)
    monkeypatch.setattr(dart, "elestock", lambda code: [
        {"rcept_dt": "20260818", "repror": "홍길동", "isu_exctv_ofcps": "대표이사",
         "chnge_rsn": "장내매수", "chnge_qy": "1,000", "rcept_no": "20260818000123"}])
    out = market_insider.insider("KR", [{"symbol": "005930", "name": "삼성전자", "yf": "005930.KS"}])
    row = out["latest"][0]
    assert (row["date"], row["shares"], row["transaction"]) == ("2026-08-18", 1000.0, "장내매수")
    # 소유보고에는 단가·금액이 없다 — 0 으로 채우면 무상 취득으로 읽힌다
    assert row["price"] is None and row["value"] is None
    assert out["top_label"] == "변동 수량 상위" and out["top"][0]["shares"] == 1000.0


def test_insider_kr_without_key_explains_why():
    out = market_insider.insider("KR", [{"symbol": "005930", "name": "삼성전자", "yf": "005930.KS"}])
    assert out["status"] == "unavailable" and "DART_API_KEY" in out["note"]
