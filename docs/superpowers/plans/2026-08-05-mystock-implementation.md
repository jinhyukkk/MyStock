# MyStock 구현 계획 (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 한국/미국 주식·암호화폐·ETF의 매수/매도 시그널을 종합 점수와 한국어 근거로 보여주는 개인용 로컬 웹앱.

**Architecture:** Python FastAPI 백엔드가 무료 데이터 소스(FinanceDataReader, yfinance, Upbit, CNN/Alternative.me)에서 일봉·심리 데이터를 수집해 SQLite에 캐시하고, 지표 계산 → 스윙/중장기 이중 스코어링 → 시장 심리 보정을 거쳐 API로 제공한다. React(Vite) 프론트엔드 빌드 결과물을 FastAPI가 정적 서빙하여 단일 명령으로 실행한다.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, pandas, finance-datareader, yfinance, requests, pytest / React 18 + TypeScript + Vite, lightweight-charts(캔들), recharts(배분 차트)

**Spec:** `docs/superpowers/specs/2026-08-05-mystock-design.md`

## Global Constraints

- 모든 데이터 소스는 무료·API 키 불필요 (FinanceDataReader, yfinance, Upbit 공개 API, CNN 공개 엔드포인트, Alternative.me)
- 시세는 일봉만. 실시간·분봉 없음
- 단일 사용자, 로그인 없음, 로컬 실행 (`./run.sh` 하나로 기동, 포트 8000)
- 외부 소스별 독립 실패 허용 — 한 소스가 죽어도 앱은 캐시로 동작하고 실패 배지 표시
- 모든 시그널에 한국어 근거 설명 필수
- UI 하단 상시 고지: "본 시그널은 지표 기반 참고 정보이며 투자 자문이 아닙니다"
- 통화: KR/크립토는 KRW, 미국은 USD. 포트폴리오 합계는 USD→KRW 환산(yfinance `KRW=X`)
- 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` 추가

## 파일 구조 (최종 형태)

```
MyStock/
├── run.sh                      # 단일 실행 스크립트
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py             # FastAPI 앱, 라우트 등록, 정적 서빙, 갱신 스케줄러
│   │   ├── db.py               # SQLite 연결·schema·repository 함수
│   │   ├── schema.sql
│   │   ├── indicators.py       # 순수 지표 계산 (pandas)
│   │   ├── scoring.py          # 지표별 점수 → 스윙/중장기 종합 점수·등급·근거
│   │   ├── sentiment.py        # VIX / CNN F&G / Crypto F&G / VKOSPI 수집 + 보정
│   │   ├── fetchers.py         # 시장별 OHLCV·펀더멘털·심볼검색 수집
│   │   ├── portfolio.py        # 매매내역 → 보유종목·평단·손익 계산 (순수 함수)
│   │   ├── service.py          # 수집→지표→스코어 오케스트레이션, 대시보드 조립
│   │   └── api.py              # REST 라우트
│   └── tests/
│       ├── conftest.py         # OHLCV 픽스처, 임시 DB
│       ├── test_db.py
│       ├── test_indicators.py
│       ├── test_scoring.py
│       ├── test_sentiment.py
│       ├── test_fetchers.py
│       ├── test_portfolio.py
│       ├── test_service.py
│       └── test_api.py
└── frontend/
    ├── package.json, vite.config.ts, tsconfig.json, index.html
    └── src/
        ├── main.tsx, App.tsx, api.ts, types.ts, theme.css
        ├── components/ (Layout.tsx, SignalBadge.tsx, SentimentGauge.tsx, ScoreBar.tsx)
        └── pages/ (Dashboard.tsx, TickerDetail.tsx, Portfolio.tsx, Watchlist.tsx)
```

## 핵심 API 계약 (백엔드 ↔ 프론트)

- `GET /api/health` → `{"status":"ok"}`
- `GET /api/dashboard` → `{sentiment, portfolio_summary, signals[], rule_alerts[], last_refresh, failed_sources[]}`
- `GET /api/tickers/{symbol}` → `{symbol,name,market,fundamentals,signal,candles[],history[],rules[]}`
- `GET /api/search?q=` → `[{symbol,name,market,is_etf}]`
- `POST /api/watchlist {symbol,name,market,is_etf}` / `DELETE /api/watchlist/{symbol}`
- `GET /api/trades?symbol=` / `POST /api/trades {symbol,side,quantity,price,trade_date}` / `DELETE /api/trades/{id}`
- `GET /api/portfolio` → `{holdings[], totals, allocation[]}`
- `GET /api/rules?symbol=` / `POST /api/rules {symbol,rule_type,value}` / `DELETE /api/rules/{id}`
- `POST /api/refresh` → 전체 갱신 실행 후 `{refreshed:true, failed_sources[]}`

등급 규칙(공통): 점수 ≥60 `강력매수`, ≥20 `매수`, >-20 `중립`, >-60 `매도`, ≤-60 `강력매도`.

---

### Task 1: 백엔드 스캐폴드 + health 엔드포인트

**Files:**
- Create: `backend/pyproject.toml`, `backend/app/__init__.py`, `backend/app/main.py`, `backend/app/api.py`, `backend/tests/conftest.py`, `backend/tests/test_api.py`, `.gitignore`

**Interfaces:**
- Produces: FastAPI `app` 객체 (`app.main:app`), `/api/health` 엔드포인트, pytest 실행 환경

- [ ] **Step 1: 프로젝트 파일 작성**

`backend/pyproject.toml`:
```toml
[project]
name = "mystock-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "pandas>=2.0",
    "finance-datareader>=0.9.50",
    "yfinance>=0.2.40",
    "requests>=2.31",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "httpx>=0.27"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["smoke: 실제 외부 API 호출 테스트 (기본 제외)"]
addopts = "-m 'not smoke'"
```

`.gitignore` (루트):
```
__pycache__/
*.pyc
.venv/
backend/mystock.db
frontend/node_modules/
frontend/dist/
.pytest_cache/
```

`backend/app/__init__.py`: 빈 파일.

- [ ] **Step 2: 실패하는 테스트 작성**

`backend/tests/test_api.py`:
```python
from fastapi.testclient import TestClient
from app.main import app

def test_health():
    client = TestClient(app)
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
```

`backend/tests/conftest.py`:
```python
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
```

- [ ] **Step 3: 실행하여 실패 확인**

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pytest tests/test_api.py -v
```
Expected: FAIL (`app.main` 없음)

- [ ] **Step 4: 최소 구현**

`backend/app/api.py`:
```python
from fastapi import APIRouter

router = APIRouter(prefix="/api")

@router.get("/health")
def health():
    return {"status": "ok"}
```

`backend/app/main.py`:
```python
from fastapi import FastAPI
from app.api import router

app = FastAPI(title="MyStock")
app.include_router(router)
```

- [ ] **Step 5: 테스트 통과 확인 후 커밋**

Run: `cd backend && .venv/bin/pytest -v` → PASS
```bash
git add backend .gitignore && git commit -m "feat: FastAPI 백엔드 스캐폴드 + health 엔드포인트"
```

---

### Task 2: SQLite DB 계층

**Files:**
- Create: `backend/app/schema.sql`, `backend/app/db.py`, `backend/tests/test_db.py`

**Interfaces:**
- Produces (다른 태스크가 사용하는 시그니처):
  - `db.get_conn(db_path: str | None = None) -> sqlite3.Connection` (row_factory=sqlite3.Row, schema 자동 적용)
  - `db.upsert_ticker(conn, symbol, market, name, is_etf=0, in_watchlist=0, yf_symbol=None, currency="KRW")`
  - `db.list_tickers(conn, watchlist_only=False) -> list[sqlite3.Row]`
  - `db.remove_from_watchlist(conn, symbol)` / `db.set_watchlist(conn, symbol, flag: int)`
  - `db.insert_trade(conn, symbol, side, quantity, price, trade_date) -> int`
  - `db.list_trades(conn, symbol=None) -> list[Row]` / `db.delete_trade(conn, trade_id)`
  - `db.insert_rule(conn, symbol, rule_type, value) -> int` / `db.list_rules(conn, symbol=None)` / `db.delete_rule(conn, rule_id)`
  - `db.save_prices(conn, symbol, df: pd.DataFrame)` (index=DatetimeIndex, cols open/high/low/close/volume, upsert)
  - `db.load_prices(conn, symbol, limit=400) -> pd.DataFrame` (같은 형태로 복원, 날짜 오름차순)
  - `db.save_signal(conn, symbol, date_str, swing_score, longterm_score, grade, details_json)`
  - `db.load_signal_history(conn, symbol, limit=90) -> list[Row]`
  - `db.get_latest_signal(conn, symbol) -> Row | None` / `db.get_prev_grade(conn, symbol) -> str | None` (최신 이전 날짜의 grade)
  - `db.set_meta(conn, key, value)` / `db.get_meta(conn, key) -> str | None`

- [ ] **Step 1: schema.sql 작성**

`backend/app/schema.sql`:
```sql
CREATE TABLE IF NOT EXISTS tickers (
  symbol TEXT PRIMARY KEY,
  market TEXT NOT NULL CHECK (market IN ('KR','US','CRYPTO')),
  name TEXT NOT NULL,
  is_etf INTEGER NOT NULL DEFAULT 0,
  in_watchlist INTEGER NOT NULL DEFAULT 0,
  yf_symbol TEXT,
  currency TEXT NOT NULL DEFAULT 'KRW'
);
CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL REFERENCES tickers(symbol),
  side TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
  quantity REAL NOT NULL,
  price REAL NOT NULL,
  trade_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS custom_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL REFERENCES tickers(symbol),
  rule_type TEXT NOT NULL CHECK (rule_type IN ('TARGET','STOP','AVG_PCT')),
  value REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS price_cache (
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  PRIMARY KEY (symbol, date)
);
CREATE TABLE IF NOT EXISTS signal_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  symbol TEXT NOT NULL,
  date TEXT NOT NULL,
  swing_score REAL NOT NULL,
  longterm_score REAL NOT NULL,
  grade TEXT NOT NULL,
  details TEXT,
  UNIQUE (symbol, date)
);
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
```

- [ ] **Step 2: 실패하는 테스트 작성**

`backend/tests/test_db.py` — 임시 DB로 각 repository 함수의 왕복(round-trip)을 검증:
```python
import pandas as pd
import pytest
from app import db

@pytest.fixture
def conn(tmp_path):
    c = db.get_conn(str(tmp_path / "test.db"))
    yield c
    c.close()

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
```

- [ ] **Step 3: 실행하여 실패 확인** — `cd backend && .venv/bin/pytest tests/test_db.py -v` → FAIL

- [ ] **Step 4: db.py 구현**

`backend/app/db.py`:
```python
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
```

- [ ] **Step 5: 테스트 통과 확인 후 커밋**

Run: `.venv/bin/pytest tests/test_db.py -v` → PASS
```bash
git add backend/app/schema.sql backend/app/db.py backend/tests/test_db.py
git commit -m "feat: SQLite DB 계층 (tickers/trades/rules/price_cache/signal_history)"
```

---

### Task 3: 지표 계산 모듈

**Files:**
- Create: `backend/app/indicators.py`, `backend/tests/test_indicators.py`
- Modify: `backend/tests/conftest.py` (OHLCV 픽스처 추가)

**Interfaces:**
- Consumes: 없음 (순수 pandas)
- Produces: `indicators.compute_indicators(df: pd.DataFrame) -> pd.DataFrame`
  - 입력: index=DatetimeIndex, columns `open,high,low,close,volume` (최소 130행)
  - 출력: 입력 + 컬럼 `sma20, sma60, sma120, rsi, macd, macd_signal, macd_hist, bb_mid, bb_upper, bb_lower, stoch_k, stoch_d, vol_ratio, pos_52w`
  - 개별 함수: `sma(s, w)`, `rsi(s, period=14)`, `macd(s)`, `bollinger(s, w=20, k=2)`, `stochastic(h, l, c)`, `volume_ratio(v, w=20)`, `pos_52w(c)`

- [ ] **Step 1: conftest에 픽스처 추가**

`backend/tests/conftest.py`에 추가:
```python
import numpy as np
import pandas as pd
import pytest

@pytest.fixture
def ohlcv_up():
    """300일 완만한 상승 추세 + 노이즈 (결정적)."""
    rng = np.random.default_rng(42)
    n = 300
    close = 100 + np.arange(n) * 0.5 + rng.normal(0, 1.5, n).cumsum() * 0.3
    close = np.maximum(close, 10)
    high = close * (1 + rng.uniform(0.001, 0.02, n))
    low = close * (1 - rng.uniform(0.001, 0.02, n))
    open_ = (high + low) / 2
    volume = rng.uniform(1e5, 3e5, n)
    idx = pd.bdate_range("2025-05-01", periods=n)
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": volume}, index=idx)

@pytest.fixture
def ohlcv_down(ohlcv_up):
    """상승 픽스처를 뒤집은 하락 추세."""
    df = ohlcv_up.copy()
    for col in ["open", "high", "low", "close"]:
        df[col] = df[col].values[::-1]
    df[["high", "low"]] = df[["low", "high"]].values  # 뒤집으면 high/low가 바뀜
    return df
```

- [ ] **Step 2: 실패하는 테스트 작성**

