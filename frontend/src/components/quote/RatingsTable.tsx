import type { Ratings } from '../../types'
import { moneyCell, pctText, ratioText } from '../../quote/fmt'
import BlockEmpty from './BlockEmpty'

/** 애널리스트 블록 — 컨센서스 요약 + 등급 변경 이력.
 *
 *  국내 종목은 증권사별 등급 변경 이력을 주는 무료 소스가 없다. 그 자리를 빈 표로
 *  두면 "변경이 없었다"로 읽히므로, 백엔드가 준 `note`(이유)와 최근 리포트 목록으로
 *  대신한다. 어느 쪽을 그릴지는 데이터 유무가 정한다 — 시장 코드로 분기하지 않는다. */
export default function RatingsTable({ block, currency, loading }: {
  block: Ratings | null | undefined; currency: string; loading?: boolean
}) {
  if (!block || block.status !== 'ok')
    return <BlockEmpty block={block} loading={loading} empty="컨센서스 정보가 없습니다." />

  const c = block.consensus
  const money = (v: number | null) => moneyCell(currency, v)
  return (
    <>
      {c ? (
        <div className="kv">
          <div className="kv-row"><span className="k">투자의견</span>
            <span className="v">{ratioText(c.recommendation_mean)}
              {c.recommendation_label && <small>{c.recommendation_label}</small>}</span></div>
          <div className="kv-row"><span className="k">목표주가(평균)</span>
            <span className="v">{money(c.target_mean)}
              {c.target_upside_pct !== null && <small>{pctText(c.target_upside_pct)}</small>}</span></div>
          <div className="kv-row"><span className="k">애널리스트</span>
            <span className="v">{c.analyst_count === null ? '—' : `${c.analyst_count}명`}
              {c.as_of && <small>{c.as_of}</small>}</span></div>
        </div>
      ) : <div className="quote-note block-empty">컨센서스 요약이 없습니다.</div>}

      {/* 1=강력매수 스케일을 화면이 명시한다 — 뒤집힌 값이 오면 여기가 거짓말이 된다 */}
      <div className="quote-note" style={{ marginTop: 4 }}>투자의견 1=강력매수 … 5=강력매도</div>

      {block.note && <div className="quote-note block-empty" style={{ marginTop: 8 }}>{block.note}</div>}

      {block.changes.length > 0 && (
        <div className="table-scroll table-cards" style={{ marginTop: 8 }}>
          <table>
            <thead><tr><th>날짜</th><th>구분</th><th>증권사</th><th>등급</th><th>목표가</th></tr></thead>
            <tbody>
              {block.changes.map((r, i) => (
                <tr key={`${r.date}-${r.firm}-${i}`}>
                  <td data-label="날짜">{r.date}</td>
                  <td data-label="구분">{r.action}</td>
                  <td data-label="증권사">{r.firm}</td>
                  <td data-label="등급">{r.from_grade || r.to_grade
                    ? `${r.from_grade ?? '—'} → ${r.to_grade ?? '—'}` : '—'}</td>
                  <td data-label="목표가">{r.from_target !== null || r.to_target !== null
                    ? `${money(r.from_target)} → ${money(r.to_target)}` : '—'}</td>
                </tr>))}
            </tbody>
          </table>
        </div>
      )}

      {block.reports.length > 0 && (
        <div className="table-scroll table-cards" style={{ marginTop: 8 }}>
          <table>
            <thead><tr><th>날짜</th><th>증권사</th><th>리포트</th></tr></thead>
            <tbody>
              {block.reports.map((r, i) => (
                <tr key={`${r.date}-${r.firm}-${i}`}>
                  <td data-label="날짜">{r.date}</td>
                  <td data-label="증권사">{r.firm}</td>
                  <td>{r.url
                    ? <a href={r.url} target="_blank" rel="noreferrer">{r.title}</a> : r.title}</td>
                </tr>))}
            </tbody>
          </table>
        </div>
      )}

      {!c && block.changes.length === 0 && block.reports.length === 0 && !block.note &&
        <div className="quote-note block-empty">애널리스트 자료가 없습니다.</div>}
    </>
  )
}
