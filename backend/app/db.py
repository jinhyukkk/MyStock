import sqlite3
from pathlib import Path

import pandas as pd

DEFAULT_DB = str(Path(__file__).parent.parent / "mystock.db")
_SCHEMA = (Path(__file__).parent / "schema.sql").read_text()


def get_conn(db_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DEFAULT_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


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


def insert_trade(conn, symbol, side, quantity, price, trade_date) -> int:
    cur = conn.execute(
        "INSERT INTO trades (symbol, side, quantity, price, trade_date) VALUES (?,?,?,?,?)",
        (symbol, side, quantity, price, trade_date))
    conn.commit()
    return cur.lastrowid


def list_trades(conn, symbol=None):
    if symbol:
        return conn.execute(
            "SELECT * FROM trades WHERE symbol=? ORDER BY trade_date, id", (symbol,)).fetchall()
    return conn.execute("SELECT * FROM trades ORDER BY trade_date, id").fetchall()


def delete_trade(conn, trade_id):
    conn.execute("DELETE FROM trades WHERE id=?", (trade_id,))
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
