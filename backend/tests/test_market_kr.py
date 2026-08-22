"""market_kr.py — 한국 블록 조립. naver·market_fetch 를 monkeypatch 해 네트워크 없이 돈다."""
import pytest

from app import market, market_fetch, market_kr
from app.sources import naver

# conftest의 no_network_sources가 ranking/investor_trend를 막는다(I3). 이 파일의 다른
# 테스트는 그 스텁을 그대로 쓰지만, 아래 두 테스트는 함수 자체의 예외 동작(I1)을
# 검증해야 하므로 실제 구현으로 되돌려 쓴다. 모듈 로드 시점(패치 전)에 잡아 둔다.
_REAL_RANKING = naver.ranking
_REAL_INVESTOR_TREND = naver.investor_trend


@pytest.fixture(autouse=True)
def fresh_cache():
    market.reset_cache()
    yield
    market.reset_cache()


def _ok(monkeypatch):
    monkeypatch.setattr(market_fetch, "intraday", lambda sym: {
        "last": 6900.0, "prev_close": 6850.0,
        "candles": [{"o": 6850, "h": 6960, "l": 6840, "c": 6900, "v": 1000}]})
    monkeypatch.setattr(market_fetch, "daily_closes", lambda syms: {
        s: {"last": 4.5, "prev_close": 4.4} for s in syms})
    monkeypatch.setattr(market_fetch, "news", lambda sym, limit=8: [
        {"title": "kospi headline", "source": "Y", "url": "u",
         "published_at": "2026-08-21T00:00:00Z"}])
    monkeypatch.setattr(naver, "index_basic", lambda code: {
        "last": 6912.95, "prev_close": 6852.58, "change": 60.37,
        "change_pct": 0.88, "traded_at": "2026-08-21T18:59:00+09:00"})
    monkeypatch.setattr(naver, "market_index", lambda cat, code: {
        "last": 1388.0, "prev_close": 1394.8, "change": -6.8,
        "change_pct": -0.49, "traded_at": "2026-08-22T08:50:38+09:00"})
    monkeypatch.setattr(naver, "investor_trend", lambda m: {
        "date": "2026-08-21", "personal": -11652.0,
        "foreign": -1760.0, "institution": 2481.0})
    monkeypatch.setattr(naver, "ranking", lambda kind, mkt, n: [
        {"symbol": "005930", "name": "삼성전자", "last": 281500.0, "change_pct": 3.87,
         "volume": 27672192.0, "market_value": 16457274.0, "is_etf": False},
        {"symbol": "069500", "name": "KODEX 200", "last": 44120.0, "change_pct": -0.35,
         "volume": 1000000.0, "market_value": 257848.0, "is_etf": True},
        {"symbol": "005935", "name": "삼성전자우", "last": 230000.0, "change_pct": 1.2,
         "volume": 500000.0, "market_value": 1660908.0, "is_etf": False},
        {"symbol": "999999", "name": "듣보종목", "last": 1000.0, "change_pct": 0.5,
         "volume": 100.0, "market_value": 50000.0, "is_etf": False},
    ][:n])


def test_kr_indices_use_naver_price_and_yf_candles(monkeypatch):
    _ok(monkeypatch)
    m = market.get_market("KR", now=1000.0)
    assert m["market"] == "KR"
    assert m["session"] == {"tz": "Asia/Seoul", "open": "09:00", "close": "15:30"}
    names = [i["name"] for i in m["indices"]]
    assert names == ["코스피", "코스닥", "코스피 200"]
    i0 = m["indices"][0]
    assert i0["symbol"] == "^KS11"
    assert i0["last"] == 6912.95 and i0["change_pct"] == 0.88   # 가격은 네이버
    assert len(i0["candles"]) == 1                               # 캔들은 yfinance
    assert m["futures"] == []                                    # KR 선물 소스 없음


def test_kr_indices_fall_back_to_candles_when_naver_dies(monkeypatch):
    _ok(monkeypatch)
    def boom(code):
        raise RuntimeError("naver blocked")
    monkeypatch.setattr(naver, "index_basic", boom)
    m = market.get_market("KR", now=1000.0)
    assert "indices" not in m["failed"]              # 블록이 살아야 한다
    assert m["indices"][0]["last"] == 6900.0         # 5분봉에서 계산
    assert m["indices"][0]["change_pct"] == 0.73


def test_kr_indices_fail_when_both_sources_die(monkeypatch):
    _ok(monkeypatch)
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(naver, "index_basic", boom)
    monkeypatch.setattr(market_fetch, "intraday", boom)
    m = market.get_market("KR", now=1000.0)
    assert "indices" in m["failed"] and m["indices"] == []


def test_kr_heatmap_drops_etf_and_preferred(monkeypatch):
    _ok(monkeypatch)
    m = market.get_market("KR", now=1000.0)
    codes = [t["symbol"] for s in m["heatmap"] for t in s["tickers"]]
    assert "005930" in codes
    assert "069500" not in codes      # ETF
    assert "005935" not in codes      # 우선주 (코드가 0 으로 안 끝나고 이름이 '우')
    assert "999999" in codes          # 매핑 없는 종목은 남되


def test_kr_heatmap_unmapped_goes_to_기타(monkeypatch):
    _ok(monkeypatch)
    m = market.get_market("KR", now=1000.0)
    by_sector = {s["name"]: [t["symbol"] for t in s["tickers"]] for s in m["heatmap"]}
    assert "005930" in by_sector["반도체·전자부품"]
    assert "999999" in by_sector[market_kr.SECTOR_FALLBACK]
    # 칸 크기는 시총(억원)
    tk = next(t for s in m["heatmap"] for t in s["tickers"] if t["symbol"] == "005930")
    assert tk["weight"] == 16457274.0 and tk["name"] == "삼성전자"


