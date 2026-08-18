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
-- 매매가 아닌 현금 변동. 배당·분배금이 원장에 없으면 커버드콜·고배당 종목의
-- 수익률이 주가 하락분만큼만 보이고, 예수금은 매매와 어긋난 채로 남는다.
CREATE TABLE IF NOT EXISTS cash_flows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  flow_type TEXT NOT NULL CHECK (flow_type IN ('DIVIDEND','DEPOSIT','WITHDRAW','INTEREST')),
  symbol TEXT REFERENCES tickers(symbol),  -- 배당은 종목 귀속, 입출금은 NULL
  currency TEXT NOT NULL DEFAULT 'KRW',
  amount REAL NOT NULL,  -- 세전 금액 (종목/계좌 통화)
  tax REAL NOT NULL DEFAULT 0,  -- 원천징수 (배당소득세 — 양도세와 별개다)
  flow_date TEXT NOT NULL,
  fx_rate REAL,  -- 입금 시점 환율. NULL이면 현재 환율 폴백 (추정 표시)
  note TEXT,
  -- 증권사에서 가져온 거래의 원천 식별자. 같은 기간을 다시 조회해도 같은 값이
  -- 나오므로, 이게 없으면 재조회할 때마다 입출금이 통째로 두 번씩 쌓인다.
  ext_key TEXT
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
-- 증권사(CODEF)에서 받아온 실제 보유 스냅샷. 원장(trades)은 매매일지·실현손익의
-- 근거로 그대로 두고, "지금 무엇을 들고 있나"는 증권사 값을 진실로 쓴다.
-- 동기화된 계좌가 있으면 화면의 보유 수량·평단이 이 표에서 나온다.
CREATE TABLE IF NOT EXISTS broker_holdings (
  symbol TEXT PRIMARY KEY,
  name TEXT,
  quantity REAL NOT NULL,
  avg_price REAL NOT NULL,  -- 증권사 평균매입가 (종목 통화 기준)
  currency TEXT NOT NULL DEFAULT 'KRW',
  account TEXT,  -- 어느 계좌에서 왔는지 — 여러 계좌를 합산할 때 출처가 필요하다
  -- 증권사가 평균매입가를 안 주면 현재가로 채운다(손익 0). 그 사실을 잃으면
  -- 화면이 '본전'이라고 말하는데 실제로는 평단을 모르는 상태가 된다.
  basis_missing INTEGER NOT NULL DEFAULT 0,
  synced_at TEXT NOT NULL
);
