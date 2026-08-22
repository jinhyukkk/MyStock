import type { Insiders } from '../../types'
import { abbrNum, intText, moneyCell } from '../../quote/fmt'
import BlockEmpty from './BlockEmpty'

/** 내부자 거래 9열 표. 390px에서는 `.table-cards`로 행이 카드로 접힌다 —
 *  9열을 가로 스크롤로 두면 모바일에서 이름 말고는 아무것도 못 읽는다. */
export default function InsiderTable({ block, currency, loading }: {
  block: Insiders | null | undefined; currency: string; loading?: boolean
}) {
  const items = block?.status === 'ok' ? block.items : []
  if (items.length === 0)
    return <BlockEmpty block={block} loading={loading} empty="공시된 내부자 거래가 없습니다." />
  return (
    <div className="table-scroll table-cards">
      <table>
        <thead><tr>
          <th>내부자</th><th>관계</th><th>날짜</th><th>거래</th><th>단가</th>
          <th>수량</th><th>금액</th><th>보유 총수</th><th>공시</th>
        </tr></thead>
        <tbody>
          {items.map((r, i) => (
            <tr key={`${r.name}-${r.date}-${i}`}>
              <td>{r.name}</td>
              <td data-label="관계">{r.relation ?? '—'}</td>
              <td data-label="날짜">{r.date}</td>
              <td data-label="거래">{r.transaction}</td>
              <td data-label="단가">{moneyCell(currency, r.price)}</td>
              <td data-label="수량">{intText(r.shares)}</td>
              <td data-label="금액">{abbrNum(currency, r.value)}</td>
              <td data-label="보유 총수">{intText(r.shares_total)}</td>
              <td data-label="공시">{r.url
                ? <a href={r.url} target="_blank" rel="noreferrer">원문</a> : '—'}</td>
            </tr>))}
        </tbody>
      </table>
    </div>
  )
}
