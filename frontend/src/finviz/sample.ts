/**
 * 아직 실데이터 소스가 없는 섹션의 정적 샘플 (2026-08-21 finviz.com 홈에서 관찰한 값).
 *
 * 실데이터가 붙은 섹션(지수·선물·환율·시그널·히트맵·Major News·헤드라인)은 `types.ts` +
 * `/api/market` 으로 옮겨 갔고, 여기 남은 것은 화면에서 "샘플" 배지를 달고 나간다.
 * 섹션을 실데이터로 바꿀 때는 여기서 배열을 지우고 Dashboard 의 `sample` 플래그를 내리면 된다.
 *
 * ── 남은 섹션의 소스 현황 ──
 * - BREADTH(상승/하락·신고가·SMA 위/아래 비율): 무료 소스 없음. 전 종목 일봉을 매일 받아
 *   직접 세야 한다 → 별도 수집 작업.
 * - PATTERNS(차트 패턴): 소스가 아니라 자체 탐지 로직(indicators.py) → 별도 작업.
 * - ECON(경제 캘린더): yf·naver·daum·krx·dart 어디에도 없음 → 새 소스 필요.
 * - EARNINGS(실적 발표): 종목 단위 yf calendar → 종목상세 세션의 sources/yf.py 완료 후,
 *   추적 종목 범위로 연결.
 * - INSIDER(내부자 거래): 종목 단위 yf.insider_transactions / dart.elestock → 종목상세
 *   세션 완료 후, 추적 종목 범위로 연결.
 */

export interface Breadth {
  leftLabel: string; rightLabel: string; center?: string
  leftPct: number; leftN: number; rightPct: number; rightN: number
}
export const BREADTH: Breadth[] = [
  { leftLabel: 'Advancing', rightLabel: 'Declining', leftPct: 35.7, leftN: 2007, rightPct: 60.2, rightN: 3386 },
  { leftLabel: 'New High', rightLabel: 'New Low', leftPct: 47.0, leftN: 127, rightPct: 53.0, rightN: 143 },
  { leftLabel: 'Above', rightLabel: 'Below', center: 'SMA50', leftPct: 51.2, leftN: 2873, rightPct: 48.8, rightN: 2738 },
  { leftLabel: 'Above', rightLabel: 'Below', center: 'SMA200', leftPct: 53.1, leftN: 2978, rightPct: 46.9, rightN: 2633 },
]

export interface PatternRow { tickers: string[]; signal: string; icon: string }
export const PATTERNS_LEFT: PatternRow[] = [
  { tickers: ['EU', 'CHD', 'AMRC', 'MLCO'], signal: 'TL Supp.', icon: '↗' },
  { tickers: ['YB', 'GNE', 'VITL', 'COSO'], signal: 'TL Resist.', icon: '↘' },
  { tickers: ['RVSB', 'KRRO', 'KPLT', 'HXHX'], signal: 'Horizontal S/R', icon: '═' },
  { tickers: ['COSO', 'HWM', 'TLX', 'HPK'], signal: 'Wedge Up', icon: '◢' },
  { tickers: ['KBON', 'TGB', 'IRM', 'YELP'], signal: 'Wedge', icon: '◀' },
  { tickers: ['NGG', 'TARS', 'IQST', 'WETH'], signal: 'Wedge Down', icon: '◥' },
  { tickers: ['OKE', 'ACET', 'IFBD', 'CHKP'], signal: 'Triangle Asc.', icon: '◣' },
  { tickers: ['MLCO', 'IMKTA', 'TGS', 'EBON'], signal: 'Triangle Desc.', icon: '◤' },
]
export const PATTERNS_RIGHT: PatternRow[] = [
  { tickers: ['TIGO', 'PEBK', 'MATX', 'RPRX'], signal: 'Channel Up', icon: '⟋' },
  { tickers: ['PLRZ', 'GPMT', 'GNLX', 'SOFI'], signal: 'Channel', icon: '═' },
  { tickers: ['GNL', 'OSRH', 'PNR', 'EH'], signal: 'Channel Down', icon: '⟍' },
  { tickers: ['RLYB', 'KOD', 'KTCC', 'CCSI'], signal: 'Double Top', icon: 'M' },
  { tickers: ['SBUX', 'NN', 'ILPT', 'ROMA'], signal: 'Multiple Top', icon: 'Ⅿ' },
  { tickers: ['ARBE', 'VGAS', 'REAX', 'JELD'], signal: 'Double Bottom', icon: 'W' },
  { tickers: ['ATCH', 'EMBJ', 'TRI', 'DRMA'], signal: 'Multiple Bottom', icon: 'Ⅶ' },
  { tickers: ['CHH', 'ELPC', 'BELFA', 'C'], signal: 'Head&Shoulders', icon: '⩓' },
]

