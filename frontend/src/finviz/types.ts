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
  /** 블록 중 가장 오래된 성공 시각(로컬 ISO). null 이면 아직 아무것도 못 받은 상태 */
  fetched_at: string | null
  /** 이번 갱신에 실패한 블록 이름 — 해당 섹션 값은 이전 성공분이거나 비어 있다 */
  failed: string[]
}