`backend/tests/test_indicators.py`:
```python
import numpy as np
import pandas as pd
from app import indicators as ind

def test_sma_basic():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    out = ind.sma(s, 3)
    assert np.isnan(out.iloc[1])
    assert out.iloc[2] == 2.0 and out.iloc[4] == 4.0

def test_rsi_extremes():
    up = pd.Series(np.arange(1, 40, dtype=float))     # 계속 상승
    down = pd.Series(np.arange(40, 1, -1, dtype=float))  # 계속 하락
    assert ind.rsi(up).iloc[-1] > 95
    assert ind.rsi(down).iloc[-1] < 5

def test_rsi_range(ohlcv_up):
    r = ind.rsi(ohlcv_up["close"]).dropna()
    assert ((r >= 0) & (r <= 100)).all()

def test_macd_shape(ohlcv_up):
    out = ind.macd(ohlcv_up["close"])
    assert list(out.columns) == ["macd", "macd_signal", "macd_hist"]
    tail = out.dropna().tail(5)
    assert np.allclose(tail["macd_hist"], tail["macd"] - tail["macd_signal"])

def test_bollinger_order(ohlcv_up):
    out = ind.bollinger(ohlcv_up["close"]).dropna()
    assert (out["bb_upper"] >= out["bb_mid"]).all()
    assert (out["bb_mid"] >= out["bb_lower"]).all()

def test_stochastic_range(ohlcv_up):
    out = ind.stochastic(ohlcv_up["high"], ohlcv_up["low"], ohlcv_up["close"]).dropna()
    assert ((out >= 0) & (out <= 100)).all().all()

def test_volume_ratio(ohlcv_up):
    v = ohlcv_up["volume"].copy()
    v.iloc[-1] = v.iloc[-21:-1].mean() * 3
    assert abs(ind.volume_ratio(v).iloc[-1] - 3.0) < 0.01

def test_pos_52w(ohlcv_up):
    p = ind.pos_52w(ohlcv_up["close"]).dropna()
    assert ((p >= 0) & (p <= 1)).all()
    assert p.iloc[-1] > 0.5  # 상승 추세면 상단

def test_compute_indicators_columns(ohlcv_up):
    out = ind.compute_indicators(ohlcv_up)
    for col in ["sma20", "sma60", "sma120", "rsi", "macd", "macd_signal",
                "macd_hist", "bb_mid", "bb_upper", "bb_lower",
                "stoch_k", "stoch_d", "vol_ratio", "pos_52w"]:
        assert col in out.columns
    assert len(out) == len(ohlcv_up)
```

- [ ] **Step 3: 실행하여 실패 확인** — `.venv/bin/pytest tests/test_indicators.py -v` → FAIL

- [ ] **Step 4: indicators.py 구현**

`backend/app/indicators.py`:
```python
import pandas as pd


def sma(s: pd.Series, window: int) -> pd.Series:
    return s.rolling(window).mean()


def rsi(s: pd.Series, period: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, min_periods=period).mean()
    rs = gain / loss.replace(0, 1e-10)
    return 100 - 100 / (1 + rs)


def macd(s: pd.Series, fast=12, slow=26, signal=9) -> pd.DataFrame:
    line = s.ewm(span=fast, min_periods=fast).mean() - s.ewm(span=slow, min_periods=slow).mean()
    sig = line.ewm(span=signal, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig})


def bollinger(s: pd.Series, window=20, k=2) -> pd.DataFrame:
    mid = s.rolling(window).mean()
    std = s.rolling(window).std()
    return pd.DataFrame({"bb_mid": mid, "bb_upper": mid + k * std, "bb_lower": mid - k * std})


def stochastic(high, low, close, k_period=14, d_period=3, smooth=3) -> pd.DataFrame:
    lowest = low.rolling(k_period).min()
    highest = high.rolling(k_period).max()
    raw_k = 100 * (close - lowest) / (highest - lowest).replace(0, 1e-10)
    k = raw_k.rolling(smooth).mean()
    d = k.rolling(d_period).mean()
    return pd.DataFrame({"stoch_k": k, "stoch_d": d})


def volume_ratio(volume: pd.Series, window=20) -> pd.Series:
    return volume / volume.shift(1).rolling(window).mean()


def pos_52w(close: pd.Series) -> pd.Series:
    window = min(len(close), 252)
    lo = close.rolling(window, min_periods=60).min()
    hi = close.rolling(window, min_periods=60).max()
    return ((close - lo) / (hi - lo).replace(0, 1e-10)).clip(0, 1)


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["sma20"] = sma(df["close"], 20)
    out["sma60"] = sma(df["close"], 60)
    out["sma120"] = sma(df["close"], 120)
    out["rsi"] = rsi(df["close"])
    out = out.join(macd(df["close"]))
    out = out.join(bollinger(df["close"]))
    out = out.join(stochastic(df["high"], df["low"], df["close"]))
    out["vol_ratio"] = volume_ratio(df["volume"])
    out["pos_52w"] = pos_52w(df["close"])
    return out
```

- [ ] **Step 5: 테스트 통과 확인 후 커밋**

Run: `.venv/bin/pytest tests/test_indicators.py -v` → PASS
```bash
git add backend/app/indicators.py backend/tests/test_indicators.py backend/tests/conftest.py
git commit -m "feat: 기술적 지표 계산 모듈 (SMA/RSI/MACD/볼린저/스토캐스틱/거래량/52주)"
```

---

### Task 4: 스코어링 엔진

**Files:**
- Create: `backend/app/scoring.py`, `backend/tests/test_scoring.py`

**Interfaces:**
- Consumes: `indicators.compute_indicators` 출력 DataFrame
- Produces:
  - `scoring.grade(score: float) -> str` — 등급 규칙(공통) 적용
  - `scoring.score_ticker(df: pd.DataFrame) -> dict`:
    ```python
    {
      "swing_score": float,      # -100..100
      "longterm_score": float,   # -100..100
      "swing_grade": str, "longterm_grade": str,
      "indicator_scores": [ {"name": str, "score": float, "reason": str, "scope": "swing"|"longterm"} ],
      "summary": str,            # 한국어 근거 요약 (상위 근거 2~3개 연결)
    }
    ```
  - 데이터 부족(130행 미만) 시 `ValueError("insufficient data")` 발생

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_scoring.py`:
```python
import pytest
from app import indicators as ind
from app import scoring

def test_grade_thresholds():
    assert scoring.grade(75) == "강력매수"
    assert scoring.grade(60) == "강력매수"
    assert scoring.grade(30) == "매수"
    assert scoring.grade(0) == "중립"
    assert scoring.grade(-30) == "매도"
    assert scoring.grade(-60) == "강력매도"

def test_uptrend_scores_positive_longterm(ohlcv_up):
    result = scoring.score_ticker(ind.compute_indicators(ohlcv_up))
    assert result["longterm_score"] > 0  # 정배열 상승 추세
    assert -100 <= result["swing_score"] <= 100

def test_downtrend_scores_negative_longterm(ohlcv_down):
    result = scoring.score_ticker(ind.compute_indicators(ohlcv_down))
    assert result["longterm_score"] < 0

def test_reasons_are_korean_and_present(ohlcv_up):
    result = scoring.score_ticker(ind.compute_indicators(ohlcv_up))
    assert len(result["indicator_scores"]) >= 6
    for item in result["indicator_scores"]:
        assert item["reason"]  # 근거 설명 필수
        assert item["scope"] in ("swing", "longterm")
    assert result["summary"]

def test_insufficient_data_raises(ohlcv_up):
    with pytest.raises(ValueError):
        scoring.score_ticker(ind.compute_indicators(ohlcv_up.head(50)))
```

- [ ] **Step 2: 실행하여 실패 확인** — `.venv/bin/pytest tests/test_scoring.py -v` → FAIL

- [ ] **Step 3: scoring.py 구현**

`backend/app/scoring.py` (전체 구현 — 지표별 점수 함수는 `(score, reason)` 반환):
```python
import pandas as pd

SWING_WEIGHTS = {"rsi": 0.20, "macd": 0.20, "sma_cross": 0.20,
                 "bollinger": 0.15, "stoch": 0.15, "volume": 0.10}
LONG_WEIGHTS = {"alignment": 0.35, "pos_52w": 0.25, "trend_slope": 0.20,
                "macd": 0.10, "rsi": 0.10}


def grade(score: float) -> str:
    if score >= 60: return "강력매수"
    if score >= 20: return "매수"
    if score > -20: return "중립"
    if score > -60: return "매도"
    return "강력매도"


def _score_rsi(row):
    r = row["rsi"]
    if r < 30: return 80, f"RSI {r:.0f} — 과매도 구간 (반등 가능성)"
    if r < 40: return 40, f"RSI {r:.0f} — 약한 과매도"
    if r > 70: return -80, f"RSI {r:.0f} — 과매수 구간 (조정 주의)"
    if r > 60: return -40, f"RSI {r:.0f} — 약한 과매수"
    return 0, f"RSI {r:.0f} — 중립 구간"


def _score_macd(df):
    last = df.iloc[-1]
    hist = df["macd_hist"].tail(4)
    crossed_up = hist.iloc[0] < 0 and hist.iloc[-1] > 0
    crossed_down = hist.iloc[0] > 0 and hist.iloc[-1] < 0
    if crossed_up: return 80, "MACD가 시그널선을 상향 돌파 (매수 전환)"
    if crossed_down: return -80, "MACD가 시그널선을 하향 돌파 (매도 전환)"
    if last["macd_hist"] > 0: return 40, "MACD 히스토그램 양(+) — 상승 모멘텀 유지"
    return -40, "MACD 히스토그램 음(-) — 하락 모멘텀 유지"


def _score_sma_cross(df):
    s20, s60 = df["sma20"], df["sma60"]
    now_above = s20.iloc[-1] > s60.iloc[-1]
    was_above = s20.iloc[-6] > s60.iloc[-6]
    if now_above and not was_above: return 80, "20일선이 60일선을 상향 돌파 (골든크로스)"
    if not now_above and was_above: return -80, "20일선이 60일선을 하향 돌파 (데드크로스)"
    if now_above: return 40, "20일선 > 60일선 — 단기 상승 흐름 유지"
    return -40, "20일선 < 60일선 — 단기 하락 흐름"


def _score_bollinger(row):
    band = row["bb_upper"] - row["bb_lower"]
    pct_b = (row["close"] - row["bb_lower"]) / (band if band else 1e-10)
    if pct_b < 0.05: return 60, "볼린저밴드 하단 이탈 — 단기 과매도"
    if pct_b < 0.2: return 30, "볼린저밴드 하단 근접"
    if pct_b > 0.95: return -60, "볼린저밴드 상단 이탈 — 단기 과열"
    if pct_b > 0.8: return -30, "볼린저밴드 상단 근접"
    return 0, "볼린저밴드 중앙 부근"


def _score_stoch(row):
    k, d = row["stoch_k"], row["stoch_d"]
    if k < 20 and k > d: return 70, f"스토캐스틱 {k:.0f} — 과매도권 상향 교차"
    if k < 20: return 40, f"스토캐스틱 {k:.0f} — 과매도권"
    if k > 80 and k < d: return -70, f"스토캐스틱 {k:.0f} — 과매수권 하향 교차"
    if k > 80: return -40, f"스토캐스틱 {k:.0f} — 과매수권"
    return 0, f"스토캐스틱 {k:.0f} — 중립"


def _score_volume(df):
    row = df.iloc[-1]
    ratio = row["vol_ratio"]
    up_day = row["close"] >= df["close"].iloc[-2]
    if pd.isna(ratio): return 0, "거래량 데이터 부족"
    if ratio >= 1.8 and up_day:
        return 50, f"거래량 20일 평균 대비 {ratio*100:.0f}% 급증 + 상승 — 매수세 유입"
    if ratio >= 1.8:
        return -50, f"거래량 20일 평균 대비 {ratio*100:.0f}% 급증 + 하락 — 매도세 출회"
    return 0, f"거래량 평균 수준 ({ratio*100:.0f}%)"


def _score_alignment(row):
    c, s60, s120 = row["close"], row["sma60"], row["sma120"]
    if c > s60 > s120: return 70, "주가 > 60일선 > 120일선 — 중장기 정배열"
    if c < s60 < s120: return -70, "주가 < 60일선 < 120일선 — 중장기 역배열"
    return 0, "이동평균선 혼조 — 중장기 방향 불명확"


def _score_pos_52w(row):
    p = row["pos_52w"]
    if p < 0.2: return 50, f"52주 저점권 ({p*100:.0f}% 위치) — 저평가 구간 가능성"
    if p > 0.9: return -30, f"52주 고점권 ({p*100:.0f}% 위치) — 고점 부담"
    return 0, f"52주 범위 중간 ({p*100:.0f}% 위치)"


def _score_trend_slope(df):
    s120 = df["sma120"].dropna()
    if len(s120) < 21: return 0, "장기 추세 판단 데이터 부족"
    change = (s120.iloc[-1] - s120.iloc[-21]) / s120.iloc[-21]
    if change > 0.02: return 60, f"120일선이 최근 1개월 +{change*100:.1f}% — 장기 상승 추세"
    if change < -0.02: return -60, f"120일선이 최근 1개월 {change*100:.1f}% — 장기 하락 추세"
    return 0, "120일선 횡보 — 장기 추세 중립"


def score_ticker(df: pd.DataFrame) -> dict:
    if len(df.dropna(subset=["sma120"])) < 10:
        raise ValueError("insufficient data")
    last = df.iloc[-1]
    swing_parts = {
        "rsi": _score_rsi(last), "macd": _score_macd(df),
        "sma_cross": _score_sma_cross(df), "bollinger": _score_bollinger(last),
        "stoch": _score_stoch(last), "volume": _score_volume(df),
    }
    long_parts = {
        "alignment": _score_alignment(last), "pos_52w": _score_pos_52w(last),
        "trend_slope": _score_trend_slope(df),
        "macd": swing_parts["macd"], "rsi": swing_parts["rsi"],
    }
    swing = sum(SWING_WEIGHTS[k] * v[0] for k, v in swing_parts.items())
    longterm = sum(LONG_WEIGHTS[k] * v[0] for k, v in long_parts.items())

    names = {"rsi": "RSI", "macd": "MACD", "sma_cross": "이동평균 교차",
             "bollinger": "볼린저밴드", "stoch": "스토캐스틱", "volume": "거래량",
             "alignment": "이평선 배열", "pos_52w": "52주 위치", "trend_slope": "장기 추세"}
    indicator_scores = (
        [{"name": names[k], "score": v[0], "reason": v[1], "scope": "swing"}
         for k, v in swing_parts.items()] +
        [{"name": names[k], "score": v[0], "reason": v[1], "scope": "longterm"}
         for k, v in long_parts.items() if k in ("alignment", "pos_52w", "trend_slope")])
    top = sorted(indicator_scores, key=lambda x: abs(x["score"]), reverse=True)[:3]
    summary = ", ".join(t["reason"] for t in top if t["score"] != 0) or "뚜렷한 시그널 없음"
    return {
        "swing_score": round(swing, 1), "longterm_score": round(longterm, 1),
        "swing_grade": grade(swing), "longterm_grade": grade(longterm),
        "indicator_scores": indicator_scores, "summary": summary,
    }
