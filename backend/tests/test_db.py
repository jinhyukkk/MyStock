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

# ── auto_positions 마이그레이션 ─────────────────────────────────────────────
# 업그레이드 전에 열린 포지션의 계좌 평단은 수동 추가매수·부분매도가 섞인 값일
# 수 있다. 그걸 "실체결 평단"으로 보고 손절선을 옮기면 손절 위치가 근거 없이
# 이동한다 — 이 기능 이전의 진입은 검증할 방법이 없으므로 잠근 채로 둔다.

def _legacy_auto_positions_db(path):
    """fill_synced·mode가 없던 시절의 auto_positions를 가진 DB를 만든다."""
    import sqlite3
    c = sqlite3.connect(path)
    c.execute("""CREATE TABLE auto_positions (
                   symbol TEXT PRIMARY KEY, qty REAL NOT NULL,
                   entry_price REAL NOT NULL, stop REAL NOT NULL,
                   entry_date TEXT NOT NULL)""")
    c.execute("INSERT INTO auto_positions VALUES ('005930',10,100.0,90.0,'2026-01-05')")
    c.commit()
    c.close()


def test_migration_locks_pre_existing_auto_positions(tmp_path):
    path = str(tmp_path / "legacy.db")
    _legacy_auto_positions_db(path)
    conn = db.get_conn(path)
    row = dict(db.list_auto_positions(conn)[0])
    assert row["fill_synced"] == 1, "기존 행을 보정 대기로 두면 첫 plan()이 손절선을 옮긴다"
    assert row["mode"] is None, "진입 계좌를 알 수 없다 — NULL이 그 사실이다"
    assert row["entry_price"] == 100.0 and row["stop"] == 90.0
    conn.close()


def test_migration_does_not_relock_positions_on_later_opens(tmp_path):
    """컬럼이 이미 있으면 UPDATE를 돌리지 않는다 — 정상 포지션의 보정 대기가 지워진다."""
    path = str(tmp_path / "legacy.db")
    _legacy_auto_positions_db(path)
    db.get_conn(path).close()
    conn = db.get_conn(path)
    db.upsert_auto_position(conn, "000660", 5, 200.0, 180.0, "2026-02-01",
                            mode="paper")
    conn.close()
    conn = db.get_conn(path)  # 서버 재시작 — 마이그레이션이 다시 돈다
    rows = {r["symbol"]: dict(r) for r in db.list_auto_positions(conn)}
    assert rows["000660"]["fill_synced"] == 0
    assert rows["000660"]["mode"] == "paper"
    conn.close()