def test_kr_heatmap_sectors_sorted_by_total_market_value(monkeypatch):
    _ok(monkeypatch)
    m = market.get_market("KR", now=1000.0)
    totals = [sum(t["weight"] for t in s["tickers"]) for s in m["heatmap"]]
    assert totals == sorted(totals, reverse=True)


def test_kr_signals_carry_name_and_label(monkeypatch):
    _ok(monkeypatch)
    m = market.get_market("KR", now=1000.0)
    r = m["signals_up"][0]
    assert r["symbol"] == "005930" and r["name"] == "삼성전자"
    assert r["signal"] == market_kr.SIGNALS_UP[0][2]
    assert {"last", "change_pct", "volume"} <= set(r)


def test_kr_investors(monkeypatch):
    _ok(monkeypatch)
    m = market.get_market("KR", now=1000.0)
    assert [r["market"] for r in m["investors"]] == ["KOSPI", "KOSDAQ"]
    assert m["investors"][0] == {"market": "KOSPI", "date": "2026-08-21",
                                 "personal": -11652.0, "foreign": -1760.0,
                                 "institution": 2481.0}


def test_kr_forex_bonds_mixes_naver_and_yf(monkeypatch):
    _ok(monkeypatch)
    m = market.get_market("KR", now=1000.0)
    names = [r["name"] for r in m["forex_bonds"]]
    assert names == [n for n, _, _, _ in market_kr.FOREX_BONDS]
    usd = m["forex_bonds"][0]
    assert usd["last"] == 1388.0 and usd["decimals"] == 2       # 네이버
    us10 = m["forex_bonds"][-1]
    assert us10["last"] == 4.5 and us10["change_pct"] == 2.27   # yfinance


def test_kr_major_news_uses_names(monkeypatch):
    _ok(monkeypatch)
    m = market.get_market("KR", now=1000.0)
    assert m["major_news"][0]["name"] is not None


def test_ranking_raises_when_stocks_key_missing(monkeypatch):
    """네이버가 200으로 스키마가 바뀐 응답(예: {"code": "error"})을 주면, 빈 리스트로
    조용히 넘어가지 않고 예외를 올려야 한다 — 그래야 상위에서 실패로 잡힌다(I1)."""
    monkeypatch.setattr(naver, "ranking", _REAL_RANKING)
    monkeypatch.setattr(naver, "_get", lambda path, params=None: {"code": "error"})
    with pytest.raises(ValueError):
        naver.ranking("up", "KOSPI", 5)


def test_investor_trend_raises_when_bizdate_missing(monkeypatch):
    """bizdate 가 없으면(스키마 변경) 예외를 올린다 — 위와 같은 이유(I1)."""
    monkeypatch.setattr(naver, "investor_trend", _REAL_INVESTOR_TREND)
    monkeypatch.setattr(naver, "_get", lambda path, params=None: {"personalValue": "1"})
    with pytest.raises(ValueError):
        naver.investor_trend("KOSPI")


def test_kr_signals_block_fails_without_wiping_previous_value(monkeypatch):
    """ranking() 이 올린 예외가 market.py 까지 전파돼 블록이 failed 에 들어가고,
    빈 리스트가 성공으로 캐시되지 않으며, 직전 성공값이 그대로 남는다 — I1 의 진짜 요점."""
    _ok(monkeypatch)
    first = market.get_market("KR", now=1000.0)
    assert first["signals_up"] != [] and "signals_up" not in first["failed"]

    def boom(kind, mkt, n):
        raise ValueError(f"naver ranking missing 'stocks': {kind}/{mkt}")
    monkeypatch.setattr(naver, "ranking", boom)
    second = market.get_market("KR", now=2000.0)   # TTL(10분) 지나 재시도
    assert "signals_up" in second["failed"]
    assert second["signals_up"] == first["signals_up"]   # 이전 값 유지, []로 안 덮인다


def test_kr_investors_block_fails_without_wiping_previous_value(monkeypatch):
    """investor_trend() 예외 전파도 signals_up 과 같은 격리를 지킨다(I1)."""
    _ok(monkeypatch)
    first = market.get_market("KR", now=1000.0)
    assert first["investors"] != [] and "investors" not in first["failed"]

    def boom(m):
        raise ValueError(f"naver investor_trend missing 'bizdate': {m}")
    monkeypatch.setattr(naver, "investor_trend", boom)
    second = market.get_market("KR", now=3000.0)   # TTL(30분) 지나 재시도
    assert "investors" in second["failed"]
    assert second["investors"] == first["investors"]   # 이전 값 유지, []로 안 덮인다


def test_sector_map_is_well_formed():
    """수기 매핑이라 오타가 나면 그 종목이 조용히 '기타'로 떨어진다 — 형태를 고정한다."""
    assert len(market_kr.SECTOR_OF) == 87       # 2026-08-22 KOSPI 시총 100 중 ETF·우선주 제외
    for code, sector in market_kr.SECTOR_OF.items():
        assert len(code) == 6, code             # 종목코드는 6자리 (0126Z0 처럼 문자가 섞이기도)
        assert sector.strip() == sector and sector, code
    # 폴백 이름을 실제 섹터로도 쓰면 "매핑 없음"과 "기타 업종"이 한 칸에 섞인다
    assert market_kr.SECTOR_FALLBACK not in set(market_kr.SECTOR_OF.values())
    # 대장주가 빠지면 히트맵 제일 큰 칸이 '기타'가 된다
    for code in ("005930", "000660", "005380", "105560"):
        assert code in market_kr.SECTOR_OF
