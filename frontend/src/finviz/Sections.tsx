import { Link } from 'react-router-dom'
import type { Breadth, EarningsRow, InsiderRow, PatternRow } from './sample'
import type { Headline, InvestorRow, MajorNewsRow, MarketName, QuoteRow, SignalRow } from './types'

const T = ({ s }: { s: string }) => <Link to={`/ticker/${s}`} className="fv-tk">{s}</Link>
const pct = (v: number | null, d = 2) => v === null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(d)}%`
const sign = (v: number | null) => v === null ? '' : v > 0 ? 'up' : v < 0 ? 'down' : ''
const num = (v: number | null, d: number) =>
  v === null ? '—' : v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
/** 거래량: finviz 식 40.76M / 419.34K */
const vol = (v: number | null) =>
  v === null ? '—' : v >= 1e9 ? `${(v / 1e9).toFixed(2)}B` : v >= 1e6 ? `${(v / 1e6).toFixed(2)}M`
  : v >= 1e3 ? `${(v / 1e3).toFixed(2)}K` : v.toFixed(0)

/** finviz 패널 공통 껍데기. `sample` 이면 우상단에 "샘플" 배지 — 실데이터 섹션과 섞여
 *  있을 때 어느 숫자가 오늘 시장인지 화면이 말해주지 않으면 샘플값으로 판단하게 된다. */
export function Panel({ children, gear, sample, className = '' }:
  { children: React.ReactNode; gear?: boolean; sample?: boolean; className?: string }) {
  return (
    <div className={`fv-panel ${className}`}>
      {sample && <span className="fv-sample" title="실데이터 소스가 아직 없어 finviz 관찰값을 그대로 보여줍니다">샘플</span>}
      {gear && !sample && <span className="fv-gear" aria-hidden>⚙</span>}
      {children}
    </div>
  )
}

export function MarketSummary({ market, onMarket, time, text, stale, failed, error, busy, onRefresh }: {
  market: MarketName; onMarket: (m: MarketName) => void
  time: string; text: string; stale: boolean; failed: string[]; error: string | null
  busy: boolean; onRefresh: () => void
}) {
  return (
    <div className="fv-summary">
      <div className="fv-mkt" role="group" aria-label="시장 선택">
        {(['KR', 'US'] as const).map(m => (
          <button key={m} className={m === market ? 'on' : ''} aria-pressed={m === market}
                  onClick={() => onMarket(m)}>{m}</button>
        ))}
      </div>
      <span className={`fv-summary-time${stale ? ' warn' : ''}`}>{stale && '⚠ '}{time}</span>
      <span className="fv-summary-text">{text}</span>
      {failed.length > 0 && <span className="warn" style={{ fontSize: 12 }}
        title={failed.join(', ')}>일부 갱신 실패 ({failed.length})</span>}
      {/* 데이터가 이미 있는 상태에서 요청이 실패했을 때(I5) — 예: KR 화면을 보다가 US 로
          전환했는데 US 요청이 실패하면, 토글만 옮겨간 채 안내 없이 KR 화면이 남는다.
          전문은 title 에 — 한 줄짜리 요약만 상시 노출한다. */}
      {error && <span className="warn" style={{ fontSize: 12 }} title={error}>갱신 실패</span>}
      <button className="ghost" style={{ fontSize: 12, padding: '4px 10px' }}
              onClick={onRefresh} disabled={busy}>{busy ? '갱신 중…' : '새로고침'}</button>
    </div>
  )
}

export function BreadthBar({ b }: { b: Breadth }) {
  // 가운데 회색 띠(미변동)는 좌우 합이 100 에 못 미치는 만큼
  const mid = Math.max(0, 100 - b.leftPct - b.rightPct)
  return (
    <div className="fv-breadth">
      <span className="fv-sample">샘플</span>
      <div className="fv-breadth-labels">
        <div className="left"><p>{b.leftLabel}</p><p>{b.leftPct.toFixed(1)}% ({b.leftN.toLocaleString('en-US')})</p></div>
        {b.center && <div className="center">{b.center}</div>}
        <div className="right"><p>{b.rightLabel}</p><p>({b.rightN.toLocaleString('en-US')}) {b.rightPct.toFixed(1)}%</p></div>
      </div>
      <div className="fv-breadth-bar">
        <div className="l" style={{ width: `${b.leftPct}%` }} />
        <div className="m" style={{ width: `${mid}%` }} />
        <div className="r" style={{ width: `${b.rightPct}%` }} />
      </div>
    </div>
  )
}

export function SignalTable({ rows, gear, krw }: { rows: SignalRow[]; gear?: boolean; krw?: boolean }) {
  return (
    <Panel gear={gear}>
      <table className="fv-table">
        <thead><tr><th>{krw ? '종목' : 'Ticker'}</th><th>{krw ? '현재가' : 'Last'}</th>
          <th>Change %</th><th>{krw ? '거래량' : 'Volume'}</th><th className="l">Signal</th></tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={5} className="c fv-dim">스크리너 응답 없음</td></tr>}
          {rows.map((r, i) => (
            <tr key={i}>
              <td><span className="fv-logo" aria-hidden>{(r.name ?? r.symbol)[0]}</span>
                <Link to={`/ticker/${r.symbol}`} className="fv-tk" title={r.symbol}>{r.name ?? r.symbol}</Link></td>
              <td className="n">{num(r.last, krw ? 0 : 2)}</td>
              <td className={`n ${sign(r.change_pct)}`}>{pct(r.change_pct)}</td>
              <td className="n">{vol(r.volume)}</td>
              <td className="l"><span className="fv-signal">{r.signal}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}

export function PatternTable({ rows }: { rows: PatternRow[] }) {
  return (
    <Panel sample>
      <table className="fv-table fv-patterns">
        <thead><tr><th colSpan={4}>Tickers</th><th className="l">Signal</th></tr></thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.signal}>
              {r.tickers.map(t => <td key={t}><T s={t} /></td>)}
              <td className="l"><span className="fv-pattern-ico" aria-hidden>{r.icon}</span>
                <span className="fv-signal">{r.signal}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}

export function MajorNews({ rows }: { rows: MajorNewsRow[] }) {
  return (
    <Panel>
      <div className="fv-panel-title" title="대형주 중 당일 등락이 큰 순">Major Movers</div>
      <div className="fv-major">
        {rows.length === 0 && <div className="fv-major-row fv-dim">—</div>}
        {rows.map(r => (
          <div key={r.symbol} className="fv-major-row">
            <Link to={`/ticker/${r.symbol}`} className="fv-tk" title={r.symbol}>{r.name ?? r.symbol}</Link>
            <span className={`fv-badge ${sign(r.change_pct)}`}>{pct(r.change_pct)}</span>
          </div>
        ))}
      </div>
    </Panel>
  )
}

/** 헤드라인 시각: 오늘이면 HH:MM, 아니면 Aug-20 (finviz 표기) */
function headlineTime(iso: string, now: number): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const n = new Date(now)
  if (d.toDateString() === n.toDateString())
    return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: true })
  return d.toLocaleDateString('en-US', { month: 'short', day: '2-digit' }).replace(' ', '-')
}
/** 출처 약자 아이콘: "Yahoo Finance" → YF, "Benzinga" → BENZ */
function sourceAbbr(s: string): string {
  const words = s.replace(/[^A-Za-z ]/g, '').trim().split(/\s+/).filter(Boolean)
  if (words.length === 0) return '·'
  if (words.length === 1) return words[0].slice(0, 4).toUpperCase()
  return words.map(w => w[0]).join('').slice(0, 4).toUpperCase()
}

export function Headlines({ rows, now }: { rows: Headline[]; now: number }) {
  return (
    <Panel>
      <table className="fv-table fv-headlines">
        <thead><tr><th className="l" colSpan={3}>Headlines</th></tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td className="c fv-dim">뉴스 없음</td></tr>}
          {rows.map((h, i) => (
            <tr key={i}>
              <td className="fv-src"><span className="fv-src-ico" title={h.source}>{sourceAbbr(h.source)}</span></td>
              <td className="fv-time">{headlineTime(h.published_at, now)}</td>
              <td className="l">
                <a href={h.url || '#'} className="fv-tk" target="_blank" rel="noreferrer">{h.title}</a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}

export function EconCalendar({ emptyDate }: { emptyDate: string }) {
  return (
    <Panel sample>
      <table className="fv-table fv-econ">
        <thead><tr>
          <th className="l">Date</th><th className="l">Time</th><th className="l">Impact</th><th className="l">Release</th>
          <th className="l">For</th><th>Actual</th><th>Expected</th><th>Prior</th>
        </tr></thead>
        <tbody>
          <tr><td className="l">{emptyDate}</td><td colSpan={7} className="c fv-dim">No economic releases today</td></tr>
        </tbody>
      </table>
    </Panel>
  )
}

export function EarningsCalendar({ rows }: { rows: EarningsRow[] }) {
  // finviz는 8칸 고정 열이지만 이 화면의 우측 열(~350px)에는 안 들어간다 — 줄바꿈되는 칩으로
  return (
    <Panel sample>
      <table className="fv-table fv-earn">
        <thead><tr><th className="l">Date</th><th className="l">Earnings Release</th></tr></thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.date}>
              <td className="l fv-dim">{r.date}</td>
              <td className="l wrap"><div className="fv-chips">
                {r.tickers.map(t => <T key={t} s={t} />)}</div></td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}

export function InsiderLatest({ rows }: { rows: InsiderRow[] }) {
  return (
    <Panel sample>
      <table className="fv-table">
        <thead><tr>
          <th className="l">Ticker</th><th className="l">Latest Insider Trading</th><th className="l">Relationship</th>
          <th className="l">Date</th><th className="l">Transaction</th><th>Cost</th><th>#Shares</th><th>Value($)</th>
        </tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={r.transaction === 'Buy' ? 'fv-row-buy' : 'fv-row-sale'}>
              <td className="l"><T s={r.ticker} /></td>
              <td className="l">{r.owner}</td>
              <td className="l">{r.relationship}</td>
              <td className="l">{r.date}</td>
              <td className="l">{r.transaction}</td>
              <td className="n">{r.cost.toFixed(2)}</td>
              <td className="n">{r.shares.toLocaleString('en-US')}</td>
              <td className="n">{r.value.toLocaleString('en-US')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}

export function InsiderTop({ rows }: { rows: InsiderRow[] }) {
  return (
    <Panel sample>
      <table className="fv-table fv-insider-top">
        <thead><tr>
          <th className="l">Ticker</th><th className="l">Top Insider Trading</th><th className="l">Date</th>
          <th className="l">Transaction</th><th>Value($)</th>
        </tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={r.transaction === 'Buy' ? 'fv-row-buy' : 'fv-row-sale'}>
              <td className="l"><T s={r.ticker} /></td>
              <td className="l wrap">{r.owner}</td>
              <td className="l">{r.date}</td>
              <td className="l">{r.transaction}</td>
              <td className="n">{r.value.toLocaleString('en-US')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}

/** 순매수 금액(억원). 부호를 항상 붙인다 — 수급은 방향이 값보다 먼저 읽혀야 한다.
 *  마이너스는 U+002D(하이픈-마이너스)로 통일한다 — `pct()` 의 `toFixed` 가 만드는
 *  부호와 같은 글리프여야 같은 화면에서 마이너스가 두 종류로 안 보인다(M4). */
const flow = (v: number | null) =>
  v === null ? '—' : `${v > 0 ? '+' : v < 0 ? '-' : ''}${Math.abs(v).toLocaleString('ko-KR')}억`

/** 투자자별 순매수. 한국 시장에서 "누가 사고 누가 팔았나"는 지수 등락만큼 자주 보는 값이고
 *  finviz 에는 대응 블록이 없어 새로 만든다. 집계 기준일을 같이 찍는 이유: 장 마감 후
 *  집계라 장중에는 전일 값이 보이는데, 날짜가 없으면 오늘 수급으로 읽힌다. */
export function InvestorFlows({ rows }: { rows: InvestorRow[] }) {
  return (
    <>
      {rows.map(r => (
        <Panel key={r.market} className="fv-flow">
          <div className="fv-panel-title">
            <span>{r.market} 투자자 순매수</span>
            <span className="fv-dim" style={{ fontWeight: 400 }}>{r.date ?? '기준일 미상'}</span>
          </div>
          <div className="fv-flow-row">
            {([['개인', r.personal], ['외국인', r.foreign], ['기관', r.institution]] as const).map(
              ([label, v]) => (
                <div key={label}>
                  <p className="fv-dim">{label}</p>
                  <p className={`fv-flow-v ${sign(v)}`}>{flow(v)}</p>
                </div>
              ))}
          </div>
        </Panel>
      ))}
    </>
  )
}

export function QuoteTable({ title, rows }: { title: string; rows: QuoteRow[] }) {
  return (
    <Panel>
      <table className="fv-table">
        <thead><tr><th className="l">{title}</th><th>Last</th><th>Change</th><th>Change %</th></tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={4} className="c fv-dim">—</td></tr>}
          {rows.map(r => (
            <tr key={r.name}>
              <td className="l">{r.name}</td>
              <td className="n">{num(r.last, r.decimals)}</td>
              <td className={`n ${sign(r.change)}`}>{r.change !== null && r.change > 0 ? '+' : ''}{num(r.change, r.decimals)}</td>
              <td className={`n ${sign(r.change_pct)}`}>{pct(r.change_pct)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}
