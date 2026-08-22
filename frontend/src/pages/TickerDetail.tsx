import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { get, post, put } from '../api'
import { isStale, relativeTime } from '../time'
import type { Company, TickerDetail as Detail } from '../types'
import { useTickerDetail } from '../ticker/useTickerDetail'
import TradeDialog from '../components/TradeDialog'
import QuoteHeader from '../components/quote/QuoteHeader'
import QuoteChart, { type PriceLevel } from '../components/quote/QuoteChart'
import SnapshotTable from '../components/quote/SnapshotTable'
import FinancialsChart from '../components/quote/FinancialsChart'
import NewsList from '../components/quote/NewsList'
import RatingsTable from '../components/quote/RatingsTable'
import InsiderTable from '../components/quote/InsiderTable'
import BlockEmpty, { BlockSource } from '../components/quote/BlockEmpty'
import { snapshotCells } from '../quote/snapshotCells'
import { changeFromPrev } from '../quote/stats'
import '../quote.css'

/** 종목 개요 — finviz Overview 구성.
 *
 *  헤더(회사 사실) → 판정 한 줄 → 차트 → 스냅샷 84칸 → 재무 막대 → 뉴스·애널리스트 →
 *  회사 설명 → 내부자 거래. 여기서 사용자가 보는 것은 "MyStock이 매긴 점수"가 아니라
 *  "시장이 준 숫자"다. 우리 판단(시그널 근거·백테스트·청산 플랜·룰·히스토리)은
 *  `/ticker/:symbol/analysis`로 옮겼다 — 판정 한 줄과 `분석` 링크가 그 입구다. */

/** 등급의 방향만 뽑는다 (+1 매수 / 0 중립 / -1 매도). */
const dir = (grade: string) => grade.includes('매수') ? 1 : grade.includes('매도') ? -1 : 0

/** 헤더 아래 한 문장 판정.
 *
 *  이게 없으면 사용자가 손절가·목표가·수량·과거 성적·계좌 리스크 다섯 숫자와
 *  최대 일곱 종류의 경고를 매번 머릿속에서 합성해야 한다. 30초 판단이 성립하지 않는다.
 *  방향을 지시하는 게 아니라 **지금 이 화면에서 먼저 볼 것**을 가리킨다. */
function verdict(detail: Detail): { text: string; tone: 'buy' | 'sell' | 'flat' } {
  const sig = detail.signal
  const held = (detail.risk?.exit_plan?.held_quantity ?? 0) > 0
  const over = detail.risk?.account_open_risk?.over_limit
  const d = sig ? dir(sig.swing_grade) : 0
  const noSizing = !!detail.risk && detail.risk.position_size_1pct === null
  if (!detail.risk)
    return { tone: 'flat', text: '가격 데이터가 부족해 손절·수량·보유 상태를 판단할 수 없습니다 — '
      + '새로고침 후 다시 확인하세요.' }
  if (!held && noSizing)
    return { tone: 'flat', text: '예수금이 입력되지 않아 리스크 기준 수량을 계산할 수 없습니다 — '
      + '포트폴리오에서 예수금을 먼저 입력하세요.' }
  if (held && d < 0)
    return { tone: 'sell', text: '보유 중인데 스윙 매도 신호입니다 — 추가 매수가 아니라 '
      + '분석 탭의 청산 플랜에서 얼마를 덜어낼지 먼저 정하세요.' }
  if (held && d > 0 && over)
    return { tone: 'sell', text: '매수 신호지만 계좌 총 미결 리스크가 상한을 넘었습니다 — '
      + '추가 매수 전에 다른 포지션 축소가 먼저입니다.' }
  if (held && d > 0)
    return { tone: 'buy', text: '보유 중이며 매수 신호가 유지됩니다 — 추가 매수는 '
      + '제안 수량과 계좌 총 리스크 안에서만.' }
  if (held)
    return { tone: 'flat', text: '보유 중이나 뚜렷한 신호가 없습니다 — 새 판단보다 '
      + '손절선 유지가 할 일입니다.' }
  if (d > 0 && over)
    return { tone: 'sell', text: '매수 신호지만 계좌 총 미결 리스크가 이미 상한을 넘었습니다 — '
      + '신규 진입보다 기존 포지션 축소가 먼저입니다.' }
  if (d > 0)
    return { tone: 'buy', text: '신규 진입 후보입니다 — 손절가를 먼저 정하고 '
      + '제안 수량을 넘기지 마세요.' }
  if (d < 0)
    return { tone: 'sell', text: '매도 신호이고 보유하지 않았습니다 — 지금 할 일은 없습니다.' }
  return { tone: 'flat', text: '뚜렷한 신호가 없습니다 — 관망 구간입니다.' }
}

