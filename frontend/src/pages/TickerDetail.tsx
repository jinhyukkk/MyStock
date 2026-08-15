import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { createChart, CandlestickSeries, LineSeries, HistogramSeries, LineStyle, type IChartApi } from 'lightweight-charts'
import { del, get, post } from '../api'
import type { Backtest, TickerDetail as Detail } from '../types'
import SignalBadge from '../components/SignalBadge'
import ScoreBar from '../components/ScoreBar'
import TradeDialog from '../components/TradeDialog'

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

export default function TickerDetail() {
  const { symbol } = useParams()
  const [detail, setDetail] = useState<Detail | null>(null)
  const [backtest, setBacktest] = useState<Backtest | null>(null)
  const [btError, setBtError] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ruleType, setRuleType] = useState('TARGET')
  const [ruleValue, setRuleValue] = useState('')
  const [ruleMsg, setRuleMsg] = useState<string | null>(null)
  const [tradeOpen, setTradeOpen] = useState(false)
  const { mainRef, rsiRef, macdRef } = useCandleChart(detail)

  const load = () => get<Detail>(`/api/tickers/${symbol}`)
    .then(d => { setDetail(d); setError(null) }).catch(e => setError(String(e)))
  useEffect(() => {
    load()
    setBacktest(null); setBtError(null)
    // 백테스트 실패를 삼키면 카드가 조용히 사라진다. 백엔드는
    // "가격 데이터 부족 — 새로고침 후 다시 시도" 같은 행동 가능한 메시지를 준다.
    get<Backtest>(`/api/tickers/${symbol}/backtest`)
      .then(setBacktest).catch(e => setBtError(String(e)))
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
  const conflict = sig && dir(sig.swing_grade) !== 0 && dir(sig.longterm_grade) !== 0
    && dir(sig.swing_grade) !== dir(sig.longterm_grade)
  const hasStopRule = detail.rules.some(r => r.rule_type === 'STOP')

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
            </div>
          </>}
          <button onClick={() => setTradeOpen(true)}>매매 기록</button>
        </div>
      </div>

      {tradeOpen && <TradeDialog symbol={detail.symbol} name={detail.name}
        currency={detail.currency} defaultPrice={last?.close ?? null}
        onClose={() => setTradeOpen(false)} onSaved={load} />}

      {/* 행동 요약 — 차트보다 위에 둔다. 차트 3개(600px)가 먼저 오면
          손절가·수량·과거 성적이 스크롤 아래로 밀려 "30초 판단"이 성립하지 않는다. */}
      <div className="card">
        <strong>행동 요약</strong>
        {detail.risk ? (
          <div style={{ display: 'flex', gap: 32, marginTop: 10, flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>제안 손절가 (2×ATR)</div>
              <div style={{ fontWeight: 700, fontSize: 18, color: 'var(--sell)' }}>
                {unit}{detail.risk.stop_price.toLocaleString('ko-KR')}
                <span style={{ fontSize: 12 }}> ({detail.risk.stop_pct}%)</span></div>
            </div>
            {detail.risk.position_size_1pct !== null && <div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>계좌 1% 리스크 수량</div>
              <div style={{ fontWeight: 700, fontSize: 18 }}>
                {detail.risk.position_size_1pct.toLocaleString('ko-KR')}
                <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
                  {' '}(리스크 ₩{detail.risk.risk_budget_krw?.toLocaleString('ko-KR')})</span></div>
            </div>}
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                이 등급의 과거 성적 (20일)</div>
              <div style={{ fontWeight: 700, fontSize: 18 }}>
                {gradeStat && gradeStat.win20 !== null
                  ? <>승률 {gradeStat.win20}%
                      <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
                        {' '}· 표본 {gradeStat.n}일</span></>
                  : <span style={{ color: 'var(--text-dim)', fontSize: 14 }}>표본 없음</span>}</div>
            </div>
            <div style={{ alignSelf: 'center' }}>
              <button className="ghost" onClick={registerStop} disabled={hasStopRule}>
                {hasStopRule ? '손절 룰 등록됨' : '손절가를 룰로 등록'}</button>
            </div>
          </div>
        ) : <div style={{ color: 'var(--text-dim)', marginTop: 8 }}>
          ATR 계산에 필요한 가격 데이터가 부족합니다 — 새로고침 후 다시 확인하세요.</div>}

        {conflict && sig && <div className="warn-box" style={{ marginTop: 12 }}>
          ⚠ 스윙 {sig.swing_grade} · 중장기 {sig.longterm_grade} — 방향이 엇갈립니다.
          어느 쪽을 따를지가 아니라 <strong>보유 기간을 먼저 정하고</strong> 그에 맞는 쪽을 보세요.</div>}
        {sig?.context_note && <div style={{ color: 'var(--accent)', fontSize: 13, marginTop: 10 }}>
          💡 {sig.context_note}</div>}
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 10 }}>
          2×ATR 손절 기준, 총자산(평가액+예수금)의 1%만 잃는 수량. 진입 전 손절가를 먼저 정하세요.
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

      {btError && <div className="card">
        <strong>시그널 백테스트</strong>
        <div className="warn-box" style={{ marginTop: 8 }}>불러오지 못했습니다: {btError}</div>
      </div>}

      {backtest && <div className="card">
        <strong>시그널 백테스트</strong>
        <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
          {' '}{backtest.start} ~ {backtest.end} · 표본 {backtest.samples}일 · 현재 스코어링 로직을 과거에 적용한 결과
          {backtest.bench_label && ` · 초과수익 = ${backtest.bench_label} 대비`}
          {` · 순 = 왕복 비용 ${backtest.cost_pct}%p 차감 · 인접일 표본 중첩(자기상관)으로 실제 독립 표본은 더 적음`}</span>
        <div className="table-scroll" style={{ marginTop: 8 }}>
        <table>
          <thead><tr><th>등급</th><th>신호 일수</th><th>5일 평균</th><th>5일 승률</th>
            <th>20일 평균</th><th>20일 승률</th>
            {backtest.bench_label && <><th>5일 초과</th><th>20일 초과</th></>}</tr></thead>
          <tbody>
            {backtest.grades.map(g => (
              <tr key={g.grade}>
                <td><SignalBadge grade={g.grade} /></td>
                <td>{g.n}</td>
                <td className={(g.avg_fwd5 ?? 0) >= 0 ? 'pos' : 'neg'}>
                  {g.avg_fwd5 === null ? '—' : `${g.avg_fwd5 >= 0 ? '+' : ''}${g.avg_fwd5}%`}
                  {g.avg_net5 !== null && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
                    {' '}(순 {g.avg_net5 >= 0 ? '+' : ''}{g.avg_net5}%)</span>}</td>
                <td>{g.win5 === null ? '—' : `${g.win5}%`}</td>
                <td className={(g.avg_fwd20 ?? 0) >= 0 ? 'pos' : 'neg'}>
                  {g.avg_fwd20 === null ? '—' : `${g.avg_fwd20 >= 0 ? '+' : ''}${g.avg_fwd20}%`}
                  {g.avg_net20 !== null && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
                    {' '}(순 {g.avg_net20 >= 0 ? '+' : ''}{g.avg_net20}%)</span>}</td>
                <td>{g.win20 === null ? '—' : `${g.win20}%`}</td>
                {backtest.bench_label && <>
                  <td className={(g.avg_excess5 ?? 0) >= 0 ? 'pos' : 'neg'}>
                    {g.avg_excess5 == null ? '—' : `${g.avg_excess5 >= 0 ? '+' : ''}${g.avg_excess5}%p`}</td>
                  <td className={(g.avg_excess20 ?? 0) >= 0 ? 'pos' : 'neg'}>
                    {g.avg_excess20 == null ? '—' : `${g.avg_excess20 >= 0 ? '+' : ''}${g.avg_excess20}%p`}</td>
                </>}
              </tr>
            ))}
          </tbody>
        </table>
        </div>
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