export const ECON_EMPTY_DATE = 'Aug 21'

export interface EarningsRow { date: string; tickers: string[] }
export const EARNINGS: EarningsRow[] = [
  { date: 'Aug 20/a', tickers: ['ROST', 'OSIS', 'FLO', 'PSEC', 'EXOZ', 'ICG', 'FLUX'] },
  { date: 'Aug 21/b', tickers: ['BEKE', 'BJ', 'BKE', 'ZKH'] },
  { date: 'Aug 21/a', tickers: ['OWLS'] },
]

export interface InsiderRow {
  ticker: string; owner: string; relationship: string; date: string
  transaction: 'Buy' | 'Sale' | 'Proposed Sale'; cost: number; shares: number; value: number
}
export const INSIDER_LATEST: InsiderRow[] = [
  { ticker: 'CNVS', owner: 'Huidor Mark Antonio', relationship: 'Pres Tech/Chief', date: 'Aug 19', transaction: 'Sale', cost: 2.68, shares: 15000, value: 40200 },
  { ticker: 'FLD', owner: 'Repass Wolfe', relationship: 'Chief Financial', date: 'Aug 18', transaction: 'Sale', cost: 0.45, shares: 2877, value: 1298 },
  { ticker: 'NTHI', owner: 'CHEN THOMAS C', relationship: 'CEO', date: 'Aug 18', transaction: 'Buy', cost: 5.49, shares: 12757, value: 69998 },
  { ticker: 'AVD', owner: 'ROSENBLOOM KEITH M', relationship: 'Director', date: 'Aug 18', transaction: 'Sale', cost: 2.20, shares: 556580, value: 1224476 },
  { ticker: 'MOBI', owner: 'Tansey Casey M', relationship: 'Director', date: 'Aug 18', transaction: 'Buy', cost: 12.07, shares: 16441, value: 198523 },
  { ticker: 'FLEX', owner: 'Hartung Michael P', relationship: 'Chief Commercia', date: 'Aug 18', transaction: 'Sale', cost: 120.64, shares: 2755, value: 332352 },
]
export const INSIDER_TOP: InsiderRow[] = [
  { ticker: 'ET', owner: 'WARREN KELCY L', relationship: '', date: 'Aug 19', transaction: 'Buy', cost: 0, shares: 0, value: 13775800 },
  { ticker: 'INTC', owner: 'TAN LIP BU', relationship: '', date: 'Aug 11', transaction: 'Buy', cost: 0, shares: 0, value: 9999985 },
  { ticker: 'GS', owner: 'GOLDMAN SACHS GROUP INC', relationship: '', date: 'Aug 06', transaction: 'Buy', cost: 0, shares: 0, value: 8500000 },
  { ticker: 'BIRK', owner: 'Chu James Michael', relationship: '', date: 'Aug 17', transaction: 'Sale', cost: 0, shares: 0, value: 1102769135 },
  { ticker: 'FA', owner: 'SLTA V (GP), L.L.C.', relationship: '', date: 'Aug 12', transaction: 'Sale', cost: 0, shares: 0, value: 275187500 },
  { ticker: 'CBRS', owner: 'SEAN LIE', relationship: '', date: 'Aug 20', transaction: 'Proposed Sale', cost: 0, shares: 0, value: 153193175 },
]
