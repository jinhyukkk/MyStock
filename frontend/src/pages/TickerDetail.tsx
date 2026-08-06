import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { createChart, CandlestickSeries, LineSeries, HistogramSeries, LineStyle, type IChartApi } from 'lightweight-charts'
import { del, get, post } from '../api'
import type { TickerDetail as Detail } from '../types'
import SignalBadge from '../components/SignalBadge'
import ScoreBar from '../components/ScoreBar'

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

export default function TickerDetail() {
  const { symbol } = useParams()
  const [detail, setDetail] = useState<Detail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ruleType, setRuleType] = useState('TARGET')
  const [ruleValue, setRuleValue] = useState('')
  const { mainRef, rsiRef, macdRef } = useCandleChart(detail)

  const load = () => get<Detail>(`/api/tickers/${symbol}`)
    .then(setDetail).catch(e => setError(String(e)))
  useEffect(() => { load() }, [symbol])

  if (error) return <div className="card">불러오기 실패: {error}</div>
  if (!detail) return (
    <div className="grid">
      <div className="card skeleton" style={{ minHeight: 120 }} />
      <div className="card skeleton" style={{ minHeight: 320 }} />
    </div>
  )
  const sig = detail.signal
  const last = detail.candles.at(-1)

  const addRule = async () => {
    if (!ruleValue) return
    await post('/api/rules', { symbol, rule_type: ruleType, value: Number(ruleValue) })
    setRuleValue(''); load()
  }

  return (
    <div className="grid">
      <div className="card" style={{ display: 'flex', justifyContent: 'space-between',
                                     alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2>{detail.name} <span style={{ color: 'var(--text-dim)', fontSize: 14 }}>
            {detail.symbol} · {detail.market}{detail.is_etf ? ' · ETF' : ''}</span></h2>
          {last && <div style={{ fontSize: 22, fontWeight: 700 }}>
            {last.close.toLocaleString('ko-KR')}</div>}
        </div>
        {sig && <div style={{ display: 'flex', gap: 24 }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>스윙</div>
            <SignalBadge grade={sig.swing_grade} />
            <ScoreBar score={sig.swing_score} />
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>중장기</div>
            <SignalBadge grade={sig.longterm_grade} />
            <ScoreBar score={sig.longterm_score} />
          </div>
        </div>}
      </div>

      {sig?.context_note && <div className="card" style={{ color: 'var(--accent)' }}>
        💡 {sig.context_note}</div>}

      <div className="card">
        <div ref={mainRef} />
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 12 }}>RSI (14)</div>
        <div ref={rsiRef} />
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 12 }}>MACD (12,26,9)</div>
        <div ref={macdRef} />
      </div>

      {sig && <div className="card">
        <strong>시그널 근거</strong>
        <p style={{ margin: '8px 0', color: 'var(--text-dim)' }}>{sig.summary}</p>
        <table>
          <thead><tr><th>지표</th><th>관점</th><th>점수</th><th style={{ textAlign: 'left' }}>근거</th></tr></thead>
          <tbody>
            {sig.indicator_scores.map((s, i) => (
              <tr key={i}>
                <td>{s.name}</td>
                <td>{s.scope === 'swing' ? '스윙' : '중장기'}</td>
                <td><ScoreBar score={s.score} /></td>
                <td style={{ textAlign: 'left' }}>{s.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>}

      <div className="grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
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
          {detail.rules.map(r => (
            <div key={r.id} style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8 }}>
              <span>{{ TARGET: '목표가', STOP: '손절가', AVG_PCT: '평단 대비 %' }[r.rule_type]}
                {' '}{r.value.toLocaleString('ko-KR')}</span>
              <button className="ghost" onClick={() => del(`/api/rules/${r.id}`).then(load)}>삭제</button>
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
  )
}
