import type { News } from '../../types'
import BlockEmpty from './BlockEmpty'

/** finviz 뉴스 목록 — 날짜가 바뀔 때만 날짜를 쓰고, 같은 날은 시각만 쓴다.
 *  20건이 모두 날짜를 달고 있으면 "오늘 무엇이 있었나"가 반복 문자열에 묻힌다. */
export default function NewsList({ block, loading }: {
  block: News | null | undefined; loading?: boolean
}) {
  const items = block?.status === 'ok' ? block.items : []
  if (items.length === 0)
    return <BlockEmpty block={block} loading={loading} empty="최근 뉴스가 없습니다." />

  let prevDate = ''
  return (
    <ul className="news-list">
      {items.map((n, i) => {
        const { date, time } = split(n.published_at)
        const showDate = date !== prevDate
        prevDate = date
        return (
          <li key={`${n.url}-${i}`} className={showDate ? 'news-item new-day' : 'news-item'}>
            <span className="news-time">{showDate ? `${date} ${time}` : time}</span>
            <a href={n.url} target="_blank" rel="noreferrer">{n.title}</a>
            {n.source && <span className="news-src">{n.source}</span>}
          </li>
        )
      })}
    </ul>
  )
}

/** ISO(KST) → 날짜·시각. 파싱이 안 되면 원문을 날짜 자리에 그대로 둔다 —
 *  Invalid Date를 숫자로 찍는 것보다 원문이 낫다. */
function split(iso: string): { date: string; time: string } {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(iso)
  if (!m) return { date: iso, time: '' }
  return { date: `${m[2]}-${m[3]}`, time: `${m[4]}:${m[5]}` }
}
