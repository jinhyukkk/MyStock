import { test } from 'node:test'
import assert from 'node:assert/strict'
import { changeFromPrev, perfPct, perfYtdPct, range52w, smaGapPct, relVolume, avgVolume,
         pctOf, volatility, avgTurnover } from './stats.ts'
import type { Candle } from '../types.ts'

/** n일치 일봉. 종가는 100, 101, 102 … 로 하루 1씩 오른다. 거래량은 1000 고정. */
function candles(n: number, start = '2026-01-05'): Candle[] {
  const out: Candle[] = []
  // toISOString은 UTC로 바꿔 KST 자정이 전날로 밀린다 — UTC 기준으로 만든다
  const d = new Date(start + 'T00:00:00Z')
  for (let i = 0; i < n; i++) {
    const date = d.toISOString().slice(0, 10)
    const close = 100 + i
    out.push({ date, open: close - 0.5, high: close + 1, low: close - 1, close, volume: 1000,
               sma20: null, sma60: null, sma120: null, bb_upper: null, bb_lower: null,
               rsi: null, macd: null, macd_signal: null, macd_hist: null })
    d.setUTCDate(d.getUTCDate() + 1)
  }
  return out
}

test('changeFromPrev: 마지막 종가와 전일 종가의 차이·등락률', () => {
  const c = candles(3)
  assert.deepEqual(changeFromPrev(c), { prev: 101, diff: 1, pct: 0.99 })
})
test('changeFromPrev: 봉이 하나면 null', () => {
  assert.equal(changeFromPrev(candles(1)), null)
})

test('perfPct: n거래일 전 종가 대비 수익률', () => {
  const c = candles(30)
  // 마지막 129 vs 5봉 전 124
  assert.equal(perfPct(c, 5), pctOf(129, 124))
})
test('perfPct: 봉이 모자라면 null', () => {
  assert.equal(perfPct(candles(3), 5), null)
})

test('perfYtdPct: 올해 첫 봉 직전 종가(작년 마지막 종가) 대비', () => {
  const c = candles(10, '2025-12-29')   // 12/29 12/30 12/31 1/1 1/2 …
  // 작년 마지막 종가 102(12/31) 대비 마지막 109
  assert.equal(perfYtdPct(c, 2026), pctOf(109, 102))
})
test('perfYtdPct: 작년 봉이 없으면 올해 첫 봉 종가 대비', () => {
  const c = candles(5, '2026-01-05')
  assert.equal(perfYtdPct(c, 2026), pctOf(104, 100))
})
test('perfYtdPct: 올해 봉이 없으면 null', () => {
  assert.equal(perfYtdPct(candles(5, '2025-03-01'), 2026), null)
})

test('range52w: 최근 252봉의 고가 최댓값·저가 최솟값과 현재가와의 거리', () => {
  const c = candles(300)
  // 최근 252봉: 인덱스 48..299 → 고가 최대 399+1=400, 저가 최소 148-1=147, 현재가 399
  assert.deepEqual(range52w(c), { high: 400, highPct: pctOf(399, 400),
                                  low: 147, lowPct: pctOf(399, 147) })
})
test('range52w: 봉이 없으면 null', () => {
  assert.equal(range52w([]), null)
})

test('smaGapPct: 현재가가 이동평균 위면 양수', () => {
  assert.equal(smaGapPct(110, 100), 10)
  assert.equal(smaGapPct(110, null), null)
})

test('avgVolume / relVolume: 직전 20봉 평균과 오늘 거래량의 비율', () => {
  const c = candles(25)
  c[24].volume = 2000
  assert.equal(avgVolume(c, 20), 1000)
  assert.equal(relVolume(c, 20), 2)
})
test('relVolume: 평균이 0이면 null', () => {
  const c = candles(3).map(x => ({ ...x, volume: 0 }))
  assert.equal(relVolume(c, 20), null)
})

test('pctOf: 소수 둘째 자리 반올림', () => {
  assert.equal(pctOf(103, 100), 3)
  assert.equal(pctOf(100, 103), -2.91)
  assert.equal(pctOf(100, 0), null)
})

test('volatility: 종가가 매일 같은 폭으로 오르면 수익률 분산이 0에 가깝다', () => {
  const c = candles(30)   // 100,101,102… 수익률이 조금씩 줄어드는 등차 수열
  const v = volatility(c, 5)
  assert.ok(v !== null && v <= 0.01, `기대: 0에 가까움, 실제: ${v}`)
})
test('volatility: 한 봉만 크게 튀면 표준편차가 그 폭을 반영한다', () => {
  const c = candles(10)
  c[9].close = c[8].close * 1.1      // 마지막 봉 +10%
  const v = volatility(c, 5)
  assert.ok(v !== null && v > 3, `기대: >3, 실제: ${v}`)
})
test('volatility: 봉이 모자라면 null', () => {
  assert.equal(volatility(candles(3), 5), null)
})

test('avgTurnover: 직전 n봉 (종가 × 거래량) 평균', () => {
  const c = candles(5)               // 종가 100..104, 거래량 1000
  // 최근 3봉 종가 102,103,104 → (102+103+104)*1000/3 = 103000
  assert.equal(avgTurnover(c, 3), 103000)
})
test('avgTurnover: 봉이 없으면 null', () => {
  assert.equal(avgTurnover([], 20), null)
})
