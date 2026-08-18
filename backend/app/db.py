import sqlite3
import threading
from pathlib import Path

import pandas as pd

DEFAULT_DB = str(Path(__file__).parent.parent / "mystock.db")
_SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


def get_conn(db_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DEFAULT_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # 연결이 스레드마다 따로 열리므로 동시 접근은 sqlite에 맡긴다.
    # WAL이면 읽기가 쓰기를 막지 않고, busy_timeout이 락 경합을 재시도로 흡수한다.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_SCHEMA)
    # 기존 DB 마이그레이션 — CREATE IF NOT EXISTS는 컬럼 추가를 못 하므로 여기서 보강
    cols = [r[1] for r in conn.execute("PRAGMA table_info(trades)")]
    for col, decl in (("fx_rate", "REAL"), ("note", "TEXT"), ("grade_at_trade", "TEXT"),
                      ("fee", "REAL"), ("tax", "REAL"), ("executed_at", "TEXT"),
                      ("exclude_from_stats", "INTEGER NOT NULL DEFAULT 0")):
        if col not in cols:
            conn.execute(f"ALTER TABLE trades ADD COLUMN {col} {decl}")
    if "ext_key" not in [r[1] for r in conn.execute("PRAGMA table_info(cash_flows)")]:
        conn.execute("ALTER TABLE cash_flows ADD COLUMN ext_key TEXT")
    # ALTER는 UNIQUE를 못 붙이므로 인덱스로 건다. schema.sql이 아니라 여기서 만드는 건
    # 기존 DB에서는 위 ALTER가 끝난 뒤라야 컬럼이 존재하기 때문이다.
    # (NULL은 중복이 허용되므로 손으로 적은 현금흐름은 영향받지 않는다)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_cash_flows_ext "
                 "ON cash_flows(ext_key)")
    conn.commit()
    return conn


class ThreadLocalDB:
    """스레드마다 sqlite 연결을 따로 준다.

    sqlite3.Connection 객체 하나를 여러 스레드가 동시에 쓰면 파이썬 인터프리터가
    세그폴트로 죽는다(check_same_thread=False는 그 검사를 끌 뿐 안전하게 만들지 않는다).
    FastAPI는 `def` 엔드포인트를 스레드풀에서 실행하므로, 종목 상세 화면이
    상세와 백테스트를 동시에 요청하는 것만으로 그 조건이 성립한다.
    """

    def __init__(self, db_path: str | None = None):
        self._path = db_path
        self._local = threading.local()
        self._all: list[sqlite3.Connection] = []
        self._lock = threading.Lock()

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = get_conn(self._path)
            self._local.conn = c
            with self._lock:
                self._all.append(c)  # 종료 시 한 번에 닫으려고 모아둔다
        return c

    def close_all(self) -> None:
        with self._lock:
            for c in self._all:
                try:
                    c.close()
                except Exception:
                    pass  # 이미 닫혔거나 소유 스레드가 끝난 연결은 무시
            self._all.clear()
        self._local = threading.local()


def upsert_ticker(conn, symbol, market, name, is_etf=0, in_watchlist=0,
                  yf_symbol=None, currency="KRW"):
    conn.execute(
        """INSERT INTO tickers (symbol, market, name, is_etf, in_watchlist, yf_symbol, currency)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(symbol) DO UPDATE SET
             name=excluded.name, is_etf=excluded.is_etf,
             in_watchlist=max(tickers.in_watchlist, excluded.in_watchlist)""",
        (symbol, market, name, is_etf, in_watchlist, yf_symbol, currency))
    conn.commit()


def list_tickers(conn, watchlist_only=False):
    q = "SELECT * FROM tickers"
    if watchlist_only:
        q += " WHERE in_watchlist=1"
    return conn.execute(q + " ORDER BY market, name").fetchall()


def get_ticker(conn, symbol):
    return conn.execute("SELECT * FROM tickers WHERE symbol=?", (symbol,)).fetchone()


def set_watchlist(conn, symbol, flag: int):
    conn.execute("UPDATE tickers SET in_watchlist=? WHERE symbol=?", (flag, symbol))
    conn.commit()


def remove_from_watchlist(conn, symbol):
    set_watchlist(conn, symbol, 0)


def insert_trade(conn, symbol, side, quantity, price, trade_date, fx_rate=None,
                 note=None, grade_at_trade=None, fee=None, tax=None,
                 executed_at=None, exclude_from_stats=0) -> int:
    cur = conn.execute(
        """INSERT INTO trades (symbol, side, quantity, price, trade_date, executed_at,
                               fx_rate, fee, tax, note, grade_at_trade, exclude_from_stats)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (symbol, side, quantity, price, trade_date, executed_at, fx_rate, fee, tax,
         note, grade_at_trade, int(exclude_from_stats)))
    conn.commit()
    return cur.lastrowid


# 시각 미기록(과거 행)은 입력 순서(id)로 폴백 — 빈 문자열이 어떤 시각보다 앞선다
_TRADE_ORDER = "ORDER BY trade_date, COALESCE(executed_at, ''), id"


def list_trades(conn, symbol=None):
    if symbol:
        return conn.execute(
            "SELECT * FROM trades WHERE symbol=? " + _TRADE_ORDER, (symbol,)).fetchall()
    return conn.execute("SELECT * FROM trades " + _TRADE_ORDER).fetchall()


def get_trade(conn, trade_id):
    return conn.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()


def delete_trade(conn, trade_id):
    conn.execute("DELETE FROM trades WHERE id=?", (trade_id,))
    conn.commit()


def insert_cash_flow(conn, flow_type, amount, flow_date, symbol=None, currency="KRW",
                     tax=0.0, fx_rate=None, note=None, ext_key=None) -> int:
    cur = conn.execute(
        """INSERT INTO cash_flows (flow_type, symbol, currency, amount, tax,
                                   flow_date, fx_rate, note, ext_key)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (flow_type, symbol, currency, amount, tax, flow_date, fx_rate, note, ext_key))
    conn.commit()
    return cur.lastrowid