```

- [ ] **Step 4: 테스트 통과 확인 후 커밋**

Run: `.venv/bin/pytest tests/test_scoring.py -v` → PASS
```bash
git add backend/app/scoring.py backend/tests/test_scoring.py
git commit -m "feat: 스윙/중장기 이중 스코어링 엔진 + 한국어 근거 생성"
```

---

### Task 5: 시장 심리 레이어 (VIX·공포탐욕)

**Files:**
- Create: `backend/app/sentiment.py`, `backend/tests/test_sentiment.py`

**Interfaces:**
- Consumes: requests, yfinance (외부 호출은 전부 함수 내부에서 — 테스트에서 monkeypatch)
- Produces:
  - `sentiment.fetch_sentiment() -> dict` — 각 소스 개별 try/except:
    ```python
    {"vix": float|None, "vkospi": float|None, "cnn_fg": int|None,
     "crypto_fg": int|None, "usdkrw": float|None, "failed": [str]}
    ```
  - `sentiment.fg_label(v: int|None) -> str` — `<25 "극단적 공포"`, `<45 "공포"`, `<=55 "중립"`, `<=75 "탐욕"`, `>75 "극단적 탐욕"`, None→"정보 없음"
  - `sentiment.adjust_score(base: float, market: str, senti: dict) -> tuple[float, str|None]`
    — 시장별 보정치와 맥락 노트. 규칙:
    - 해당 시장의 F&G(US/KR→cnn_fg, CRYPTO→crypto_fg)가 있으면 `adj = (50 - fg) / 5` (최대 ±10, 역발상 방향)
    - US/KR에서 VIX ≥ 30이면 노트에 "변동성(VIX {v}) 높음 — 신중" 추가, VIX ≤ 15면 노트 없음
    - fg < 25 & base > 0 → 노트 "시장 극단적 공포 — 역발상 매수 참고"
    - fg > 75 & base > 0 → 노트 "시장 과열 구간 — 추격 매수 신중"
    - 결과 점수는 -100..100으로 클립

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_sentiment.py`:
```python
from app import sentiment

def test_fg_label():
    assert sentiment.fg_label(10) == "극단적 공포"
    assert sentiment.fg_label(30) == "공포"
    assert sentiment.fg_label(50) == "중립"
    assert sentiment.fg_label(70) == "탐욕"
    assert sentiment.fg_label(90) == "극단적 탐욕"
    assert sentiment.fg_label(None) == "정보 없음"

def test_adjust_extreme_fear_boosts_buy():
    senti = {"vix": 35.0, "vkospi": None, "cnn_fg": 15, "crypto_fg": None, "failed": []}
    adjusted, note = sentiment.adjust_score(40, "US", senti)
    assert adjusted > 40           # 공포 = 역발상 가산
    assert "공포" in note and "VIX" in note

def test_adjust_extreme_greed_dampens_buy():
    senti = {"vix": 12.0, "vkospi": None, "cnn_fg": 85, "crypto_fg": None, "failed": []}
    adjusted, note = sentiment.adjust_score(40, "US", senti)
    assert adjusted < 40
    assert "과열" in note

def test_adjust_crypto_uses_crypto_fg():
    senti = {"vix": None, "vkospi": None, "cnn_fg": None, "crypto_fg": 20, "failed": []}
    adjusted, note = sentiment.adjust_score(0, "CRYPTO", senti)
    assert adjusted == 6.0         # (50-20)/5

def test_adjust_missing_sources_no_change():
    senti = {"vix": None, "vkospi": None, "cnn_fg": None, "crypto_fg": None, "failed": ["cnn"]}
    adjusted, note = sentiment.adjust_score(40, "US", senti)
    assert adjusted == 40 and note is None

def test_fetch_sentiment_survives_all_failures(monkeypatch):
    import requests
    def boom(*a, **k): raise requests.ConnectionError("down")
    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr(sentiment, "_fetch_yf_last", lambda t: (_ for _ in ()).throw(RuntimeError))
    out = sentiment.fetch_sentiment()
    assert out["vix"] is None and out["cnn_fg"] is None
    assert len(out["failed"]) >= 3
```

- [ ] **Step 2: 실행하여 실패 확인** — `.venv/bin/pytest tests/test_sentiment.py -v` → FAIL

- [ ] **Step 3: sentiment.py 구현**

`backend/app/sentiment.py`:
```python
import requests

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
ALT_URL = "https://api.alternative.me/fng/?limit=1"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def _fetch_yf_last(ticker: str) -> float:
    import yfinance as yf
    hist = yf.Ticker(ticker).history(period="5d")
    return float(hist["Close"].dropna().iloc[-1])


def fetch_sentiment() -> dict:
    out = {"vix": None, "vkospi": None, "cnn_fg": None, "crypto_fg": None,
           "usdkrw": None, "failed": []}
    try:
        out["vix"] = _fetch_yf_last("^VIX")
    except Exception:
        out["failed"].append("vix")
    try:
        out["usdkrw"] = _fetch_yf_last("KRW=X")
    except Exception:
        out["failed"].append("usdkrw")
    try:
        import FinanceDataReader as fdr
        out["vkospi"] = float(fdr.DataReader("VKOSPI").iloc[-1]["Close"])
    except Exception:
        out["failed"].append("vkospi")
    try:
        r = requests.get(CNN_URL, headers=_HEADERS, timeout=10)
        r.raise_for_status()
        out["cnn_fg"] = int(round(r.json()["fear_and_greed"]["score"]))
    except Exception:
        out["failed"].append("cnn")
    try:
        r = requests.get(ALT_URL, timeout=10)
        r.raise_for_status()
        out["crypto_fg"] = int(r.json()["data"][0]["value"])
    except Exception:
        out["failed"].append("crypto_fg")
    return out


def fg_label(v) -> str:
    if v is None: return "정보 없음"
    if v < 25: return "극단적 공포"
    if v < 45: return "공포"
    if v <= 55: return "중립"
    if v <= 75: return "탐욕"
    return "극단적 탐욕"


def adjust_score(base: float, market: str, senti: dict):
    fg = senti.get("crypto_fg") if market == "CRYPTO" else senti.get("cnn_fg")
    notes = []
    adjusted = base
    if fg is not None:
        adjusted = max(-100.0, min(100.0, base + (50 - fg) / 5))
        if fg < 25 and base > 0:
            notes.append("시장 극단적 공포 — 역발상 매수 참고")
        elif fg < 25:
            notes.append("시장 극단적 공포 구간")
        elif fg > 75 and base > 0:
            notes.append("시장 과열 구간 — 추격 매수 신중")
        elif fg > 75:
            notes.append("시장 과열(탐욕) 구간")
    vix = senti.get("vix")
    if market in ("US", "KR") and vix is not None and vix >= 30:
        notes.append(f"변동성(VIX {vix:.0f}) 높음 — 신중")
    return round(adjusted, 1), (" · ".join(notes) or None)
```

- [ ] **Step 4: 테스트 통과 확인 후 커밋** — PASS 후:

```bash
git add backend/app/sentiment.py backend/tests/test_sentiment.py
git commit -m "feat: 시장 심리 레이어 (VIX/VKOSPI/공포탐욕지수 수집·보정)"
```

---

### Task 6: 데이터 수집 (fetchers)

**Files:**
- Create: `backend/app/fetchers.py`, `backend/tests/test_fetchers.py`

**Interfaces:**
- Produces:
  - `fetchers.normalize_ohlcv(df, colmap) -> pd.DataFrame` — 소스별 DataFrame을 표준형(index=DatetimeIndex, `open,high,low,close,volume`)으로 변환하는 순수 함수 (단위 테스트 대상)
  - `fetchers.parse_upbit_candles(json_list) -> pd.DataFrame` — Upbit 응답 JSON → 표준형 (순수 함수)
  - `fetchers.fetch_ohlcv(symbol, market, yf_symbol=None, days=400) -> pd.DataFrame` — market 디스패치: `KR`→FinanceDataReader, `US`→yfinance, `CRYPTO`→Upbit REST. 실패 시 예외 그대로 전파 (호출측 service가 처리)
  - `fetchers.fetch_fundamentals(yf_symbol) -> dict|None` — yfinance `.info`에서 `{"per","pbr","dividend_yield","market_cap"}` (없는 값 None, 전체 실패 시 None)
  - `fetchers.search_symbols(query, conn=None) -> list[dict]` — `{symbol,name,market,is_etf,yf_symbol,currency}`
    - KR: `fdr.StockListing("KRX")` 결과(모듈 캐시)에서 이름/코드 부분일치. Market 컬럼 KOSPI→`.KS`, KOSDAQ→`.KQ`로 yf_symbol 생성. ETF는 `fdr.StockListing("ETF/KR")` 병합, is_etf=1
    - CRYPTO: Upbit `GET /v1/market/all` (모듈 캐시)에서 한글명/심볼 부분일치, KRW- 마켓만
    - US: query가 대문자 알파벳 1~5자면 yfinance로 심볼 검증(`fast_info`에 가격이 있으면 결과 포함), name은 info의 shortName 또는 심볼, currency="USD"
  - Upbit 일봉 URL: `https://api.upbit.com/v1/candles/days?market={symbol}&count=200` (200개 초과 필요 시 `to` 파라미터로 2회 페이징하여 400개 확보)

- [ ] **Step 1: 실패하는 테스트 작성 (순수 함수 + 스모크 분리)**

`backend/tests/test_fetchers.py`:
```python
import pandas as pd
import pytest
from app import fetchers

def test_normalize_ohlcv_renames_and_sorts():
    df = pd.DataFrame({"Open": [2, 1], "High": [3, 2], "Low": [1, 0.5],
                       "Close": [2.5, 1.5], "Volume": [10, 20]},
                      index=pd.to_datetime(["2026-01-02", "2026-01-01"]))
    out = fetchers.normalize_ohlcv(df, {"Open": "open", "High": "high", "Low": "low",
                                        "Close": "close", "Volume": "volume"})
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert out.index[0] < out.index[1]

def test_parse_upbit_candles():
    payload = [
        {"candle_date_time_kst": "2026-01-02T09:00:00", "opening_price": 100.0,
         "high_price": 110.0, "low_price": 90.0, "trade_price": 105.0,
         "candle_acc_trade_volume": 12.5},
        {"candle_date_time_kst": "2026-01-01T09:00:00", "opening_price": 95.0,
         "high_price": 101.0, "low_price": 94.0, "trade_price": 100.0,
         "candle_acc_trade_volume": 10.0},
    ]
    out = fetchers.parse_upbit_candles(payload)
    assert len(out) == 2
    assert out.index[0].strftime("%Y-%m-%d") == "2026-01-01"  # 오름차순
    assert out.iloc[1]["close"] == 105.0

def test_fetch_ohlcv_unknown_market():
    with pytest.raises(ValueError):
        fetchers.fetch_ohlcv("X", "LONDON")

@pytest.mark.smoke
def test_smoke_fetch_kr():
    df = fetchers.fetch_ohlcv("005930", "KR", days=30)
    assert len(df) > 10 and "close" in df.columns

@pytest.mark.smoke
def test_smoke_fetch_us():
    df = fetchers.fetch_ohlcv("AAPL", "US", yf_symbol="AAPL", days=30)
    assert len(df) > 10

@pytest.mark.smoke
def test_smoke_fetch_crypto():
    df = fetchers.fetch_ohlcv("KRW-BTC", "CRYPTO", days=30)
    assert len(df) > 10

@pytest.mark.smoke
def test_smoke_search():
    assert any(r["symbol"] == "005930" for r in fetchers.search_symbols("삼성전자"))
    assert any(r["market"] == "CRYPTO" for r in fetchers.search_symbols("비트코인"))
```

- [ ] **Step 2: 실행하여 실패 확인** — `.venv/bin/pytest tests/test_fetchers.py -v` → FAIL (smoke는 기본 제외)

- [ ] **Step 3: fetchers.py 구현**

