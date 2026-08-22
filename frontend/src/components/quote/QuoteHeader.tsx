import { Link } from 'react-router-dom'
import type { TickerDetail as Detail } from '../../types'
import { moneyCell } from '../../quote/fmt'
import { relativeTime } from '../../time'

/** finviz 쿼트 헤더 — 좌: 심볼·종목명·시장 링크, 우: 현재가·전일대비·기준시각·버튼. */
export default function QuoteHeader({ detail, change, stale, now, busy, onRefresh, onTrade }: {
  detail: Detail
  change: { prev: number; diff: number; pct: number | null } | null
  stale: boolean
  now: number
  busy: boolean
  onRefresh: () => void
  onTrade: () => void
}) {
  const last = detail.candles.at(-1) ?? null
  const sig = detail.signal
  const p = detail.profile ?? null
  // finviz 헤더의 섹터·산업·국가·거래소 줄. 링크가 아니라 텍스트다 — 이 앱에는
  // 업종 스크리너가 없어서 링크를 만들면 갈 곳 없는 파란 글씨가 된다.
  const facts = [p?.sector, p?.industry, p?.country, p?.exchange,
                 p?.employees != null ? `직원 ${p.employees.toLocaleString('ko-KR')}명` : null]
    .filter((x): x is string => !!x)
  const tone = change === null || change.diff === 0 ? '' : change.diff > 0 ? 'pos' : 'neg'
  // 헤더 $311.3 ↔ 스냅샷 311.30처럼 같은 값이 다른 자릿수로 보이면 다른 값으로 읽힌다.
  // format.ts의 cur는 전역 규칙이라 손대지 않고, 화면 전용 moneyCell에 기호만 붙인다.
  const sym = detail.currency === 'USD' ? '$' : '₩'
  const price = (v: number | null | undefined) =>
    v === null || v === undefined ? '—' : `${sym}${moneyCell(detail.currency, v)}`
  /** 부호는 통화기호 앞에 — `$-5.53`은 읽는 순서가 뒤집힌다 */
  const signedPrice = (v: number) => `${v < 0 ? '-' : '+'}${sym}${moneyCell(detail.currency, Math.abs(v))}`
  return (
    <div className="quote-head" id="top">
      <div>
        <div>
          <span className="quote-ticker">{detail.symbol}</span>
          <span className="quote-name">{detail.name}</span>
        </div>
        <div className="quote-links">
          <Link to="/watchlist">{detail.market}</Link>
          <span>·</span><span>{detail.is_etf ? 'ETF' : '주식'}</span>
          <span>·</span><span>{detail.currency}</span>
          {sig?.regime_label && <><span>·</span><span>{sig.regime_label}</span></>}
        </div>
        {facts.length > 0 && <div className="quote-links quote-facts">
          {facts.map((t, i) => <span key={i}>{i > 0 && <span className="sep">·</span>}{t}</span>)}
        </div>}
      </div>
      <div className="quote-pricebox">
        <div>
          <div className="quote-price">{price(last?.close)}</div>
          <div className={`quote-change ${tone}`}>
            {change ? <>{signedPrice(change.diff)}
              {' '}({change.pct !== null ? `${change.pct > 0 ? '+' : ''}${change.pct.toFixed(2)}%` : '—'})</>
              : <span style={{ color: 'var(--text-dim)' }}>전일 비교 불가</span>}
          </div>
          <div className="quote-asof" title={detail.last_refresh ?? ''}>
            {last?.date} 종가{sig?.bar_complete === false && <span className="warn"> · 미확정 봉</span>}
            {' · '}<span className={stale ? 'warn' : ''}>{stale && '⚠ '}갱신 {relativeTime(detail.last_refresh, now)}</span>
          </div>
        </div>
        <div className="quote-actions">
          <button className="ghost" onClick={onRefresh} disabled={busy}>{busy ? '갱신 중…' : '새로고침'}</button>
          <button onClick={onTrade}>매매 기록</button>
        </div>
      </div>
    </div>
  )
}
