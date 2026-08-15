import threading

import pandas as pd
import pytest
from app import db

@pytest.fixture
def conn(tmp_path):
    c = db.get_conn(str(tmp_path / "test.db"))
    yield c
    c.close()


def test_connection_uses_wal(conn):
    """스레드마다 연결이 따로 열리므로 동시 읽기/쓰기를 WAL로 받아낸다."""
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_thread_local_db_gives_each_thread_its_own_connection(tmp_path):
    """sqlite3 연결 하나를 여러 스레드가 동시에 쓰면 파이썬이 세그폴트로 죽는다.
    FastAPI는 동기 엔드포인트를 스레드풀에서 돌리므로 종목 상세와 백테스트가
    동시에 들어오면 그 조건이 그대로 성립한다."""
    pool = db.ThreadLocalDB(str(tmp_path / "t.db"))
    main_conn = pool.conn()
    assert pool.conn() is main_conn  # 같은 스레드는 재사용

    other: list = []
    t = threading.Thread(target=lambda: other.append(pool.conn()))
    t.start(); t.join()
    assert other[0] is not main_conn

    db.upsert_ticker(other[0], "005930", "KR", "삼성전자", in_watchlist=1)
    assert len(db.list_tickers(main_conn, watchlist_only=True)) == 1  # 같은 파일을 본다
    pool.close_all()

def test_ticker_upsert_and_watchlist(conn):
    db.upsert_ticker(conn, "005930", "KR", "삼성전자", in_watchlist=1, yf_symbol="005930.KS")
    db.upsert_ticker(conn, "005930", "KR", "삼성전자", in_watchlist=1)  # 중복 upsert 허용
    rows = db.list_tickers(conn, watchlist_only=True)
    assert len(rows) == 1 and rows[0]["name"] == "삼성전자"
    db.set_watchlist(conn, "005930", 0)
    assert db.list_tickers(conn, watchlist_only=True) == []

def test_trades_roundtrip(conn):
    db.upsert_ticker(conn, "AAPL", "US", "Apple", currency="USD")
    tid = db.insert_trade(conn, "AAPL", "BUY", 10, 150.0, "2026-01-05")
    assert len(db.list_trades(conn, "AAPL")) == 1
    db.delete_trade(conn, tid)
    assert db.list_trades(conn) == []

def test_rules_roundtrip(conn):
    db.upsert_ticker(conn, "KRW-BTC", "CRYPTO", "비트코인")
    rid = db.insert_rule(conn, "KRW-BTC", "TARGET", 200000000)
    assert db.list_rules(conn, "KRW-BTC")[0]["rule_type"] == "TARGET"
    db.delete_rule(conn, rid)
    assert db.list_rules(conn) == []

def test_price_cache_roundtrip(conn):
    idx = pd.date_range("2026-01-01", periods=3)
    df = pd.DataFrame({"open":[1,2,3],"high":[2,3,4],"low":[1,1,2],
                       "close":[2,3,3],"volume":[100,200,300]}, index=idx)
    db.save_prices(conn, "TEST", df)
    db.save_prices(conn, "TEST", df)  # 중복 저장 허용 (upsert)
    out = db.load_prices(conn, "TEST")
    assert len(out) == 3 and list(out.columns) == ["open","high","low","close","volume"]
    assert out.index[0] < out.index[-1]

def test_signal_history(conn):
    db.save_signal(conn, "TEST", "2026-01-01", 30, 10, "매수", "{}")
    db.save_signal(conn, "TEST", "2026-01-02", 65, 20, "강력매수", "{}")
    db.save_signal(conn, "TEST", "2026-01-02", 66, 21, "강력매수", "{}")  # 같은 날 upsert
    assert db.get_latest_signal(conn, "TEST")["swing_score"] == 66
    assert db.get_prev_grade(conn, "TEST") == "매수"
    assert len(db.load_signal_history(conn, "TEST")) == 2

def test_meta(conn):
    assert db.get_meta(conn, "last_refresh") is None
    db.set_meta(conn, "last_refresh", "2026-08-05T09:00:00")
    assert db.get_meta(conn, "last_refresh") == "2026-08-05T09:00:00"
