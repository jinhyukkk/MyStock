import { useCallback, useEffect, useRef, useState } from 'react'
import '../finviz/finviz.css'
import { get, post } from '../api'
import { isStale, relativeTime } from '../time'
import IndexChart from '../finviz/IndexChart'
import Heatmap from '../finviz/Heatmap'
import { BreadthBar, EarningsCalendar, EconCalendar, Headlines, InsiderLatest, InsiderTop,
         MajorNews, MarketSummary, Panel, PatternTable, QuoteTable, SignalTable } from '../finviz/Sections'
import { BREADTH, EARNINGS, ECON_EMPTY_DATE, INSIDER_LATEST, INSIDER_TOP, PATTERNS_LEFT,
         PATTERNS_RIGHT } from '../finviz/sample'
import type { IndexRow, MarketData, MarketName } from '../finviz/types'

const MARKET_KEY = 'dashboard.market'
function initialMarket(): MarketName {
  const v = localStorage.getItem(MARKET_KEY)
  return v === 'US' ? 'US' : 'KR'      // 기본은 한국. 알 수 없는 값도 KR 로 떨어진다
}

/** finviz 상단 한 줄 요약 대신, 지수 등락으로 만든 문장. 뉴스 요약 소스가 없어
 *  문장을 지어내지 않고 숫자만 나열한다. */
function summaryText(indices: IndexRow[], market: MarketName): string {
  const shown = indices.filter(i => i.change_pct !== null)
  if (shown.length === 0) return '지수 데이터를 아직 받지 못했습니다'
  const parts = shown.map(i => `${i.name} ${i.change_pct! > 0 ? '+' : ''}${i.change_pct!.toFixed(2)}%`)
  const ups = shown.filter(i => i.change_pct! > 0).length
  const tone = market === 'KR'
    ? (ups === shown.length ? '국내 증시 상승' : ups === 0 ? '국내 증시 하락' : '국내 증시 혼조')
    : (ups === shown.length ? 'US stocks rose' : ups === 0 ? 'US stocks fell' : 'US stocks mixed')
  return `${tone} — ${parts.join(' · ')}`
}

/**
 * 메인 페이지 — finviz.com 홈 구성, MyStock 테마.
 * 실데이터(`/api/market`): 지수 차트·시그널 표·히트맵·Major Movers·헤드라인·선물·환율/채권.
 * 샘플("샘플" 배지, `finviz/sample.ts`): Breadth·차트패턴·경제/실적 캘린더·인사이더 —
 * 소스가 생기면 섹션 단위로 교체한다.
 */
export default function Dashboard() {
  const [market, setMarket] = useState<MarketName>(initialMarket)
  const [data, setData] = useState<MarketData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [now, setNow] = useState(Date.now())

  // 응답이 도착했을 때 "그 사이 시장이 바뀌었는가"를 봐야 한다. state 를 클로저로 읽으면
  // 요청을 쏠 때 캡처된 옛 값이라 자기 자신과 비교하게 되어 항상 참이 된다 — ref 는 항상 최신을 가리킨다.
  const currentMarket = useRef(market)
  useEffect(() => { currentMarket.current = market }, [market])

  const load = useCallback(() => {
    const requested = market
    return get<MarketData>(`/api/market?market=${requested}`)
      .then(d => {
        if (currentMarket.current !== requested) return   // 그 사이 토글됨 — 늦게 온 응답을 버린다
        setData(d); setError(null); setNow(Date.now())
      })
      .catch(e => {
        if (currentMarket.current !== requested) return   // 옛 요청의 실패는 지금 진행 중인 요청과 무관하다
        setError(String(e))
      })
  }, [market])
  useEffect(() => { load() }, [load])

  const pickMarket = (m: MarketName) => {
    if (m === market) return
    localStorage.setItem(MARKET_KEY, m)
    setBusy(true)
    setMarket(m)          // load 가 market 에 걸려 있어 이 한 줄로 다시 받는다
  }
  // 전환 요청이 끝나면(또는 실패하면) busy 를 내린다. data 를 지우지 않는 이유는
  // 스켈레톤으로 되돌아가면 화면이 통째로 깜빡이기 때문 — 이전 시장을 두고 위에서 갱신한다.
  useEffect(() => { setBusy(false) }, [data, error])

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
    const requested = market
    setBusy(true)
    try {
      const d = await post<MarketData>(`/api/market/refresh?market=${requested}`)
      // load 와 같은 이유 — 새로고침 중에 시장을 바꿨으면 늦게 온 결과를 버린다
      if (currentMarket.current !== requested) return
      setData(d); setNow(Date.now())
    } catch (e) {
      if (currentMarket.current !== requested) return
      setError(String(e))
    } finally {
      if (currentMarket.current === requested) setBusy(false)
    }
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
        {market === 'KR'
          ? '첫 로드는 네이버·야후에서 지수와 순위 100여 종목을 받아오느라 몇 초 걸립니다.'
          : '첫 로드는 야후 파이낸스에서 지수·스크리너·100여 종목을 받아오느라 10초쯤 걸립니다.'}</div>
    </div>
  )

  const stale = isStale(data.fetched_at, now)
  return (
    <div className="fv">
      <MarketSummary market={market} onMarket={pickMarket}
                     time={`기준 ${relativeTime(data.fetched_at, now)}`}
                     text={summaryText(data.indices, market)}
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
          <div className="fv-panel-title"><span>
            {market === 'KR' ? 'KOSPI 대형주 – 1일 등락' : 'US Large Caps - 1 Day Performance'}</span></div>
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

      <div className="fv-row quotes" style={data.futures.length === 0 ? { gridTemplateColumns: '1fr' } : undefined}>
        {data.futures.length > 0 && <QuoteTable title="Futures" rows={data.futures} />}
        <QuoteTable title={market === 'KR' ? '환율 & 금리' : 'Forex & Bonds'} rows={data.forex_bonds} />
      </div>
    </div>
  )
}
