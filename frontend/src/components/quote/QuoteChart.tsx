import { useEffect, useRef, useState } from 'react'
import { createChart, CandlestickSeries, LineSeries, HistogramSeries, LineStyle,
         type IChartApi } from 'lightweight-charts'
import type { Candle } from '../../types'

const CHART_OPTS = {
  // 컨테이너 폭이 잡히기 전에 createChart가 돌면 캔버스가 기본 300px로 굳는다(빌드본에서
  // 재현). autoSize는 ResizeObserver로 컨테이너를 따라가므로 첫 레이아웃·창 크기 변경 모두 안전.
  // 단 컨테이너 높이는 CSS(.quote-chart-main)로 반드시 고정해야 한다 —
  // auto면 차트가 자기 높이를 다시 재는 루프가 되어 아래로 끝없이 늘어난다. 아래 height
  // 옵션은 ResizeObserver가 없을 때만 쓰이는 폴백이라 CSS 값과 같게 유지한다.
  autoSize: true,
  layout: { background: { color: 'transparent' }, textColor: '#8b93a3', fontSize: 11 },
  grid: { vertLines: { color: '#1c2230' }, horzLines: { color: '#1c2230' } },
  timeScale: { borderColor: '#232a36' },
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
  const chartsRef = useRef<IChartApi[]>([])
  const [tf, setTf] = useState<number | null>(132)
  const levelsKey = JSON.stringify(levels)

  useEffect(() => {
    if (!mainRef.current || candles.length === 0) return
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

    chartsRef.current = charts
    applyTimeframe(charts, candles.length, tf)
    return () => { charts.forEach(c => c.remove()); chartsRef.current = [] }
    // tf는 아래 effect가 따로 적용한다 — 버튼마다 차트를 다시 만들 이유가 없다.
    // levels는 부모가 렌더마다 새 배열로 넘기므로 내용 키로 비교한다 — 참조로 비교하면
    // 회사 자료 도착·탭 변경 같은 무관한 렌더에도 차트가 통째로 다시 만들어진다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candles, levelsKey])

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
      <div className="quote-chart-main" ref={mainRef} />
    </div>
  )
}

function applyTimeframe(charts: IChartApi[], total: number, bars: number | null) {
  if (charts.length === 0 || total === 0) return
  const main = charts[0]
  if (bars === null) main.timeScale().fitContent()
  else main.timeScale().setVisibleLogicalRange({ from: Math.max(0, total - bars), to: total + 1 })
}
