/** `GET /api/market` 응답 (backend/app/market.py). 공용 types.ts 는 종목상세 작업이
 *  진행 중이라 거기 섞지 않고 대시보드 전용으로 둔다. */

export type MarketName = 'KR' | 'US'
export interface Session { tz: string; open: string; close: string }
export interface InvestorRow {
  market: string
  /** 집계 기준일. 장 마감 후 집계라 오늘이 아닐 수 있다 — 화면에 같이 찍는다 */
  date: string | null
  personal: number | null
  foreign: number | null
  institution: number | null
}

export interface Candle { o: number | null; h: number | null; l: number | null; c: number | null; v: number | null }
export interface IndexRow {
  name: string; symbol: string; last: number | null; prev_close: number | null
  change: number | null; change_pct: number | null; candles: Candle[]
}
export interface QuoteRow {
  name: string; symbol: string; last: number | null; change: number | null
  change_pct: number | null; decimals: number
}
export interface SignalRow {
  symbol: string; name: string | null; last: number | null
  change_pct: number | null; volume: number | null; signal: string
}
export interface HeatTicker { symbol: string; name: string | null; weight: number; change_pct: number | null }
export interface HeatSector { name: string; tickers: HeatTicker[] }
export interface MajorNewsRow { symbol: string; name: string | null; change_pct: number }
export interface Headline { title: string; source: string; url: string; published_at: string }

/** 시총 상위 유니버스에서 센 시장 내부 지표(backend/app/market_breadth.py). */
export interface BreadthBarData {
  left_label: string; right_label: string; center: string | null
  left_pct: number; left_n: number; right_pct: number; right_n: number
}
export interface UniverseBlock { universe?: string; as_of?: string | null }
export interface BreadthBlock extends UniverseBlock { bars?: BreadthBarData[] }

export interface PatternTicker { symbol: string; name: string | null }
export interface PatternRow { signal: string; icon: string; tickers: PatternTicker[] }
export interface PatternBlock extends UniverseBlock { rows?: PatternRow[] }

/** 키가 필요한 소스는 `unavailable` + `note`(발급 안내)로 온다 — 빈 표를 "일정 없음"으로
 *  읽지 않게 하려는 것. 아직 안 받은 블록은 `{}` 라 `status` 자체가 없다. */
export type BlockStatus = 'ok' | 'unavailable'
export interface EconRow { date: string | null; name: string; value: string | null; unit: string | null }
export interface EconBlock {
  status?: BlockStatus; note?: string | null
  /** indicator = 국내(최신값), release = 미국(발표 예정일) */
  kind?: 'indicator' | 'release'
  rows?: EconRow[]
}
export interface EarningsRow { date: string; tickers: PatternTicker[] }
export interface EarningsBlock {
  status?: BlockStatus; note?: string | null
  /** 실제로 훑은 범위(예: "상위 40종목") — 유니버스 전체가 아니다 */
  scope?: string | null
  rows?: EarningsRow[]
}

export interface InsiderRow {
  symbol: string; name: string | null; owner: string; relation: string
  date: string | null; transaction: string
  shares: number | null
  /** 국내(DART 소유보고)에는 단가·금액이 없어 null 이다 */
  value: number | null; price: number | null
  url?: string | null
}
export interface InsiderBlock {
  status?: BlockStatus; note?: string | null
  /** 두 번째 표의 정렬 기준 — 시장마다 다르다(거래대금 / 변동 수량) */
  top_label?: string
  /** 실제로 훑은 범위(예: "상위 25종목") */
  scope?: string | null
  latest?: InsiderRow[]; top?: InsiderRow[]
}

export interface MarketData {
  market: MarketName
  session: Session
  indices: IndexRow[]
  futures: QuoteRow[]
  forex_bonds: QuoteRow[]
  signals_up: SignalRow[]
  signals_down: SignalRow[]
  heatmap: HeatSector[]
  major_news: MajorNewsRow[]
  headlines: Headline[]
  /** 투자자별 순매수(억원). 한국만 채워지고 미국은 빈 배열 */
  investors: InvestorRow[]
  breadth: BreadthBlock
  patterns: PatternBlock
  econ: EconBlock
  earnings: EarningsBlock
  insider: InsiderBlock
  /** 블록 중 가장 오래된 성공 시각(로컬 ISO). null 이면 아직 아무것도 못 받은 상태 */
  fetched_at: string | null
  /** 이번 갱신에 실패한 블록 이름 — 해당 섹션 값은 이전 성공분이거나 비어 있다 */
  failed: string[]
}
