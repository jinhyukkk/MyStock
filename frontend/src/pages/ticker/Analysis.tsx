import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { del, get, post } from '../../api'
import { isStale } from '../../time'
import { cur } from '../../format'
import type { Backtest } from '../../types'
import { useTickerDetail } from '../../ticker/useTickerDetail'
import SignalBadge from '../../components/SignalBadge'
import ScoreBar from '../../components/ScoreBar'
import TradeDialog from '../../components/TradeDialog'
import BacktestTable from '../../components/BacktestTable'
import QuoteHeader from '../../components/quote/QuoteHeader'
import { changeFromPrev } from '../../quote/stats'
import '../../quote.css'

/** MyStock 고유 판단 블록 — 시그널 근거·백테스트·청산 플랜·커스텀 룰·시그널 히스토리.
 *
 *  개요(`/ticker/:symbol`)를 finviz 구성(회사가 파는 것·밸류·시장의 말)으로 바꾸면서
 *  이 다섯 블록을 여기로 **옮겼다**(지운 게 아니다). 특히 커스텀 룰은 손절·목표 알림을
 *  등록·삭제하는 UI가 앱 전체에서 여기뿐이라, 사라지면 알림 기능 자체가 죽는다.
 *
 *  개요와 같은 `GET /api/tickers/{symbol}`을 다시 부르고, `/backtest`는 이제 이 화면만
 *  부른다 — 개요는 백테스트 UI가 없는데도 매번 계산을 시키고 있었다. */

/** 등급의 방향만 뽑는다 (+1 매수 / 0 중립 / -1 매도). */
const dir = (grade: string) => grade.includes('매수') ? 1 : grade.includes('매도') ? -1 : 0
const signed = (v: number, digits = 2) => `${v > 0 ? '+' : ''}${v.toFixed(digits)}`

const TABS: [string, string][] = [
  ['signal', '시그널'], ['backtest', '백테스트'], ['position', '포지션'],
  ['rules', '커스텀 룰'], ['history', '히스토리'],
]

