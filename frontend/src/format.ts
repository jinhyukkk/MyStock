/** 화면 전역 숫자 포맷. null은 "값 없음"이며 0과 구분해서 보여야 한다 —
 *  0으로 찍으면 "데이터가 없다"가 "손익이 없다"로 읽힌다. */
export const fmt = (n: number | null) =>
  n === null ? '—' : n.toLocaleString('ko-KR', { maximumFractionDigits: 2 })

export const cur = (c: string, n: number | null) =>
  n === null ? '—' : (c === 'USD' ? '$' : '₩') + fmt(n)
