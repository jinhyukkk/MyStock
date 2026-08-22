import { test } from 'node:test'
import assert from 'node:assert/strict'
import { abbrNum, pctText, levelPct, ratioText, intText, moneyCell } from './fmt.ts'

test('abbrNum USD: B/M/K 축약, 소수 둘째 자리', () => {
  assert.equal(abbrNum('USD', 333_700_000_000), '333.70B')
  assert.equal(abbrNum('USD', 92_200_000), '92.20M')
  assert.equal(abbrNum('USD', 42_650), '42.65K')
  assert.equal(abbrNum('USD', 3_170_000_000_000), '3.17T')
  assert.equal(abbrNum('USD', -1_500_000), '-1.50M')
})

test('abbrNum KRW: 조/억/만, 원 단위 소수점 없음', () => {
  assert.equal(abbrNum('KRW', 12_300_000_000_000), '12.3조')
  assert.equal(abbrNum('KRW', 456_000_000_000), '4,560억')
  assert.equal(abbrNum('KRW', 1_263_751_800_000_000), '1,263.8조')  // 네 자리 조는 구분 없이 못 읽는다
  assert.equal(abbrNum('KRW', 728_002_365), '7.3억')   // 정수로 끊으면 '7억'이 된다
  assert.equal(abbrNum('KRW', 12_345_678), '1,235만')
  assert.equal(abbrNum('KRW', 8_421), '8,421')
  // 억 단위 이하에서 소수점이 새어 나오면 원화 표기 규칙 위반이다
  assert.ok(!abbrNum('KRW', 456_780_000_000).includes('.'))
})

test('abbrNum: null·NaN은 —', () => {
  assert.equal(abbrNum('USD', null), '—')
  assert.equal(abbrNum('KRW', undefined), '—')
  assert.equal(abbrNum('USD', NaN), '—')
})

test('pctText: 양수에만 +, null은 —', () => {
  assert.equal(pctText(2.43), '+2.43%')
  assert.equal(pctText(-33.98), '-33.98%')
  assert.equal(pctText(0), '0.00%')
  assert.equal(pctText(null), '—')
})

test('levelPct: 수준 퍼센트는 부호를 붙이지 않는다', () => {
  assert.equal(levelPct(49.54), '49.54%')
  assert.equal(levelPct(null), '—')
})

test('ratioText / intText / moneyCell', () => {
  assert.equal(ratioText(25.2531), '25.25')
  assert.equal(ratioText(null), '—')
  assert.equal(intText(16000), '16,000')
  assert.equal(intText(null), '—')
  assert.equal(moneyCell('USD', 80.1), '80.10')
  assert.equal(moneyCell('KRW', 268_500.4), '268,500')
  assert.equal(moneyCell('KRW', null), '—')
})
