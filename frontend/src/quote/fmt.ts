/** 종목상세 전용 숫자 표기.
 *
 *  `format.ts`의 `fmt`/`cur`는 앱 전역(대시보드·포트폴리오)이 쓰는 규칙이라
 *  건드리지 않는다. 축약(B/M·조/억)은 finviz 스냅샷 84칸에서만 쓰는 규칙이고,
 *  전역에 번지면 손익·잔고까지 반올림돼 보인다. */

/** 큰 수 축약. USD는 `333.70B`/`92.20M`, KRW는 `12.3조`/`4,560억`.
 *
 *  원화에 소수점 원 단위를 만들지 않는다 — 억 미만은 정수로 끊는다.
 *  주식수처럼 통화가 아닌 큰 수도 같은 규칙으로 읽는다(7.3억 주). */
export function abbrNum(currency: string, n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '—'
  const sign = n < 0 ? '-' : ''
  const a = Math.abs(n)
  if (currency === 'USD') {
    if (a >= 1e12) return `${sign}${(a / 1e12).toFixed(2)}T`
    if (a >= 1e9) return `${sign}${(a / 1e9).toFixed(2)}B`
    if (a >= 1e6) return `${sign}${(a / 1e6).toFixed(2)}M`
    if (a >= 1e3) return `${sign}${(a / 1e3).toFixed(2)}K`
    return `${sign}${a.toLocaleString('en-US', { maximumFractionDigits: 2 })}`
  }
  // 1263.8조처럼 네 자리가 되면 자릿수를 눈으로 못 센다 — 천단위 구분을 넣는다
  if (a >= 1e12)
    return `${sign}${(a / 1e12).toLocaleString('ko-KR', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}조`
  // 100억 미만에서 정수로 끊으면 7.28억 주가 '7억'이 된다 — 자릿수가 하나 날아간다
  if (a >= 1e10) return `${sign}${Math.round(a / 1e8).toLocaleString('ko-KR')}억`
  if (a >= 1e8) return `${sign}${(a / 1e8).toFixed(1)}억`
  if (a >= 1e4) return `${sign}${Math.round(a / 1e4).toLocaleString('ko-KR')}만`
  return `${sign}${Math.round(a).toLocaleString('ko-KR')}`
}

/** 부호를 붙이는 퍼센트 — 변화율·이격·성과 칸 전용. */
export const pctText = (v: number | null | undefined, digits = 2): string =>
  v === null || v === undefined || !Number.isFinite(v) ? '—'
    : `${v > 0 ? '+' : ''}${v.toFixed(digits)}%`

/** 수준을 나타내는 퍼센트(ROE·마진·지분율) — finviz도 여기엔 부호를 붙이지 않는다. */
export const levelPct = (v: number | null | undefined, digits = 2): string =>
  v === null || v === undefined || !Number.isFinite(v) ? '—' : `${v.toFixed(digits)}%`

/** 배수·비율(PER·PBR·베타). 소수 자릿수를 고정해 세로로 자릿점이 맞는다. */
export const ratioText = (v: number | null | undefined, digits = 2): string =>
  v === null || v === undefined || !Number.isFinite(v) ? '—' : v.toFixed(digits)

/** 정수(직원수·거래량·주식수 원값). */
export const intText = (v: number | null | undefined): string =>
  v === null || v === undefined || !Number.isFinite(v) ? '—' : Math.round(v).toLocaleString('ko-KR')

/** 스냅샷 칸의 금액 — 통화 기호를 붙이지 않는다. 기호까지 넣으면
 *  `₩2,987,000 -42%` 가 칸을 넘긴다. 통화는 헤더에 한 번만 쓴다.
 *  USD는 센트까지, KRW는 원 단위까지. */
export const moneyCell = (currency: string, v: number | null | undefined): string =>
  v === null || v === undefined || !Number.isFinite(v) ? '—'
    : currency === 'USD' ? v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
      : Math.round(v).toLocaleString('ko-KR')

/** `2026-08-21` → `08-21` 같은 축약이 아니라, 없는 날짜를 —로 만드는 통로. */
export const dateText = (v: string | null | undefined): string => v ? v : '—'
