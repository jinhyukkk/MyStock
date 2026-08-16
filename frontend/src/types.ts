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
  avg_price: number | null; holding_pnl_pct: number | null;
  context_note: string | null; summary: string | null;
  summary_tags: { label: string; score: number; warn: boolean }[];
  // 장중 미완성 봉으로 계산된 등급인지 — 마감 때 뒤집힐 수 있고 백테스트가 검증한 적 없다
  bar_complete: boolean; bar_date: string;
}
export interface RuleAlert {
  symbol: string; name: string; rule_type: string; value: number; message: string;
  intraday_only: boolean;  // 장중에만 터치하고 종가는 되돌아온 경우
}
export interface Dashboard {
  sentiment: Sentiment;
  portfolio_summary: { total_value_krw: number; total_pnl_krw: number;
    total_pnl_pct: number; total_pnl_pct_of_asset: number; holdings_count: number;
    cash_krw: number; cash_usd: number; cash_usd_krw: number;
    total_asset_krw: number; cash_pct: number };
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
export interface OpenRisk {
  rows: { symbol: string; name: string; risk_krw: number; risk_pct: number | null }[];
  total_risk_krw: number; total_risk_pct: number | null;
  limit_pct: number; over_limit: boolean;
}
export interface TickerRisk {
  atr: number; atr_pct: number; stop_price: number; stop_pct: number; mdd_pct: number;
  // 손절가만 있으면 손익비를 모른 채 진입하게 된다 — 목표가를 함께 낸다
  target_price: number; target_pct: number; target_r: number; reward_risk: number | null;
  resistance_60d: number | null; resistance_pct: number | null;
  target_above_resistance: boolean; resistance_reward_risk: number | null;
  position_size_1pct: number | null; risk_budget_krw: number | null;
  // 1% 룰 수량이 종목 상한을 넘어 잘렸는지 — 잘리지 않은 수량은 계좌 전액을 넘길 수 있다
  position_size_capped: boolean; cap_reason: string | null; max_weight_pct: number;
  position_notional_krw: number | null;
  held_quantity: number | null; addable_quantity: number | null;
  account_open_risk: OpenRisk | null;
  // 보유 중일 때만 채워진다 — 진입 정보만 있으면 나가는 판단이 매번 즉흥이 된다
  exit_plan: ExitPlan | null;
}
export interface ExitPlan {
  held_quantity: number; avg_price: number;
  unrealized_pnl_pct: number; unrealized_pnl_krw: number;
  stop_from_avg_pct: number; risk_to_stop_krw: number;
  slices: { label: string; quantity: number;
            proceeds_krw: number; realized_pnl_krw: number }[];
}
export interface TickerDetail {
  symbol: string; name: string; market: string; currency: string; is_etf: number;
  fundamentals: { per: number | null; pbr: number | null;
    dividend_yield: number | null; market_cap: number | null } | null;
  signal: { swing_score: number; swing_grade: string; longterm_score: number;
    longterm_grade: string; regime?: string; regime_label?: string;
    indicator_scores: IndicatorScore[];
    summary: string; context_note: string | null;
    bar_complete?: boolean; bar_date?: string } | null;
  candles: Candle[];
  risk: TickerRisk | null;
  // 주문 프리뷰의 비용 추정 근거 — 프론트에 요율 상수를 복제하지 않기 위해 받는다
  cost_rates: { fee_pct: number; sell_tax_pct: number };
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
  buy_price: number; sell_price: number;
  // pnl은 수수료·세금 차감 후(net). gross와 cost를 함께 실어 차이를 눈으로 볼 수 있게 한다.
  pnl: number; pnl_pct: number; pnl_gross: number; cost: number; cost_estimated: boolean;
  // 원화 정산 — 매수/매도 환율을 각각 반영하고 가격 손익과 환 손익을 분리
  buy_fx: number; sell_fx: number;
  pnl_krw: number; price_pnl_krw: number; fx_pnl_krw: number; cost_krw: number;
  entry_grade: string | null; note: string | null;
  // 평단 맞춤용 보정 로트가 원가에 섞인 건 — 체결가가 인위적이라 집계에서 뺀다
  basis_adjusted: boolean;
}
export interface RealizedStats {
  count: number; excluded_count: number; total_pnl_krw: number; win_rate: number | null;
  fx_pnl_krw: number; cost_krw: number; cost_estimated: boolean;
  avg_win_pct: number | null; avg_loss_pct: number | null; payoff_ratio: number | null;
  by_entry_grade: { grade: string; count: number; win_rate: number; avg_pnl_pct: number }[];
}
export interface Portfolio {
  holdings: Holding[];
  totals: { total_value_krw: number; total_cost_krw: number;
    total_pnl_krw: number; total_pnl_pct: number; total_pnl_pct_of_asset: number;
    cash_krw: number; cash_usd: number; cash_usd_krw: number;
    total_asset_krw: number; cash_pct: number };
  allocation: { label: string; value_krw: number }[];
  realized: { entries: RealizedEntry[]; stats: RealizedStats };
  risk: AccountRisk | null;
  open_risk: OpenRisk | null;
}
export interface AccountRisk {
  days: number;
  weights: { symbol: string; name: string; weight_pct: number }[];
  max_weight_pct: number | null;
  volatility_pct: number;
  periods_per_year: number;  // 거래일 교집합에서 실측한 연간 관측 수 (주식 ~252, 코인 ~365)
  mdd_pct: number;
  mdd_note: string;
  calendar_note: string;
  corr: { symbols: string[]; names: string[]; matrix: number[][] } | null;
}
/** 한 등급 × 한 horizon의 집계. 필드명이 `avg_fwd5`처럼 horizon을 접미사로 갖기 때문에
 *  인덱스 시그니처로 받고, 화면에서는 `pick(g, 'avg_fwd', h)`로 꺼낸다. */
export interface BacktestGrade {
  grade: string; n: number;
  [key: string]: string | number | boolean | null;
}
export interface Backtest {
  version: number; samples: number; start: string; end: string;
  bench_label: string | null; cost_pct: number; stop_atr_mult: number;
  min_episodes: number; horizons: number[]; long_horizons: number[];
  // horizon별로 이 관측 기간이 만들 수 있는 비중첩 표본 상한. min_episodes보다 작으면
  // 데이터가 더 쌓여서 채워질 칸이 아니라 애초에 검증이 불가능한 구간이다.
  max_episodes: Record<string, number>;
  entry_rule: string; exit_rule: string;
  grades: BacktestGrade[];
  longterm_grades: BacktestGrade[];
  // 관측 기간 중 0회 — 빈 행을 "아직 안 쌓임"으로 오해하지 않도록 명시한다
  missing_grades: string[];
  missing_longterm_grades: string[];
}
export interface SearchResult {
  symbol: string; name: string; market: string; is_etf: number;
  yf_symbol: string | null; currency: string;
}
