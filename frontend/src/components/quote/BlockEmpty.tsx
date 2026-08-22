import type { CompanyBlock } from '../../types'
import { relativeTime } from '../../time'

/** /company 4블록(재무·뉴스·애널리스트·내부자)의 공통 빈 상태·스켈레톤.
 *
 *  문구를 프론트에서 만들지 않는다. "국내 종목 내부자 거래는 OpenDART 키…" 같은
 *  이유는 어느 소스가 없는지 아는 백엔드만 정확히 쓸 수 있고, 같은 분기를 화면에
 *  복제하면 두 곳이 서로 다른 말을 하게 된다. 여기서는 `status`로 무엇을 그릴지만
 *  고르고 `note`는 그대로 흘려보낸다.
 *
 *  - 로딩(block=null): 스켈레톤
 *  - pending: 아직 수집 전 — 새로고침으로 지금 가져올 수 있다
 *  - unavailable: 구조적 미제공 — note가 이유다
 *  - ok인데 항목 0건: empty 문구(호출부가 블록별로 넘긴다) */
export default function BlockEmpty({ block, loading, empty, height = 88 }: {
  block: CompanyBlock | null | undefined
  loading?: boolean
  empty?: string
  height?: number
}) {
  if (loading || !block) return <div className="skeleton" style={{ height, marginTop: 4 }} />
  if (block.status === 'pending')
    return <div className="quote-note block-empty">
      {block.note ?? '회사 자료를 아직 받지 못했습니다 — 새로고침을 누르면 지금 가져옵니다.'}</div>
  if (block.status === 'unavailable')
    return <div className="quote-note block-empty">{block.note ?? '제공되지 않는 데이터입니다.'}</div>
  return <div className="quote-note block-empty">{empty ?? '표시할 항목이 없습니다.'}</div>
}

/** 블록 제목 옆의 출처·갱신시각 한 줄. 캐시가 얼마나 낡았는지를 화면이 숨기면
 *  사용자는 어제 뉴스를 오늘 것으로 읽는다. */
export function BlockSource({ block, now }: { block: CompanyBlock | null | undefined; now: number }) {
  // 출처 없이 '3분 전'만 뜨면 무엇이 3분 전인지 알 수 없다 — 출처가 이 줄의 주어다
  if (!block?.source) return null
  const when = block.fetched_at ? ` · ${relativeTime(block.fetched_at, now)}` : ''
  return <small>{`출처: ${block.source}${when}`}</small>
}