`backend/app/fetchers.py`:
```python
from datetime import date, timedelta
from functools import lru_cache

import pandas as pd
import requests

UPBIT_CANDLES = "https://api.upbit.com/v1/candles/days"
UPBIT_MARKETS = "https://api.upbit.com/v1/market/all"


def normalize_ohlcv(df: pd.DataFrame, colmap: dict) -> pd.DataFrame:
    out = df.rename(columns=colmap)[["open", "high", "low", "close", "volume"]].copy()
    out.index = pd.to_datetime(out.index)
    out = out.sort_index()
    return out.dropna(subset=["close"]).astype(float)


def parse_upbit_candles(payload: list) -> pd.DataFrame:
    df = pd.DataFrame(payload)
    df.index = pd.to_datetime(df["candle_date_time_kst"].str[:10])
    return normalize_ohlcv(df, {"opening_price": "open", "high_price": "high",
                                "low_price": "low", "trade_price": "close",
                                "candle_acc_trade_volume": "volume"})


def fetch_ohlcv(symbol: str, market: str, yf_symbol: str | None = None,
                days: int = 400) -> pd.DataFrame:
    start = (date.today() - timedelta(days=int(days * 1.6))).isoformat()
    if market == "KR":
        import FinanceDataReader as fdr
        df = fdr.DataReader(symbol, start)
        return normalize_ohlcv(df, {"Open": "open", "High": "high", "Low": "low",
                                    "Close": "close", "Volume": "volume"})
    if market == "US":
        import yfinance as yf
        df = yf.Ticker(yf_symbol or symbol).history(start=start, auto_adjust=True)
        df.index = df.index.tz_localize(None)
        return normalize_ohlcv(df, {"Open": "open", "High": "high", "Low": "low",
                                    "Close": "close", "Volume": "volume"})
    if market == "CRYPTO":
        params = {"market": symbol, "count": 200}
        r = requests.get(UPBIT_CANDLES, params=params, timeout=10)
        r.raise_for_status()
        payload = r.json()
        if days > 200 and payload:
            to = payload[-1]["candle_date_time_utc"]
            r2 = requests.get(UPBIT_CANDLES,
                              params={"market": symbol, "count": 200, "to": to}, timeout=10)
            r2.raise_for_status()
            payload += r2.json()
        return parse_upbit_candles(payload)
    raise ValueError(f"unknown market: {market}")


def fetch_fundamentals(yf_symbol: str) -> dict | None:
    try:
        import yfinance as yf
        info = yf.Ticker(yf_symbol).info
        dy = info.get("dividendYield")
        return {
            "per": info.get("trailingPE"),
            "pbr": info.get("priceToBook"),
            "dividend_yield": round(dy, 2) if dy else None,
            "market_cap": info.get("marketCap"),
        }
    except Exception:
        return None


@lru_cache(maxsize=1)
def _krx_listing() -> pd.DataFrame:
    import FinanceDataReader as fdr
    df = fdr.StockListing("KRX")[["Code", "Name", "Market"]].dropna()
    df["is_etf"] = 0
    try:
        etf = fdr.StockListing("ETF/KR")[["Symbol", "Name"]].dropna()
        etf = etf.rename(columns={"Symbol": "Code"})
        etf["Market"] = "KOSPI"
        etf["is_etf"] = 1
        df = pd.concat([df, etf], ignore_index=True)
    except Exception:
        pass
    return df


@lru_cache(maxsize=1)
def _upbit_markets() -> list:
    r = requests.get(UPBIT_MARKETS, timeout=10)
    r.raise_for_status()
    return [m for m in r.json() if m["market"].startswith("KRW-")]


def search_symbols(query: str, conn=None) -> list[dict]:
    q = query.strip()
    results = []
    try:
        krx = _krx_listing()
        hit = krx[krx["Name"].str.contains(q, case=False, na=False) |
                  krx["Code"].str.contains(q, na=False)].head(10)
        for _, row in hit.iterrows():
            suffix = ".KQ" if row["Market"] == "KOSDAQ" else ".KS"
            results.append({"symbol": row["Code"], "name": row["Name"], "market": "KR",
                            "is_etf": int(row["is_etf"]),
                            "yf_symbol": row["Code"] + suffix, "currency": "KRW"})
    except Exception:
        pass
    try:
        for m in _upbit_markets():
            if q.lower() in m["korean_name"].lower() or q.upper() in m["market"]:
                results.append({"symbol": m["market"], "name": m["korean_name"],
                                "market": "CRYPTO", "is_etf": 0,
                                "yf_symbol": None, "currency": "KRW"})
        results = results[:20]
    except Exception:
        pass
    if q.isalpha() and q.isupper() and len(q) <= 5:
        try:
            import yfinance as yf
            t = yf.Ticker(q)
            price = t.fast_info.get("lastPrice")
            if price:
                name = (t.info.get("shortName") or q)
                is_etf = 1 if t.info.get("quoteType") == "ETF" else 0
                results.insert(0, {"symbol": q, "name": name, "market": "US",
                                   "is_etf": is_etf, "yf_symbol": q, "currency": "USD"})
        except Exception:
            pass
    return results
```

- [ ] **Step 4: 단위 테스트 통과 확인** — `.venv/bin/pytest tests/test_fetchers.py -v` → PASS

- [ ] **Step 5: 스모크 테스트 1회 실행 (네트워크 필요)**

Run: `.venv/bin/pytest tests/test_fetchers.py -m smoke -v`
Expected: PASS (외부 API 정상 시). 실패한 소스가 있으면 원인을 기록하되 구현 결함이 아니면 진행.

- [ ] **Step 6: 커밋**

```bash
git add backend/app/fetchers.py backend/tests/test_fetchers.py
git commit -m "feat: 시장별 데이터 수집 (FDR/yfinance/Upbit) + 통합 심볼 검색"
```

---

### Task 7: 포트폴리오 계산 (순수 함수)

**Files:**
- Create: `backend/app/portfolio.py`, `backend/tests/test_portfolio.py`

**Interfaces:**
- Consumes: `db.list_trades` 결과 (dict-like rows: symbol, side, quantity, price, trade_date)
- Produces:
  - `portfolio.compute_holdings(trades: list) -> dict[str, dict]` — 심볼별 `{"quantity": float, "avg_price": float}`. 평균단가법: BUY는 가중평균, SELL은 수량만 차감(평단 유지). 수량 0 이하가 되면 보유에서 제외
  - `portfolio.build_portfolio(holdings, prices: dict[str, float], tickers: dict[str, dict], usdkrw: float|None) -> dict`:
    ```python
    {"holdings": [{"symbol","name","market","currency","quantity","avg_price",
                    "close","value","pnl","pnl_pct"}],
     "totals": {"total_value_krw": float, "total_cost_krw": float,
                "total_pnl_krw": float, "total_pnl_pct": float},
     "allocation": [{"label": str, "value_krw": float}]}  # 시장별 합계
    ```
    USD 종목은 usdkrw로 환산(없으면 1400.0 기본값), value=quantity*close, pnl=(close-avg_price)*quantity

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_portfolio.py`:
```python
from app import portfolio

def T(symbol, side, qty, price, d="2026-01-01"):
    return {"symbol": symbol, "side": side, "quantity": qty, "price": price, "trade_date": d}

def test_avg_price_weighted():
    h = portfolio.compute_holdings([T("A", "BUY", 10, 100), T("A", "BUY", 10, 200)])
    assert h["A"]["quantity"] == 20 and h["A"]["avg_price"] == 150

def test_sell_keeps_avg_price():
    h = portfolio.compute_holdings([T("A", "BUY", 10, 100), T("A", "SELL", 4, 300)])
    assert h["A"]["quantity"] == 6 and h["A"]["avg_price"] == 100

def test_full_sell_removes_holding():
    h = portfolio.compute_holdings([T("A", "BUY", 10, 100), T("A", "SELL", 10, 120)])
    assert "A" not in h

def test_build_portfolio_usd_conversion():
    holdings = {"AAPL": {"quantity": 10, "avg_price": 100.0}}
    tickers = {"AAPL": {"name": "Apple", "market": "US", "currency": "USD"}}
    out = portfolio.build_portfolio(holdings, {"AAPL": 150.0}, tickers, usdkrw=1000.0)
    h = out["holdings"][0]
    assert h["pnl"] == 500.0 and h["pnl_pct"] == 50.0
    assert out["totals"]["total_value_krw"] == 1_500_000.0
    assert out["allocation"][0]["label"] == "미국 주식"

def test_build_portfolio_missing_price():
    holdings = {"A": {"quantity": 5, "avg_price": 10.0}}
    tickers = {"A": {"name": "가", "market": "KR", "currency": "KRW"}}
    out = portfolio.build_portfolio(holdings, {}, tickers, usdkrw=None)
    assert out["holdings"][0]["close"] is None  # 가격 없어도 죽지 않음
```

- [ ] **Step 2: 실행하여 실패 확인** — FAIL

- [ ] **Step 3: portfolio.py 구현**

```python
MARKET_LABELS = {"KR": "한국 주식", "US": "미국 주식", "CRYPTO": "암호화폐"}
DEFAULT_USDKRW = 1400.0


def compute_holdings(trades: list) -> dict:
    holdings: dict[str, dict] = {}
    for t in trades:
        s = t["symbol"]
        h = holdings.setdefault(s, {"quantity": 0.0, "avg_price": 0.0})
        if t["side"] == "BUY":
            total_cost = h["avg_price"] * h["quantity"] + t["price"] * t["quantity"]
            h["quantity"] += t["quantity"]
            h["avg_price"] = total_cost / h["quantity"]
        else:
            h["quantity"] -= t["quantity"]
        if h["quantity"] <= 1e-9:
            holdings.pop(s)
    return holdings


def build_portfolio(holdings: dict, prices: dict, tickers: dict, usdkrw) -> dict:
    fx = usdkrw or DEFAULT_USDKRW
    rows, alloc = [], {}
    total_value = total_cost = 0.0
    for symbol, h in holdings.items():
        info = tickers.get(symbol, {})
        currency = info.get("currency", "KRW")
        close = prices.get(symbol)
        rate = fx if currency == "USD" else 1.0
        value = pnl = pnl_pct = None
        if close is not None:
            value = close * h["quantity"]
            pnl = (close - h["avg_price"]) * h["quantity"]
            pnl_pct = round((close / h["avg_price"] - 1) * 100, 2) if h["avg_price"] else None
            total_value += value * rate
            total_cost += h["avg_price"] * h["quantity"] * rate
            label = MARKET_LABELS.get(info.get("market"), "기타")
            alloc[label] = alloc.get(label, 0.0) + value * rate
        rows.append({"symbol": symbol, "name": info.get("name", symbol),
                     "market": info.get("market"), "currency": currency,
                     "quantity": h["quantity"], "avg_price": h["avg_price"],
                     "close": close, "value": value, "pnl": pnl, "pnl_pct": pnl_pct})
    totals = {"total_value_krw": round(total_value, 0),
              "total_cost_krw": round(total_cost, 0),
              "total_pnl_krw": round(total_value - total_cost, 0),
              "total_pnl_pct": round((total_value / total_cost - 1) * 100, 2) if total_cost else 0.0}
    allocation = [{"label": k, "value_krw": round(v, 0)} for k, v in
                  sorted(alloc.items(), key=lambda x: -x[1])]
    return {"holdings": rows, "totals": totals, "allocation": allocation}
```

- [ ] **Step 4: 테스트 통과 확인 후 커밋**

```bash
git add backend/app/portfolio.py backend/tests/test_portfolio.py
git commit -m "feat: 포트폴리오 계산 (평균단가법, USD→KRW 환산, 자산 배분)"
```

---

### Task 8: 시그널 서비스 (오케스트레이션 + 갱신)

**Files:**
- Create: `backend/app/service.py`, `backend/tests/test_service.py`

**Interfaces:**
- Consumes: `db.*`, `fetchers.fetch_ohlcv/fetch_fundamentals`, `indicators.compute_indicators`, `scoring.score_ticker`, `sentiment.fetch_sentiment/adjust_score/fg_label`, `portfolio.*`
- Produces:
  - `service.refresh_all(conn) -> dict` — 등록된 모든 티커에 대해: OHLCV 수집→캐시 저장→지표→스코어→심리 보정→signal_history 저장. 심리 데이터는 meta에 JSON 저장(`sentiment`), `last_refresh`(ISO 시각) 기록. 티커별 실패는 수집해서 `{"refreshed": True, "failed_sources": [...], "failed_tickers": [...]}` 반환. **티커 하나 실패가 전체를 멈추지 않는다.**
  - `service.check_rules(conn, prices: dict, avg_prices: dict) -> list[dict]` — `{"symbol","name","rule_type","value","message"}`. TARGET: close ≥ value → "목표가 도달", STOP: close ≤ value → "손절가 도달", AVG_PCT: 평단 대비 등락률 ≥ |value| (value 부호 방향) → "평단 대비 ±N% 도달"
  - `service.get_dashboard(conn) -> dict` — API 계약의 dashboard 응답 조립. signals는 최신 signal_history + 티커 정보 + 현재가/전일比 + `grade_changed`(prev_grade와 비교) + `is_holding` + context_note. 정렬: |swing_score| 내림차순
  - `service.get_ticker_detail(conn, symbol) -> dict|None` — 캐시 시세로 캔들(지표 오버레이 컬럼 포함, 최근 200개), 최신 시그널 상세(details JSON 파싱), 히스토리, 룰, 펀더멘털(meta 캐시 `fund:{symbol}`, refresh 시 갱신)

- [ ] **Step 1: 실패하는 테스트 작성**

`backend/tests/test_service.py` — fetchers/sentiment를 monkeypatch하여 네트워크 없이 검증:
```python
import json
import pytest
from app import db, service, fetchers, sentiment

FAKE_SENTI = {"vix": 20.0, "vkospi": None, "cnn_fg": 40, "crypto_fg": 55,
              "usdkrw": 1300.0, "failed": ["vkospi"]}

@pytest.fixture
def conn(tmp_path, ohlcv_up, monkeypatch):
    c = db.get_conn(str(tmp_path / "t.db"))
    db.upsert_ticker(c, "005930", "KR", "삼성전자", in_watchlist=1, yf_symbol="005930.KS")
    db.upsert_ticker(c, "AAPL", "US", "Apple", in_watchlist=1, yf_symbol="AAPL", currency="USD")
    monkeypatch.setattr(fetchers, "fetch_ohlcv", lambda *a, **k: ohlcv_up)
    monkeypatch.setattr(fetchers, "fetch_fundamentals", lambda *a, **k: {"per": 15.0})
    monkeypatch.setattr(sentiment, "fetch_sentiment", lambda: dict(FAKE_SENTI))
    yield c
    c.close()

def test_refresh_all_stores_signals(conn):
    out = service.refresh_all(conn)
    assert out["refreshed"] is True
    assert db.get_latest_signal(conn, "005930") is not None
    assert db.get_meta(conn, "last_refresh")
    assert json.loads(db.get_meta(conn, "sentiment"))["cnn_fg"] == 40

def test_refresh_survives_single_ticker_failure(conn, monkeypatch):
    def flaky(symbol, market, **k):
        if symbol == "AAPL":
            raise RuntimeError("api down")
        return fetchers.fetch_ohlcv.__wrapped__(symbol, market) if False else None
    # 간단화: AAPL만 실패, 나머지는 기존 monkeypatch 유지
    orig = fetchers.fetch_ohlcv
    monkeypatch.setattr(fetchers, "fetch_ohlcv",
        lambda symbol, market, **k: (_ for _ in ()).throw(RuntimeError("down"))
        if symbol == "AAPL" else orig(symbol, market, **k))
    out = service.refresh_all(conn)
    assert "AAPL" in out["failed_tickers"]
    assert db.get_latest_signal(conn, "005930") is not None

