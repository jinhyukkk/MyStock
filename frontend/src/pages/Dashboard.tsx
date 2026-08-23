import { useCallback, useEffect, useRef, useState } from 'react'
import '../finviz/finviz.css'
import { get, post } from '../api'
import { isStale, relativeTime } from '../time'
import IndexChart from '../finviz/IndexChart'
import Heatmap from '../finviz/Heatmap'
import AdSlot from '../components/AdSlot'
import { BreadthRow, EarningsCalendar, EconCalendar, Headlines, InsiderLatest, InsiderTop,
         InvestorFlows, MajorNews, MarketSummary, Panel, PatternTable, QuoteTable,
         SignalTable } from '../finviz/Sections'
import type { IndexRow, MarketData, MarketName } from '../finviz/types'

const MARKET_KEY = 'dashboard.market'
function initialMarket(): MarketName {
  // getItem 도 Safari 프라이빗 모드 등에서 throw 할 수 있다(M1) — 그때는 기본값 KR.
  try {
    const v = localStorage.getItem(MARKET_KEY)
    return v === 'US' ? 'US' : 'KR'      // 기본은 한국. 알 수 없는 값도 KR 로 떨어진다
  } catch {
    return 'KR'
  }
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
 * 모든 칸이 `/api/market` 실데이터다. 샘플은 없다.
 * - 지수·시그널·히트맵·Major Movers·헤드라인·선물·환율/채권: 네이버/야후 시세
 * - Breadth·차트패턴: 시총 상위 유니버스 일봉에서 자체 계산(backend/app/market_breadth.py)
 * - 실적·인사이더: 종목마다 외부 호출이라 첫 화면 뒤 백그라운드로 채워진다(SLOW_BLOCKS)
 * - 경제지표: 무료 키가 필요한 소스(ECOS·FRED) — 키가 없으면 그 칸이 발급 안내를 띄운다
 */
export default function Dashboard() {
  const [market, setMarket] = useState<MarketName>(initialMarket)
  const [data, setData] = useState<MarketData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [now, setNow] = useState(Date.now())

  // 요청마다 세대를 올리고, 응답이 왔을 때 자기 세대가 아직 최신인지만 본다. 시장 값으로
  // 비교하면(예: currentMarket.current !== requested) KR→US→KR 처럼 왕복했을 때 값이 우연히
  // 같아져 옛 요청이 통과한다(ABA 문제) — 세대는 단조 증가라 왕복해도 옛 요청은 반드시 걸러진다.
  const gen = useRef(0)

  // refresh() 와 같은 형태의 세대 가드 + finally 로 busy 를 내린다. 예전에는
  // `useEffect(() => setBusy(false), [data, error])` 로 내렸는데, setError 를 직전과
  // 같은 문자열로 두 번 부르면 React 가 상태 변경을 bail-out 해 deps 가 안 바뀌고
  // 이펙트가 안 돌아 busy 가 영구히 true 로 남는 문제가 있었다(I4).
  const load = useCallback(async () => {
    const mine = ++gen.current
    try {
      const d = await get<MarketData>(`/api/market?market=${market}`)
      if (mine !== gen.current) return   // 그 사이 새 요청이 나갔다 — 늦게 온 응답을 버린다
      setData(d); setError(null); setNow(Date.now())
    } catch (e) {
      if (mine !== gen.current) return   // 옛 요청의 실패는 지금 진행 중인 최신 요청과 무관하다
      setError(String(e))
    } finally {
      // 세대가 밀렸으면 그 사이 더 최신 요청이 자기 finally 에서 busy 를 책임진다.
      if (mine === gen.current) setBusy(false)
    }
  }, [market])
  useEffect(() => { load() }, [load])

  const pickMarket = (m: MarketName) => {
    if (m === market) return
    setBusy(true)
    setMarket(m)          // load 가 market 에 걸려 있어 이 한 줄로 다시 받는다
    // localStorage.setItem 은 Safari 프라이빗 모드 등에서 throw 할 수 있다(M1) — 상태
    // 갱신 뒤에 두고 감싸서, 저장이 실패해도 토글 자체는 항상 동작하게 한다.
    try { localStorage.setItem(MARKET_KEY, m) } catch { /* 저장 실패는 무시 — 다음 방문에 KR 기본값으로 돌아갈 뿐 */ }
  }

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
    const mine = ++gen.current   // load 와 같은 세대 카운터를 공유 — 토글 중 새로고침이 겹쳐도 최신만 반영
    setBusy(true)
    try {
      const d = await post<MarketData>(`/api/market/refresh?market=${market}`)
      if (mine !== gen.current) return
      // load() 의 성공 분기와 대칭 — I5 로 MarketSummary 가 error 를 렌더하게 되면서
      // 이전 실패로 남은 error 를 지우지 않으면, 새로고침이 성공해도 "갱신 실패" 배지가
      // 계속 남는다(재리뷰 지적).
      setData(d); setError(null); setNow(Date.now())
    } catch (e) {
      if (mine !== gen.current) return
      setError(String(e))
    } finally {
      // 세대가 밀렸으면 그 사이 더 최신 요청(load 또는 refresh)이 자기 finally 에서
      // busy 를 책임진다 — 여기서 내리면 아직 진행 중인 최신 요청의 busy 를 조기에 끈다.
      if (mine === gen.current) setBusy(false)
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
      {/* MarketSummary 의 market prop 은 토글 표시 전용 — 사용자가 방금 누른 선택을 즉시
          보여줘야 한다. 반면 text 는 화면에 그려진 데이터(data)를 설명하므로 data.market 을 쓴다.
          전환 도중 몇 초는 market !== data.market 일 수 있는데, 그때 토글은 새 시장을 가리키되
          문장은 아직 화면에 있는 이전 시장 숫자를 정확히 설명해야 오독이 없다. */}
      <MarketSummary market={market} onMarket={pickMarket}
                     time={`기준 ${relativeTime(data.fetched_at, now)}`}
                     text={summaryText(data.indices, data.market)}
                     stale={stale} failed={data.failed} error={error} busy={busy} onRefresh={refresh} />

      <div className="fv-row charts">
        {data.indices.map(i => <IndexChart key={i.symbol} data={i} asOf={data.fetched_at} session={data.session} />)}
      </div>

      {data.investors.length > 0 && (
        <div className="fv-row flows"><InvestorFlows rows={data.investors} /></div>
      )}

      <div className="fv-row breadth">
        <BreadthRow block={data.breadth} />
      </div>

      {/* 아래 라벨·소수점 분기는 전부 data.market 을 본다 — market(사용자 선택)이 아니라
          화면에 그려진 값이 실제로 어느 시장 것인지를 설명해야 하기 때문 */}
      <div className="fv-row signals">
        <SignalTable rows={data.signals_up} krw={data.market === 'KR'} />
        <SignalTable rows={data.signals_down} gear krw={data.market === 'KR'} />
        <Panel className="fv-heatmap-panel" gear>
          <div className="fv-panel-title"><span>
            {data.market === 'KR' ? 'KOSPI 대형주 – 1일 등락' : 'US Large Caps - 1 Day Performance'}</span></div>
          <Heatmap sectors={data.heatmap} />
        </Panel>
      </div>

      {/* 광고는 첫 화면(지수·수급·시그널·히트맵) 바로 아래 한 칸 — finviz 와 같은 자리다.
          더 위에 두면 첫 화면의 시세가 밀려 내려가고, 맨 아래는 스크롤이 닿지 않아 노출이 없다.
          환경변수가 비어 있으면 AdSlot 이 null 을 돌려줘 이 줄은 높이 0 이다. */}
      <AdSlot slot={import.meta.env.VITE_ADSENSE_SLOT_DASHBOARD} />

      {/* finviz: 좌 2/3 = 차트패턴 표 2개 + 그 아래 헤드라인, 우 1/3 = Major News 가 두 줄에 걸침 */}
      <div className="fv-row patterns">
        <div className="fv-col">
          <div className="fv-row two">
            <PatternTable block={data.patterns} half="left" />
            <PatternTable block={data.patterns} half="right" />
          </div>
          <Headlines rows={data.headlines} now={now} />
        </div>
        <MajorNews rows={data.major_news} />
      </div>

      <div className="fv-row calendar">
        <EconCalendar block={data.econ} />
        {/* 실적 일정은 유니버스 상위 종목만 본다 — 어디까지 본 목록인지 꼬리표로 남긴다 */}
        <EarningsCalendar block={data.earnings} universe={data.breadth.universe} />
      </div>

      <div className="fv-row insider">
        <InsiderLatest block={data.insider} krw={data.market === 'KR'}
                       universe={data.breadth.universe} />
        <InsiderTop block={data.insider} />
      </div>

      <div className="fv-row quotes" style={data.futures.length === 0 ? { gridTemplateColumns: '1fr' } : undefined}>
        {data.futures.length > 0 && <QuoteTable title="Futures" rows={data.futures} />}
        <QuoteTable title={data.market === 'KR' ? '환율 & 금리' : 'Forex & Bonds'} rows={data.forex_bonds} />
      </div>
    </div>
  )
}
