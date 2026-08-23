import { Link } from 'react-router-dom'
import type { BreadthBlock, EarningsBlock, EconBlock, Headline, InsiderBlock, InvestorRow,
              MajorNewsRow, MarketName, PatternBlock, PatternTicker, QuoteRow,
              SignalRow } from './types'

const pct = (v: number | null, d = 2) => v === null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(d)}%`
const sign = (v: number | null) => v === null ? '' : v > 0 ? 'up' : v < 0 ? 'down' : ''
const num = (v: number | null, d: number) =>
  v === null ? '—' : v.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
/** 거래량: finviz 식 40.76M / 419.34K */
const vol = (v: number | null) =>
  v === null ? '—' : v >= 1e9 ? `${(v / 1e9).toFixed(2)}B` : v >= 1e6 ? `${(v / 1e6).toFixed(2)}M`
  : v >= 1e3 ? `${(v / 1e3).toFixed(2)}K` : v.toFixed(0)

/** finviz 패널 공통 껍데기. `scope` 는 이 패널 숫자가 어느 범위에서 나왔는지
 *  (예: "코스피·코스닥 시총 200 · 08-21") — 이 화면의 breadth·패턴은 전 종목이 아니라
 *  유니버스에서 센 값이라, 패널이 스스로 말하지 않으면 시장 전체 통계로 읽힌다.
 *  표 위에 겹치는 배지가 아니라 "기준" 라벨을 단 자기 줄로 둬서, 아래 표 전체가
 *  이 범위 얘기라는 게 한눈에 들어오게 한다. */
export function Panel({ children, gear, scope, scopeHidden, className = '' }:
  { children: React.ReactNode; gear?: boolean; scope?: string; scopeHidden?: boolean; className?: string }) {
  return (
    <div className={`fv-panel ${className}`}>
      {/* scopeHidden: 같은 줄의 옆 패널(예: 차트 패턴 좌/우 표)에는 캡션을 안 보이되,
          자리는 그대로 차지해야 두 표 머리글 높이가 어긋나지 않는다 — visibility 로 숨긴다. */}
      {scope && <div className="fv-scope-bar" style={scopeHidden ? { visibility: 'hidden' } : undefined}>
        <span className="fv-scope-label">기준</span><span>{scope}</span></div>}
      {gear && !scope && <span className="fv-gear" aria-hidden>⚙</span>}
      {children}
    </div>
  )
}

/** 유니버스 꼬리표. 기준일이 있으면 "…시총 200 · 08-21". */
function scopeOf(b: { universe?: string; as_of?: string | null }): string | undefined {
  if (!b.universe) return undefined
  return b.as_of ? `${b.universe} · ${b.as_of.slice(5)}` : b.universe
}

/** 빈 표 한 줄 안내. 셋을 구분한다:
 *  - `status` 없음  → 아직 안 받은 칸(느린 블록은 첫 화면 뒤 백그라운드로 채워진다)
 *  - `unavailable` → 소스가 없다(키 미설정). 왜 비었는지를 안내로 그대로 보여준다
 *  - `ok` 인데 0줄 → 진짜로 해당 기간에 일정이 없다
 *  구분 없이 빈 표를 두면 "오늘은 아무 일도 없었다"로 읽힌다. */
function BlockNote({ block, cols, loading = '수집 중…', empty = '해당 없음' }:
  { block: { status?: string; note?: string | null }; cols: number
    loading?: string; empty?: string }) {
  const text = block.status === 'unavailable' ? (block.note ?? '소스 없음')
    : block.status === 'ok' ? empty : loading
  return <tr><td colSpan={cols} className="c fv-dim" style={{ whiteSpace: 'normal' }}>{text}</td></tr>
}

const tickerLink = (t: PatternTicker) => (
  <Link key={t.symbol} to={`/ticker/${t.symbol}`} className="fv-tk" title={t.symbol}>
    {t.name ?? t.symbol}</Link>
)

/** 좁은 칸(패턴 표 4열)에서 쓰는 표기. 국내 코드(005930)는 사람이 못 읽으니 이름을,
 *  미국 티커(AAPL)는 이름("Thermo Fisher Scientific")보다 티커가 짧고 더 통용된다. */
const compactTicker = (t: PatternTicker) => {
  const numeric = /^\d+$/.test(t.symbol)
  return (
    <Link key={t.symbol} to={`/ticker/${t.symbol}`} className="fv-tk"
          title={t.name ? `${t.name} (${t.symbol})` : t.symbol}>
      {numeric ? (t.name ?? t.symbol) : t.symbol}</Link>
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

/** 상승/하락·신고가/신저가·SMA 위아래 네 줄. 개수를 같이 찍는 이유: 52주 신고가처럼
 *  분모가 몇 종목뿐인 줄도 있어서, 비율만 보면 200 종목을 센 줄과 구분이 안 된다. */
export function BreadthRow({ block }: { block: BreadthBlock }) {
  const bars = block.bars ?? []
  if (bars.length === 0)
    return <div className="fv-breadth fv-dim" style={{ padding: '10px 12px' }}>시장 내부 지표 수집 중…</div>
  return (
    <>
      {bars.map(b => {
        // 가운데 회색 띠(보합)는 좌우 합이 100 에 못 미치는 만큼
        const mid = Math.max(0, 100 - b.left_pct - b.right_pct)
        const scope = scopeOf(block)
        return (
          <div className="fv-breadth" key={b.left_label + (b.center ?? '')}
               title={scope ? `${scope} 기준` : undefined}>
            <div className="fv-breadth-labels">
              <div className="left"><p>{b.left_label}</p>
                <p>{b.left_pct.toFixed(1)}% ({b.left_n.toLocaleString('en-US')})</p></div>
              {b.center && <div className="center">{b.center}</div>}
              <div className="right"><p>{b.right_label}</p>
                <p>({b.right_n.toLocaleString('en-US')}) {b.right_pct.toFixed(1)}%</p></div>
            </div>
            <div className="fv-breadth-bar">
              <div className="l" style={{ width: `${b.left_pct}%` }} />
              <div className="m" style={{ width: `${mid}%` }} />
              <div className="r" style={{ width: `${b.right_pct}%` }} />
            </div>
          </div>
        )
      })}
    </>
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

/** 자체 탐지한 차트 패턴. `half` 로 좌/우 표를 나눈다(finviz 와 같은 2열 배치).
 *  종목 칸이 4개 미만인 줄이 있어 빈 칸을 채워 열을 맞춘다. */
export function PatternTable({ block, half }: { block: PatternBlock; half: 'left' | 'right' }) {
  const all = block.rows ?? []
  const mid = Math.ceil(all.length / 2)
  const rows = half === 'left' ? all.slice(0, mid) : all.slice(mid)
  return (
    <Panel scope={scopeOf(block)} scopeHidden={half === 'right'}>
      <table className="fv-table fv-patterns">
        <thead><tr><th colSpan={4}>{half === 'left' ? '종목' : ''}</th>
          <th className="l">패턴</th></tr></thead>
        <tbody>
          {all.length === 0 && <BlockNote block={{}} cols={5} loading="차트 패턴 계산 중…" />}
          {rows.map(r => (
            <tr key={r.signal}>
              {r.tickers.map(t => <td key={t.symbol}>{compactTicker(t)}</td>)}
              {Array.from({ length: Math.max(0, 4 - r.tickers.length) },
                          (_, i) => <td key={`pad${i}`} />)}
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
      <div className="fv-panel-title" title="대형주 중 당일 등락이 큰 순">주요 등락 종목</div>
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

/** 경제지표. 국내는 한국은행 100대 지표의 최신값, 미국은 FRED 발표 예정일 —
 *  소스가 주는 것이 달라 표 머리도 다르다. 예상치·실제치 칸을 두지 않는 이유는
 *  무료 소스에 컨센서스가 없어서다(빈 칸이 "예상 없음"으로 읽히는 게 더 나쁘다). */
export function EconCalendar({ block }: { block: EconBlock }) {
  const rows = block.rows ?? []
  const release = block.kind === 'release'
  return (
    <Panel>
      <table className="fv-table fv-econ">
        <thead><tr>
          <th className="l">{release ? '발표일' : '기준시점'}</th>
          <th className="l">{release ? '경제지표 발표 예정' : '주요 경제지표'}</th>
          {!release && <th>값</th>}
        </tr></thead>
        <tbody>
          {rows.length === 0 && <BlockNote block={block} cols={3}
            empty={release ? '예정된 지표 발표 없음' : '지표 없음'} />}
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="l fv-dim">{r.date ?? '—'}</td>
              <td className="l wrap">{r.name}</td>
              {!release && <td className="n">{r.value ?? '—'}
                {r.unit && <span className="fv-dim"> {r.unit}</span>}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}

/** 실적 발표 예정. 유니버스 상위 종목만 본다(종목당 야후 1회 호출) — 그래서
 *  "이 목록이 전부"가 아니라는 걸 꼬리표로 남긴다. */
export function EarningsCalendar({ block, universe }: { block: EarningsBlock; universe?: string }) {
  const rows = block.rows ?? []
  // "코스피·코스닥 시총 200 상위 40종목" — 어느 목록의 어디까지를 훑었는지 한 줄로
  const scope = [universe, block.scope].filter(Boolean).join(' ') || undefined
  // finviz는 8칸 고정 열이지만 이 화면의 우측 열(~350px)에는 안 들어간다 — 줄바꿈되는 칩으로
  return (
    <Panel scope={scope}>
      <table className="fv-table fv-earn">
        <thead><tr><th className="l">발표일</th><th className="l">실적 발표 예정</th></tr></thead>
        <tbody>
          {rows.length === 0 && <BlockNote block={block} cols={2}
            loading="실적 일정 수집 중… (첫 로드 뒤 잠시)"
            empty="유니버스 상위 종목의 예정된 실적 발표 없음" />}
          {rows.map(r => (
            <tr key={r.date}>
              <td className="l fv-dim">{r.date.slice(5)}</td>
              <td className="l wrap"><div className="fv-chips">
                {r.tickers.map(tickerLink)}</div></td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}

/** 매수/매도 방향. 소스마다 표기가 달라(yfinance "Sale"/"Purchase", DART "장내매수")
 *  문자열을 그대로 색으로 옮기지 않고 여기서 한 번에 판정한다. 모르면 색을 안 준다 —
 *  방향을 잘못 칠하는 것이 안 칠하는 것보다 나쁘다. */
function side(t: string): 'buy' | 'sale' | '' {
  const s = (t || '').toLowerCase()
  if (s.includes('purchase') || s.includes('buy') || t.includes('매수') || t.includes('취득')) return 'buy'
  if (s.includes('sale') || s.includes('sell') || t.includes('매도') || t.includes('처분')) return 'sale'
  return ''
}
const rowClass = (t: string) => {
  const s = side(t)
  return s === 'buy' ? 'fv-row-buy' : s === 'sale' ? 'fv-row-sale' : ''
}
const qty = (v: number | null) => v === null ? '—' : v.toLocaleString('en-US')

export function InsiderLatest({ block, krw, universe }:
  { block: InsiderBlock; krw?: boolean; universe?: string }) {
  const rows = block.latest ?? []
  const scope = [universe, block.scope].filter(Boolean).join(' ') || undefined
  return (
    <Panel scope={scope}>
      <table className="fv-table">
        <thead><tr>
          <th className="l">종목</th><th className="l">최근 내부자 거래</th><th className="l">직위</th>
          <th className="l">일자</th><th className="l">유형</th><th>단가</th><th>수량</th>
          <th>{krw ? '금액' : 'Value($)'}</th>
        </tr></thead>
        <tbody>
          {rows.length === 0 && <BlockNote block={block} cols={8}
            loading="내부자 거래 수집 중… (첫 로드 뒤 잠시)"
            empty="최근 신고된 내부자 거래 없음" />}
          {rows.map((r, i) => (
            <tr key={i} className={rowClass(r.transaction)}>
              <td className="l">{tickerLink(r)}</td>
              <td className="l wrap">{r.owner || '—'}</td>
              <td className="l">{r.relation || '—'}</td>
              <td className="l">{r.date ?? '—'}</td>
              <td className="l">{r.transaction || '—'}</td>
              <td className="n">{num(r.price, 2)}</td>
              <td className="n">{qty(r.shares)}</td>
              <td className="n">{qty(r.value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  )
}

export function InsiderTop({ block }: { block: InsiderBlock }) {
  const rows = block.top ?? []
  // 정렬 기준이 시장마다 다르다(거래대금 / 변동 수량) — 머리글에 그 기준을 그대로 쓴다
  const label = block.top_label ?? '주요 내부자 거래'
  const byShares = label.includes('수량')
  return (
    <Panel>
      <table className="fv-table fv-insider-top">
        <thead><tr>
          <th className="l">종목</th><th className="l">{label}</th><th className="l">일자</th>
          <th className="l">유형</th><th>{byShares ? '수량' : '금액'}</th>
        </tr></thead>
        <tbody>
          {/* 안내문은 왼쪽 표에 이미 한 번 나갔다 — 같은 문단을 나란히 두 번 두면
              화면 절반이 안내문이 된다 */}
          {rows.length === 0 && <BlockNote block={{ ...block, note: '소스 없음 — 왼쪽 표의 안내 참고' }}
            cols={5} loading="내부자 거래 수집 중…" empty="—" />}
          {rows.map((r, i) => (
            <tr key={i} className={rowClass(r.transaction)}>
              <td className="l">{tickerLink(r)}</td>
              <td className="l wrap">{r.owner || '—'}</td>
              <td className="l">{r.date ?? '—'}</td>
              <td className="l">{r.transaction || '—'}</td>
              <td className="n">{qty(byShares ? r.shares : r.value)}</td>
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
