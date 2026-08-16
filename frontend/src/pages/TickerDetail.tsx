import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { createChart, CandlestickSeries, LineSeries, HistogramSeries, LineStyle, type IChartApi } from 'lightweight-charts'
import { del, get, post } from '../api'
import { isStale, relativeTime } from '../time'
import type { Backtest, TickerDetail as Detail } from '../types'
import SignalBadge from '../components/SignalBadge'
import ScoreBar from '../components/ScoreBar'
import TradeDialog from '../components/TradeDialog'
import BacktestTable from '../components/BacktestTable'

const CHART_OPTS = {
  layout: { background: { color: 'transparent' }, textColor: '#8b93a3' },
  grid: { vertLines: { color: '#232a36' }, horzLines: { color: '#232a36' } },
  timeScale: { borderColor: '#232a36' }, rightPriceScale: { borderColor: '#232a36' },
} as const

function useCandleChart(detail: Detail | null) {
  const mainRef = useRef<HTMLDivElement>(null)
  const rsiRef = useRef<HTMLDivElement>(null)
  const macdRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!detail || !mainRef.current || !rsiRef.current || !macdRef.current) return
    const charts: IChartApi[] = []
    const candles = detail.candles

    const main = createChart(mainRef.current, { ...CHART_OPTS, height: 360 })
    charts.push(main)
    main.addSeries(CandlestickSeries, {
      upColor: '#2ecc71', downColor: '#ff5252',
      wickUpColor: '#2ecc71', wickDownColor: '#ff5252', borderVisible: false,
    }).setData(candles.map(c => ({ time: c.date, open: c.open, high: c.high,
                                   low: c.low, close: c.close })))
    const lines: [keyof typeof candles[0], string, number][] = [
      ['sma20', '#f7c948', 1], ['sma60', '#4f8ef7', 1], ['sma120', '#b06ef7', 1],
    ]
    for (const [key, color, width] of lines) {
      main.addSeries(LineSeries, { color, lineWidth: width as 1 })
        .setData(candles.filter(c => c[key] !== null)
          .map(c => ({ time: c.date, value: c[key] as number })))
    }
    for (const key of ['bb_upper', 'bb_lower'] as const) {
      main.addSeries(LineSeries, { color: '#3a4356', lineWidth: 1 as const, lineStyle: LineStyle.Dashed })
        .setData(candles.filter(c => c[key] !== null)
          .map(c => ({ time: c.date, value: c[key] as number })))
    }
    main.timeScale().fitContent()

    const rsiChart = createChart(rsiRef.current, { ...CHART_OPTS, height: 120 })
    charts.push(rsiChart)
    const rsiSeries = rsiChart.addSeries(LineSeries, { color: '#f7c948', lineWidth: 1 as 1 })
    rsiSeries.setData(candles.filter(c => c.rsi !== null)
      .map(c => ({ time: c.date, value: c.rsi as number })))
    for (const price of [70, 30]) {
      rsiSeries.createPriceLine({ price, color: '#3a4356', lineStyle: LineStyle.Dashed, lineWidth: 1 })
    }
    rsiChart.timeScale().fitContent()

    const macdChart = createChart(macdRef.current, { ...CHART_OPTS, height: 120 })
    charts.push(macdChart)
    macdChart.addSeries(HistogramSeries, {})
      .setData(candles.filter(c => c.macd_hist !== null)
        .map(c => ({ time: c.date, value: c.macd_hist as number,
          color: (c.macd_hist as number) >= 0 ? 'rgba(46,204,113,.5)' : 'rgba(255,82,82,.5)' })))
    macdChart.addSeries(LineSeries, { color: '#4f8ef7', lineWidth: 1 as 1 })
      .setData(candles.filter(c => c.macd !== null)
        .map(c => ({ time: c.date, value: c.macd as number })))
    macdChart.addSeries(LineSeries, { color: '#ff8a65', lineWidth: 1 as 1 })
      .setData(candles.filter(c => c.macd_signal !== null)
        .map(c => ({ time: c.date, value: c.macd_signal as number })))
    macdChart.timeScale().fitContent()

    return () => charts.forEach(c => c.remove())
  }, [detail])
  return { mainRef, rsiRef, macdRef }
}

/** 등급의 방향만 뽑는다 (+1 매수 / 0 중립 / -1 매도). */
const dir = (grade: string) => grade.includes('매수') ? 1 : grade.includes('매도') ? -1 : 0

