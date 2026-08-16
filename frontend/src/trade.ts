/** 매매 기록 응답과 그 해석. 화면 두 곳(포트폴리오 폼, 종목 상세 모달)에서
 *  같은 판정을 써야 한 쪽만 경고가 뜨는 일이 없다. */

export interface TradeResult {
  id: number
  cash: {
    currency: string
    delta: number        // 예수금에서 빠졌어야 할 금액
    applied: number      // 실제로 빠진 금액
    cash_krw: number
    cash_usd: number
    clamped: boolean     // 예수금이 모자라 0에서 잘렸는가
  } | null
}

const fmt = (n: number) => Math.abs(n).toLocaleString('ko-KR', { maximumFractionDigits: 2 })

/** 예수금 부족으로 잘린 경우의 경고 문구. 잘린 사실을 숨기면 총자산이 실제보다
 *  작게 남고, 그 총자산을 분모로 쓰는 1% 리스크 수량이 전 종목에서 과소 계산된다. */
export function cashClampWarning(res: TradeResult | null): string | null {
  const c = res?.cash
  if (!c?.clamped) return null
  const unit = c.currency === 'USD' ? '$' : '₩'
  const short = Math.abs(c.delta) - Math.abs(c.applied)
  return `예수금이 ${unit}${fmt(short)} 부족해 ${unit}0으로 잘렸습니다 `
    + `(체결 대금 ${unit}${fmt(c.delta)} 중 ${unit}${fmt(c.applied)}만 차감). `
    + '총자산이 실제보다 작게 잡히고, 이를 분모로 쓰는 제안 수량도 함께 작아집니다 — '
    + '예수금을 실제 잔고로 수정하세요.'
}
