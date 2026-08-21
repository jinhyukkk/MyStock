import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { del, get, post } from '../api'
import { isStale } from '../time'
import { cur, fmt } from '../format'
import type { Backtest, TickerDetail as Detail } from '../types'
import SignalBadge from '../components/SignalBadge'
import ScoreBar from '../components/ScoreBar'
import TradeDialog from '../components/TradeDialog'
import BacktestTable from '../components/BacktestTable'
import QuoteHeader from '../components/quote/QuoteHeader'
import QuoteChart, { type PriceLevel } from '../components/quote/QuoteChart'
import SnapshotTable, { type SnapCell } from '../components/quote/SnapshotTable'
import { pctCell } from '../quote/cells'
import { avgVolume, changeFromPrev, perfPct, perfYtdPct, range52w, relVolume, smaGapPct } from '../quote/stats'
import '../quote.css'

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
      + '우측 청산 플랜에서 얼마를 덜어낼지 먼저 정하세요.' }
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
  ['top', '개요'], ['chart', '차트'], ['snapshot', '스냅샷'], ['signal', '시그널'],
  ['backtest', '백테스트'], ['position', '포지션'], ['rules', '룰·기록'],
]

const signed = (v: number, digits = 2) => `${v > 0 ? '+' : ''}${v.toFixed(digits)}`