/** 행동 요약 최상단의 한 문장 판정.
 *
 *  이게 없으면 사용자가 손절가·목표가·수량·과거 성적·계좌 리스크 다섯 숫자와
 *  최대 일곱 종류의 경고를 매번 머릿속에서 합성해야 한다. 30초 판단이 성립하지 않는다.
 *  방향을 지시하는 게 아니라 **지금 이 화면에서 먼저 볼 것**을 가리킨다. */
function verdict(detail: Detail): { text: string; tone: 'buy' | 'sell' | 'flat' } {
  const sig = detail.signal
  const held = (detail.risk?.exit_plan?.held_quantity ?? 0) > 0
  const over = detail.risk?.account_open_risk?.over_limit
  const d = sig ? dir(sig.swing_grade) : 0
  if (held && d < 0)
    return { tone: 'sell', text: '보유 중인데 스윙 매도 신호입니다 — 추가 매수가 아니라 '
      + '아래 청산 플랜에서 얼마를 덜어낼지 먼저 정하세요.' }
  if (held && d > 0 && over)
    return { tone: 'sell', text: '매수 신호지만 계좌 총 미결 리스크가 상한을 넘었습니다 — '
      + '추가 매수 전에 다른 포지션 축소가 먼저입니다.' }
  if (held && d > 0)
    return { tone: 'buy', text: '보유 중이며 매수 신호가 유지됩니다 — 추가 매수는 아래 '
      + '제안 수량과 계좌 총 리스크 안에서만.' }
  if (held)
    return { tone: 'flat', text: '보유 중이나 뚜렷한 신호가 없습니다 — 새 판단보다 '
      + '손절선 유지가 할 일입니다.' }
  if (d > 0 && over)
    return { tone: 'sell', text: '매수 신호지만 계좌 총 미결 리스크가 이미 상한을 넘었습니다 — '
      + '신규 진입보다 기존 포지션 축소가 먼저입니다.' }
  if (d > 0)
    return { tone: 'buy', text: '신규 진입 후보입니다 — 아래 손절가를 먼저 정하고 '
      + '제안 수량을 넘기지 마세요.' }
  if (d < 0)
    return { tone: 'sell', text: '매도 신호이고 보유하지 않았습니다 — 지금 할 일은 없습니다.' }
  return { tone: 'flat', text: '뚜렷한 신호가 없습니다 — 관망 구간입니다.' }
}

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
  const [busy, setBusy] = useState(false)
  const [now, setNow] = useState(Date.now())
  const { mainRef, rsiRef, macdRef } = useCandleChart(detail)

  const load = () => get<Detail>(`/api/tickers/${symbol}`)
    .then(d => { setDetail(d); setError(null); setNow(Date.now()) })
    .catch(e => setError(String(e)))

  /** 이 종목만 갱신 — 전체 갱신은 수 초 걸린다. 백테스트도 새 봉으로 다시 받는다. */
  const refresh = async () => {
    setBusy(true)
    try {
      await post(`/api/refresh?symbol=${encodeURIComponent(symbol!)}`)
      await load()
      setBtLoading(true); setBtError(null)
      await get<Backtest>(`/api/tickers/${symbol}/backtest`)
        .then(setBacktest).catch(e => setBtError(String(e)))
        .finally(() => setBtLoading(false))
    } catch (e) { setError(String(e)) }
    finally { setBusy(false) }
  }
  useEffect(() => {
    load()
    setBacktest(null); setBtError(null); setBtLoading(true)
    // 백테스트 실패를 삼키면 카드가 조용히 사라진다. 백엔드는
    // "가격 데이터 부족 — 새로고침 후 다시 시도" 같은 행동 가능한 메시지를 준다.
    get<Backtest>(`/api/tickers/${symbol}/backtest`)
      .then(setBacktest).catch(e => setBtError(String(e)))
      .finally(() => setBtLoading(false))
  }, [symbol])

  if (error) return (
    <div className="card">
      <div style={{ color: 'var(--sell)' }}>불러오기 실패: {error}</div>
      <button style={{ marginTop: 10 }} onClick={() => { setError(null); load() }}>다시 시도</button>
    </div>
  )
  if (!detail) return (
    <div className="grid">
      <div className="card skeleton" style={{ minHeight: 120 }} />
      <div className="card skeleton" style={{ minHeight: 320 }} />
    </div>
  )
  const sig = detail.signal
  const last = detail.candles.at(-1)
  const unit = detail.currency === 'USD' ? '$' : '₩'
  // 현재 등급이 과거에 어떤 성적을 냈는지 — 등급 배지만으로는 그 등급을 믿을 근거가 없다
  const gradeStat = backtest?.grades.find(g => g.grade === sig?.swing_grade) ?? null
  // 중장기 등급이 통계적으로 뒷받침되는지 — 아니면 배지에 "미검증"을 붙인다
  const longtermStat = backtest?.longterm_grades.find(g => g.grade === sig?.longterm_grade) ?? null
  const longtermUnverified = !!backtest &&
    (!longtermStat || backtest.long_horizons.every(h => longtermStat[`insufficient${h}`] === true))
  const conflict = sig && dir(sig.swing_grade) !== 0 && dir(sig.longterm_grade) !== 0
    && dir(sig.swing_grade) !== dir(sig.longterm_grade)
  const hasStopRule = detail.rules.some(r => r.rule_type === 'STOP')
  const v = verdict(detail)
  const disc = backtest?.discrimination?.['20'] ?? null
  const stale = isStale(detail.last_refresh, now)
  const plan = detail.risk?.exit_plan ?? null
  // 보유 + 매도 신호에서 '추가 매수 가능'을 띄우는 것은 물타기 유도다 — 그 줄만 접는다
  const holdingSellSignal = !!plan && !!sig && dir(sig.swing_grade) < 0

  const addRule = async () => {
    if (!ruleValue) return
    try {
      await post('/api/rules', { symbol, rule_type: ruleType, value: Number(ruleValue) })
      setRuleValue(''); setRuleMsg(null); load()
    } catch (e) { setRuleMsg(String(e)) }
  }

  /** 손절가는 이 화면에서 이미 계산돼 있는데 룰 등록은 수동 재입력이었다.
   *  옮겨 적는 사이에 값이 틀리거나 아예 등록을 건너뛰게 된다. */
  const registerStop = async () => {
    if (!detail.risk) return
    try {
      await post('/api/rules', { symbol, rule_type: 'STOP', value: detail.risk.stop_price })
      setRuleMsg(null); load()
    } catch (e) { setRuleMsg(String(e)) }
  }

  return (
    <div className="grid">
      <div className="card" style={{ display: 'flex', justifyContent: 'space-between',
                                     alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2>{detail.name} <span style={{ color: 'var(--text-dim)', fontSize: 14 }}>
            {detail.symbol} · {detail.market}{detail.is_etf ? ' · ETF' : ''}
            {sig?.regime_label ? ` · ${sig.regime_label}` : ''}</span></h2>
          {last && <div style={{ fontSize: 22, fontWeight: 700 }}>
            {detail.currency === 'USD' ? '$' : '₩'}{last.close.toLocaleString('ko-KR')}</div>}
          {/* 장중 미완성 봉으로 계산된 등급은 마감 때 뒤집힌다. 백테스트가 검증한 것은
              확정 종가 신호이므로, 이 배지가 붙은 등급은 검증 밖에 있다. */}
          {sig?.bar_complete === false && <div className="warn" style={{ fontSize: 12, marginTop: 4 }}>
            ⚠ 미확정 — {sig.bar_date} 봉이 마감 전입니다. 종가 확정 시 등급이 바뀔 수 있고,
            백테스트는 확정 종가 신호만 검증했습니다.</div>}
        </div>
        <div style={{ display: 'flex', gap: 24, alignItems: 'center', flexWrap: 'wrap' }}>
          {sig && <>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>스윙</div>
              <SignalBadge grade={sig.swing_grade} />
              <ScoreBar score={sig.swing_score} label="스윙" />
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>중장기</div>
              <SignalBadge grade={sig.longterm_grade} />
              <ScoreBar score={sig.longterm_score} label="중장기" />
              {/* 검증된 신호와 검증 안 된 신호가 같은 시각적 무게로 놓이면 구분되지 않는다.
                  중장기는 60/120일 구간이라 3년 데이터로도 독립 표본이 모자란다. */}
              {longtermUnverified && <div className="warn" style={{ fontSize: 11 }}
                   title="60/120일 구간은 관측 기간이 만들 수 있는 독립 표본이 부족해 통계적으로 검증되지 않았습니다.">
                미검증</div>}
            </div>
          </>}
          {/* 갱신시각이 대시보드에만 있으면 이 화면의 가격이 언제 것인지 알 수 없다 */}
          <div style={{ textAlign: 'right' }}>
            <div className={stale ? 'warn' : ''} style={{ fontSize: 12,
                   color: stale ? undefined : 'var(--text-dim)' }}
                 title={detail.last_refresh ?? ''}>
              {stale && '⚠ '}기준: {relativeTime(detail.last_refresh, now)}</div>
            <div style={{ display: 'flex', gap: 8, marginTop: 6 }}>
              <button className="ghost" onClick={refresh} disabled={busy}>
                {busy ? '갱신 중…' : '새로고침'}</button>
              <button onClick={() => setTradeOpen(holdingSellSignal ? 'SELL' : 'BUY')}>매매 기록</button>
            </div>
          </div>
        </div>
      </div>

      {tradeOpen && <TradeDialog symbol={detail.symbol} name={detail.name}
        currency={detail.currency} defaultPrice={last?.close ?? null}
        defaultSide={tradeOpen}
        costRates={detail.cost_rates} exitPlan={detail.risk?.exit_plan}
        suggestedQuantity={detail.risk?.addable_quantity ?? detail.risk?.position_size_1pct}
        onClose={() => setTradeOpen(null)} onSaved={load} />}

      {/* 행동 요약 — 차트보다 위에 둔다. 차트 3개(600px)가 먼저 오면
          손절가·수량·과거 성적이 스크롤 아래로 밀려 "30초 판단"이 성립하지 않는다. */}
      <div className="card">
        <strong>행동 요약</strong>
        {/* 다섯 숫자와 일곱 경고를 사용자가 머릿속에서 합성하던 작업을 한 줄로 대신한다 */}
        <div style={{ marginTop: 8, padding: '10px 12px', borderRadius: 6,
                      background: 'var(--bg)', borderLeft: `3px solid ${
                        v.tone === 'buy' ? 'var(--buy)' : v.tone === 'sell' ? 'var(--sell)' : 'var(--border)'}`,
                      fontSize: 15, fontWeight: 600 }}>
          {v.text}
        </div>

        {/* 보유 중이면 나가는 쪽 숫자를 진입 숫자보다 먼저 놓는다. 매도 신호가 뜬
            종목에서 화면이 '추가 매수 가능 수량'만 보여주면 물타기를 권하는 꼴이 된다. */}
        {plan && <div style={{ marginTop: 12, padding: 12, borderRadius: 6,
                               border: '1px solid var(--border)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between',
                        flexWrap: 'wrap', gap: 8 }}>
            <strong>청산 플랜 — 보유 {plan.held_quantity.toLocaleString('ko-KR')}
              {/* +27%보다 +2.1R이 익절·추격 판단에 직접 닿는다 */}
              {plan.r_multiple !== null && <span className={plan.r_multiple >= 0 ? 'pos' : 'neg'}
                title={`1R = ${unit}${plan.r_unit?.toLocaleString('ko-KR')} (평단에서 손절선까지)`}>
                {' '}{plan.r_multiple >= 0 ? '+' : ''}{plan.r_multiple}R</span>}</strong>
            <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>
              평단 {unit}{plan.avg_price.toLocaleString('ko-KR')}</span>
          </div>
          <div style={{ display: 'flex', gap: 28, marginTop: 10, flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>평가손익</div>
              <div className={plan.unrealized_pnl_pct >= 0 ? 'pos' : 'neg'}
                   style={{ fontWeight: 700, fontSize: 18 }}>
                {plan.unrealized_pnl_pct >= 0 ? '+' : ''}{plan.unrealized_pnl_pct}%
                <span style={{ fontSize: 12 }}>
                  {' '}(₩{Math.round(plan.unrealized_pnl_krw).toLocaleString('ko-KR')})</span></div>
            </div>
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                {/* 손절선이 평단 위면 그 손절은 손실 확정이 아니라 이익 확정이다 */}
                {plan.stop_locks_profit ? '손절선 (이익 확정 구간)' : '손절선 (평단 대비)'}</div>
              <div style={{ fontWeight: 700, fontSize: 18,
                            color: plan.stop_locks_profit ? 'var(--buy)' : 'var(--sell)' }}>
                {plan.stop_from_avg_pct >= 0 ? '+' : ''}{plan.stop_from_avg_pct}%</div>
              <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                {plan.stop_locks_profit
                  ? `손절에 닿아도 평단 위에서 청산됩니다 · 여기서 ₩${Math.round(plan.risk_to_stop_krw).toLocaleString('ko-KR')} 되돌림`
                  : `여기서 손절까지 ₩${Math.round(plan.risk_to_stop_krw).toLocaleString('ko-KR')} 추가 손실`}</div>
            </div>
          </div>
          <table style={{ marginTop: 10 }}>
            <thead><tr><th>덜어낼 비중</th><th>수량</th><th>순회수액</th>
              <th>확정 손익</th></tr></thead>
            <tbody>
              {plan.slices.map(s => (
                <tr key={s.label}>
                  <td style={{ textAlign: 'left' }}>{s.label}</td>
                  <td>{s.quantity.toLocaleString('ko-KR')}</td>
                  <td>₩{Math.round(s.proceeds_krw).toLocaleString('ko-KR')}</td>
                  <td className={s.realized_pnl_krw >= 0 ? 'pos' : 'neg'}>
                    {s.realized_pnl_krw >= 0 ? '+' : ''}
                    ₩{Math.round(s.realized_pnl_krw).toLocaleString('ko-KR')}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 8 }}>
            회수액·손익은 매도 수수료·세금을 뺀 추정치이며 평단 기준입니다.
            {' '}실제 체결가는 호가에 따라 달라집니다.</div>
          <button style={{ marginTop: 10 }} onClick={() => setTradeOpen('SELL')}>매도 기록</button>
        </div>}

        {detail.risk ? (
          <div style={{ display: 'flex', gap: 32, marginTop: 10, flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>제안 손절가 (2×ATR)</div>
              <div style={{ fontWeight: 700, fontSize: 18, color: 'var(--sell)' }}>
                {unit}{detail.risk.stop_price.toLocaleString('ko-KR')}
                <span style={{ fontSize: 12 }}> ({detail.risk.stop_pct}%)</span></div>
            </div>
            {/* 손절가만 있고 목표가가 없으면 손익비를 모른 채 사이즈를 정하게 된다 */}
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                제안 목표가 (손익비 {detail.risk.target_r}:1)</div>
              <div style={{ fontWeight: 700, fontSize: 18, color: 'var(--buy)' }}>
                {unit}{detail.risk.target_price.toLocaleString('ko-KR')}
                <span style={{ fontSize: 12 }}> (+{detail.risk.target_pct}%)</span></div>
              {detail.risk.resistance_60d !== null && <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                60일 고점 {unit}{detail.risk.resistance_60d.toLocaleString('ko-KR')}
                {' '}(손익비 {detail.risk.resistance_reward_risk}:1)</div>}
            </div>
            {detail.risk.position_size_1pct !== null && !holdingSellSignal && <div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                제안 수량 (1% 리스크, 비중 {detail.risk.max_weight_pct}% 상한)</div>
              <div style={{ fontWeight: 700, fontSize: 18 }}>
                {detail.risk.position_size_1pct.toLocaleString('ko-KR')}
                <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
                  {' '}(리스크 ₩{detail.risk.risk_budget_krw?.toLocaleString('ko-KR')}
                  {detail.risk.position_notional_krw !== null &&
                    ` · 평가액 ₩${detail.risk.position_notional_krw.toLocaleString('ko-KR')}`})</span></div>
              {(detail.risk.held_quantity ?? 0) > 0 && <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                이미 {detail.risk.held_quantity?.toLocaleString('ko-KR')} 보유 →
                {' '}추가 매수 가능 <strong>{detail.risk.addable_quantity?.toLocaleString('ko-KR')}</strong></div>}
              {/* 소수점 주문이 안 되는 시장에서 5.095주를 제시하면 사용자가 매번
                  스스로 잘라야 하고, 그 과정에서 리스크 한도가 흐려진다 */}
              {detail.risk.lot_size === 1 && (detail.risk.position_size_raw ?? 0) > detail.risk.position_size_1pct &&
                <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                  1주 단위로 내림 (계산값 {detail.risk.position_size_raw?.toLocaleString('ko-KR')})</div>}
              {detail.risk.position_size_1pct === 0 && <div className="warn" style={{ fontSize: 11 }}>
                ⚠ 1% 리스크로는 1주도 살 수 없습니다 — 변동성 대비 계좌가 작습니다</div>}
              {/* 중소형주에서는 주문 크기 자체가 체결가를 밀어버린다. 반올림해서 0%가
                  되면 계산이 깨진 것처럼 보이므로 "미미함"으로 말한다. */}
              {detail.risk.liquidity_pct !== null && <div style={{ fontSize: 11,
                color: detail.risk.liquidity_pct >= 1 ? 'var(--warn)' : 'var(--text-dim)' }}>
                {detail.risk.liquidity_pct < 0.01
                  ? '일평균 거래대금 대비 0.01% 미만 — 체결 영향 미미'
                  : `일평균 거래대금의 ${detail.risk.liquidity_pct}%`}
                {detail.risk.liquidity_pct >= 1 && ' — 이 크기는 체결가를 밀 수 있습니다'}</div>}
            </div>}
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                이 등급의 과거 성적 (20일)
                {/* 승률 62%만 크게 보여주면 그 62%가 중립 등급 50%와 다를 게 없다는
                    사실, 나아가 매도 등급이 더 나았다는 사실이 아래 표 속에 묻힌다 */}
                {disc && !disc.discriminates && <span className="warn" title={
                  `매수 등급 ${disc.buy_net}% vs 매도 등급 ${disc.sell_net}% (20일 순수익)`}>
                  {' '}· ⚠ 등급이 방향을 못 가름 ({disc.spread}%p)</span>}
                {disc && disc.discriminates && <span style={{ color: 'var(--text-dim)' }} title={
                  `매수 등급 ${disc.buy_net}% vs 매도 등급 ${disc.sell_net}% (20일 순수익)`}>
                  {' '}· 판별력 +{disc.spread}%p</span>}</div>
              <div style={{ fontWeight: 700, fontSize: 18 }}>
                {gradeStat && gradeStat.insufficient20 !== true && typeof gradeStat.win20 === 'number'
                  ? <>승률 {gradeStat.win20}%
                      <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
                        {' '}(비용 차감 후) · 독립 표본 {gradeStat.episodes20}개</span></>
                  /* 아직 응답 전인 것과 검증해보니 표본이 없는 것은 전혀 다른 사실이다 */
                  : btLoading
                  ? <span style={{ color: 'var(--text-dim)', fontSize: 14 }}>불러오는 중…</span>
                  : btError
                  ? <span style={{ color: 'var(--text-dim)', fontSize: 14 }}>
                      백테스트를 불러오지 못했습니다</span>
                  : <span style={{ color: 'var(--text-dim)', fontSize: 14 }}>
                      표본 부족 — 이 등급은 판단 근거로 쓰기에 관측이 부족합니다</span>}</div>
            </div>
            <div style={{ alignSelf: 'center' }}>
              <button className="ghost" onClick={registerStop} disabled={hasStopRule}>
                {hasStopRule ? '손절 룰 등록됨' : '손절가를 룰로 등록'}</button>
            </div>
          </div>
        ) : <div style={{ color: 'var(--text-dim)', marginTop: 8 }}>
          ATR 계산에 필요한 가격 데이터가 부족합니다 — 새로고침 후 다시 확인하세요.</div>}

        {/* 상한이 걸렸다는 사실 자체가 리스크 정보다 — 잘리지 않은 1% 룰 수량은
            저변동성 구간에서 계좌 전액을 넘길 수 있다. */}
        {detail.risk?.position_size_capped && <div className="warn-box" style={{ marginTop: 12 }}>
          ⚠ {detail.risk.cap_reason}</div>}
        {/* -21% 손절을 제시하면 실제로 그걸 지키는 사람은 없고 손절 없는 매매가 된다 */}
        {detail.risk?.stop_too_wide && <div className="warn-box" style={{ marginTop: 12 }}>
          ⚠ 2×ATR 손절폭이 {Math.abs(detail.risk.stop_pct)}%로 스윙 타임프레임에 과대합니다
          (기준 {detail.risk.max_stop_pct}%). 이 폭을 실제로 견딜 수 있는지 먼저 판단하세요 —
          못 지킬 손절은 없는 손절과 같습니다. 더 긴 보유 기간을 전제하거나 종목을 거르는 편이 낫습니다.</div>}
        {/* 목표가가 매물대 위면 그 구간을 뚫어야 도달한다 — 손익비가 종이 위에서만 성립한다 */}
        {detail.risk?.target_above_resistance && <div className="warn-box" style={{ marginTop: 12 }}>
          ⚠ 목표가가 60일 고점({unit}{detail.risk.resistance_60d?.toLocaleString('ko-KR')}) 위입니다 —
          그 매물대를 뚫어야 도달합니다. 고점까지만 보면 손익비는
          {' '}{detail.risk.resistance_reward_risk}:1입니다.</div>}
        {detail.risk?.account_open_risk && <div style={{
          marginTop: 12, fontSize: 13,
          color: detail.risk.account_open_risk.over_limit ? 'var(--sell)' : 'var(--text-dim)' }}>
          현재 계좌 총 미결 리스크 <strong>{detail.risk.account_open_risk.total_risk_pct}%</strong>
          {' '}/ 상한 {detail.risk.account_open_risk.limit_pct}%
          {detail.risk.account_open_risk.over_limit && ' — 신규 진입 전에 기존 포지션 축소를 먼저 검토하세요'}</div>}

        {conflict && sig && <div className="warn-box" style={{ marginTop: 12 }}>
          ⚠ 스윙 {sig.swing_grade} · 중장기 {sig.longterm_grade} — 방향이 엇갈립니다.
          어느 쪽을 따를지가 아니라 <strong>보유 기간을 먼저 정하고</strong> 그에 맞는 쪽을 보세요.</div>}
        {sig?.context_note && <div style={{ color: 'var(--accent)', fontSize: 13, marginTop: 10 }}>
          💡 {sig.context_note}</div>}
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 10 }}>
          2×ATR 손절 기준 총자산의 1%만 잃는 수량이되, 한 종목이 총자산의
          {' '}{detail.risk?.max_weight_pct ?? 20}%를 넘지 않도록 상한을 겁니다. 진입 전 손절가를 먼저 정하세요.
          {' '}손절가는 자동 예약주문이 아니며 갭 하락 시 계획보다 더 잃을 수 있습니다.
          <br />지표 기반 참고 정보이며 투자 자문이 아닙니다. 최종 판단과 책임은 본인에게 있습니다.</div>
        {ruleMsg && <div style={{ color: 'var(--sell)', fontSize: 12, marginTop: 8 }}>{ruleMsg}</div>}
      </div>

      {sig && <div className="card">
        <strong>시그널 근거</strong>
        <p style={{ margin: '8px 0', color: 'var(--text-dim)' }}>{sig.summary}</p>
        <div className="table-scroll">
        <table>
          <thead><tr><th>지표</th><th>관점</th><th>점수</th><th style={{ textAlign: 'left' }}>근거</th></tr></thead>
          <tbody>
            {sig.indicator_scores.map((s, i) => (
              <tr key={i}>
                <td>{s.name}</td>
                <td>{s.scope === 'swing' ? '스윙' : '중장기'}</td>
                <td><ScoreBar score={s.score} label={s.name} /></td>
                <td style={{ textAlign: 'left' }}>{s.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>}

      <div className="card">
        {detail.risk && <div style={{ color: 'var(--text-dim)', fontSize: 12, marginBottom: 10 }}>
          ATR(14) {detail.risk.atr.toLocaleString('ko-KR')} ({detail.risk.atr_pct}%)
          {' · '}최대 낙폭(400일) {detail.risk.mdd_pct}%</div>}
        <div ref={mainRef} />
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 12 }}>RSI (14)</div>
        <div ref={rsiRef} />
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 12 }}>MACD (12,26,9)</div>
        <div ref={macdRef} />
      </div>

      {/* 자리표시가 없으면 카드가 통째로 없는 것으로 보여 "이 종목엔 백테스트가 없다"로 읽힌다 */}
      {btLoading && <div className="card">
        <strong>시그널 백테스트</strong>
        <div style={{ color: 'var(--text-dim)', fontSize: 13, marginTop: 8 }}>
          등급별 과거 성적을 계산하는 중입니다…</div>
        <div className="skeleton" style={{ height: 120, marginTop: 10 }} />
      </div>}

      {btError && <div className="card">
        <strong>시그널 백테스트</strong>
        <div className="warn-box" style={{ marginTop: 8 }}>불러오지 못했습니다: {btError}</div>
      </div>}

      {backtest && <div className="card">
        <strong>시그널 백테스트</strong>
        <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
          {' '}{backtest.start} ~ {backtest.end} · 신호일 {backtest.samples}일
          {backtest.bench_label && ` · 초과수익 = ${backtest.bench_label} 대비`}</span>
        {/* 검증한 전략과 실행하는 전략이 같아야 이 숫자에 의미가 있다.
            진입가·청산 규칙을 눈에 보이게 적어두는 것이 그 약속이다. */}
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 6 }}>
          진입 {backtest.entry_rule} · 청산 {backtest.exit_rule} ·
          {' '}순·승률은 왕복 비용 {backtest.cost_pct}%p 차감 후 기준
          {/* 비용이 무엇을 포함하는지 밝히지 않으면 5일 +0.3%대 엣지가 실집행에서
              사라질 수 있다는 사실이 화면 어디에도 없다 */}
          <br />{backtest.cost_breakdown.note} 각 칸의 <strong>스트레스</strong> 값이
          {' '}비용 {backtest.cost_breakdown.stress_pct}%p 가정 결과이며, 여기서
          {' '}마이너스면 그 엣지는 실집행에서 사라질 수 있습니다.
          <br />±1σ는 <strong>비중첩 에피소드</strong> 기준 표준오차입니다 — 인접일 신호는 구간이
          겹쳐 독립 표본이 아니므로, 신호일 수로 계산한 오차는 실제보다 작게 나옵니다.
          독립 표본 {backtest.min_episodes}개 미만인 칸은 수치를 감춥니다.
        </div>
        <BacktestTable bt={backtest} grades={backtest.grades} horizons={backtest.horizons}
                       missing={backtest.missing_grades} caption="스윙 등급" />
        <BacktestTable bt={backtest} grades={backtest.longterm_grades}
                       horizons={backtest.long_horizons}
                       missing={backtest.missing_longterm_grades}
                       caption="중장기 등급 — 보유 기간이 길어 독립 표본이 훨씬 적습니다" />
      </div>}

      <div className="grid-2">
        <div className="card">
          <strong>펀더멘털 (참고)</strong>
          {detail.fundamentals ? (
            <table><tbody>
              <tr><td style={{ textAlign: 'left' }}>PER</td>
                  <td>{detail.fundamentals.per?.toFixed(1) ?? '—'}</td></tr>
              <tr><td style={{ textAlign: 'left' }}>PBR</td>
                  <td>{detail.fundamentals.pbr?.toFixed(2) ?? '—'}</td></tr>
              <tr><td style={{ textAlign: 'left' }}>배당수익률</td>
                  <td>{detail.fundamentals.dividend_yield ?? '—'}%</td></tr>
              <tr><td style={{ textAlign: 'left' }}>시가총액</td>
                  <td>{detail.fundamentals.market_cap
                    ? (detail.fundamentals.market_cap / 1e12).toFixed(2) + '조' : '—'}</td></tr>
            </tbody></table>
          ) : <div style={{ color: 'var(--text-dim)', marginTop: 8 }}>정보 없음</div>}
        </div>
        <div className="card">
          <strong>커스텀 룰</strong>
          {detail.rules.length === 0 && <div className="empty" style={{ padding: '14px 0' }}>
            등록된 룰이 없습니다. 목표가·손절가를 걸어두면 도달 시 알림을 받습니다.</div>}
          {detail.rules.map(r => (
            <div key={r.id} style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
              <span>{{ TARGET: '목표가', STOP: '손절가', AVG_PCT: '평단 대비 %' }[r.rule_type]}
                {' '}{r.value.toLocaleString('ko-KR')}</span>
              <button className="ghost" onClick={() => {
                const label = { TARGET: '목표가', STOP: '손절가', AVG_PCT: '평단 대비 %' }[r.rule_type]
                if (confirm(`${label} ${r.value.toLocaleString('ko-KR')} 룰을 삭제합니다.`
                  + (r.rule_type === 'STOP' ? '\n손절 알림이 더 이상 오지 않습니다.' : '')))
                  del(`/api/rules/${r.id}`).then(load)
              }}>삭제</button>
            </div>
          ))}
          <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
            <select value={ruleType} onChange={e => setRuleType(e.target.value)}>
              <option value="TARGET">목표가</option>
              <option value="STOP">손절가</option>
              <option value="AVG_PCT">평단 대비 %</option>
            </select>
            <input type="number" placeholder="값" value={ruleValue}
                   onChange={e => setRuleValue(e.target.value)} style={{ width: 120 }} />
            <button onClick={addRule}>추가</button>
          </div>
        </div>
      </div>

      <div className="card">
        <strong>시그널 히스토리</strong>
        <div className="table-scroll">
        <table>
          <thead><tr><th>날짜</th><th>스윙 점수</th><th>중장기 점수</th><th>등급</th></tr></thead>
          <tbody>
            {detail.history.slice(0, 20).map(h => (
              <tr key={h.date}>
                <td style={{ textAlign: 'left' }}>{h.date}</td>
                <td>{h.swing_score.toFixed(0)}</td>
                <td>{h.longterm_score.toFixed(0)}</td>
                <td><SignalBadge grade={h.grade} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>
    </div>
  )
}
