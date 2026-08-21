import { Link } from 'react-router-dom'
import type { TickerDetail as Detail } from '../../types'
import { cur } from '../../format'
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
  const tone = change === null || change.diff === 0 ? '' : change.diff > 0 ? 'pos' : 'neg'
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
      </div>
      <div className="quote-pricebox">
        <div>
          <div className="quote-price">{last ? cur(detail.currency, last.close) : '—'}</div>
          <div className={`quote-change ${tone}`}>
            {change ? <>{change.diff > 0 ? '+' : ''}{cur(detail.currency, change.diff).replace(/^([₩$])-/, '-$1')}
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