export default function TickerDetail() {
  const { symbol } = useParams()
  const [detail, setDetail] = useState<Detail | null>(null)
  const [backtest, setBacktest] = useState<Backtest | null>(null)
  const [btError, setBtError] = useState<string | null>(null)
  // 백테스트는 상세와 별개 요청이라 먼저 그려지는 프레임이 존재한다. 그 프레임에서
  // "표본 부족"이라고 단정하면 아직 오지 않은 근거를 없다고 말하는 셈이 된다.
  const [btLoading, setBtLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [ruleType, setRuleType] = useState('TARGET')
  const [ruleValue, setRuleValue] = useState('')
  const [ruleMsg, setRuleMsg] = useState<string | null>(null)
  const [tradeOpen, setTradeOpen] = useState<'BUY' | 'SELL' | null>(null)
  const [sellQuantity, setSellQuantity] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [now, setNow] = useState(Date.now())
  const [tab, setTab] = useState('top')

  const load = () => get<Detail>(`/api/tickers/${symbol}`)
    .then(d => { setDetail(d); setError(null); setNow(Date.now()) })
    .catch(e => setError(String(e)))

  const loadBacktest = () => {
    setBtLoading(true); setBtError(null)
    return get<Backtest>(`/api/tickers/${symbol}/backtest`)
      .then(setBacktest).catch(e => setBtError(String(e)))
      .finally(() => setBtLoading(false))
  }

  /** 이 종목만 갱신 — 전체 갱신은 수 초 걸린다. 백테스트도 새 봉으로 다시 받는다. */
  const refresh = async () => {
    setBusy(true)
    try { await post(`/api/refresh?symbol=${encodeURIComponent(symbol!)}`); await load(); await loadBacktest() }
    catch (e) { setError(String(e)) }
    finally { setBusy(false) }
  }
  useEffect(() => { load(); setBacktest(null); loadBacktest() }, [symbol])

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

  if (error) return (
    <div className="card">
      <div style={{ color: 'var(--sell)' }}>불러오기 실패: {error}</div>
      <button style={{ marginTop: 10 }} onClick={() => { setError(null); load() }}>다시 시도</button>
    </div>
  )
  if (!detail) return (
    <div className="grid">
      <div className="card skeleton" style={{ minHeight: 80 }} />
      <div className="card skeleton" style={{ minHeight: 380 }} />
      <div className="card skeleton" style={{ minHeight: 240 }} />
    </div>
  )

  const sig = detail.signal
  const c = detail.candles
  const last = c.at(-1) ?? null
  const ccy = detail.currency
  const money = (n: number | null | undefined) => cur(ccy, n ?? null)
  // 스냅샷 칸은 통화 기호 없이 숫자만 — 기호까지 붙이면 '2,987,000 -42%'가 칸을 넘친다. 통화는 헤더에 있다.
  const num = (n: number | null | undefined) => n == null ? '—' : ccy === 'USD' ? fmt(n) : fmt(Math.round(n))
  const change = changeFromPrev(c)
  const gradeStat = backtest?.grades.find(g => g.grade === sig?.swing_grade) ?? null
  const gradeH = backtest?.horizons.find(h =>
    gradeStat?.[`insufficient${h}`] !== true && typeof gradeStat?.[`avg_net${h}`] === 'number') ?? null
  const gradeNet = gradeH !== null ? gradeStat![`avg_net${gradeH}`] as number : null
  const gradeContradicts = gradeNet !== null && sig
    ? (dir(sig.swing_grade) > 0 && gradeNet < 0) || (dir(sig.swing_grade) < 0 && gradeNet > 0)
    : false
  const longtermStat = backtest?.longterm_grades.find(g => g.grade === sig?.longterm_grade) ?? null
  const longtermUnverified = !!backtest &&
    (!longtermStat || backtest.long_horizons.every(h => longtermStat[`insufficient${h}`] === true))
  const conflict = sig && dir(sig.swing_grade) !== 0 && dir(sig.longterm_grade) !== 0
    && dir(sig.swing_grade) !== dir(sig.longterm_grade)
  const hasStopRule = detail.rules.some(r => r.rule_type === 'STOP')
  const v = verdict(detail)
  const disc = backtest?.discrimination?.['20'] ?? null
  const stale = isStale(detail.last_refresh, now)
  const risk = detail.risk
  const plan = risk?.exit_plan ?? null
  const holdingSellSignal = !!plan && !!sig && dir(sig.swing_grade) < 0
  const r52 = range52w(c)
  const win20 = gradeStat && gradeStat.insufficient20 !== true && typeof gradeStat.win20 === 'number'
    ? gradeStat.win20 : null

  const addRule = async () => {
    if (!ruleValue) return
    try {
      await post('/api/rules', { symbol, rule_type: ruleType, value: Number(ruleValue) })
      setRuleValue(''); setRuleMsg(null); load()
    } catch (e) { setRuleMsg(String(e)) }
  }
  /** 손절가는 이미 계산돼 있다 — 손으로 옮겨 적게 두면 값이 틀리거나 등록을 건너뛴다.
   *  갱신 시 기존 STOP 룰을 지운다: 두 개가 남으면 어느 쪽이 울리는지 알 수 없다. */
  const registerStop = async () => {
    if (!risk) return
    try {
      for (const r of detail.rules.filter(r => r.rule_type === 'STOP')) await del(`/api/rules/${r.id}`)
      await post('/api/rules', { symbol, rule_type: 'STOP', value: risk.atr_stop_price })
      setRuleMsg(null); load()
    } catch (e) { setRuleMsg(String(e)) }
  }

  const levels: PriceLevel[] = []
  if (risk) {
    levels.push({ price: risk.stop_price, label: risk.stop_source === 'rule' ? '손절(룰)' : '손절(2×ATR)', color: '#ff5c7a' })
    levels.push({ price: risk.target_price, label: '목표', color: '#2ee59d' })
  }
  if (plan) levels.push({ price: plan.avg_price, label: '평단', color: '#5b8cff' })

  // ── 스냅샷 표: finviz snapshot-table2 자리. 6쌍 × 9행. ──
  const f = detail.fundamentals
  const gradeCell = (label: string, grade: string, extra?: string): SnapCell =>
    ({ label, value: <><SignalBadge grade={grade} />{extra && <small>{extra}</small>}</> })
  const scoreCell = (label: string, s: number): SnapCell =>
    ({ label, value: signed(s, 0), tone: s > 0 ? 'pos' : s < 0 ? 'neg' : null })
  const cells: SnapCell[] = [
    { label: '시장', value: detail.market },
    { label: '시가총액', value: !f?.market_cap ? '—'
        : ccy === 'USD' ? `$${(f.market_cap / 1e9).toFixed(1)}B` : `${(f.market_cap / 1e12).toFixed(1)}조` },
    { label: 'PER', value: f?.per?.toFixed(1) ?? '—' },
    { label: 'PBR', value: f?.pbr?.toFixed(2) ?? '—' },
    { label: '배당수익률', value: f?.dividend_yield !== null && f?.dividend_yield !== undefined ? `${f.dividend_yield}%` : '—' },
    { label: '구분', value: detail.is_etf ? 'ETF' : '주식' },

    { label: '현재가', value: num(last?.close) },
    { label: '전일 종가', value: num(change?.prev) },
    { label: '전일 대비', value: change ? `${change.diff > 0 ? '+' : ''}${fmt(change.diff)}` : '—',
      tone: !change || change.diff === 0 ? null : change.diff > 0 ? 'pos' : 'neg' },
    pctCell('등락률', change?.pct ?? null),
    { label: '거래량', value: last ? fmt(last.volume) : '—' },
    { label: '평균 거래량(20)', value: fmt(avgVolume(c, 20)) },

    { label: '상대 거래량', value: relVolume(c, 20)?.toFixed(2) ?? '—',
      tone: (relVolume(c, 20) ?? 0) >= 1.5 ? 'warn' : null, title: '오늘 거래량 ÷ 직전 20일 평균' },
    { label: '52주 고가', value: r52 ? <>{num(r52.high)}<small>{r52.highPct !== null ? `${signed(r52.highPct)}%` : ''}</small></> : '—' },
    { label: '52주 저가', value: r52 ? <>{num(r52.low)}<small>{r52.lowPct !== null ? `${signed(r52.lowPct)}%` : ''}</small></> : '—' },
    pctCell('SMA20 이격', last ? smaGapPct(last.close, last.sma20) : null),
    pctCell('SMA60 이격', last ? smaGapPct(last.close, last.sma60) : null),
    pctCell('SMA120 이격', last ? smaGapPct(last.close, last.sma120) : null),

    { label: 'RSI (14)', value: last?.rsi?.toFixed(1) ?? '—',
      tone: last?.rsi != null && (last.rsi >= 70 || last.rsi <= 30) ? 'warn' : null },
    { label: 'MACD', value: last?.macd != null ? signed(last.macd) : '—',
      tone: last?.macd != null ? (last.macd > 0 ? 'pos' : 'neg') : null },
    { label: 'MACD 히스토', value: last?.macd_hist != null ? signed(last.macd_hist) : '—',
      tone: last?.macd_hist != null ? (last.macd_hist > 0 ? 'pos' : 'neg') : null },
    { label: 'ATR (14)', value: risk ? <>{fmt(risk.atr)}<small>{risk.atr_pct}%</small></> : '—' },
    { label: 'BB 상단', value: num(last?.bb_upper) },
    { label: 'BB 하단', value: num(last?.bb_lower) },
    pctCell('최대 낙폭(400일)', risk ? -Math.abs(risk.mdd_pct) : null),

    pctCell('1주', perfPct(c, 5)), pctCell('1개월', perfPct(c, 21)), pctCell('3개월', perfPct(c, 63)),
    pctCell('6개월', perfPct(c, 126)), pctCell('연초 대비', perfYtdPct(c, new Date(now).getFullYear())),
    pctCell('1년', perfPct(c, 252)),

    sig ? scoreCell('스윙 점수', sig.swing_score) : { label: '스윙 점수', value: '—' },
    sig ? gradeCell('스윙 등급', sig.swing_grade) : { label: '스윙 등급', value: '—' },
    sig ? scoreCell('중장기 점수', sig.longterm_score) : { label: '중장기 점수', value: '—' },
    sig ? gradeCell('중장기 등급', sig.longterm_grade, longtermUnverified ? '미검증' : undefined)
        : { label: '중장기 등급', value: '—' },
    { label: '국면', value: sig?.regime_label ?? '—' },
    { label: '봉 상태', value: sig?.bar_complete === false ? '미확정' : '확정', tone: sig?.bar_complete === false ? 'warn' : null,
      title: sig?.bar_complete === false ? `${sig.bar_date} 봉이 마감 전입니다. 종가 확정 시 등급이 바뀔 수 있습니다.` : undefined },

    { label: risk?.stop_source === 'rule' ? '손절가(룰)' : '손절가(2ATR)', title: risk?.stop_source === 'rule' ? '등록한 손절 룰' : '2×ATR 제안 손절가',
      value: risk ? <>{num(risk.stop_price)}<small>{risk.stop_pct}%</small></> : '—', tone: 'neg' },
    { label: `목표가 (${risk?.target_r ?? '—'}R)`, value: risk ? <>{num(risk.target_price)}<small>+{risk.target_pct}%</small></> : '—', tone: 'pos' },
    { label: '손익비', value: risk?.reward_risk !== null && risk?.reward_risk !== undefined ? `${risk.reward_risk}:1` : '—' },
    { label: '제안 수량(1%)', value: risk?.position_size_1pct != null ? risk.position_size_1pct.toLocaleString('ko-KR') : '—',
      tone: risk?.position_size_1pct === 0 ? 'warn' : null },
    { label: '60일 고점', value: risk?.resistance_60d != null ? num(risk.resistance_60d) : '—' },
    { label: '계좌 미결 리스크', value: risk?.account_open_risk
        ? <>{risk.account_open_risk.total_risk_pct}%<small>/ {risk.account_open_risk.limit_pct}%</small></> : '—',
      tone: risk?.account_open_risk?.over_limit ? 'warn' : null },

    { label: '보유 수량', value: plan ? plan.held_quantity.toLocaleString('ko-KR') : '—' },
    { label: '평단', value: plan ? num(plan.avg_price) : '—' },
    { label: '평가손익', value: plan ? <>{signed(plan.unrealized_pnl_pct)}%<small>₩{Math.round(plan.unrealized_pnl_krw).toLocaleString('ko-KR')}</small></> : '—',
      tone: plan ? (plan.unrealized_pnl_pct >= 0 ? 'pos' : 'neg') : null },
    { label: 'R 배수', value: plan?.r_multiple != null ? `${signed(plan.r_multiple)}R` : '—',
      tone: plan?.r_multiple != null ? (plan.r_multiple >= 0 ? 'pos' : 'neg') : null,
      title: plan?.r_unit != null ? `1R = ${money(plan.r_unit)} (현재가 − 손절선)` : undefined },
    pctCell(plan?.stop_locks_profit ? '손절선 (이익 확정)' : '손절선 (평단 대비)', plan?.stop_from_avg_pct ?? null),
    { label: '누적 배당(세후)', value: detail.dividends.count > 0
        ? <>₩{Math.round(detail.dividends.total_net_krw).toLocaleString('ko-KR')}<small>{detail.dividends.count}회</small></> : '—' },

    { label: '승률 (20일)', value: win20 !== null ? `${win20}%` : btLoading ? '…' : '표본 부족',
      tone: win20 !== null ? (win20 >= 50 ? 'pos' : 'neg') : null, title: '비용 차감 후, 현재 스윙 등급 기준' },
    pctCell(`순수익 (${gradeH ?? 20}일)`, gradeNet),
    { label: '독립 표본', value: gradeStat && gradeH !== null ? String(gradeStat[`episodes${gradeH}`] ?? '—') : '—' },
    { label: '판별력', value: disc ? `${disc.spread > 0 ? '+' : ''}${disc.spread}%p` : '—',
      tone: disc ? (disc.discriminates ? 'pos' : 'warn') : null,
      title: disc ? `매수 등급 ${disc.buy_net}% vs 매도 등급 ${disc.sell_net}% (20일 순수익)` : undefined },
    { label: '등록 룰', value: `${detail.rules.length}개` },
  ]

  /** 진입 수량 블록. 미보유면 포지션 섹션 상단에, 보유 중이면 '추가 매수 검토' 안에 놓인다. */
  const sizingBlock = !risk ? null
    : risk.position_size_1pct === null ? (
      <div className="kv-row"><span className="k">제안 수량 (1% 리스크)</span>
        <span className="v" style={{ fontWeight: 400, color: 'var(--text-dim)' }}>
          예수금 입력 후 계산 — <Link to="/portfolio/settings">설정</Link></span></div>
    ) : (<>
      <div className="kv-row"><span className="k">제안 수량 (1%, 비중 {risk.max_weight_pct}% 상한)</span>
        <span className="v">{risk.position_size_1pct.toLocaleString('ko-KR')}
          <small>리스크 ₩{risk.risk_budget_krw?.toLocaleString('ko-KR')}</small></span></div>
      {risk.position_notional_krw !== null && <div className="kv-sub">
        평가액 ₩{risk.position_notional_krw.toLocaleString('ko-KR')}
        {(risk.held_quantity ?? 0) > 0 && <> · 이미 {risk.held_quantity?.toLocaleString('ko-KR')} 보유 →
          추가 매수 가능 <strong>{risk.addable_quantity?.toLocaleString('ko-KR')}</strong></>}
        {risk.lot_size === 1 && (risk.position_size_raw ?? 0) > risk.position_size_1pct &&
          <> · 1주 단위 내림 (계산값 {risk.position_size_raw?.toLocaleString('ko-KR')})</>}
      </div>}
      {risk.position_size_1pct === 0 && <div className="warn" style={{ fontSize: 11 }}>
        ⚠ 1% 리스크로는 1주도 살 수 없습니다 — 변동성 대비 계좌가 작습니다</div>}
      {risk.liquidity_pct !== null && <div className="kv-sub"
        style={{ color: risk.liquidity_pct >= 1 ? 'var(--warn)' : undefined }}>
        {risk.liquidity_pct < 0.01 ? '일평균 거래대금 대비 0.01% 미만 — 체결 영향 미미'
          : `일평균 거래대금의 ${risk.liquidity_pct}%`}
        {risk.liquidity_pct >= 1 && ' — 이 크기는 체결가를 밀 수 있습니다'}</div>}
    </>)

  const noteCount = [risk?.position_size_capped, risk?.target_above_resistance,
                     conflict, disc ? !disc.discriminates : false].filter(Boolean).length

  const goTab = (id: string) => {
    setTab(id)
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <div className="quote">
      <QuoteHeader detail={detail} change={change} stale={stale} now={now} busy={busy}
                   onRefresh={refresh} onTrade={() => setTradeOpen(holdingSellSignal ? 'SELL' : 'BUY')} />

      <div className={`quote-verdict ${v.tone}`}>{v.text}</div>
      {/* 판정을 뒤집는 사실은 판정 바로 아래 — 다른 곳에 두면 검증된 신호를 따른다고 믿게 된다 */}
      {gradeContradicts && sig && <div className="warn-box critical">
        ⚠ 이 종목에서 <strong>{sig.swing_grade}</strong> 등급의 과거 {gradeH}일 순수익은
        {' '}{signed(gradeNet!)}%로 등급 방향과 반대였습니다
        (독립 표본 {String(gradeStat?.[`episodes${gradeH}`] ?? '—')}개). 이 배지를 따르는 것은
        이 종목의 관측 이력과 반대로 가는 선택입니다.</div>}
      {risk?.basis_adjusted && <div className="warn-box note">
        ⓘ 이 종목의 원가에는 평단 맞춤용 <strong>보정 로트</strong>가 섞여 있습니다 —
        평단·평가손익·R·손절선·확정손익은 실제 체결가만으로 만든 값이 아닙니다.</div>}

      {tradeOpen && <TradeDialog symbol={detail.symbol} name={detail.name}
        currency={detail.currency} defaultPrice={last?.close ?? null}
        defaultSide={tradeOpen} defaultQuantity={sellQuantity}
        costRates={detail.cost_rates} exitPlan={plan}
        suggestedQuantity={risk?.addable_quantity ?? risk?.position_size_1pct}
        cash={detail.cash} entryReview={detail.entry_review}
        position={risk ? { stopPrice: risk.stop_price, stopSource: risk.stop_source,
                           totalAssetKrw: risk.total_asset_krw, fxRate: risk.fx_rate,
                           maxWeightPct: risk.max_weight_pct } : null}
        onClose={() => { setTradeOpen(null); setSellQuantity(null) }} onSaved={load} />}

      <nav className="quote-tabs" aria-label="섹션">
        {TABS.map(([id, label]) => (
          <button key={id} className={`quote-tab${tab === id ? ' active' : ''}`}
                  onClick={() => goTab(id)}>{label}</button>))}
      </nav>

      <section className="quote-section" id="chart" style={{ marginTop: 0 }}>
        <QuoteChart candles={c} levels={levels} />
      </section>

      <SnapshotTable id="snapshot" cells={cells} />

      <div className="quote-grid">
        {/* ── 좌: 시그널 근거 + 백테스트 (finviz 뉴스 컬럼 자리) ── */}
        <div>
          <section className="quote-section" id="signal">
            <h3>시그널 근거 {sig && <small>{sig.summary}</small>}</h3>
            {sig ? sig.indicator_scores.map((s, i) => (
              <div className="reason-row" key={i}>
                <strong>{s.name}</strong>
                <span className="scope">{s.scope === 'swing' ? '스윙' : '중장기'}</span>
                <ScoreBar score={s.score} label={s.name} />
                <span className="why">{s.reason}</span>
              </div>
            )) : <div className="quote-note">시그널이 아직 계산되지 않았습니다.</div>}
            {sig?.context_note && <div style={{ color: 'var(--accent)', fontSize: 12, marginTop: 8 }}>💡 {sig.context_note}</div>}
            {conflict && sig && <div className="warn-box note">
              ⚠ 스윙 {sig.swing_grade} · 중장기 {sig.longterm_grade} — 방향이 엇갈립니다.
              어느 쪽을 따를지가 아니라 <strong>보유 기간을 먼저 정하고</strong> 그에 맞는 쪽을 보세요.</div>}
          </section>

          <section className="quote-section" id="backtest">
            <h3>시그널 백테스트
              {backtest && <small>{backtest.start} ~ {backtest.end} · 신호일 {backtest.samples}일
                {backtest.bench_label && ` · 초과수익 = ${backtest.bench_label} 대비`}</small>}</h3>
            {btLoading && <>
              <div className="quote-note">등급별 과거 성적을 계산하는 중입니다…</div>
              <div className="skeleton" style={{ height: 100, marginTop: 8 }} /></>}
            {btError && <div className="warn-box">불러오지 못했습니다: {btError}</div>}
            {backtest && <>
              <div className="quote-note">
                진입 {backtest.entry_rule} · 청산 {backtest.exit_rule} ·
                {' '}순·승률은 왕복 비용 {backtest.cost_pct}%p 차감 후 기준.
                {' '}{backtest.cost_breakdown.note} 각 칸의 <strong>스트레스</strong> 값은
                {' '}비용 {backtest.cost_breakdown.stress_pct}%p 가정 결과이며, 여기서
                {' '}마이너스면 그 엣지는 실집행에서 사라질 수 있습니다.
                {' '}±1σ는 <strong>비중첩 에피소드</strong> 기준 표준오차이고,
                독립 표본 {backtest.min_episodes}개 미만인 칸은 수치를 감춥니다.
                {disc && !disc.discriminates && <span className="warn"> ⚠ 등급이 방향을 못 가름 ({disc.spread}%p)</span>}
              </div>
              <BacktestTable bt={backtest} grades={backtest.grades} horizons={backtest.horizons}
                             missing={backtest.missing_grades} caption="스윙 등급"
                             highlightGrade={sig?.swing_grade} />
              <BacktestTable bt={backtest} grades={backtest.longterm_grades}
                             horizons={backtest.long_horizons}
                             missing={backtest.missing_longterm_grades}
                             highlightGrade={sig?.longterm_grade}
                             caption="중장기 등급 — 보유 기간이 길어 독립 표본이 훨씬 적습니다" />
            </>}
          </section>
        </div>

        {/* ── 우: 포지션·리스크 / 룰 / 히스토리 (finviz 애널리스트·내부자 컬럼 자리) ── */}
        <div>
          <section className="quote-section" id="position">
            <h3>{plan ? '청산 플랜' : '진입 플랜'}
              {plan && <small>보유 {plan.held_quantity.toLocaleString('ko-KR')} · 평단 {money(plan.avg_price)}</small>}</h3>
            {!risk && <div className="quote-note">ATR 계산에 필요한 가격 데이터가 부족합니다 — 새로고침 후 다시 확인하세요.</div>}

            {plan && <>
              <div className="kv">
                <div className="kv-row"><span className="k">평가손익</span>
                  <span className={`v ${plan.unrealized_pnl_pct >= 0 ? 'pos' : 'neg'}`}>
                    {signed(plan.unrealized_pnl_pct)}%<small>₩{Math.round(plan.unrealized_pnl_krw).toLocaleString('ko-KR')}</small></span></div>
                {detail.dividends.count > 0 && <div className="kv-row"><span className="k">배당 포함</span>
                  <span className={`v ${plan.unrealized_pnl_krw + detail.dividends.total_net_krw >= 0 ? 'pos' : 'neg'}`}>
                    {plan.unrealized_pnl_krw + detail.dividends.total_net_krw >= 0 ? '+' : ''}
                    ₩{Math.round(plan.unrealized_pnl_krw + detail.dividends.total_net_krw).toLocaleString('ko-KR')}
                    <small>배당 ₩{Math.round(detail.dividends.total_net_krw).toLocaleString('ko-KR')} 세후 · {detail.dividends.count}회</small></span></div>}
                {plan.r_multiple !== null && <div className="kv-row"><span className="k">R 배수</span>
                  <span className={`v ${plan.r_multiple >= 0 ? 'pos' : 'neg'}`}>{signed(plan.r_multiple)}R
                    <small>1R = {money(plan.r_unit)} (현재가 − 손절선)</small></span></div>}
                <div className="kv-row"><span className="k">{plan.stop_locks_profit ? '손절선 (이익 확정 구간)' : '손절선 (평단 대비)'}</span>
                  <span className="v" style={{ color: plan.stop_locks_profit ? 'var(--buy)' : 'var(--sell)' }}>
                    {signed(plan.stop_from_avg_pct)}%</span></div>
              </div>
              <div className="kv-sub">
                {plan.stop_locks_profit
                  ? `손절에 닿아도 평단 위에서 청산됩니다 · 여기서 ₩${Math.round(plan.risk_to_stop_krw).toLocaleString('ko-KR')} 되돌림`
                  : `여기서 손절까지 ₩${Math.round(plan.risk_to_stop_krw).toLocaleString('ko-KR')} 추가 손실`}
                {plan.r_multiple !== null && ' · 손절폭이 바뀌면 같은 손익도 배수가 달라집니다'}
              </div>
              <div className="table-scroll" style={{ marginTop: 6 }}>
                <table>
                  <thead><tr><th>비중</th><th>수량</th><th>순회수액</th>
                    <th>{plan.taxable_overseas ? '확정손익(세후)' : '확정손익'}</th><th></th></tr></thead>
                  <tbody>
                    {plan.slices.map(s => (
                      <tr key={s.label}>
                        <td>{s.label}</td>
                        <td>{s.quantity.toLocaleString('ko-KR')}</td>
                        <td>₩{Math.round(s.proceeds_krw).toLocaleString('ko-KR')}</td>
                        <td className={s.realized_pnl_after_tax_krw >= 0 ? 'pos' : 'neg'}>
                          {s.realized_pnl_after_tax_krw >= 0 ? '+' : ''}
                          ₩{Math.round(s.realized_pnl_after_tax_krw).toLocaleString('ko-KR')}
                          {s.tax_krw > 0 && <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                            양도세 -₩{Math.round(s.tax_krw).toLocaleString('ko-KR')}</div>}</td>
                        <td><button className="ghost" style={{ padding: '3px 8px', fontSize: 11 }}
                              onClick={() => { setSellQuantity(s.quantity); setTradeOpen('SELL') }}>기록</button></td>
                      </tr>))}
                  </tbody>
                </table>
              </div>
              <div className="quote-note" style={{ marginTop: 6 }}>
                회수액은 매도 수수료·거래세를 뺀 추정치이며 평단 기준입니다. 실제 체결가는 호가에 따라 달라집니다.
                {plan.taxable_overseas && <> 해외 양도세 22%는 이듬해 5월에 냅니다 —
                  올해 남은 기본공제 ₩{Math.round(plan.deduction_left_krw ?? 0).toLocaleString('ko-KR')}을 반영한 한계 세액입니다.</>}
              </div>
              <button style={{ marginTop: 8, padding: '6px 12px', fontSize: 12 }} onClick={() => setTradeOpen('SELL')}>매도 기록</button>
            </>}

            {risk && <>
              <div className="kv" style={{ marginTop: plan ? 14 : 0 }}>
                <div className="kv-row"><span className="k">{risk.stop_source === 'rule' ? '내 손절선 (룰 등록됨)' : '제안 손절가 (2×ATR)'}</span>
                  <span className="v neg">{money(risk.stop_price)}<small>{risk.stop_pct}%</small></span></div>
                {risk.stop_source === 'rule' && <div className="kv-sub">
                  오늘의 2×ATR 제안 {money(risk.atr_stop_price)} ({risk.atr_stop_pct}%)</div>}
                <div className="kv-row"><span className="k">제안 목표가 (손익비 {risk.target_r}:1)</span>
                  <span className="v pos">{money(risk.target_price)}<small>+{risk.target_pct}%</small></span></div>
                {!plan && sizingBlock}
              </div>
              <button className="ghost" style={{ marginTop: 8, padding: '5px 10px', fontSize: 12 }}
                      onClick={registerStop} disabled={hasStopRule && !risk.stop_drift}>
                {!hasStopRule ? '손절가를 룰로 등록' : risk.stop_drift ? '오늘의 제안으로 룰 갱신' : '손절 룰 등록됨'}</button>

              {risk.stop_drift && <div className="warn-box critical">
                ⚠ 등록한 손절선({money(risk.stop_price)})과 오늘의 2×ATR 제안({money(risk.atr_stop_price)})이
                현재가의 {Math.abs(risk.stop_drift_pct ?? 0)}%만큼 벌어졌습니다 — 변동성이 변했습니다.
                알림은 등록한 값에서 울립니다. 그대로 둘지 갱신할지 정하세요.</div>}
              {risk.stop_too_wide && <div className="warn-box critical">
                ⚠ {risk.stop_source === 'rule' ? '손절폭' : '2×ATR 손절폭'}이 {Math.abs(risk.stop_pct)}%로
                스윙 타임프레임에 과대합니다 (기준 {risk.max_stop_pct}%). 못 지킬 손절은 없는 손절과 같습니다.</div>}
              {risk.account_open_risk?.over_limit && <div className="warn-box critical">
                ⚠ 계좌 총 미결 리스크 {risk.account_open_risk.total_risk_pct}%가 상한 {risk.account_open_risk.limit_pct}%를
                넘었습니다 — 신규 진입 전에 기존 포지션 축소가 먼저입니다.</div>}

              {/* 나가는 판단과 들어가는 판단이 같은 무게로 경쟁하면 물타기 쪽이 이긴다 */}
              {plan && risk.position_size_1pct !== null && !holdingSellSignal &&
                <details className="premises"><summary>추가 매수 검토</summary>
                  <div className="kv" style={{ marginTop: 6 }}>{sizingBlock}</div></details>}

              <details className="premises">
                <summary>이 판단의 전제 보기{noteCount > 0 && <span className="warn">⚠ {noteCount}</span>}</summary>
                <div className="kv" style={{ marginTop: 6 }}>
                  <div className="kv-row"><span className="k">이 등급의 과거 성적 (20일)</span>
                    <span className="v">{win20 !== null
                      ? <>승률 {win20}%<small>독립 표본 {gradeStat!.episodes20}개</small></>
                      : <small>{btLoading ? '불러오는 중…' : btError ? '백테스트 없음' : '표본 부족'}</small>}</span></div>
                  {risk.resistance_60d !== null && <div className="kv-row"><span className="k">60일 고점 (매물대)</span>
                    <span className="v">{money(risk.resistance_60d)}<small>손익비 {risk.resistance_reward_risk}:1</small></span></div>}
                  {risk.account_open_risk && <div className="kv-row"><span className="k">계좌 총 미결 리스크</span>
                    <span className="v">{risk.account_open_risk.total_risk_pct}%<small>/ 상한 {risk.account_open_risk.limit_pct}%</small></span></div>}
                </div>
                {risk.position_size_capped && <div className="warn-box note">⚠ {risk.cap_reason}</div>}
                {risk.target_above_resistance && <div className="warn-box note">
                  ⚠ 목표가가 60일 고점({money(risk.resistance_60d)}) 위입니다 — 그 매물대를 뚫어야 도달합니다.
                  고점까지만 보면 손익비는 {risk.resistance_reward_risk}:1입니다.</div>}
                <div className="quote-note" style={{ marginTop: 8 }}>
                  손절 기준 총자산의 1%만 잃는 수량이되, 한 종목이 총자산의 {risk.max_weight_pct}%를 넘지 않도록
                  상한을 겁니다. 손절가는 자동 예약주문이 아니며 갭 하락 시 계획보다 더 잃을 수 있습니다.
                  지표 기반 참고 정보이며 투자 자문이 아닙니다.</div>
              </details>
            </>}
            {ruleMsg && <div style={{ color: 'var(--sell)', fontSize: 12, marginTop: 8 }}>{ruleMsg}</div>}
          </section>

          <section className="quote-section" id="rules">
            <h3>커스텀 룰 <small>도달 시 알림</small></h3>
            {detail.rules.length === 0 && <div className="quote-note">
              등록된 룰이 없습니다. 목표가·손절가를 걸어두면 도달 시 알림을 받습니다.</div>}
            <div className="kv">
              {detail.rules.map(r => {
                const label = { TARGET: '목표가', STOP: '손절가', AVG_PCT: '평단 대비 %' }[r.rule_type]
                return (
                  <div key={r.id} className="kv-row">
                    <span className="k">{label}</span>
                    <span className="v">{r.value.toLocaleString('ko-KR')}
                      {' '}<button className="ghost" style={{ padding: '2px 8px', fontSize: 11, marginLeft: 6 }} onClick={() => {
                        if (confirm(`${label} ${r.value.toLocaleString('ko-KR')} 룰을 삭제합니다.`
                          + (r.rule_type === 'STOP' ? '\n손절 알림이 더 이상 오지 않습니다.' : '')))
                          del(`/api/rules/${r.id}`).then(load)
                      }}>삭제</button></span>
                  </div>)
              })}
            </div>
            <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
              <select value={ruleType} onChange={e => setRuleType(e.target.value)} style={{ fontSize: 12 }}>
                <option value="TARGET">목표가</option>
                <option value="STOP">손절가</option>
                <option value="AVG_PCT">평단 대비 %</option>
              </select>
              <input type="number" placeholder="값" value={ruleValue}
                     onChange={e => setRuleValue(e.target.value)} style={{ width: 100, fontSize: 12 }} />
              <button onClick={addRule} style={{ padding: '6px 12px', fontSize: 12 }}>추가</button>
            </div>
          </section>

          <section className="quote-section" id="history">
            <h3>시그널 히스토리 <small>최근 20일</small></h3>
            <div className="table-scroll">
              <table>
                <thead><tr><th>날짜</th><th>스윙</th><th>중장기</th><th>등급</th></tr></thead>
                <tbody>
                  {detail.history.slice(0, 20).map(h => (
                    <tr key={h.date}>
                      <td>{h.date}</td>
                      <td>{h.swing_score.toFixed(0)}</td>
                      <td>{h.longterm_score.toFixed(0)}</td>
                      <td><SignalBadge grade={h.grade} /></td>
                    </tr>))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </div>
    </div>
  )
}