const TABS: [string, string][] = [
  ['top', '개요'], ['chart', '차트'], ['snapshot', '스냅샷'], ['financials', '재무'],
  ['news', '뉴스'], ['description', '회사'], ['insiders', '내부자'],
]

export default function TickerDetail() {
  const { symbol } = useParams()
  const { detail, status, error, loadedAt, reload } = useTickerDetail(symbol)
  const now = loadedAt
  // 회사 자료(뉴스·재무·애널리스트·내부자)는 첫 페인트 뒤에 따로 받는다 —
  // 개요 응답은 이미 candles 200봉을 싣고 있고, 이 4블록은 전부 스크롤 아래에 있다.
  const [company, setCompany] = useState<Company | null>(null)
  const [companyError, setCompanyError] = useState<string | null>(null)
  const [tradeOpen, setTradeOpen] = useState<'BUY' | 'SELL' | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [tab, setTab] = useState('top')

  const loadCompany = () => {
    setCompanyError(null)
    return get<Company>(`/api/tickers/${symbol}/company`)
      .then(setCompany)
      .catch(e => { setCompany(null); setCompanyError(String(e)) })
  }

  /** 이 종목만 갱신 — 전체 갱신은 수 초 걸린다. 회사 자료도 같은 버튼으로 강제 갱신된다. */
  const refresh = async () => {
    setBusy(true); setActionError(null)
    try { await post(`/api/refresh?symbol=${encodeURIComponent(symbol!)}`); reload(); await loadCompany() }
    catch (e) { setActionError(String(e)) }
    finally { setBusy(false) }
  }

  /** 조회만 하던 종목을 워치리스트로 올린다. 여기서만 등록된다 —
   *  검색해서 열어본 것이 저절로 워치리스트에 쌓이면 "지켜보기로 정한 것"이 무의미해진다. */
  const track = async () => {
    setBusy(true); setActionError(null)
    try { await put(`/api/watchlist/${encodeURIComponent(symbol!)}`); reload() }
    catch (e) { setActionError(String(e)) }
    finally { setBusy(false) }
  }

  useEffect(() => { setCompany(null) }, [symbol])
  // 회사 자료는 ready 이후에만 부른다 — pending 중에는 /company가 404를 준다
  useEffect(() => {
    if (status !== 'ready' || !detail) return
    const t = setTimeout(loadCompany, 0)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, detail?.symbol])

  // 탭 활성 상태는 스크롤 위치를 따라간다 — 클릭한 탭만 켜두면 스크롤 후 거짓말이 된다
  useEffect(() => {
    if (!detail) return
    const els = TABS.map(([id]) => document.getElementById(id)).filter((e): e is HTMLElement => !!e)
    const io = new IntersectionObserver(entries => {
      const hit = entries.filter(e => e.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0]
      if (hit) setTab(hit.target.id)
    }, { rootMargin: '-48px 0px -60% 0px' })
    els.forEach(e => io.observe(e))
    return () => io.disconnect()
  }, [detail])

  if (status === 'failed') return (
    <div className="card">
      <div style={{ color: 'var(--sell)' }}>
        {error ? `종목 정보를 불러오지 못했습니다: ${error}` : '다시 불러오는 중…'}
      </div>
      <button style={{ marginTop: 10 }} onClick={reload}>다시 시도</button>
    </div>
  )
  if (!detail) return (
    <div className="grid">
      {/* pending은 "멈춘 것"이 아니라 "받는 중"이다 — 구분해 주지 않으면
          사용자가 새로고침을 반복하며 같은 수집을 기다린다 */}
      {status === 'pending' &&
        <div className="quote-note">시세를 받아오는 중…</div>}
      <div className="card skeleton" style={{ minHeight: 80 }} />
      <div className="card skeleton" style={{ minHeight: 380 }} />
      <div className="card skeleton" style={{ minHeight: 240 }} />
    </div>
  )

  const sig = detail.signal
  const c = detail.candles
  const last = c.at(-1) ?? null
  const change = changeFromPrev(c)
  const stale = isStale(detail.last_refresh, now)
  const risk = detail.risk
  const plan = risk?.exit_plan ?? null
  const holdingSellSignal = !!plan && !!sig && dir(sig.swing_grade) < 0
  const v = verdict(detail)
  const profile = detail.profile ?? null
  const cells = snapshotCells(detail, now)

  const levels: PriceLevel[] = []
  if (risk) {
    levels.push({ price: risk.stop_price, label: risk.stop_source === 'rule' ? '손절(룰)' : '손절(2×ATR)', color: '#ff5c7a' })
    levels.push({ price: risk.target_price, label: '목표', color: '#2ee59d' })
  }
  if (plan) levels.push({ price: plan.avg_price, label: '평단', color: '#5b8cff' })

  const goTab = (id: string) => {
    setTab(id)
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  /** /company 요청 자체가 실패한 상태 — 블록 status와 구분해서 보여준다.
   *  (구버전 백엔드처럼 엔드포인트가 없을 때도 여기로 온다) */
  const companyFail = companyError
    ? <div className="quote-note block-empty" title={companyError}>
        회사 자료를 불러오지 못했습니다 — 새로고침 후 다시 확인하세요.</div>
    : null

  return (
    <div className="quote">
      <QuoteHeader detail={detail} change={change} stale={stale} now={now} busy={busy}
                   onRefresh={refresh} onTrade={() => setTradeOpen(holdingSellSignal ? 'SELL' : 'BUY')} />
      {!detail.tracked &&
        <button onClick={track} disabled={busy} title="워치리스트에 추가">관심 등록</button>}
      {actionError &&
        <div className="quote-note" style={{ color: 'var(--sell)' }}>{actionError}</div>}

      <div className={`quote-verdict ${v.tone}`}>
        <span>{v.text}</span>
        {/* 판정의 근거(시그널·백테스트·플랜)는 이제 다른 화면에 있다 — 입구를 판정 옆에 둔다 */}
        <Link className="verdict-link" to={`/ticker/${symbol}/analysis`}>분석 →</Link>
      </div>
      {risk?.basis_adjusted && <div className="warn-box note">
        ⓘ 이 종목의 원가에는 평단 맞춤용 <strong>보정 로트</strong>가 섞여 있습니다 —
        평단·평가손익·R·손절선·확정손익은 실제 체결가만으로 만든 값이 아닙니다.</div>}

      {tradeOpen && <TradeDialog symbol={detail.symbol} name={detail.name}
        currency={detail.currency} defaultPrice={last?.close ?? null}
        defaultSide={tradeOpen} defaultQuantity={null}
        costRates={detail.cost_rates} exitPlan={plan}
        suggestedQuantity={risk?.addable_quantity ?? risk?.position_size_1pct}
        cash={detail.cash} entryReview={detail.entry_review}
        position={risk ? { stopPrice: risk.stop_price, stopSource: risk.stop_source,
                           totalAssetKrw: risk.total_asset_krw, fxRate: risk.fx_rate,
                           maxWeightPct: risk.max_weight_pct } : null}
        onClose={() => setTradeOpen(null)} onSaved={reload} />}

      <nav className="quote-tabs" aria-label="섹션">
        {TABS.map(([id, label]) => (
          <button key={id} className={`quote-tab${tab === id ? ' active' : ''}`}
                  onClick={() => goTab(id)}>{label}</button>))}
        <Link className="quote-tab" to={`/ticker/${symbol}/analysis`}>분석</Link>
      </nav>

      <section className="quote-section" id="chart" style={{ marginTop: 0 }}>
        <QuoteChart candles={c} levels={levels} />
      </section>

      <SnapshotTable id="snapshot" cells={cells} />
      {/* pending 문구는 계약 v2의 snapshot.note(BE가 쓴 한국어)를 그대로 쓴다 —
          같은 문장을 FE가 또 만들면 나중에 한쪽만 고쳐진다 */}
      <div className="quote-note" style={{ marginTop: 6 }}>
        {detail.snapshot?.sources?.length
          ? <>출처: {detail.snapshot.sources.join(' · ')}
              {detail.snapshot.fetched_at && ` · ${relativeTime(detail.snapshot.fetched_at, now)}`}</>
          : detail.snapshot?.note ?? '스냅샷 지표는 회사 자료 갱신 후 채워집니다'}
      </div>

      <section className="quote-section" id="financials">
        <h3>재무 <BlockSource block={company?.financials} now={now} /></h3>
        {companyFail ?? <FinancialsChart block={company?.financials} currency={detail.currency}
                                         loading={!company && !companyError} />}
      </section>

      <div className="quote-grid">
        {/* ── 좌: 뉴스 (finviz 하단 2:1의 넓은 쪽) ── */}
        <div>
          <section className="quote-section" id="news" style={{ marginTop: 0 }}>
            <h3>뉴스 <BlockSource block={company?.news} now={now} /></h3>
            {companyFail ?? <NewsList block={company?.news} loading={!company && !companyError} />}
          </section>
        </div>
        {/* ── 우: 애널리스트 ── */}
        <div>
          <section className="quote-section" id="ratings" style={{ marginTop: 0 }}>
            <h3>애널리스트 <BlockSource block={company?.ratings} now={now} /></h3>
            {companyFail ?? <RatingsTable block={company?.ratings} currency={detail.currency}
                                          loading={!company && !companyError} />}
          </section>
        </div>
      </div>

      <section className="quote-section" id="description">
        <h3>회사 설명
          <small>
            {profile?.source && `출처: ${profile.source}`}
            {profile?.source && profile.fetched_at && ` · ${relativeTime(profile.fetched_at, now)}`}
            {profile?.description_lang === 'en' && ' · 영문 원문'}
          </small></h3>
        {/* 문구는 BE가 쓴다(profile.status/note, 계약 v2). 구버전 응답이면 status가 없으므로
            아직 수집 전으로 보고 BlockEmpty의 pending 폴백 문구가 나간다 — 같은 문장을
            두 곳에서 관리하지 않기 위한 통로다. */}
        {profile?.description
          ? <p className="company-desc">{profile.description}
              {profile.description_truncated && <span className="quote-note"> …(요약본)</span>}</p>
          : <BlockEmpty height={60} empty="이 종목은 회사 설명이 제공되지 않습니다."
              block={{ status: profile?.status ?? 'pending',
              note: profile?.note ?? null, source: profile?.source ?? null,
              fetched_at: profile?.fetched_at ?? null }} />}
      </section>

      <section className="quote-section" id="insiders">
        <h3>내부자 거래 <BlockSource block={company?.insiders} now={now} /></h3>
        {companyFail ?? <InsiderTable block={company?.insiders} currency={detail.currency}
                                      loading={!company && !companyError} />}
      </section>
    </div>
  )
}