def cash_flow_ext_keys(conn) -> set:
    """이미 가져온 증권사 거래의 키 — 재조회 시 중복 적재를 막는다."""
    return {r[0] for r in
            conn.execute("SELECT ext_key FROM cash_flows WHERE ext_key IS NOT NULL")}


def list_cash_flows(conn, symbol=None, flow_type=None):
    q, params = "SELECT * FROM cash_flows", []
    where = []
    if symbol:
        where.append("symbol=?"); params.append(symbol)
    if flow_type:
        where.append("flow_type=?"); params.append(flow_type)
    if where:
        q += " WHERE " + " AND ".join(where)
    return conn.execute(q + " ORDER BY flow_date DESC, id DESC", params).fetchall()


def get_cash_flow(conn, flow_id):
    return conn.execute("SELECT * FROM cash_flows WHERE id=?", (flow_id,)).fetchone()


def update_cash_flow_symbol(conn, flow_id, symbol):
    """배당의 귀속 종목만 바꾼다.

    금액·통화·환율은 입금 시점의 사실이라 건드리지 않는다 — 종목을 붙였다고 원화로
    들어온 배당이 달러가 되지는 않는다.
    """
    conn.execute("UPDATE cash_flows SET symbol=? WHERE id=?", (symbol, flow_id))
    conn.commit()


def delete_cash_flow(conn, flow_id):
    conn.execute("DELETE FROM cash_flows WHERE id=?", (flow_id,))
    conn.commit()


def insert_rule(conn, symbol, rule_type, value) -> int:
    cur = conn.execute(
        "INSERT INTO custom_rules (symbol, rule_type, value) VALUES (?,?,?)",
        (symbol, rule_type, value))
    conn.commit()
    return cur.lastrowid


def list_rules(conn, symbol=None):
    if symbol:
        return conn.execute("SELECT * FROM custom_rules WHERE symbol=?", (symbol,)).fetchall()
    return conn.execute("SELECT * FROM custom_rules").fetchall()


def delete_rule(conn, rule_id):
    conn.execute("DELETE FROM custom_rules WHERE id=?", (rule_id,))
    conn.commit()


def save_prices(conn, symbol, df: pd.DataFrame):
    rows = [(symbol, idx.strftime("%Y-%m-%d"),
             float(r["open"]), float(r["high"]), float(r["low"]),
             float(r["close"]), float(r["volume"]))
            for idx, r in df.iterrows()]
    conn.executemany(
        """INSERT INTO price_cache (symbol, date, open, high, low, close, volume)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(symbol, date) DO UPDATE SET
             open=excluded.open, high=excluded.high, low=excluded.low,
             close=excluded.close, volume=excluded.volume""", rows)
    conn.commit()


def load_prices(conn, symbol, limit=400) -> pd.DataFrame:
    rows = conn.execute(
        """SELECT date, open, high, low, close, volume FROM
             (SELECT * FROM price_cache WHERE symbol=? ORDER BY date DESC LIMIT ?)
           ORDER BY date ASC""", (symbol, limit)).fetchall()
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame([dict(r) for r in rows])
    df.index = pd.to_datetime(df.pop("date"))
    return df


def save_signal(conn, symbol, date_str, swing_score, longterm_score, grade, details_json):
    conn.execute(
        """INSERT INTO signal_history (symbol, date, swing_score, longterm_score, grade, details)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(symbol, date) DO UPDATE SET
             swing_score=excluded.swing_score, longterm_score=excluded.longterm_score,
             grade=excluded.grade, details=excluded.details""",
        (symbol, date_str, swing_score, longterm_score, grade, details_json))
    conn.commit()


def load_signal_history(conn, symbol, limit=90):
    return conn.execute(
        "SELECT * FROM signal_history WHERE symbol=? ORDER BY date DESC LIMIT ?",
        (symbol, limit)).fetchall()


def get_latest_signal(conn, symbol):
    rows = load_signal_history(conn, symbol, limit=1)
    return rows[0] if rows else None


def get_prev_grade(conn, symbol):
    rows = load_signal_history(conn, symbol, limit=2)
    return rows[1]["grade"] if len(rows) > 1 else None


def set_meta(conn, key, value):
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value))
    conn.commit()


def get_meta(conn, key):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def replace_broker_holdings(conn, rows: list[dict], synced_at: str):
    """증권사 스냅샷을 통째로 갈아끼운다.

    부분 갱신(upsert)만 하면 증권사에서 이미 전량 매도된 종목이 표에 남아
    화면에 유령 보유로 계속 뜬다 — 스냅샷은 전체가 한 시점의 사실이어야 한다.
    """
    conn.execute("DELETE FROM broker_holdings")
    conn.executemany(
        """INSERT INTO broker_holdings (symbol, name, quantity, avg_price, currency,
                                        account, basis_missing, synced_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        [(r["symbol"], r.get("name"), r["quantity"], r["avg_price"],
          r.get("currency", "KRW"), r.get("account"),
          int(bool(r.get("basis_missing"))), synced_at) for r in rows])
    conn.commit()


def list_broker_holdings(conn):
    return conn.execute("SELECT * FROM broker_holdings ORDER BY symbol").fetchall()


def clear_broker_holdings(conn):
    conn.execute("DELETE FROM broker_holdings")
    conn.commit()
