"""유니버스 구성 — 무엇을 세는 목록인지가 breadth·패턴·실적·인사이더 전부를 좌우한다."""
import pandas as pd
import pytest

from app import market_fetch, market_history


@pytest.fixture(autouse=True)
def fresh():
    market_history.reset_cache()
    yield
    market_history.reset_cache()


def _listing(rows):
    return [{"symbol": c, "name": n, "market": m, "marcap": cap, "change_pct": 0.0}
            for c, n, m, cap in rows]


def test_kr_universe_drops_preferred_and_konex(monkeypatch):
    monkeypatch.setattr(market_fetch, "krx_listing", lambda: _listing([
        ("005930", "삼성전자", "KOSPI", 9e14),
        ("005935", "삼성전자우", "KOSPI", 2e14),     # 우선주 — 같은 회사가 두 번 세진다
        ("006800", "미래에셋증권", "KOSPI", 5e12),   # 이름이 '우'로 끝나지만 보통주
        ("900110", "이스트아시아홀딩스", "KONEX", 1e10),
    ]))
    monkeypatch.setattr(market_fetch, "daily_closes_matrix",
                        lambda syms, period="1y": pd.DataFrame(
                            {s: [1.0, 2.0] for s in syms},
                            index=pd.bdate_range(end="2026-08-21", periods=2)))
    h = market_history.history("KR", now=0.0)
    assert [r["symbol"] for r in h["rows"]] == ["005930", "006800"]
    # 야후 심볼은 시장별 접미사, 화면 심볼은 6자리 코드 — 열 이름은 화면 쪽이어야 한다
    assert h["rows"][0]["yf"] == "005930.KS"
    assert list(h["closes"].columns) == ["005930", "006800"]
    assert h["as_of"] == "2026-08-21" and h["label"].endswith("200")


def test_us_universe_puts_large_caps_first(monkeypatch):
    monkeypatch.setattr(market_fetch, "sp500_listing", lambda: [
        {"symbol": "AOS", "name": "A.O. Smith"}, {"symbol": "NVDA", "name": "NVIDIA"},
        {"symbol": "MMM", "name": "3M"}, {"symbol": "AAPL", "name": "Apple"}])
    monkeypatch.setattr(market_fetch, "daily_closes_matrix",
                        lambda syms, period="1y": pd.DataFrame(
                            {s: [1.0] for s in syms}, index=pd.bdate_range(end="2026-08-21", periods=1)))
    h = market_history.history("US", now=0.0)
    # 알파벳순(AOS…)이면 실적·인사이더가 보는 상위 N 이 이름 빠른 종목이 된다
    assert [r["symbol"] for r in h["rows"]][:2] == ["NVDA", "AAPL"]


def test_history_is_shared_within_ttl(monkeypatch):
    calls = []
    monkeypatch.setattr(market_fetch, "krx_listing", lambda: (
        calls.append(1) or _listing([("005930", "삼성전자", "KOSPI", 9e14)])))
    monkeypatch.setattr(market_fetch, "daily_closes_matrix",
                        lambda syms, period="1y": pd.DataFrame(
                            {s: [1.0] for s in syms}, index=pd.bdate_range(end="2026-08-21", periods=1)))
    market_history.history("KR", now=0.0)
    market_history.history("KR", now=60.0)          # breadth 다음에 patterns 가 부른다
    assert len(calls) == 1
    market_history.history("KR", now=market_history.TTL_SEC + 1)
    assert len(calls) == 2


def test_empty_result_is_not_cached(monkeypatch):
    """소스가 잠깐 막힌 날 빈 화면이 30분 굳지 않게."""
    monkeypatch.setattr(market_fetch, "krx_listing", lambda: [])
    monkeypatch.setattr(market_fetch, "daily_closes_matrix",
                        lambda syms, period="1y": pd.DataFrame())
    h = market_history.history("KR", now=0.0)
    assert h["as_of"] is None
    monkeypatch.setattr(market_fetch, "krx_listing",
                        lambda: _listing([("005930", "삼성전자", "KOSPI", 9e14)]))
    monkeypatch.setattr(market_fetch, "daily_closes_matrix",
                        lambda syms, period="1y": pd.DataFrame(
                            {s: [1.0] for s in syms}, index=pd.bdate_range(end="2026-08-21", periods=1)))
    assert market_history.history("KR", now=1.0)["rows"]
