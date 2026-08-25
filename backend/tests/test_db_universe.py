"""universe_prices / universe_meta 헬퍼 — 재수집 멱등성과 load 형태를 지킨다."""
import pandas as pd
import pytest

from app import db


@pytest.fixture
def conn(tmp_path):
    c = db.get_conn(str(tmp_path / "test.db"))
    yield c
    c.close()


def _df(dates, base=100.0):
    return pd.DataFrame(
        {"open": base, "high": base + 1, "low": base - 1, "close": base,
         "volume": 1000.0},
        index=pd.to_datetime(dates))


def test_save_and_load_universe_prices_roundtrip(conn):
    db.save_universe_prices(conn, "000001", _df(["2024-01-02", "2024-01-03"]))
    df = db.load_universe_prices(conn, "000001")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 2 and str(df.index[0].date()) == "2024-01-02"


def test_save_universe_prices_is_idempotent(conn):
    """재수집이 중복 행을 만들면 거래대금 중앙값이 두 배로 계산된다."""
    db.save_universe_prices(conn, "000001", _df(["2024-01-02"]))
    db.save_universe_prices(conn, "000001", _df(["2024-01-02", "2024-01-03"], base=200))
    df = db.load_universe_prices(conn, "000001")
    assert len(df) == 2
    assert df["close"].iloc[0] == 200  # 최신 수집이 이전 값을 대체한다


def test_load_universe_prices_empty(conn):
    df = db.load_universe_prices(conn, "없는종목")
    assert df.empty and list(df.columns) == ["open", "high", "low", "close", "volume"]


def test_universe_meta_upsert(conn):
    db.upsert_universe_meta(conn, "000001", "테스트", "KR", "2020-01-01", None, 0)
    db.upsert_universe_meta(conn, "000001", "테스트", "KR", "2020-01-01", "2025-06-30", 0)
    rows = [dict(r) for r in db.list_universe_meta(conn)]
    assert len(rows) == 1
    assert rows[0]["delisting_date"] == "2025-06-30"  # 폐지일 갱신이 반영된다