def test_dashboard_shape(conn):
    service.refresh_all(conn)
    d = service.get_dashboard(conn)
    assert d["sentiment"]["cnn_fg_label"] == "공포"
    assert len(d["signals"]) == 2
    s = d["signals"][0]
    for key in ["symbol", "name", "market", "close", "change_pct", "swing_score",
                "swing_grade", "longterm_score", "longterm_grade",
                "grade_changed", "is_holding"]:
        assert key in s
    assert d["last_refresh"]

def test_rule_alerts(conn):
    service.refresh_all(conn)
    close = db.load_prices(conn, "005930").iloc[-1]["close"]
    db.insert_rule(conn, "005930", "TARGET", close * 0.9)   # 이미 도달
    db.insert_rule(conn, "005930", "STOP", close * 0.5)     # 미도달
    d = service.get_dashboard(conn)
    assert len(d["rule_alerts"]) == 1
    assert d["rule_alerts"][0]["rule_type"] == "TARGET"

def test_ticker_detail(conn):
    service.refresh_all(conn)
    detail = service.get_ticker_detail(conn, "005930")
    assert detail["name"] == "삼성전자"
    assert len(detail["candles"]) <= 200
    assert {"date", "open", "close", "sma20", "rsi", "macd"} <= set(detail["candles"][-1])
    assert detail["signal"]["swing_grade"]
    assert detail["fundamentals"] == {"per": 15.0}
    assert service.get_ticker_detail(conn, "NOPE") is None
```

- [ ] **Step 2: 실행하여 실패 확인** — FAIL

- [ ] **Step 3: service.py 구현**

```python
import json
from datetime import datetime

import pandas as pd

from app import db, fetchers, indicators, portfolio, scoring, sentiment


def refresh_all(conn) -> dict:
    senti = sentiment.fetch_sentiment()
    db.set_meta(conn, "sentiment", json.dumps(senti))
    failed_tickers = []
    for t in db.list_tickers(conn):
        try:
            df = fetchers.fetch_ohlcv(t["symbol"], t["market"],
                                      yf_symbol=t["yf_symbol"], days=400)
            db.save_prices(conn, t["symbol"], df)
            _compute_and_store_signal(conn, t, senti)
            if t["yf_symbol"]:
                fund = fetchers.fetch_fundamentals(t["yf_symbol"])
                if fund:
                    db.set_meta(conn, f"fund:{t['symbol']}", json.dumps(fund))
        except Exception:
            failed_tickers.append(t["symbol"])
    db.set_meta(conn, "last_refresh", datetime.now().isoformat(timespec="seconds"))
    return {"refreshed": True, "failed_sources": senti["failed"],
            "failed_tickers": failed_tickers}


def _compute_and_store_signal(conn, ticker_row, senti):
    df = db.load_prices(conn, ticker_row["symbol"])
    if df.empty:
        return
    enriched = indicators.compute_indicators(df)
    result = scoring.score_ticker(enriched)
    adj_swing, note = sentiment.adjust_score(
        result["swing_score"], ticker_row["market"], senti)
    result["swing_score"] = adj_swing
    result["swing_grade"] = scoring.grade(adj_swing)
    result["context_note"] = note
    date_str = df.index[-1].strftime("%Y-%m-%d")
    db.save_signal(conn, ticker_row["symbol"], date_str,
                   result["swing_score"], result["longterm_score"],
                   result["swing_grade"], json.dumps(result, ensure_ascii=False))


def _latest_close_and_change(conn, symbol):
    df = db.load_prices(conn, symbol, limit=2)
    if df.empty:
        return None, None
    close = float(df.iloc[-1]["close"])
    if len(df) < 2:
        return close, None
    prev = float(df.iloc[-2]["close"])
    return close, round((close / prev - 1) * 100, 2)


def _holdings_map(conn):
    trades = [dict(r) for r in db.list_trades(conn)]
    return portfolio.compute_holdings(trades)


def check_rules(conn, prices: dict, avg_prices: dict) -> list:
    alerts = []
    for r in db.list_rules(conn):
        symbol = r["symbol"]
        close = prices.get(symbol)
        if close is None:
            continue
        t = db.get_ticker(conn, symbol)
        name = t["name"] if t else symbol
        if r["rule_type"] == "TARGET" and close >= r["value"]:
            alerts.append({"symbol": symbol, "name": name, "rule_type": "TARGET",
                           "value": r["value"],
                           "message": f"{name} 목표가 {r['value']:,.0f} 도달 (현재 {close:,.0f})"})
        elif r["rule_type"] == "STOP" and close <= r["value"]:
            alerts.append({"symbol": symbol, "name": name, "rule_type": "STOP",
                           "value": r["value"],
                           "message": f"{name} 손절가 {r['value']:,.0f} 도달 (현재 {close:,.0f})"})
        elif r["rule_type"] == "AVG_PCT":
            avg = avg_prices.get(symbol)
            if not avg:
                continue
            change = (close / avg - 1) * 100
            v = r["value"]
            if (v > 0 and change >= v) or (v < 0 and change <= v):
                alerts.append({"symbol": symbol, "name": name, "rule_type": "AVG_PCT",
                               "value": v,
                               "message": f"{name} 평단 대비 {change:+.1f}% (조건 {v:+.0f}%)"})
    return alerts


def get_sentiment_view(conn) -> dict:
    raw = db.get_meta(conn, "sentiment")
    senti = json.loads(raw) if raw else {"vix": None, "vkospi": None,
                                         "cnn_fg": None, "crypto_fg": None,
                                         "usdkrw": None, "failed": []}
    senti["cnn_fg_label"] = sentiment.fg_label(senti.get("cnn_fg"))
    senti["crypto_fg_label"] = sentiment.fg_label(senti.get("crypto_fg"))
    return senti


def get_dashboard(conn) -> dict:
    senti = get_sentiment_view(conn)
    holdings = _holdings_map(conn)
    prices, signals = {}, []
    for t in db.list_tickers(conn):
        close, change = _latest_close_and_change(conn, t["symbol"])
        if close is not None:
            prices[t["symbol"]] = close
        sig = db.get_latest_signal(conn, t["symbol"])
        if not sig:
            continue
        details = json.loads(sig["details"]) if sig["details"] else {}
        prev_grade = db.get_prev_grade(conn, t["symbol"])
        signals.append({
            "symbol": t["symbol"], "name": t["name"], "market": t["market"],
            "currency": t["currency"], "close": close, "change_pct": change,
            "swing_score": sig["swing_score"], "swing_grade": sig["grade"],
            "longterm_score": sig["longterm_score"],
            "longterm_grade": scoring.grade(sig["longterm_score"]),
            "grade_changed": prev_grade is not None and prev_grade != sig["grade"],
            "is_holding": t["symbol"] in holdings,
            "context_note": details.get("context_note"),
            "summary": details.get("summary"),
        })
    signals.sort(key=lambda s: -abs(s["swing_score"]))
    tickers_map = {t["symbol"]: dict(t) for t in db.list_tickers(conn)}
    pf = portfolio.build_portfolio(holdings, prices, tickers_map, senti.get("usdkrw"))
    avg_prices = {s: h["avg_price"] for s, h in holdings.items()}
    return {
        "sentiment": senti,
        "portfolio_summary": {**pf["totals"], "holdings_count": len(holdings)},
        "signals": signals,
        "rule_alerts": check_rules(conn, prices, avg_prices),
        "last_refresh": db.get_meta(conn, "last_refresh"),
        "failed_sources": senti.get("failed", []),
    }


def get_ticker_detail(conn, symbol) -> dict | None:
    t = db.get_ticker(conn, symbol)
    if not t:
        return None
    df = db.load_prices(conn, symbol)
    candles = []
    if not df.empty:
        enriched = indicators.compute_indicators(df).tail(200)
        enriched = enriched.where(pd.notna(enriched), None)
        for idx, row in enriched.iterrows():
            candles.append({"date": idx.strftime("%Y-%m-%d"), **{
                k: (round(row[k], 4) if row[k] is not None else None)
                for k in ["open", "high", "low", "close", "volume", "sma20", "sma60",
                          "sma120", "bb_upper", "bb_lower", "rsi", "macd",
                          "macd_signal", "macd_hist"]}})
    sig = db.get_latest_signal(conn, symbol)
    signal = json.loads(sig["details"]) if sig and sig["details"] else None
    fund_raw = db.get_meta(conn, f"fund:{symbol}")
    return {
        "symbol": symbol, "name": t["name"], "market": t["market"],
        "currency": t["currency"], "is_etf": t["is_etf"],
        "fundamentals": json.loads(fund_raw) if fund_raw else None,
        "signal": signal, "candles": candles,
        "history": [{"date": r["date"], "swing_score": r["swing_score"],
                     "longterm_score": r["longterm_score"], "grade": r["grade"]}
                    for r in db.load_signal_history(conn, symbol)],
        "rules": [dict(r) for r in db.list_rules(conn, symbol)],
    }
```

- [ ] **Step 4: 테스트 통과 확인 후 커밋**

Run: `.venv/bin/pytest tests/test_service.py -v` → PASS. 전체 회귀: `.venv/bin/pytest -v` → PASS
```bash
git add backend/app/service.py backend/tests/test_service.py
git commit -m "feat: 시그널 서비스 (갱신 오케스트레이션, 대시보드/상세 조립, 커스텀 룰)"
```

---

### Task 9: REST API 라우트 + 백그라운드 갱신

**Files:**
- Modify: `backend/app/api.py`, `backend/app/main.py`
- Modify: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `service.*`, `db.*`, `fetchers.search_symbols`
- Produces: "핵심 API 계약" 절의 전체 엔드포인트. `app.state.conn`에 DB 연결 보관, 테스트에서 임시 DB로 교체 가능하도록 `main.create_app(db_path=None)` 팩토리 제공. 앱 시작 시(lifespan) 갱신 1회 + `asyncio.create_task`로 6시간(21600초) 주기 갱신 루프(`main.REFRESH_INTERVAL` 모듈 상수, 테스트에서 비활성화 가능하도록 `create_app(refresh_on_start=False)`)

- [ ] **Step 1: 실패하는 테스트 작성** (`test_api.py` 전면 교체)

```python
import pytest
from fastapi.testclient import TestClient
from app import db, fetchers, sentiment
from app.main import create_app

FAKE_SENTI = {"vix": 18.0, "vkospi": None, "cnn_fg": 60, "crypto_fg": 50,
              "usdkrw": 1300.0, "failed": []}

@pytest.fixture
def client(tmp_path, ohlcv_up, monkeypatch):
    monkeypatch.setattr(fetchers, "fetch_ohlcv", lambda *a, **k: ohlcv_up)
    monkeypatch.setattr(fetchers, "fetch_fundamentals", lambda *a, **k: None)
    monkeypatch.setattr(fetchers, "search_symbols",
        lambda q, conn=None: [{"symbol": "005930", "name": "삼성전자", "market": "KR",
                               "is_etf": 0, "yf_symbol": "005930.KS", "currency": "KRW"}])
    monkeypatch.setattr(sentiment, "fetch_sentiment", lambda: dict(FAKE_SENTI))
    app = create_app(db_path=str(tmp_path / "t.db"), refresh_on_start=False)
    with TestClient(app) as c:
        yield c

def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}

def test_watchlist_flow(client):
    res = client.post("/api/watchlist", json={"symbol": "005930", "name": "삼성전자",
                                              "market": "KR", "is_etf": 0,
                                              "yf_symbol": "005930.KS", "currency": "KRW"})
    assert res.status_code == 200
    client.post("/api/refresh")
    d = client.get("/api/dashboard").json()
    assert len(d["signals"]) == 1
    assert d["sentiment"]["cnn_fg"] == 60
    assert client.delete("/api/watchlist/005930").status_code == 200

def test_search(client):
    out = client.get("/api/search", params={"q": "삼성"}).json()
    assert out[0]["symbol"] == "005930"

def test_trades_and_portfolio(client):
    client.post("/api/watchlist", json={"symbol": "005930", "name": "삼성전자",
                                        "market": "KR", "is_etf": 0,
                                        "yf_symbol": "005930.KS", "currency": "KRW"})
    client.post("/api/refresh")
    res = client.post("/api/trades", json={"symbol": "005930", "side": "BUY",
                                           "quantity": 10, "price": 70000,
                                           "trade_date": "2026-01-05"})
    tid = res.json()["id"]
    pf = client.get("/api/portfolio").json()
    assert pf["holdings"][0]["quantity"] == 10
    assert client.delete(f"/api/trades/{tid}").status_code == 200

def test_rules_crud(client):
    client.post("/api/watchlist", json={"symbol": "005930", "name": "삼성전자",
                                        "market": "KR", "is_etf": 0,
                                        "yf_symbol": "005930.KS", "currency": "KRW"})
    rid = client.post("/api/rules", json={"symbol": "005930", "rule_type": "TARGET",
                                          "value": 90000}).json()["id"]
    assert len(client.get("/api/rules").json()) == 1
    assert client.delete(f"/api/rules/{rid}").status_code == 200

def test_ticker_detail_404(client):
    assert client.get("/api/tickers/NOPE").status_code == 404

def test_ticker_detail_ok(client):
    client.post("/api/watchlist", json={"symbol": "005930", "name": "삼성전자",
                                        "market": "KR", "is_etf": 0,
                                        "yf_symbol": "005930.KS", "currency": "KRW"})
    client.post("/api/refresh")
    detail = client.get("/api/tickers/005930").json()
    assert detail["signal"]["swing_grade"]
    assert len(detail["candles"]) > 0
