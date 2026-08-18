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
  // 상향(+1)/하향(-1) — 불리언만으로는 강등에도 상승색 배지가 붙는다
  grade_change_dir: number; prev_grade: string | null;
  avg_price: number | null; holding_pnl_pct: number | null;
  // 룰 알림은 손절선을 뚫어야 난다 — 그 전에 알 수 있게 남은 거리를 함께 받는다
  stop_price: number | null; stop_source: 'rule' | 'atr' | null;
  stop_distance_pct: number | null;
  context_note: string | null; summary: string | null;
  summary_tags: { label: string; score: number; warn: boolean }[];
  // 장중 미완성 봉으로 계산된 등급인지 — 마감 때 뒤집힐 수 있고 백테스트가 검증한 적 없다
  bar_complete: boolean; bar_date: string;
}
export interface RuleAlert {
  symbol: string; name: string; rule_type: string; value: number; message: string;
  intraday_only: boolean;  // 장중에만 터치하고 종가는 되돌아온 경우
}
/** 보유 종목 수 룰. 비중·리스크 한도를 다 지키면서 종목 수만 두 배가 된 계좌는
 *  지금까지 어떤 경고도 받지 못했다 — 추적 가능한 개수 자체가 규율의 전제다. */
export interface PositionRule {
  count: number; min: number; max: number;
  status: 'ok' | 'over' | 'under';
  excess: number; shortfall: number;
  trim_candidates: { symbol: string; name: string; weight_pct: number | null;
                     swing_score: number | null; reason: string }[];
}
/** 등급 컷 — 점수 옆에 눈금이 없으면 -21이 얼마나 나쁜지 화면에 나타나지 않는다 */
export interface ScoreCuts {
  strong_buy: number; buy: number; sell: number; strong_sell: number;
}
export interface Dashboard {
  sentiment: Sentiment;
  portfolio_summary: { total_value_krw: number; total_pnl_krw: number;
    total_pnl_pct: number; total_pnl_pct_of_asset: number; holdings_count: number;
    cash_krw: number; cash_usd: number; cash_usd_krw: number;
    total_asset_krw: number; cash_pct: number };
  position_rule: PositionRule;
  /** 보유 중인데 STOP 룰이 없는 종목 — 알림이 울리지 않는 자리다 */
  unstopped: { symbol: string; name: string; atr_stop_price: number }[];
  score_scale: { swing: ScoreCuts; longterm: ScoreCuts };
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
  rows: { symbol: string; name: string; risk_krw: number; risk_pct: number | null;
          stop_source: 'rule' | 'atr' }[];
  total_risk_krw: number; total_risk_pct: number | null;
  limit_pct: number; over_limit: boolean;
  // 손절 룰이 없어 2×ATR로 '가정'한 종목 수 — 가정을 사실처럼 읽으면 안 된다
  unregistered_count: number;
}
export interface TickerRisk {
  atr: number; atr_pct: number; stop_price: number; stop_pct: number; mdd_pct: number;
  // 알림을 울리는 것은 등록된 룰뿐이다 — 화면의 손절선도 같은 값이어야 한다
  stop_source: 'rule' | 'atr';
  atr_stop_price: number; atr_stop_pct: number;
  stop_drift_pct: number | null; stop_drift: boolean;
  // 손절가만 있으면 손익비를 모른 채 진입하게 된다 — 목표가를 함께 낸다
  target_price: number; target_pct: number; target_r: number; reward_risk: number | null;
  resistance_60d: number | null; resistance_pct: number | null;
  target_above_resistance: boolean; resistance_reward_risk: number | null;
  position_size_1pct: number | null; risk_budget_krw: number | null;
  // 1% 룰 수량이 종목 상한을 넘어 잘렸는지 — 잘리지 않은 수량은 계좌 전액을 넘길 수 있다
  position_size_capped: boolean; cap_reason: string | null; max_weight_pct: number;
  // 화면이 '체결 후 비중'을 낼 때 쓰는 분모와 환율 — 프론트가 역산하면 규칙이
  // 바뀌는 순간 비중만 조용히 틀려진다
  total_asset_krw: number; fx_rate: number;
  position_notional_krw: number | null;
  held_quantity: number | null; addable_quantity: number | null;
  account_open_risk: OpenRisk | null;
  // 2×ATR 손절폭이 이 타임프레임에 안 맞으면 손절 자체가 지켜지지 않는다
  stop_too_wide: boolean; max_stop_pct: number;
  // 주문 가능한 단위로 내린 수량과, 내리기 전 원값
  lot_size: number | null; position_size_raw: number | null;
  // 일평균 거래대금 대비 주문 크기 — 중소형주에서는 이게 체결가를 밀어버린다
  turnover_krw: number | null; liquidity_pct: number | null;
  // 원가에 평단 보정 로트가 섞였는지 — 평단 기반 숫자 전체의 전제가 달라진다
  basis_adjusted: boolean;
  // 보유 중일 때만 채워진다 — 진입 정보만 있으면 나가는 판단이 매번 즉흥이 된다
  exit_plan: ExitPlan | null;
}
export interface ExitPlan {
  held_quantity: number; avg_price: number;
  // 손익을 '감수한 리스크의 몇 배'로 잰 값 — 손절선이 평단 위면 null
  r_unit: number | null; r_multiple: number | null;
  unrealized_pnl_pct: number; unrealized_pnl_krw: number;
  stop_from_avg_pct: number; risk_to_stop_krw: number; stop_locks_profit: boolean;
  // 해외 포지션은 확정손익에서 이듬해 5월 양도세가 더 빠진다
  taxable_overseas: boolean; deduction_left_krw: number | null;
  slices: { label: string; quantity: number;
            proceeds_krw: number; realized_pnl_krw: number;
            tax_krw: number; realized_pnl_after_tax_krw: number }[];
}
export interface OverseasTax {
  year: number; gain_krw: number; deduction_krw: number; deduction_left_krw: number;
  taxable_krw: number; tax_krw: number; rate_pct: number;
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
  // 주문 프리뷰의 '체결 후 잔액' — 예수금 초과를 사후 클램프가 아니라 미리 안다
  cash: { krw: number; usd: number };
  // 이 종목이 준 현금 — 주가 손익 옆에 없으면 배당주가 늘 실패한 포지션으로 읽힌다
  dividends: DividendView;
  history: { date: string; swing_score: number; longterm_score: number; grade: string }[];
  rules: { id: number; symbol: string; rule_type: string; value: number }[];
  /** 현재 포지션을 열었을 때의 근거. 물타기는 "얼마나 물렸나"가 아니라
   *  "그때 산 이유가 아직 서 있나"로 결정해야 한다. 보유가 없으면 null. */
  entry_review: EntryReview | null;
  last_refresh: string | null;
}
export interface EntryReview {
  first_entry_date: string; first_entry_price: number;
  entry_note: string | null; entry_grade: string | null;
  current_grade: string | null; grade_downgraded: boolean;
  buy_count: number;
}
export interface Holding {
  symbol: string; name: string; market: string; currency: string;
  quantity: number; avg_price: number; close: number | null;
  // 원가에 평단 맞춤 보정 로트가 섞였는지 — 이 행의 숫자 전체의 전제가 달라진다
  basis_adjusted: boolean;
  // 증권사가 평균매입가를 안 줘서 현재가로 채운 행 — 손익 0은 '본전'이 아니라 '평단 모름'
  basis_missing: boolean;
  /** 이 수량·평단의 출처 */
  source: 'ledger' | 'broker';
  value: number | null; pnl: number | null; pnl_pct: number | null;
  // 통화가 섞이면 종목 통화 표시만으로는 포지션 크기를 나란히 볼 수 없다
  value_krw: number | null; weight_pct: number | null;
  // 지금 전량 팔면 실제로 들어오는 금액 — 수익률만 보고 본전으로 읽는 것을 막는다
  exit_cost: number | null; net_proceeds: number | null; net_pnl: number | null;
  // 원화 손익을 주가 기여와 환 기여로 분리
  price_pnl_krw: number | null; fx_pnl_krw: number | null; pnl_krw: number | null;
  // 이 종목이 준 현금(누적 배당 순액). 주가 손익만 보면 배당주는 늘 실패로 읽힌다.
  dividend_krw: number;
  total_return_krw: number | null; total_return_pct: number | null;
}
export interface CashFlow {
  id: number; flow_type: 'DIVIDEND' | 'DEPOSIT' | 'WITHDRAW' | 'INTEREST';
  symbol: string | null; currency: string;
  amount: number; tax: number; flow_date: string;
  fx_rate: number | null; note: string | null;
}
export interface DividendView {
  year: number | null; count: number; ytd_count: number;
  total_gross_krw: number; total_tax_krw: number; total_net_krw: number;
  ytd_gross_krw: number; ytd_net_krw: number;
  // 올해 배당 ÷ 배당을 준 종목들의 현재 원가. 중간에 사고 판 종목이 섞이면 null.
  yield_on_cost_pct: number | null; yield_basis_krw: number; yield_partial: boolean;
  fx_estimated: boolean;
  by_symbol: { symbol: string; name: string; currency: string; count: number;
               gross: number; tax: number; net: number;
               net_krw: number; ytd_net_krw: number;
               first_date: string | null; last_date: string | null;
               held: boolean; position_changed: boolean;
               yield_on_cost_pct: number | null }[];
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
    total_asset_krw: number; cash_pct: number;
    // 원화 환산에 실제로 쓴 환율 — estimated면 수집 실패로 기본값을 쓴 것이다
    usdkrw: number; usdkrw_estimated: boolean;
    // 평가손익 + 누적 배당. 배당이 0이면 같은 숫자가 두 번 나오므로 null이다.
    dividend_krw: number;
    total_return_krw: number | null; total_return_pct: number | null };
  allocation: { label: string; value_krw: number }[];
  dividends: DividendView;
  realized: { entries: RealizedEntry[]; stats: RealizedStats; overseas_tax: OverseasTax };
  risk: AccountRisk | null;
  open_risk: OpenRisk | null;
  last_refresh: string | null;
  broker: BrokerStatus;
}
export interface BrokerAccount {
  organization: string; account: string; display: string; name: string | null;
}
export interface BrokerStatus {
  /** .env에 CODEF 키가 설정되어 있는지 — 없으면 연결 자체가 불가능하다 */
  configured: boolean;
  env: string;
  connected: boolean;
  accounts: BrokerAccount[];
  synced_at: string | null;
  flow_synced_at: string | null;
  holdings_count: number;
}
export interface BrokerFlowResult {
  start: string; end: string; synced_at: string;
  added: { DEPOSIT: number; WITHDRAW: number; DIVIDEND: number; INTEREST: number };
  total_added: number;
  /** 이미 가져온 거래 — 같은 기간을 다시 눌러도 중복으로 쌓이지 않는다 */
  duplicates: number;
  /** 매매 대금 줄 — 원장(trades)이 진실이라 가져오지 않는다 */
  skipped_trades: number;
  /** 종목을 못 붙인 배당 적요 — 합계엔 들어가지만 종목별 배당수익률엔 안 잡힌다 */
  no_symbol: string[];
}
export interface BrokerSyncResult {
  synced_at: string; holdings: number; cash_krw: number; cash_usd: number;
  /** 앱 심볼로 확정하지 못한 종목 — 조용히 빼면 총자산이 실제보다 작아진다 */
  unmapped: { name: string; raw_code: string; quantity: number }[];
  basis_missing: string[];
}
/** 등급이 방향을 가르는가 — 매수 등급 성적 − 매도 등급 성적 (%p, 비용 차감 후) */
export interface Discrimination {
  horizon: number; buy_net: number; sell_net: number;
  spread: number; discriminates: boolean;
}
export interface AccountRisk {
  days: number;
  weights: { symbol: string; name: string; weight_pct: number }[];
  max_weight_pct: number | null;
  // 상관 0.7+ 로 묶인 종목들 — 종목별 비중이 낮아도 이 합이 실제 베팅 크기다
  clusters: { symbols: string[]; names: string[]; weight_pct: number }[];
  max_cluster_pct: number | null; cluster_threshold: number;
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
  // 비용 가정이 무엇을 포함하는지, 그 가정이 2배 틀렸을 때 어떻게 되는지
  cost_breakdown: { total_pct: number; stress_pct: number; note: string };
  min_episodes: number; horizons: number[]; long_horizons: number[];
  // horizon별로 이 관측 기간이 만들 수 있는 비중첩 표본 상한. min_episodes보다 작으면
  // 데이터가 더 쌓여서 채워질 칸이 아니라 애초에 검증이 불가능한 구간이다.
  max_episodes: Record<string, number>;
  entry_rule: string; exit_rule: string;
  grades: BacktestGrade[];
  discrimination: Record<string, Discrimination | null>;
  longterm_grades: BacktestGrade[];
  // 관측 기간 중 0회 — 빈 행을 "아직 안 쌓임"으로 오해하지 않도록 명시한다
  missing_grades: string[];
  missing_longterm_grades: string[];
}
export interface SearchResult {
  symbol: string; name: string; market: string; is_etf: number;
  yf_symbol: string | null; currency: string;
}
export interface Trade {
  id: number; symbol: string; side: string; quantity: number;
  price: number; trade_date: string; executed_at: string | null;
  fee: number | null; tax: number | null;
  note: string | null; grade_at_trade: string | null;
  exclude_from_stats: number;
}
