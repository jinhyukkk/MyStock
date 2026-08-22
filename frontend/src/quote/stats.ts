/** 스냅샷 표에 들어가는 순수 계산.
 *
 *  finviz 스냅샷의 칸(52W High, Perf Week, SMA20 %, Rel Volume …)은 전부 일봉
 *  배열에서 나온다. 백엔드에 새 필드를 요구하지 않고 여기서 만든다. */
import type { Candle } from '../types'

/** (a / b − 1) × 100, 소수 둘째 자리. b가 0이거나 없으면 null. */
export const pctOf = (a: number, b: number | null | undefined): number | null =>
  b === null || b === undefined || b === 0 ? null : Math.round((a / b - 1) * 10000) / 100

/** 전일 종가 대비 변화. 봉이 둘 미만이면 null. */
export function changeFromPrev(c: Candle[]) {
  if (c.length < 2) return null
  const last = c[c.length - 1].close, prev = c[c.length - 2].close
  return { prev, diff: Math.round((last - prev) * 10000) / 10000, pct: pctOf(last, prev) }
}

/** n거래일 전 종가 대비 수익률. 봉이 모자라면 null. */
export function perfPct(c: Candle[], bars: number): number | null {
  if (c.length <= bars) return null
  return pctOf(c[c.length - 1].close, c[c.length - 1 - bars].close)
}

/** 연초 대비 — 작년 마지막 종가가 있으면 그것, 없으면 올해 첫 봉 종가 기준. */
export function perfYtdPct(c: Candle[], year: number): number | null {
  const first = c.findIndex(x => x.date.startsWith(String(year)))
  if (first < 0) return null
  const base = first > 0 ? c[first - 1].close : c[first].close
  return pctOf(c[c.length - 1].close, base)
}

/** 최근 252봉의 고가 최댓값·저가 최솟값과 현재가의 거리. */
export function range52w(c: Candle[]) {
  if (c.length === 0) return null
  const w = c.slice(-252)
  const last = c[c.length - 1].close
  const high = Math.max(...w.map(x => x.high)), low = Math.min(...w.map(x => x.low))
  return { high, highPct: pctOf(last, high), low, lowPct: pctOf(last, low) }
}

/** 현재가의 이동평균 이격률. */
export const smaGapPct = (close: number, sma: number | null): number | null => pctOf(close, sma)

/** 오늘을 뺀 직전 n봉 평균 거래량. */
export function avgVolume(c: Candle[], bars: number): number | null {
  const w = c.slice(0, -1).slice(-bars)
  if (w.length === 0) return null
  return Math.round(w.reduce((s, x) => s + x.volume, 0) / w.length)
}

/** 오늘 거래량 ÷ 직전 n봉 평균. 평균이 0이면 null. */
export function relVolume(c: Candle[], bars: number): number | null {
  const avg = avgVolume(c, bars)
  if (!avg || c.length === 0) return null
  return Math.round(c[c.length - 1].volume / avg * 100) / 100
}

/** 일간 수익률의 표준편차(%). finviz Volatility 칸(주=5봉, 월=21봉).
 *
 *  ATR은 갭을 포함한 절대 폭이고 이건 종가 수익률의 흩어짐이라 서로 다른 질문에
 *  답한다 — 둘 다 스냅샷에 있어야 "폭"과 "흔들림"을 구분할 수 있다. */
export function volatility(c: Candle[], bars: number): number | null {
  if (c.length < bars + 1) return null
  const w = c.slice(-(bars + 1))
  const r: number[] = []
  for (let i = 1; i < w.length; i++) {
    const prev = w[i - 1].close
    if (!prev) return null
    r.push((w[i].close / prev - 1) * 100)
  }
  const mean = r.reduce((s, x) => s + x, 0) / r.length
  const varc = r.reduce((s, x) => s + (x - mean) ** 2, 0) / r.length
  return Math.round(Math.sqrt(varc) * 100) / 100
}

/** 직전 n봉 평균 거래대금(종가×거래량, 종목 통화).
 *
 *  거래량만으로는 5만 원 주식과 500달러 주식의 유동성을 비교할 수 없다. */
export function avgTurnover(c: Candle[], bars: number): number | null {
  const w = c.slice(-bars)
  if (w.length === 0) return null
  return Math.round(w.reduce((s, x) => s + x.close * x.volume, 0) / w.length)
}