```

- [ ] **Step 2: 실행하여 실패 확인** — FAIL

- [ ] **Step 3: api.py / main.py 구현**

`backend/app/api.py` 전면 교체:
```python
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app import db, fetchers, service

router = APIRouter(prefix="/api")


class WatchItem(BaseModel):
    symbol: str
    name: str
    market: str
    is_etf: int = 0
    yf_symbol: str | None = None
    currency: str = "KRW"


class TradeIn(BaseModel):
    symbol: str
    side: str
    quantity: float
    price: float
    trade_date: str


class RuleIn(BaseModel):
    symbol: str
    rule_type: str
    value: float


def _conn(request: Request):
    return request.app.state.conn


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/dashboard")
def dashboard(request: Request):
    return service.get_dashboard(_conn(request))


@router.post("/refresh")
def refresh(request: Request):
    return service.refresh_all(_conn(request))


@router.get("/search")
def search(q: str, request: Request):
    return fetchers.search_symbols(q)


@router.get("/tickers/{symbol}")
def ticker_detail(symbol: str, request: Request):
    out = service.get_ticker_detail(_conn(request), symbol)
    if out is None:
        raise HTTPException(404, "ticker not found")
    return out


@router.post("/watchlist")
def add_watch(item: WatchItem, request: Request):
    conn = _conn(request)
    db.upsert_ticker(conn, item.symbol, item.market, item.name,
                     is_etf=item.is_etf, in_watchlist=1,
                     yf_symbol=item.yf_symbol, currency=item.currency)
    return {"ok": True}


@router.delete("/watchlist/{symbol}")
def remove_watch(symbol: str, request: Request):
    db.remove_from_watchlist(_conn(request), symbol)
    return {"ok": True}


@router.get("/trades")
def get_trades(request: Request, symbol: str | None = None):
    return [dict(r) for r in db.list_trades(_conn(request), symbol)]


@router.post("/trades")
def add_trade(t: TradeIn, request: Request):
    conn = _conn(request)
    if not db.get_ticker(conn, t.symbol):
        raise HTTPException(400, "unknown symbol — 워치리스트에 먼저 추가하세요")
    tid = db.insert_trade(conn, t.symbol, t.side, t.quantity, t.price, t.trade_date)
    return {"id": tid}


@router.delete("/trades/{trade_id}")
def remove_trade(trade_id: int, request: Request):
    db.delete_trade(_conn(request), trade_id)
    return {"ok": True}


@router.get("/portfolio")
def get_portfolio(request: Request):
    conn = _conn(request)
    from app.service import _holdings_map, _latest_close_and_change, get_sentiment_view
    holdings = _holdings_map(conn)
    prices = {}
    for s in holdings:
        close, _ = _latest_close_and_change(conn, s)
        if close is not None:
            prices[s] = close
    tickers_map = {t["symbol"]: dict(t) for t in db.list_tickers(conn)}
    from app import portfolio as pf
    return pf.build_portfolio(holdings, prices, tickers_map,
                              get_sentiment_view(conn).get("usdkrw"))


@router.get("/rules")
def get_rules(request: Request, symbol: str | None = None):
    return [dict(r) for r in db.list_rules(_conn(request), symbol)]


@router.post("/rules")
def add_rule(r: RuleIn, request: Request):
    rid = db.insert_rule(_conn(request), r.symbol, r.rule_type, r.value)
    return {"id": rid}


@router.delete("/rules/{rule_id}")
def remove_rule(rule_id: int, request: Request):
    db.delete_rule(_conn(request), rule_id)
    return {"ok": True}
```

`backend/app/main.py` 전면 교체:
```python
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db, service
from app.api import router

REFRESH_INTERVAL = 6 * 60 * 60  # 6시간


