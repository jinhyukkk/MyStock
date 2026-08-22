import { useCallback, useEffect, useState } from 'react'
import '../finviz/finviz.css'
import { get, post } from '../api'
import { isStale, relativeTime } from '../time'
import IndexChart from '../finviz/IndexChart'
import Heatmap from '../finviz/Heatmap'
import { BreadthBar, EarningsCalendar, EconCalendar, Headlines, InsiderLatest, InsiderTop,
         MajorNews, MarketSummary, Panel, PatternTable, QuoteTable, SignalTable } from '../finviz/Sections'
import { BREADTH, EARNINGS, ECON_EMPTY_DATE, INSIDER_LATEST, INSIDER_TOP, PATTERNS_LEFT,
         PATTERNS_RIGHT } from '../finviz/sample'
import type { IndexRow, MarketData } from '../finviz/types'

/** finviz 상단 한 줄 요약 대신, 세 지수 등락으로 만든 문장. 뉴스 요약 소스가 없어
 *  문장을 지어내지 않고 숫자만 나열한다. */
function summaryText(indices: IndexRow[]): string {
  const parts = indices.filter(i => i.change_pct !== null)
    .map(i => `${i.name} ${i.change_pct! > 0 ? '+' : ''}${i.change_pct!.toFixed(2)}%`)
  if (parts.length === 0) return '지수 데이터를 아직 받지 못했습니다'
  const ups = indices.filter(i => (i.change_pct ?? 0) > 0).length
  const tone = ups === indices.length ? 'US stocks rose' : ups === 0 ? 'US stocks fell' : 'US stocks mixed'
  return `${tone} — ${parts.join(' · ')}`
}

/**
 * 메인 페이지 — finviz.com 홈 구성, MyStock 테마.
 * 실데이터(`/api/market`): 지수 차트·시그널 표·히트맵·Major Movers·헤드라인·선물·환율/채권.
 * 샘플("샘플" 배지, `finviz/sample.ts`): Breadth·차트패턴·경제/실적 캘린더·인사이더 —
 * 소스가 생기면 섹션 단위로 교체한다.
 */
export default function Dashboard() {
  const [data, setData] = useState<MarketData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [now, setNow] = useState(Date.now())

  const load = useCallback(() => get<MarketData>('/api/market')
    .then(d => { setData(d); setError(null); setNow(Date.now()) })
    .catch(e => setError(String(e))), [])
  useEffect(() => { load() }, [load])

  // 백엔드는 TTL 이 지나면 백그라운드로 갱신하지만 열어둔 탭은 모른다 —
  // 탭으로 돌아올 때 다시 받고, 머무는 동안 "몇 분 전" 표기를 흘려보낸다.
  useEffect(() => {
    const onFocus = () => { if (document.visibilityState === 'visible') load() }
    document.addEventListener('visibilitychange', onFocus)
    window.addEventListener('focus', onFocus)
    const tick = setInterval(() => setNow(Date.now()), 30_000)
    return () => {
      document.removeEventListener('visibilitychange', onFocus)
      window.removeEventListener('focus', onFocus)
      clearInterval(tick)
    }
  }, [load])

  const refresh = async () => {
    setBusy(true)
    try { setData(await post<MarketData>('/api/market/refresh')); setNow(Date.now()) }
    catch (e) { setError(String(e)) }
    finally { setBusy(false) }
  }

  if (error && !data) return (
    <div className="card">
      <div style={{ color: 'var(--sell)' }}>시장 데이터 불러오기 실패: {error}</div>
      <button style={{ marginTop: 10 }} onClick={() => { setError(null); load() }}>다시 시도</button>
    </div>
  )
  if (!data) return (
    <div className="fv">
      <div className="card skeleton" style={{ minHeight: 44 }} />
      <div className="fv-row charts">
        {[0, 1, 2].map(i => <div key={i} className="card skeleton" style={{ minHeight: 200 }} />)}
      </div>
      <div className="card skeleton" style={{ minHeight: 420 }} />
      <div className="fv-dim" style={{ textAlign: 'center', fontSize: 12 }}>
        첫 로드는 야후 파이낸스에서 지수·스크리너·100여 종목을 받아오느라 10초쯤 걸립니다.</div>
    </div>
  )

  const stale = isStale(data.fetched_at, now)
  return (
    <div className="fv">
      <MarketSummary time={`기준 ${relativeTime(data.fetched_at, now)}`} text={summaryText(data.indices)}
                     stale={stale} failed={data.failed} busy={busy} onRefresh={refresh} />

      <div className="fv-row charts">
        {data.indices.map(i => <IndexChart key={i.symbol} data={i} asOf={data.fetched_at} />)}
      </div>

      <div className="fv-row breadth">
        {BREADTH.map(b => <BreadthBar key={b.leftLabel + b.center} b={b} />)}
      </div>

      <div className="fv-row signals">
        <SignalTable rows={data.signals_up} />
        <SignalTable rows={data.signals_down} gear />
        <Panel className="fv-heatmap-panel" gear>
          <div className="fv-panel-title"><span>US Large Caps - 1 Day Performance</span></div>
          <Heatmap sectors={data.heatmap} />
        </Panel>
      </div>

      {/* finviz: 좌 2/3 = 차트패턴 표 2개 + 그 아래 헤드라인, 우 1/3 = Major News 가 두 줄에 걸침 */}
      <div className="fv-row patterns">
        <div className="fv-col">
          <div className="fv-row two">
            <PatternTable rows={PATTERNS_LEFT} />
            <PatternTable rows={PATTERNS_RIGHT} />
          </div>
          <Headlines rows={data.headlines} now={now} />
        </div>
        <MajorNews rows={data.major_news} />
      </div>

      <div className="fv-row calendar">
        <EconCalendar emptyDate={ECON_EMPTY_DATE} />
        <EarningsCalendar rows={EARNINGS} />
      </div>

      <div className="fv-row insider">
        <InsiderLatest rows={INSIDER_LATEST} />
        <InsiderTop rows={INSIDER_TOP} />
      </div>

      <div className="fv-row quotes">
        <QuoteTable title="Futures" rows={data.futures} />
        <QuoteTable title="Forex & Bonds" rows={data.forex_bonds} />
      </div>
    </div>
  )
}