export default function Analysis() {
  const { symbol } = useParams()
  const { detail, status, error, loadedAt, reload } = useTickerDetail(symbol)
  const now = loadedAt
  const [backtest, setBacktest] = useState<Backtest | null>(null)
  const [btError, setBtError] = useState<string | null>(null)
  // 백테스트는 상세와 별개 요청이라 먼저 그려지는 프레임이 존재한다. 그 프레임에서
  // "표본 부족"이라고 단정하면 아직 오지 않은 근거를 없다고 말하는 셈이 된다.
  const [btLoading, setBtLoading] = useState(true)
  const [ruleType, setRuleType] = useState('TARGET')
  const [ruleValue, setRuleValue] = useState('')
  const [ruleMsg, setRuleMsg] = useState<string | null>(null)
  const [tradeOpen, setTradeOpen] = useState<'BUY' | 'SELL' | null>(null)
  const [sellQuantity, setSellQuantity] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [tab, setTab] = useState('signal')

  const loadBacktest = () => {
    setBtLoading(true); setBtError(null)
    return get<Backtest>(`/api/tickers/${symbol}/backtest`)
      .then(setBacktest).catch(e => setBtError(String(e)))
      .finally(() => setBtLoading(false))
  }

  /** 이 종목만 갱신 — 전체 갱신은 수 초 걸린다. 백테스트도 새 봉으로 다시 받는다. */
  const refresh = async () => {
    setBusy(true); setActionError(null)
    try { await post(`/api/refresh?symbol=${encodeURIComponent(symbol!)}`); reload(); await loadBacktest() }
    catch (e) { setActionError(String(e)) }
    finally { setBusy(false) }
  }

  // `/backtest`는 tickers 행이 없으면 404다. pending 중에 쏘면 수집이 끝나기도 전에
  // 백테스트 블록이 에러로 굳는다 — ready가 된 뒤에만 부른다.
  // deps는 `detail?.symbol`(TickerDetail.tsx와 동일)이어야 한다 — `symbol`(URL 파라미터)을
  // 쓰면 A(ready) → B로 라우팅되는 첫 렌더에서 status가 아직 A의 'ready'로 남아 있는 동안
  // symbol만 B로 바뀌어 effect가 발화한다. B가 미등록이면 아직 행이 없어 404가 뜬다.
  useEffect(() => { setBacktest(null); setBtError(null); setBtLoading(true) }, [symbol])
  useEffect(() => {
    if (status !== 'ready') return
    loadBacktest()
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
  const ccy = detail.currency
  const money = (n: number | null | undefined) => cur(ccy, n ?? null)
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
  const disc = backtest?.discrimination?.['20'] ?? null
  const stale = isStale(detail.last_refresh, now)
  const risk = detail.risk
  const plan = risk?.exit_plan ?? null
  const holdingSellSignal = !!plan && !!sig && dir(sig.swing_grade) < 0
  const win20 = gradeStat && gradeStat.insufficient20 !== true && typeof gradeStat.win20 === 'number'
    ? gradeStat.win20 : null

  const addRule = async () => {
    if (!ruleValue) return
    try {
      await post('/api/rules', { symbol, rule_type: ruleType, value: Number(ruleValue) })
      setRuleValue(''); setRuleMsg(null); reload()
    } catch (e) { setRuleMsg(String(e)) }
  }
  /** 손절가는 이미 계산돼 있다 — 손으로 옮겨 적게 두면 값이 틀리거나 등록을 건너뛴다.
   *  갱신 시 기존 STOP 룰을 지운다: 두 개가 남으면 어느 쪽이 울리는지 알 수 없다. */
  const registerStop = async () => {
    if (!risk) return
    try {
      for (const r of detail.rules.filter(r => r.rule_type === 'STOP')) await del(`/api/rules/${r.id}`)
      await post('/api/rules', { symbol, rule_type: 'STOP', value: risk.atr_stop_price })
      setRuleMsg(null); reload()
    } catch (e) { setRuleMsg(String(e)) }
  }

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
      {actionError &&
        <div className="quote-note" style={{ color: 'var(--sell)' }}>{actionError}</div>}

      {/* 판정을 뒤집는 사실은 판정과 같은 화면에 — 개요의 판정 한 줄이 여기로 넘어온 근거다 */}
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
        onClose={() => { setTradeOpen(null); setSellQuantity(null) }} onSaved={reload} />}

      <nav className="quote-tabs" aria-label="섹션">
        <Link className="quote-tab" to={`/ticker/${symbol}`}>← 개요</Link>
        {TABS.map(([id, label]) => (
          <button key={id} className={`quote-tab${tab === id ? ' active' : ''}`}
                  onClick={() => goTab(id)}>{label}</button>))}
      </nav>

      <div className="quote-grid">
        {/* ── 좌: 시그널 근거 + 백테스트 ── */}
        <div>
          <section className="quote-section" id="signal" style={{ marginTop: 0 }}>
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
            {sig && <div className="kv" style={{ marginTop: 10 }}>
              <div className="kv-row"><span className="k">스윙</span>
                <span className="v"><SignalBadge grade={sig.swing_grade} />
                  <small>{signed(sig.swing_score, 0)}점</small></span></div>
              <div className="kv-row"><span className="k">중장기</span>
                <span className="v"><SignalBadge grade={sig.longterm_grade} />
                  <small>{signed(sig.longterm_score, 0)}점{longtermUnverified ? ' · 미검증' : ''}</small></span></div>
            </div>}
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

        {/* ── 우: 포지션·리스크 / 룰 / 히스토리 ── */}
        <div>
          <section className="quote-section" id="position" style={{ marginTop: 0 }}>
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
                          del(`/api/rules/${r.id}`).then(reload)
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
            {detail.history.length === 0 && <div className="quote-note">기록된 등급 이력이 없습니다.</div>}
          </section>
        </div>
      </div>
    </div>
  )
}
