/** 화면 전역 숫자 포맷. null은 "값 없음"이며 0과 구분해서 보여야 한다 —
 *  0으로 찍으면 "데이터가 없다"가 "손익이 없다"로 읽힌다. */
export const fmt = (n: number | null) =>
  n === null ? '—' : n.toLocaleString('ko-KR', { maximumFractionDigits: 2 })

/** 원화는 원 단위가 최소 단위다 — ₩672,613.12 같은 센트는 수수료 계산의
 *  중간값이 새어 나온 것이지 정보가 아니다. USD만 소수점을 유지한다. */
export const cur = (c: string, n: number | null) =>
  n === null ? '—' : c === 'USD' ? '$' + fmt(n) : '₩' + fmt(Math.round(n))
