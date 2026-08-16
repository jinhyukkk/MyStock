import { useOutletContext } from 'react-router-dom'
import type { CashFlow, Portfolio as PF, Trade } from '../../types'

export interface PortfolioContext {
  /** 레이아웃이 로딩·에러를 먼저 처리하므로 하위 화면에서는 항상 non-null */
  pf: PF
  trades: Trade[]
  flows: CashFlow[]
  posRule: { min: string; max: string }
  setPosRule: (u: (r: { min: string; max: string }) => { min: string; max: string }) => void
  /** 기준시각 계산용 — isStale/relativeTime에 넘긴다 */
  now: number
  /** 입력·삭제 후 4개 API를 다시 불러 모든 탭을 함께 갱신한다 */
  reload: () => void
  /** 예수금 클램프 경고 — 총자산에 관한 내용이라 스트립 아래에 뜬다 */
  setCashWarn: (msg: string | null) => void
}

export const usePortfolio = () => useOutletContext<PortfolioContext>()
