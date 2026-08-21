import { useEffect, useRef, useState } from 'react'
import { createChart, CandlestickSeries, LineSeries, HistogramSeries, LineStyle,
         type IChartApi, type LogicalRange } from 'lightweight-charts'
import type { Candle } from '../../types'

const CHART_OPTS = {
  layout: { background: { color: 'transparent' }, textColor: '#8b93a3', fontSize: 11 },
  grid: { vertLines: { color: '#1c2230' }, horzLines: { color: '#1c2230' } },
  timeScale: { borderColor: '#232a36' },
  // 세 패널의 가격축 폭을 같게 — 폭이 다르면 같은 범위를 보여도 봉의 x좌표가 어긋난다
  rightPriceScale: { borderColor: '#232a36', minimumWidth: 84 },
} as const

/** finviz 차트 상단의 기간 버튼. 값은 보여줄 봉 수(null = 전체). */
const TIMEFRAMES: [string, number | null][] = [
  ['1M', 22], ['3M', 66], ['6M', 132], ['1Y', 252], ['전체', null],
]

/** 차트에 수평선으로 얹는 기준가 — 손절·목표·평단. 가격축에 붙어 있어야
 *  "지금 어디쯤인가"를 표에서 숫자를 찾지 않고 읽는다. */
export interface PriceLevel { price: number; label: string; color: string }

export default function QuoteChart({ candles, levels }: { candles: Candle[]; levels: PriceLevel[] }) {
  const mainRef = useRef<HTMLDivElement>(null)
  const rsiRef = useRef<HTMLDivElement>(null)
  const macdRef = useRef<HTMLDivElement>(null)
  const chartsRef = useRef<IChartApi[]>([])
  const [tf, setTf] = useState<number | null>(132)

  useEffect(() => {
    if (!mainRef.current || !rsiRef.current || !macdRef.current || candles.length === 0) return
    const charts: IChartApi[] = []

    const main = createChart(mainRef.current, { ...CHART_OPTS, height: 380 })
    charts.push(main)
    const candleSeries = main.addSeries(CandlestickSeries, {
      upColor: '#2ecc71', downColor: '#ff5252',
      wickUpColor: '#2ecc71', wickDownColor: '#ff5252', borderVisible: false,
    })
    candleSeries.setData(candles.map(c => ({ time: c.date, open: c.open, high: c.high,
                                             low: c.low, close: c.close })))
    // 거래량은 메인 패널 하단 20%에 겹쳐 그린다 (finviz와 같은 자리)
    main.addSeries(HistogramSeries, { priceScaleId: 'vol', priceFormat: { type: 'volume' } })
      .setData(candles.map(c => ({ time: c.date, value: c.volume,
        color: c.close >= c.open ? 'rgba(46,204,113,.28)' : 'rgba(255,82,82,.28)' })))
    main.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 }, visible: false })

    const lines: [keyof Candle, string][] = [['sma20', '#f7c948'], ['sma60', '#4f8ef7'], ['sma120', '#b06ef7']]
    for (const [key, color] of lines) {
      main.addSeries(LineSeries, { color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
        .setData(candles.filter(c => c[key] !== null).map(c => ({ time: c.date, value: c[key] as number })))
    }
    for (const key of ['bb_upper', 'bb_lower'] as const) {
      main.addSeries(LineSeries, { color: '#3a4356', lineWidth: 1, lineStyle: LineStyle.Dashed,
                                   priceLineVisible: false, lastValueVisible: false })
        .setData(candles.filter(c => c[key] !== null).map(c => ({ time: c.date, value: c[key] as number })))
    }
    for (const lv of levels) {
      candleSeries.createPriceLine({ price: lv.price, color: lv.color, lineWidth: 1,
                                     lineStyle: LineStyle.Dotted, title: lv.label })
    }

    const rsiChart = createChart(rsiRef.current, { ...CHART_OPTS, height: 100 })
    charts.push(rsiChart)
    const rsiSeries = rsiChart.addSeries(LineSeries, { color: '#f7c948', lineWidth: 1 })
    rsiSeries.setData(candles.filter(c => c.rsi !== null).map(c => ({ time: c.date, value: c.rsi as number })))
    for (const price of [70, 30])
      rsiSeries.createPriceLine({ price, color: '#3a4356', lineStyle: LineStyle.Dashed, lineWidth: 1 })

    const macdChart = createChart(macdRef.current, { ...CHART_OPTS, height: 100 })
    charts.push(macdChart)
    // 우측 끝 값 라벨 세 개가 겹친다 — MACD 선 하나만 남긴다
    macdChart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false })
      .setData(candles.filter(c => c.macd_hist !== null).map(c => ({ time: c.date, value: c.macd_hist as number,
        color: (c.macd_hist as number) >= 0 ? 'rgba(46,204,113,.5)' : 'rgba(255,82,82,.5)' })))
    macdChart.addSeries(LineSeries, { color: '#4f8ef7', lineWidth: 1 })
      .setData(candles.filter(c => c.macd !== null).map(c => ({ time: c.date, value: c.macd as number })))
    macdChart.addSeries(LineSeries, { color: '#ff8a65', lineWidth: 1, priceLineVisible: false, lastValueVisible: false })
      .setData(candles.filter(c => c.macd_signal !== null).map(c => ({ time: c.date, value: c.macd_signal as number })))

    // 세 패널의 시간축을 묶는다 — 따로 놀면 RSI 70 돌파일이 어느 봉인지 맞춰볼 수 없다
    let syncing = false
    for (const c of charts) {
      c.timeScale().subscribeVisibleLogicalRangeChange((range: LogicalRange | null) => {
        if (syncing || !range) return
        syncing = true
        for (const o of charts) if (o !== c) o.timeScale().setVisibleLogicalRange(range)
        syncing = false
      })
    }
    chartsRef.current = charts
    applyTimeframe(charts, candles.length, tf)
    return () => { charts.forEach(c => c.remove()); chartsRef.current = [] }
    // tf는 아래 effect가 따로 적용한다 — 버튼마다 차트를 다시 만들 이유가 없다
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candles, levels])

  useEffect(() => { applyTimeframe(chartsRef.current, candles.length, tf) }, [tf, candles.length])

  return (
    <div>
      <div className="quote-chart-bar">
        {TIMEFRAMES.map(([label, n]) => (
          <button key={label} className={`tf-btn${tf === n ? ' on' : ''}`}
                  onClick={() => setTf(n)}>{label}</button>))}
        <span className="sep" />
        <div className="chart-legend">
          <span><i style={{ background: '#f7c948' }} />SMA20</span>
          <span><i style={{ background: '#4f8ef7' }} />SMA60</span>
          <span><i style={{ background: '#b06ef7' }} />SMA120</span>
          <span><i style={{ background: '#3a4356' }} />BB(20,2)</span>
          {levels.map(l => <span key={l.label}><i style={{ background: l.color }} />{l.label}</span>)}
        </div>
      </div>
      <div ref={mainRef} />
      <div className="chart-sub-label">RSI (14)</div>
      <div ref={rsiRef} />
      <div className="chart-sub-label">MACD (12,26,9)</div>
      <div ref={macdRef} />
    </div>
  )
}

function applyTimeframe(charts: IChartApi[], total: number, bars: number | null) {
  if (charts.length === 0 || total === 0) return
  const main = charts[0]
  if (bars === null) main.timeScale().fitContent()
  else main.timeScale().setVisibleLogicalRange({ from: Math.max(0, total - bars), to: total + 1 })
}
