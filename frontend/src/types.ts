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
  grade_changed: boolean; is_holding: boolean; in_watchlist: boolean;
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
    longterm_grade: string; regime?: string; regime_label?: string;
    indicator_scores: IndicatorScore[];
    summary: string; context_note: string | null } | null;
  candles: Candle[];
  risk: { atr: number; atr_pct: number; stop_price: number; stop_pct: number;
    mdd_pct: number; position_size_1pct: number | null;
    risk_budget_krw: number | null } | null;
  history: { date: string; swing_score: number; longterm_score: number; grade: string }[];
  rules: { id: number; symbol: string; rule_type: string; value: number }[];
}
export interface Holding {
  symbol: string; name: string; market: string; currency: string;
  quantity: number; avg_price: number; close: number | null;
  value: number | null; pnl: number | null; pnl_pct: number | null;
}
export interface RealizedEntry {
  symbol: string; trade_date: string; quantity: number;
  buy_price: number; sell_price: number; pnl: number; pnl_pct: number;
}
export interface RealizedStats {
  count: number; total_pnl_krw: number; win_rate: number | null;
  avg_win_pct: number | null; avg_loss_pct: number | null; payoff_ratio: number | null;
}
export interface Portfolio {
  holdings: Holding[];
  totals: { total_value_krw: number; total_cost_krw: number;
    total_pnl_krw: number; total_pnl_pct: number };
  allocation: { label: string; value_krw: number }[];
  realized: { entries: RealizedEntry[]; stats: RealizedStats };
}
export interface BacktestGrade {
  grade: string; n: number;
  avg_fwd5: number | null; win5: number | null;
  avg_fwd20: number | null; win20: number | null;
  avg_net5: number | null; avg_net20: number | null;
  avg_excess5: number | null; avg_excess20: number | null;
}
export interface Backtest {
  samples: number; start: string; end: string;
  bench_label: string | null; cost_pct: number; grades: BacktestGrade[];
}
export interface SearchResult {
  symbol: string; name: string; market: string; is_etf: number;
  yf_symbol: string | null; currency: string;
}
