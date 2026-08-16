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
  trade_date TEXT NOT NULL,
  executed_at TEXT,  -- 체결 시각 (HH:MM). 같은 날 매도 후 재매수의 순서를 지킨다
  fx_rate REAL,  -- 체결 시점 원화 환율 (KRW 종목은 1.0, 과거 행은 NULL → 현재 환율 폴백)
  fee REAL,  -- 위탁수수료 (종목 통화 기준, NULL → 시장 요율로 추정)
  tax REAL,  -- 거래세·부과금 (매도만, NULL → 시장 요율로 추정)
  note TEXT,  -- 매매 일지 메모 (진입/청산 근거)
  grade_at_trade TEXT,  -- 체결 시점 스윙 시그널 등급 스냅샷
  -- 평단 맞춤용 보정 로트 표시. 체결가가 인위적이라 평단에는 반영하되
  -- 승률·실현손익 집계에서는 빼야 복기가 거짓이 되지 않는다.
  exclude_from_stats INTEGER NOT NULL DEFAULT 0
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