def create_app(db_path: str | None = None, refresh_on_start: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.conn = db.get_conn(db_path)
        task = None
        if refresh_on_start:
            async def loop():
                while True:
                    try:
                        await asyncio.to_thread(service.refresh_all, app.state.conn)
                    except Exception:
                        pass
                    await asyncio.sleep(REFRESH_INTERVAL)
            task = asyncio.create_task(loop())
        yield
        if task:
            task.cancel()
        app.state.conn.close()

    app = FastAPI(title="MyStock", lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
```

- [ ] **Step 4: 테스트 통과 확인 후 커밋**

Run: `.venv/bin/pytest -v` (전체) → PASS
```bash
git add backend/app/api.py backend/app/main.py backend/tests/test_api.py
git commit -m "feat: REST API 전체 라우트 + 6시간 주기 백그라운드 갱신"
```

---

### Task 10: 프론트엔드 스캐폴드 (테마·레이아웃·API 클라이언트)

**Files:**
- Create: `frontend/` (Vite react-ts 템플릿), `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/src/theme.css`, `frontend/src/components/Layout.tsx`, `frontend/src/components/SignalBadge.tsx`, `frontend/src/components/ScoreBar.tsx`, `frontend/src/App.tsx` 교체

**Interfaces:**
- Consumes: 백엔드 API 계약 (dev 시 Vite proxy → `localhost:8000`)
- Produces: 라우팅(`/`, `/ticker/:symbol`, `/portfolio`, `/watchlist`), 공용 컴포넌트, `api.ts`의 `get<T>(path)`, `post(path, body)`, `del(path)` 함수, `types.ts`의 API 응답 타입

- [ ] **Step 1: 스캐폴드 생성**

```bash
cd frontend가 아니라 루트에서: npm create vite@latest frontend -- --template react-ts
cd frontend && npm install && npm install react-router-dom lightweight-charts recharts
```

`frontend/vite.config.ts`에 proxy 추가:
```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
```

- [ ] **Step 2: 다크 프로 테마 작성**

`frontend/src/theme.css` (기본 스타일 전체 교체 — `index.css` 내용은 삭제하고 이 파일만 import):
```css
:root {
  --bg: #0e1117; --bg-card: #161b24; --bg-hover: #1c2330;
  --border: #232a36; --text: #e6e9ef; --text-dim: #8b93a3;
  --buy: #2ecc71; --buy-strong: #00e676; --sell: #ff5252;
  --sell-strong: #ff1744; --neutral: #8b93a3; --accent: #4f8ef7;
  --font: 'Pretendard', -apple-system, 'Apple SD Gothic Neo', sans-serif;
}
* { box-sizing: border-box; margin: 0; }
body { background: var(--bg); color: var(--text); font-family: var(--font); font-size: 14px; }
a { color: inherit; text-decoration: none; }
.card { background: var(--bg-card); border: 1px solid var(--border);
        border-radius: 10px; padding: 16px; }
.grid { display: grid; gap: 14px; }
table { width: 100%; border-collapse: collapse; }
th { color: var(--text-dim); font-weight: 500; font-size: 12px;
     text-align: right; padding: 8px 10px; border-bottom: 1px solid var(--border); }
th:first-child, td:first-child { text-align: left; }
td { padding: 10px; text-align: right; border-bottom: 1px solid var(--border); }
tr:hover td { background: var(--bg-hover); }
.pos { color: var(--buy); } .neg { color: var(--sell); }
button { background: var(--accent); color: #fff; border: 0; border-radius: 6px;
         padding: 8px 14px; cursor: pointer; font-family: inherit; }
button.ghost { background: transparent; border: 1px solid var(--border); color: var(--text-dim); }
input, select { background: var(--bg); border: 1px solid var(--border); color: var(--text);
                border-radius: 6px; padding: 8px 10px; font-family: inherit; }
.badge { display: inline-block; padding: 3px 10px; border-radius: 20px;
         font-size: 12px; font-weight: 600; }
```

- [ ] **Step 3: api.ts / types.ts 작성**

`frontend/src/api.ts`:
```ts
export async function get<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}
export async function post<T = unknown>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`)
  return res.json()
}
export async function del(path: string): Promise<void> {
  const res = await fetch(path, { method: 'DELETE' })
  if (!res.ok) throw new Error(`${res.status}`)
}
```

`frontend/src/types.ts` — 백엔드 응답 그대로 타입화:
```ts
export interface Sentiment {
  vix: number | null; vkospi: number | null;
  cnn_fg: number | null; crypto_fg: number | null;
  cnn_fg_label: string; crypto_fg_label: string;
  usdkrw: number | null; failed: string[];
}
export interface SignalRow {
  symbol: string; name: string; market: string; currency: string;
  close: number | null; change_pct: number | null;
  swing_score: number; swing_grade: string;
  longterm_score: number; longterm_grade: string;
  grade_changed: boolean; is_holding: boolean;
  context_note: string | null; summary: string | null;
}
export interface RuleAlert { symbol: string; name: string; rule_type: string; value: number; message: string }
export interface Dashboard {
  sentiment: Sentiment;
  portfolio_summary: { total_value_krw: number; total_pnl_krw: number;
    total_pnl_pct: number; holdings_count: number };
  signals: SignalRow[]; rule_alerts: RuleAlert[];
  last_refresh: string | null; failed_sources: string[];
}
export interface Candle {
  date: string; open: number; high: number; low: number; close: number; volume: number;
  sma20: number | null; sma60: number | null; sma120: number | null;
  bb_upper: number | null; bb_lower: number | null;
  rsi: number | null; macd: number | null; macd_signal: number | null; macd_hist: number | null;
}
export interface IndicatorScore { name: string; score: number; reason: string; scope: string }
export interface TickerDetail {
  symbol: string; name: string; market: string; currency: string; is_etf: number;
  fundamentals: { per: number | null; pbr: number | null;
    dividend_yield: number | null; market_cap: number | null } | null;
  signal: { swing_score: number; swing_grade: string; longterm_score: number;
    longterm_grade: string; indicator_scores: IndicatorScore[];
    summary: string; context_note: string | null } | null;
  candles: Candle[];
  history: { date: string; swing_score: number; longterm_score: number; grade: string }[];
  rules: { id: number; symbol: string; rule_type: string; value: number }[];
}
export interface Holding {
  symbol: string; name: string; market: string; currency: string;
  quantity: number; avg_price: number; close: number | null;
  value: number | null; pnl: number | null; pnl_pct: number | null;
}
export interface Portfolio {
  holdings: Holding[];
  totals: { total_value_krw: number; total_cost_krw: number;
    total_pnl_krw: number; total_pnl_pct: number };
  allocation: { label: string; value_krw: number }[];
}
export interface SearchResult {
  symbol: string; name: string; market: string; is_etf: number;
  yf_symbol: string | null; currency: string;
}
```

- [ ] **Step 4: 공용 컴포넌트 + 라우팅**

`frontend/src/components/SignalBadge.tsx`:
```tsx
const COLORS: Record<string, [string, string]> = {
  '강력매수': ['var(--buy-strong)', 'rgba(0,230,118,.12)'],
  '매수': ['var(--buy)', 'rgba(46,204,113,.12)'],
  '중립': ['var(--neutral)', 'rgba(139,147,163,.12)'],
  '매도': ['var(--sell)', 'rgba(255,82,82,.12)'],
  '강력매도': ['var(--sell-strong)', 'rgba(255,23,68,.12)'],
}
export default function SignalBadge({ grade }: { grade: string }) {
  const [fg, bg] = COLORS[grade] ?? COLORS['중립']
  return <span className="badge" style={{ color: fg, background: bg }}>{grade}</span>
}
```

`frontend/src/components/ScoreBar.tsx` (-100..100 점수 시각화):
```tsx
export default function ScoreBar({ score }: { score: number }) {
  const pct = Math.min(Math.abs(score), 100) / 2
  const color = score >= 0 ? 'var(--buy)' : 'var(--sell)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ position: 'relative', width: 120, height: 6,
                    background: 'var(--border)', borderRadius: 3 }}>
        <div style={{ position: 'absolute', height: 6, borderRadius: 3, background: color,
                      left: score >= 0 ? '50%' : `${50 - pct}%`, width: `${pct}%` }} />
      </div>
      <span style={{ color, fontVariantNumeric: 'tabular-nums', minWidth: 36,
                     textAlign: 'right' }}>{score.toFixed(0)}</span>
    </div>
  )
}
```

`frontend/src/components/Layout.tsx`:
```tsx
import { NavLink, Outlet } from 'react-router-dom'

const tabs = [
  { to: '/', label: '대시보드' }, { to: '/portfolio', label: '포트폴리오' },
  { to: '/watchlist', label: '워치리스트' },
]
export default function Layout() {
  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '20px 16px 60px' }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: 24, marginBottom: 20 }}>
        <h1 style={{ fontSize: 20 }}>MyStock</h1>
        <nav style={{ display: 'flex', gap: 4 }}>
          {tabs.map(t => (
            <NavLink key={t.to} to={t.to} end={t.to === '/'}
              style={({ isActive }) => ({
                padding: '6px 14px', borderRadius: 6,
                color: isActive ? 'var(--text)' : 'var(--text-dim)',
                background: isActive ? 'var(--bg-card)' : 'transparent',
              })}>{t.label}</NavLink>
          ))}
        </nav>
      </header>
      <Outlet />
      <footer style={{ marginTop: 40, color: 'var(--text-dim)', fontSize: 12,
                       textAlign: 'center' }}>
        본 시그널은 지표 기반 참고 정보이며 투자 자문이 아닙니다.
      </footer>
    </div>
  )
}
```

`frontend/src/App.tsx` 전면 교체 (페이지는 우선 placeholder, 이후 태스크에서 구현):
```tsx
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import TickerDetail from './pages/TickerDetail'
import Portfolio from './pages/Portfolio'
import Watchlist from './pages/Watchlist'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/ticker/:symbol" element={<TickerDetail />} />
          <Route path="/portfolio" element={<Portfolio />} />
          <Route path="/watchlist" element={<Watchlist />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
```

`frontend/src/main.tsx`에서 `import './theme.css'`로 교체, 템플릿 기본 CSS(`App.css`, `index.css`) 및 로고 삭제. 각 페이지 파일은 `export default function X() { return <div /> }` 스텁 생성.

- [ ] **Step 5: 빌드 검증 후 커밋**

Run: `cd frontend && npm run build` → 성공 (타입 에러 0)
```bash
git add frontend && git commit -m "feat: 프론트엔드 스캐폴드 (다크 테마, 라우팅, API 클라이언트)"
```

---

### Task 11: 대시보드 페이지

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`
- Create: `frontend/src/components/SentimentGauge.tsx`

**Interfaces:**
- Consumes: `GET /api/dashboard` (`Dashboard` 타입), `POST /api/refresh`, `SignalBadge`, `ScoreBar`

- [ ] **Step 1: SentimentGauge 구현**

`frontend/src/components/SentimentGauge.tsx` — 0~100 반원 게이지 (SVG):
```tsx
export default function SentimentGauge({ label, value, valueLabel }:
  { label: string; value: number | null; valueLabel: string }) {
  const v = value ?? 50
  const angle = (v / 100) * 180
  const color = value === null ? 'var(--neutral)'
    : v < 45 ? 'var(--sell)' : v > 55 ? 'var(--buy)' : 'var(--neutral)'
  const rad = (Math.PI * (180 - angle)) / 180
  return (
    <div style={{ textAlign: 'center' }}>
      <svg width="120" height="70" viewBox="0 0 120 70">
        <path d="M 10 65 A 50 50 0 0 1 110 65" fill="none"
              stroke="var(--border)" strokeWidth="10" strokeLinecap="round" />
        <path d="M 10 65 A 50 50 0 0 1 110 65" fill="none" stroke={color}
              strokeWidth="10" strokeLinecap="round"
              strokeDasharray={`${(v / 100) * 157} 157`} />
        <circle cx={60 + 50 * Math.cos(rad)} cy={65 - 50 * Math.sin(rad)} r="4" fill={color} />
        <text x="60" y="58" textAnchor="middle" fill="var(--text)"
              fontSize="18" fontWeight="700">{value === null ? '—' : Math.round(v)}</text>
      </svg>
      <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>{label}</div>
      <div style={{ fontSize: 13, color }}>{valueLabel}</div>
    </div>
  )
}
```

- [ ] **Step 2: Dashboard 페이지 구현**

`frontend/src/pages/Dashboard.tsx`:
```tsx
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { get, post } from '../api'
import type { Dashboard as DashboardData } from '../types'
import SentimentGauge from '../components/SentimentGauge'
import SignalBadge from '../components/SignalBadge'
import ScoreBar from '../components/ScoreBar'

const fmt = (n: number | null, cur = 'KRW') =>
  n === null ? '—' : n.toLocaleString('ko-KR', {
    maximumFractionDigits: cur === 'USD' ? 2 : 0 })

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = () => get<DashboardData>('/api/dashboard')
    .then(setData).catch(e => setError(String(e)))
  useEffect(() => { load() }, [])

  const refresh = async () => {
    setBusy(true)
    try { await post('/api/refresh'); await load() }
    catch (e) { setError(String(e)) }
    finally { setBusy(false) }
  }

  if (error) return <div className="card">불러오기 실패: {error}</div>
  if (!data) return <div className="card">불러오는 중…</div>
  const { sentiment: s, portfolio_summary: pf } = data
  const pnlCls = pf.total_pnl_krw >= 0 ? 'pos' : 'neg'

  return (
    <div className="grid">
      <div className="grid" style={{ gridTemplateColumns: '2fr 1fr' }}>
        <div className="card" style={{ display: 'flex', justifyContent: 'space-around' }}>
          <SentimentGauge label="주식 공포탐욕" value={s.cnn_fg} valueLabel={s.cnn_fg_label} />
          <SentimentGauge label="크립토 공포탐욕" value={s.crypto_fg} valueLabel={s.crypto_fg_label} />
          <div style={{ textAlign: 'center', alignSelf: 'center' }}>
            <div style={{ fontSize: 22, fontWeight: 700 }}>{s.vix?.toFixed(1) ?? '—'}</div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>VIX</div>
            {s.vkospi && <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
              VKOSPI {s.vkospi.toFixed(1)}</div>}
          </div>
        </div>
        <div className="card">
          <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>포트폴리오 평가액 (KRW 환산)</div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>₩{fmt(pf.total_value_krw)}</div>
          <div className={pnlCls}>
            {pf.total_pnl_krw >= 0 ? '+' : ''}₩{fmt(pf.total_pnl_krw)} ({pf.total_pnl_pct}%)
          </div>
          <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 4 }}>
            보유 {pf.holdings_count}종목</div>
        </div>
      </div>

      {data.rule_alerts.length > 0 && (
        <div className="card" style={{ borderColor: 'var(--accent)' }}>
          <strong>알림</strong>
          {data.rule_alerts.map((a, i) => (
            <div key={i} style={{ marginTop: 6 }}>
              <Link to={`/ticker/${a.symbol}`}>🔔 {a.message}</Link>
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
          <strong>오늘의 시그널</strong>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            {data.failed_sources.length > 0 &&
              <span style={{ color: 'var(--sell)', fontSize: 12 }}>
                일부 소스 갱신 실패: {data.failed_sources.join(', ')}</span>}
            <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
              기준: {data.last_refresh ?? '—'}</span>
            <button onClick={refresh} disabled={busy}>{busy ? '갱신 중…' : '새로고침'}</button>
          </div>
        </div>
        {data.signals.length === 0 &&
          <div style={{ color: 'var(--text-dim)' }}>
            워치리스트에 종목을 추가하면 시그널이 표시됩니다.</div>}
        <table>
          <thead><tr>
            <th>종목</th><th>현재가</th><th>등락</th><th>스윙</th><th>스윙 점수</th>
            <th>중장기</th><th>중장기 점수</th>
          </tr></thead>
          <tbody>
            {data.signals.map(sig => (
              <tr key={sig.symbol}>
                <td>
                  <Link to={`/ticker/${sig.symbol}`}>
                    <strong>{sig.name}</strong>
                    {sig.is_holding && <span style={{ color: 'var(--accent)', fontSize: 11 }}> 보유</span>}
                    {sig.grade_changed && <span style={{ color: 'var(--buy-strong)', fontSize: 11 }}> 등급변경</span>}
                    <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>
                      {sig.summary}{sig.context_note ? ` · ${sig.context_note}` : ''}</div>
                  </Link>
                </td>
                <td>{fmt(sig.close, sig.currency)}</td>
                <td className={(sig.change_pct ?? 0) >= 0 ? 'pos' : 'neg'}>
                  {sig.change_pct === null ? '—' : `${sig.change_pct >= 0 ? '+' : ''}${sig.change_pct}%`}</td>
                <td><SignalBadge grade={sig.swing_grade} /></td>
                <td><ScoreBar score={sig.swing_score} /></td>
                <td><SignalBadge grade={sig.longterm_grade} /></td>
                <td><ScoreBar score={sig.longterm_score} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: 빌드 검증 후 커밋**

Run: `cd frontend && npm run build` → 성공
```bash
git add frontend/src && git commit -m "feat: 대시보드 (심리 게이지, 시그널 요약, 포트폴리오 요약, 룰 알림)"
```

---

### Task 12: 종목 상세 페이지 (차트)

**Files:**
- Modify: `frontend/src/pages/TickerDetail.tsx`

**Interfaces:**
- Consumes: `GET /api/tickers/{symbol}` (`TickerDetail` 타입), lightweight-charts v4+ (`createChart`), `SignalBadge`, `ScoreBar`, 룰 CRUD API

- [ ] **Step 1: 페이지 구현**

`frontend/src/pages/TickerDetail.tsx` — 캔들+SMA20/60/120+볼린저 오버레이 차트, RSI/MACD 서브차트, 점수 분해 테이블, 펀더멘털, 룰 관리, 시그널 히스토리:
```tsx
import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { createChart, type IChartApi, LineStyle } from 'lightweight-charts'
import { del, get, post } from '../api'
import type { TickerDetail as Detail } from '../types'
import SignalBadge from '../components/SignalBadge'
import ScoreBar from '../components/ScoreBar'

const CHART_OPTS = {
  layout: { background: { color: 'transparent' }, textColor: '#8b93a3' },
  grid: { vertLines: { color: '#232a36' }, horzLines: { color: '#232a36' } },
  timeScale: { borderColor: '#232a36' }, rightPriceScale: { borderColor: '#232a36' },
} as const

function useCandleChart(detail: Detail | null) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!detail || !ref.current) return
    const charts: IChartApi[] = []
    const main = createChart(ref.current, { ...CHART_OPTS, height: 360 })
    charts.push(main)
    const candles = detail.candles
    main.addCandlestickSeries({
      upColor: '#2ecc71', downColor: '#ff5252',
      wickUpColor: '#2ecc71', wickDownColor: '#ff5252', borderVisible: false,
    }).setData(candles.map(c => ({ time: c.date, open: c.open, high: c.high,
                                   low: c.low, close: c.close })))
    const lines: [keyof typeof candles[0], string, number][] = [
      ['sma20', '#f7c948', 1], ['sma60', '#4f8ef7', 1], ['sma120', '#b06ef7', 1],
    ]
    for (const [key, color, width] of lines) {
      main.addLineSeries({ color, lineWidth: width as 1 })
        .setData(candles.filter(c => c[key] !== null)
          .map(c => ({ time: c.date, value: c[key] as number })))
    }
    for (const key of ['bb_upper', 'bb_lower'] as const) {
      main.addLineSeries({ color: '#3a4356', lineWidth: 1, lineStyle: LineStyle.Dashed })
        .setData(candles.filter(c => c[key] !== null)
          .map(c => ({ time: c.date, value: c[key] as number })))
    }
    main.timeScale().fitContent()
    return () => charts.forEach(c => c.remove())
  }, [detail])
  return ref
}

export default function TickerDetail() {
  const { symbol } = useParams()
  const [detail, setDetail] = useState<Detail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ruleType, setRuleType] = useState('TARGET')
  const [ruleValue, setRuleValue] = useState('')
  const chartRef = useCandleChart(detail)

  const load = () => get<Detail>(`/api/tickers/${symbol}`)
    .then(setDetail).catch(e => setError(String(e)))
  useEffect(() => { load() }, [symbol])

  if (error) return <div className="card">불러오기 실패: {error}</div>
  if (!detail) return <div className="card">불러오는 중…</div>
  const sig = detail.signal
  const last = detail.candles.at(-1)

  const addRule = async () => {
    if (!ruleValue) return
    await post('/api/rules', { symbol, rule_type: ruleType, value: Number(ruleValue) })
    setRuleValue(''); load()
  }

  return (
    <div className="grid">
      <div className="card" style={{ display: 'flex', justifyContent: 'space-between',
                                     alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2>{detail.name} <span style={{ color: 'var(--text-dim)', fontSize: 14 }}>
            {detail.symbol} · {detail.market}{detail.is_etf ? ' · ETF' : ''}</span></h2>
          {last && <div style={{ fontSize: 22, fontWeight: 700 }}>
            {last.close.toLocaleString('ko-KR')}</div>}
        </div>
        {sig && <div style={{ display: 'flex', gap: 24 }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>스윙</div>
            <SignalBadge grade={sig.swing_grade} />
            <ScoreBar score={sig.swing_score} />
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>중장기</div>
            <SignalBadge grade={sig.longterm_grade} />
            <ScoreBar score={sig.longterm_score} />
          </div>
        </div>}
      </div>

      {sig?.context_note && <div className="card" style={{ color: 'var(--accent)' }}>
        💡 {sig.context_note}</div>}

      <div className="card"><div ref={chartRef} /></div>

      {sig && <div className="card">
        <strong>시그널 근거</strong>
        <p style={{ margin: '8px 0', color: 'var(--text-dim)' }}>{sig.summary}</p>
        <table>
          <thead><tr><th>지표</th><th>관점</th><th>점수</th><th style={{ textAlign: 'left' }}>근거</th></tr></thead>
          <tbody>
            {sig.indicator_scores.map((s, i) => (
              <tr key={i}>
                <td>{s.name}</td>
                <td>{s.scope === 'swing' ? '스윙' : '중장기'}</td>
                <td><ScoreBar score={s.score} /></td>
                <td style={{ textAlign: 'left' }}>{s.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>}

      <div className="grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
        <div className="card">
          <strong>펀더멘털 (참고)</strong>
          {detail.fundamentals ? (
            <table><tbody>
              <tr><td style={{ textAlign: 'left' }}>PER</td>
                  <td>{detail.fundamentals.per?.toFixed(1) ?? '—'}</td></tr>
              <tr><td style={{ textAlign: 'left' }}>PBR</td>
                  <td>{detail.fundamentals.pbr?.toFixed(2) ?? '—'}</td></tr>
              <tr><td style={{ textAlign: 'left' }}>배당수익률</td>
                  <td>{detail.fundamentals.dividend_yield ?? '—'}%</td></tr>
              <tr><td style={{ textAlign: 'left' }}>시가총액</td>
                  <td>{detail.fundamentals.market_cap
                    ? (detail.fundamentals.market_cap / 1e12).toFixed(2) + '조' : '—'}</td></tr>
            </tbody></table>
          ) : <div style={{ color: 'var(--text-dim)', marginTop: 8 }}>정보 없음</div>}
        </div>
        <div className="card">
          <strong>커스텀 룰</strong>
          {detail.rules.map(r => (
            <div key={r.id} style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
              <span>{{ TARGET: '목표가', STOP: '손절가', AVG_PCT: '평단 대비 %' }[r.rule_type]}
                {' '}{r.value.toLocaleString('ko-KR')}</span>
              <button className="ghost" onClick={() => del(`/api/rules/${r.id}`).then(load)}>삭제</button>
            </div>
          ))}
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <select value={ruleType} onChange={e => setRuleType(e.target.value)}>
              <option value="TARGET">목표가</option>
              <option value="STOP">손절가</option>
              <option value="AVG_PCT">평단 대비 %</option>
            </select>
            <input type="number" placeholder="값" value={ruleValue}
                   onChange={e => setRuleValue(e.target.value)} style={{ width: 120 }} />
            <button onClick={addRule}>추가</button>
          </div>
        </div>
      </div>

      <div className="card">
        <strong>시그널 히스토리</strong>
        <table>
          <thead><tr><th>날짜</th><th>스윙 점수</th><th>중장기 점수</th><th>등급</th></tr></thead>
          <tbody>
            {detail.history.slice(0, 20).map(h => (
              <tr key={h.date}>
                <td style={{ textAlign: 'left' }}>{h.date}</td>
                <td>{h.swing_score.toFixed(0)}</td>
                <td>{h.longterm_score.toFixed(0)}</td>
                <td><SignalBadge grade={h.grade} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
```

주의: lightweight-charts v5에서는 `addCandlestickSeries`가 `addSeries(CandlestickSeries, …)`로 바뀌었다. 설치된 버전을 확인하고 v5면 v5 API(`chart.addSeries(CandlestickSeries, opts)`, `chart.addSeries(LineSeries, opts)`)로 작성할 것.

- [ ] **Step 2: 빌드 검증 후 커밋**

Run: `cd frontend && npm run build` → 성공
```bash
git add frontend/src && git commit -m "feat: 종목 상세 (캔들차트, 점수 분해, 펀더멘털, 커스텀 룰, 히스토리)"
```

---

### Task 13: 포트폴리오 + 워치리스트 페이지

**Files:**
- Modify: `frontend/src/pages/Portfolio.tsx`, `frontend/src/pages/Watchlist.tsx`

**Interfaces:**
- Consumes: `GET /api/portfolio`, trades CRUD, `GET /api/search`, watchlist CRUD, `GET /api/dashboard`(워치리스트 시그널 목록 재사용), recharts `PieChart`

- [ ] **Step 1: Portfolio 페이지 구현**

`frontend/src/pages/Portfolio.tsx`:
```tsx
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { del, get, post } from '../api'
import type { Portfolio as PF, SearchResult } from '../types'

const PIE_COLORS = ['#4f8ef7', '#2ecc71', '#f7c948', '#b06ef7', '#ff8a65']
const fmt = (n: number | null) => n === null ? '—' : n.toLocaleString('ko-KR', { maximumFractionDigits: 2 })

interface Trade { id: number; symbol: string; side: string; quantity: number;
                  price: number; trade_date: string }

export default function Portfolio() {
  const [pf, setPf] = useState<PF | null>(null)
  const [trades, setTrades] = useState<Trade[]>([])
  const [form, setForm] = useState({ symbol: '', side: 'BUY', quantity: '', price: '',
    trade_date: new Date().toISOString().slice(0, 10) })
  const [msg, setMsg] = useState<string | null>(null)

  const load = () => Promise.all([
    get<PF>('/api/portfolio').then(setPf),
    get<Trade[]>('/api/trades').then(setTrades),
  ]).catch(e => setMsg(String(e)))
  useEffect(() => { load() }, [])

  const addTrade = async () => {
    try {
      await post('/api/trades', { ...form, quantity: Number(form.quantity),
                                  price: Number(form.price) })
      setMsg(null); setForm({ ...form, quantity: '', price: '' }); load()
    } catch (e) { setMsg(String(e)) }
  }

  if (!pf) return <div className="card">불러오는 중…</div>
  const t = pf.totals
  return (
    <div className="grid">
      <div className="grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
        <div className="card">
          <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>총 평가액 (KRW 환산)</div>
          <div style={{ fontSize: 26, fontWeight: 700 }}>₩{fmt(t.total_value_krw)}</div>
          <div className={t.total_pnl_krw >= 0 ? 'pos' : 'neg'} style={{ fontSize: 16 }}>
            {t.total_pnl_krw >= 0 ? '+' : ''}₩{fmt(t.total_pnl_krw)} ({t.total_pnl_pct}%)</div>
        </div>
        <div className="card" style={{ height: 180 }}>
          {pf.allocation.length > 0 ? (
            <ResponsiveContainer>
              <PieChart>
                <Pie data={pf.allocation} dataKey="value_krw" nameKey="label"
                     innerRadius={40} outerRadius={65}>
                  {pf.allocation.map((_, i) =>
                    <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                </Pie>
                <Tooltip formatter={(v: number) => `₩${fmt(v)}`} />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : <div style={{ color: 'var(--text-dim)' }}>보유 종목 없음</div>}
        </div>
      </div>

      <div className="card">
        <strong>보유 종목</strong>
        <table>
          <thead><tr><th>종목</th><th>수량</th><th>평단가</th><th>현재가</th>
            <th>평가액</th><th>손익</th><th>수익률</th></tr></thead>
          <tbody>
            {pf.holdings.map(h => (
              <tr key={h.symbol}>
                <td><Link to={`/ticker/${h.symbol}`}><strong>{h.name}</strong>
                  <span style={{ color: 'var(--text-dim)', fontSize: 12 }}> {h.currency}</span></Link></td>
                <td>{fmt(h.quantity)}</td>
                <td>{fmt(h.avg_price)}</td>
                <td>{fmt(h.close)}</td>
                <td>{fmt(h.value)}</td>
                <td className={(h.pnl ?? 0) >= 0 ? 'pos' : 'neg'}>{fmt(h.pnl)}</td>
                <td className={(h.pnl_pct ?? 0) >= 0 ? 'pos' : 'neg'}>
                  {h.pnl_pct === null ? '—' : `${h.pnl_pct >= 0 ? '+' : ''}${h.pnl_pct}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <strong>매매 입력</strong>
        <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
          <input placeholder="심볼 (예: 005930, AAPL, KRW-BTC)" value={form.symbol}
                 onChange={e => setForm({ ...form, symbol: e.target.value })} style={{ width: 200 }} />
          <select value={form.side} onChange={e => setForm({ ...form, side: e.target.value })}>
            <option value="BUY">매수</option><option value="SELL">매도</option>
          </select>
          <input type="number" placeholder="수량" value={form.quantity}
                 onChange={e => setForm({ ...form, quantity: e.target.value })} style={{ width: 100 }} />
          <input type="number" placeholder="단가" value={form.price}
                 onChange={e => setForm({ ...form, price: e.target.value })} style={{ width: 130 }} />
          <input type="date" value={form.trade_date}
                 onChange={e => setForm({ ...form, trade_date: e.target.value })} />
          <button onClick={addTrade}>추가</button>
        </div>
        {msg && <div style={{ color: 'var(--sell)', marginTop: 8 }}>{msg}</div>}
        <table style={{ marginTop: 12 }}>
          <thead><tr><th>날짜</th><th>심볼</th><th>구분</th><th>수량</th><th>단가</th><th></th></tr></thead>
          <tbody>
            {trades.slice().reverse().map(tr => (
              <tr key={tr.id}>
                <td style={{ textAlign: 'left' }}>{tr.trade_date}</td>
                <td>{tr.symbol}</td>
                <td className={tr.side === 'BUY' ? 'pos' : 'neg'}>
                  {tr.side === 'BUY' ? '매수' : '매도'}</td>
                <td>{fmt(tr.quantity)}</td>
                <td>{fmt(tr.price)}</td>
                <td><button className="ghost"
                  onClick={() => del(`/api/trades/${tr.id}`).then(load)}>삭제</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Watchlist 페이지 구현**

`frontend/src/pages/Watchlist.tsx`:
```tsx
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { del, get, post } from '../api'
import type { Dashboard, SearchResult } from '../types'
import SignalBadge from '../components/SignalBadge'

export default function Watchlist() {
  const [q, setQ] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [dash, setDash] = useState<Dashboard | null>(null)
  const [busy, setBusy] = useState(false)

  const load = () => get<Dashboard>('/api/dashboard').then(setDash)
  useEffect(() => { load() }, [])

  const search = async () => {
    if (!q.trim()) return
    setBusy(true)
    try { setResults(await get<SearchResult[]>(`/api/search?q=${encodeURIComponent(q)}`)) }
    finally { setBusy(false) }
  }

  const add = async (r: SearchResult) => {
    await post('/api/watchlist', r)
    await post('/api/refresh')     // 새 종목 시세·시그널 즉시 계산
    setResults([]); setQ(''); load()
  }

  return (
    <div className="grid">
      <div className="card">
        <strong>종목 검색</strong>
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <input placeholder="이름 또는 심볼 (삼성전자 / AAPL / 비트코인)" value={q}
                 onChange={e => setQ(e.target.value)}
                 onKeyDown={e => e.key === 'Enter' && search()} style={{ flex: 1 }} />
          <button onClick={search} disabled={busy}>{busy ? '검색 중…' : '검색'}</button>
        </div>
        {results.map(r => (
          <div key={r.market + r.symbol}
               style={{ display: 'flex', justifyContent: 'space-between',
                        padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
            <span>{r.name} <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
              {r.symbol} · {r.market}{r.is_etf ? ' · ETF' : ''}</span></span>
            <button className="ghost" onClick={() => add(r)}>+ 추가</button>
          </div>
        ))}
      </div>

      <div className="card">
        <strong>워치리스트</strong>
        <table>
          <thead><tr><th>종목</th><th>스윙</th><th>중장기</th><th></th></tr></thead>
          <tbody>
            {dash?.signals.map(s => (
              <tr key={s.symbol}>
                <td><Link to={`/ticker/${s.symbol}`}><strong>{s.name}</strong>
                  <span style={{ color: 'var(--text-dim)', fontSize: 12 }}> {s.symbol}</span></Link></td>
                <td><SignalBadge grade={s.swing_grade} /></td>
                <td><SignalBadge grade={s.longterm_grade} /></td>
                <td><button className="ghost"
                  onClick={() => del(`/api/watchlist/${s.symbol}`).then(load)}>제거</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: 빌드 검증 후 커밋**

Run: `cd frontend && npm run build` → 성공
```bash
git add frontend/src && git commit -m "feat: 포트폴리오·워치리스트 페이지"
```

---

### Task 14: 정적 서빙 + 실행 스크립트 + README + 최종 검증

**Files:**
- Modify: `backend/app/main.py` (정적 서빙 추가)
- Create: `run.sh`, `README.md`

**Interfaces:**
- Consumes: `frontend/dist` 빌드 결과물
- Produces: `./run.sh` 단일 명령 실행, SPA 라우팅 폴백

- [ ] **Step 1: main.py에 정적 서빙 추가**

`create_app` 안 `app.include_router(router)` 뒤에 추가:
```python
    from pathlib import Path
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            file = dist / path
            if path and file.is_file():
                return FileResponse(file)
            return FileResponse(dist / "index.html")
```

- [ ] **Step 2: run.sh 작성**

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d backend/.venv ]; then
  echo "▸ 파이썬 가상환경 생성 중..."
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q -e "backend[dev]"
fi

if [ ! -d frontend/dist ]; then
  echo "▸ 프론트엔드 빌드 중..."
  (cd frontend && npm install --silent && npm run build)
fi

echo "▸ MyStock 실행: http://localhost:8000"
cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

`chmod +x run.sh`

- [ ] **Step 3: README.md 작성**

```markdown
# MyStock

종목별 매수/매도 시그널을 한눈에 보는 개인용 투자관리 웹앱.

## 실행

​```bash
./run.sh
​```

브라우저에서 http://localhost:8000 접속.

## 기능

- 한국/미국 주식, 암호화폐, ETF 통합 워치리스트
- 스윙/중장기 이중 시그널 (기술적 지표 종합 점수 + 한국어 근거)
- VIX·공포탐욕지수 시장 심리 게이지 및 점수 보정
- 보유 종목 수익률·자산 배분 (매매 내역 직접 입력)
- 종목별 목표가/손절가/평단 대비 % 커스텀 룰 알림
- 6시간 주기 자동 갱신 + 수동 새로고침

> 본 시그널은 지표 기반 참고 정보이며 투자 자문이 아닙니다.

## 개발

​```bash
cd backend && .venv/bin/pytest          # 백엔드 테스트
cd backend && .venv/bin/pytest -m smoke # 외부 API 스모크 테스트
cd frontend && npm run dev              # 프론트 개발 서버 (proxy → :8000)
​```
```
(README의 ​``` 는 실제 백틱으로)

- [ ] **Step 4: 최종 통합 검증**

1. `cd backend && .venv/bin/pytest -v` → 전체 PASS
2. `cd frontend && npm run build` → 성공
3. `./run.sh` 백그라운드 실행 → `curl -s localhost:8000/api/health` → `{"status":"ok"}`
4. `curl -s "localhost:8000/api/search?q=삼성전자"` → 결과 확인 (네트워크 필요)
5. 브라우저(또는 Browser 도구)로 `localhost:8000` 접속 → 4개 페이지 렌더링, 워치리스트에 "삼성전자"·"AAPL"·"비트코인" 추가 → 대시보드에 시그널 표시 확인
6. 서버 종료

- [ ] **Step 5: 커밋**

```bash
git add backend/app/main.py run.sh README.md
git commit -m "feat: 정적 서빙 + 단일 실행 스크립트 + README"
```

---

## Self-Review 결과 (계획 작성 후 점검)

- **스펙 커버리지**: 4개 시장 수집(T6), 이중 스코어링+근거(T4), 심리 레이어(T5), 커스텀 룰(T8), 포트폴리오(T7/T13), 워치리스트(T13), 대시보드(T11), 상세 차트(T12), 6시간 갱신(T9), 실패 배지(T11), 고지 문구(T10 Layout), 단일 실행(T14) — 전부 매핑됨. 백테스팅·알림·배포는 스펙대로 제외.
- **타입 일관성**: `db.py` 시그니처(T2) ↔ `service.py`(T8) ↔ `api.py`(T9) ↔ `types.ts`(T10) 교차 확인 완료. `grade()` 등급 문자열 5종은 T4에서 정의, T10 SignalBadge와 일치.
- **주의점 명시**: lightweight-charts v4/v5 API 차이(T12), FDR ETF 목록 컬럼명 차이 가능성(T6 — try/except로 완화), CNN 엔드포인트 User-Agent 필요(T5).
```
