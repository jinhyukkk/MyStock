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
  /** 회사 프로필·finviz 84칸 스냅샷. 백엔드가 아직 안 붙였거나 캐시 전이면 없다 —
   *  선택 필드라 구버전 응답에서도 화면이 그대로 뜬다. */
  profile?: Profile | null;
  snapshot?: Snapshot | null;
  last_refresh: string | null;
}
/** `GET /api/tickers/{symbol}` 응답.
 *
 *  미등록 종목은 백그라운드 수집이 끝날 때까지 pending이 온다. 실패에 404가 아니라
 *  status를 쓰는 이유는 백엔드 주석 참고 — 첫 응답 시점엔 '없는 종목'인지
 *  '아직 수집 전'인지 구분할 수 없다. */
export type TickerDetailReady = TickerDetail & { status: 'ready'; tracked: boolean }
export type TickerDetailResponse =
  | { status: 'pending'; symbol: string }
  | { status: 'failed'; symbol: string; message: string }
  | TickerDetailReady
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
}
/** 알림(텔레그램). 봇 토큰은 저장 여부만 돌려받는다 — 화면에 평문을 다시 그리지 않는다 */
export interface NotifyStatus {
  enabled: boolean; token_set: boolean; chat_id: string; source: 'env' | '설정';
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
  bench_label: string | null; cost_pct: number; excess_net?: boolean; stop_atr_mult: number;
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

/* ── 종목상세 회사 자료 (spec 20_spec.md §5) ──
   전부 백엔드가 뒤늦게 붙이는 신규 필드다. 구버전 백엔드(또는 구버전 빌드본)에서도
   화면이 컴파일·렌더돼야 하므로 TickerDetail 쪽 진입점은 선택 필드로 선언한다. */
export interface Profile {
  sector: string | null; industry: string | null; country: string | null;
  exchange: string | null; employees: number | null; ipo_date: string | null;
  website: string | null;
  description: string | null; description_truncated?: boolean;
  /** 계약 v2 — 회사 자료 수집 전이면 'pending' + note(BE가 쓴 한국어 문구).
   *  BE가 아직 안 내려주는 동안도 화면이 서야 하므로 선택 필드다. */
  status?: 'ok' | 'pending';
  note?: string | null;
  // KR 종목에서 'en'이면 화면이 "영문 원문" 배지를 붙인다 — 한국어 개요를 못 받은 상태다
  description_lang: 'ko' | 'en' | null;
  source: string; fetched_at: string | null;
}
/** 기간별 성과(%). candles는 200봉뿐이라 1년 이상은 백엔드(price_cache)만 만들 수 있다. */
export interface SnapshotPerf {
  w1: number | null; m1: number | null; m3: number | null; m6: number | null;
  ytd: number | null; y1: number | null; y3: number | null; y5: number | null;
  y10: number | null;
}
/** finviz 84칸 중 백엔드가 외부 소스에서 채우는 값. 하위 키는 전부 null 허용. */
export interface Snapshot {
  market_cap: number | null; enterprise_value: number | null;
  income_ttm: number | null; sales_ttm: number | null;
  book_per_share: number | null; cash_per_share: number | null;
  dividend_est: number | null; dividend_ttm: number | null;
  // 계약 v2 — fundamentals.dividend_yield와 달리 §5.1 퍼센트 정규화·스케일 가드를 거친 값
  dividend_yield_pct?: number | null;
  dividend_ex_date: string | null;
  dividend_growth_3y_pct: number | null; dividend_growth_5y_pct: number | null;
  payout_pct: number | null;
  pe: number | null; forward_pe: number | null; peg: number | null;
  ps: number | null; pb: number | null; pc: number | null; p_fcf: number | null;
  ev_ebitda: number | null; ev_sales: number | null;
  quick_ratio: number | null; current_ratio: number | null;
  debt_eq: number | null; lt_debt_eq: number | null; float_pct: number | null;
  eps_ttm: number | null; eps_next_y: number | null; eps_next_q: number | null;
  eps_this_y_pct: number | null; eps_next_y_pct: number | null; eps_next_5y_pct: number | null;
  eps_past_3y_pct: number | null; eps_past_5y_pct: number | null;
  sales_past_3y_pct: number | null; sales_past_5y_pct: number | null;
  eps_yoy_ttm_pct: number | null; sales_yoy_ttm_pct: number | null;
  eps_qoq_pct: number | null; sales_qoq_pct: number | null;
  earnings_date: string | null; earnings_timing: string | null;
  eps_surprise_pct: number | null; sales_surprise_pct: number | null;
  insider_own_pct: number | null; insider_trans_pct: number | null;
  inst_own_pct: number | null; inst_trans_pct: number | null;
  // KR은 기관 변동 대신 외국인 지분이 온다 — 값이 있는 쪽을 화면이 고른다
  foreign_own_pct: number | null;
  roa_pct: number | null; roe_pct: number | null; roic_pct: number | null;
  gross_margin_pct: number | null; oper_margin_pct: number | null; profit_margin_pct: number | null;
  shares_outstanding: number | null; shares_float: number | null;
  short_float_pct: number | null; short_ratio: number | null; short_interest: number | null;
  beta: number | null;
  perf: SnapshotPerf;
  // 1=강력매수 기준으로 백엔드가 정규화해서 보낸다. scale 문자열이 이 전제를 고정한다.
  recommendation_mean: number | null; recommendation_scale: string;
  target_price: number | null;
  sources: string[]; fetched_at: string | null;
  status: 'ok' | 'pending';
  // pending일 때 BE가 쓴 사용자 문구 — 프론트가 같은 문구를 다시 만들지 않는다
  note?: string | null;
}
/** /company의 4블록 공통 래퍼. note는 백엔드가 만든 한국어 문구를 그대로 렌더한다 —
 *  같은 분기 로직을 프론트에 복제하면 두 곳이 서로 다른 말을 하게 된다. */
export interface CompanyBlock {
  status: 'ok' | 'pending' | 'unavailable';
  note: string | null; source: string | null; fetched_at: string | null;
}
export interface FinancialsItem {
  period: string; end_date: string | null;
  eps: number | null; sales: number | null; shares_outstanding: number | null;
  // 컨센서스 추정치 — 실적으로 읽히면 안 되므로 화면에서 반투명 + (E)
  estimate: boolean;
}
export interface Financials extends CompanyBlock {
  annual: FinancialsItem[]; quarterly: FinancialsItem[];
  shares_note: string | null;
}
export interface NewsItem {
  published_at: string; title: string; source: string | null; url: string; lang: 'ko' | 'en';
}
export interface News extends CompanyBlock { items: NewsItem[] }
export interface RatingsConsensus {
  recommendation_mean: number | null; recommendation_label: string | null;
  target_mean: number | null; target_upside_pct: number | null;
  analyst_count: number | null; as_of: string | null;
}
export interface RatingChange {
  date: string; firm: string; action: string;
  from_grade: string | null; to_grade: string | null;
  from_target: number | null; to_target: number | null;
}
export interface ResearchReport { date: string; firm: string; title: string; url: string | null }
export interface Ratings extends CompanyBlock {
  consensus: RatingsConsensus | null;
  changes: RatingChange[];
  // KR 대체 — 증권사별 등급 변경 이력을 주는 무료 소스가 없어 리포트 목록으로 대신한다
  reports: ResearchReport[];
}
export interface InsiderItem {
  name: string; relation: string | null; date: string; transaction: string;
  price: number | null; shares: number | null; value: number | null;
  shares_total: number | null; url: string | null;
}
export interface Insiders extends CompanyBlock { items: InsiderItem[] }
export interface Company {
  symbol: string;
  financials: Financials; news: News; ratings: Ratings; insiders: Insiders;
}

/** 전략 연구실 — 계좌 단위 백테스트 (등급 검증용 Backtest와 다른 것) */
export interface EquityPoint { date: string; equity_krw: number }
export interface StrategyTrade {
  symbol: string; name: string;
  entry_date: string; entry_price: number;
  exit_date: string; exit_price: number;
  /** stop=손절 터치, signal=청산 신호, end=데이터 끝 평가청산,
      delisted=상장폐지 강제청산(마지막 종가 근사 — 실손실 과소평가 가능) */
  exit_reason: 'stop' | 'signal' | 'end' | 'delisted';
  qty: number; cost_krw: number; pnl_krw: number;
}
export interface StrategyMetrics {
  /** 유니버스가 비어 자본곡선이 없으면 null — 0%가 아니다 */
  cagr: number | null;
  mdd: number | null;
  /** 무위험수익률 0 가정. 변동성이 0이면 null */
  sharpe: number | null;
  /** 비용 차감 후 손익이 양(+)인 거래 비율. 거래가 없으면 null */
  win_rate: number | null;
  trade_count: number;
  /** 유니버스가 비면 null — 0을 그리면 전액 손실처럼 보인다 */
  final_equity_krw: number | null;
  /** 벤치마크(KOSPI) 매수보유 CAGR */
  bench_cagr: number | null;
  /** 유니버스 동일가중 매수보유 CAGR */
  buy_and_hold_cagr: number | null;
  /** 초과수익 = 전략 CAGR − 벤치마크 CAGR */
  excess_vs_bench: number | null;
}
export interface StrategyResult {
  equity_curve: EquityPoint[];
  buy_and_hold: EquityPoint[];
  benchmark: EquityPoint[];
  benchmark_label: string | null;
  trades: StrategyTrade[];
  metrics: StrategyMetrics;
  max_concurrent: number; universe_size: number;
  preset: string; params: Record<string, number>;
  /** 서버가 내려주는 유니버스 편향 경고 — 화면이 문구를 지어내지 않는다 */
  universe_warning: string;
  fx_note: string;
  initial_capital_krw: number;
}
export interface StrategyParamMeta {
  default: number; min: number; max: number; label: string;
  /** 최적화 그리드 서치 탐색 후보 */
  grid?: number[];
}
/** engine.metrics 원형 — 최적화 표는 벤치마크 비교 없이 이 6개만 받는다 */
export interface OptimizeMetrics {
  cagr: number | null; mdd: number | null; sharpe: number | null;
  win_rate: number | null; trade_count: number;
  final_equity_krw: number | null;
}
export interface OptimizeRow {
  params: Record<string, number>;
  train: OptimizeMetrics;
  valid: OptimizeMetrics;
}
export interface OptimizeResult {
  /** 표본이 120일 미만이면 null — 결과도 빈 배열 */
  split_date: string | null;
  valid_start?: string;
  train_days: number; valid_days: number;
  /** 검증 샤프 내림차순(null 최하) 정렬 상태로 내려온다 */
  results: OptimizeRow[];
  universe_warning: string;
  note: string;
}
export interface StrategyPreset {
  key: string; label: string; params: Record<string, StrategyParamMeta>;
}

/** engine.metrics 그대로 — StrategyMetrics의 bench 필드는 백테스트 API가
    별도로 붙이는 것이라 워크포워드 폴드에는 없다 */
export interface WalkforwardMetrics {
  cagr: number | null; mdd: number | null; sharpe: number | null;
  win_rate: number | null; trade_count: number;
  final_equity_krw: number | null;
}
export interface WalkforwardFold {
  fold: number;
  train_end: string; valid_start: string; valid_end: string;
  /** 학습 구간 그리드 1등(학습 샤프 기준) — 이 조합이 검증 구간을 돌았다 */
  params: Record<string, number>;
  valid: WalkforwardMetrics;
  bench_cagr: number | null;
  /** 검증 CAGR − 같은 구간 벤치마크 CAGR. 이 값이 판정 기준이다 */
  excess_pct: number | null;
}
export interface WalkforwardSummary {
  median_excess_pct: number | null;
  positive_folds: number; total_folds: number;
  param_stability: { distinct_combos: number; note: string };
}
export interface WalkforwardResult {
  folds: WalkforwardFold[];
  summary: WalkforwardSummary | null;
  /** 폴드 검증 곡선을 체인링크로 이은 것 — 실전 기대값에 가장 가까운 곡선 */
  stitched_curve: EquityPoint[];
  stitched_metrics: WalkforwardMetrics;
  stitched_bench: EquityPoint[];
  preset: string; universe: string; universe_size: number;
  initial_capital_krw: number;
  benchmark_label: string | null;
  universe_warning: string;
}
export interface JobProgress { done: number; total: number | null }
export interface JobStatus<T> {
  status: 'running' | 'done' | 'error';
  progress: JobProgress;
  started_at?: string;
  result?: T; error?: string;
}
export interface UniverseStatus {
  symbols: number; last_date: string | null;
  delisted_count: number; collected_at: string | null;
}

// ── 자동매매 ────────────────────────────────────────────────────────────────
export interface AutoPosition {
  symbol: string; qty: number;
  /** 주문 시점 직전 종가 근사 — 실제 체결가와 다를 수 있다 */
  entry_price: number;
  stop: number; entry_date: string;
}
export interface AutoOrderRow {
  id: number; created_at: string; mode: string;
  symbol: string; name: string | null;
  side: 'BUY' | 'SELL'; qty: number;
  reason: 'enter' | 'exit_signal' | 'stop';
  status: 'sent' | 'failed';
  order_no: string | null; error: string | null; price_ref: number | null;
}
export interface AutotradeStatus {
  configured: boolean;
  mode: string;
  settings: { preset: string; params: Record<string, number> };
  positions: AutoPosition[];
  orders: AutoOrderRow[];
}
export interface PlannedOrder {
  symbol: string; name: string;
  side: 'BUY' | 'SELL'; qty: number;
  reason: 'enter' | 'exit_signal' | 'stop';
  price_ref: number; stop: number | null;
  /** execute 응답에만 실림 */
  status?: 'sent' | 'failed'; order_no?: string; error?: string;
}
export interface AutotradePlan {
  date: string;
  /** 신호 계산에 쓴 마지막 일봉 날짜 — 오래됐으면 warnings에 경고가 실린다 */
  as_of: string | null;
  mode: string;
  preset: string; params: Record<string, number>;
  equity_krw: number; cash_krw: number;
  orders: PlannedOrder[];
  warnings: string[];
}
