import type { IndexRow } from './types'

const W = 340, H = 170
// 가격 영역과 거래량 영역을 세로로 나눈다. finviz는 거래량이 차트 하단 1/4쯤.
const PAD = { top: 26, right: 46, bottom: 22, left: 30 }
const PRICE_H = 88, VOL_H = 30
const TIMES = ['10AM', '11AM', '12PM', '1PM', '2PM', '3PM', '4PM']

/** finviz 홈 상단 지수 미니 차트 — 5분봉 캔들 + 거래량 + 우측 가격축 + 마지막가 라벨. */
export default function IndexChart({ data, asOf }: { data: IndexRow; asOf: string | null }) {
  // 값이 빠진 봉(거래 정지 등)은 그리지 않는다 — NaN 좌표가 하나 있으면 SVG 전체가 안 그려진다
  const cs = data.candles.filter((c): c is { o: number; h: number; l: number; c: number; v: number } =>
    c.o !== null && c.h !== null && c.l !== null && c.c !== null && c.v !== null)
  const dateLabel = asOf ? new Date(asOf).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : ''
  if (cs.length === 0) return (
    <div className="fv-chart">
      <div className="fv-chart-head"><span className="fv-chart-name">{data.name}</span>
        <span className="fv-chart-date">{dateLabel}</span></div>
      <div className="fv-dim c" style={{ height: H, display: 'grid', placeItems: 'center' }}>장중 데이터 없음</div>
    </div>
  )
  const n = cs.length
  const lo = Math.min(...cs.map(c => c.l)), hi = Math.max(...cs.map(c => c.h))
  const span = hi - lo || 1
  const vmax = Math.max(...cs.map(c => c.v))
  const plotW = W - PAD.left - PAD.right
  const step = plotW / n
  const y = (p: number) => PAD.top + (hi - p) / span * PRICE_H
  const volTop = PAD.top + PRICE_H + 6
  const up = (data.change ?? 0) >= 0
  const cls = up ? 'up' : 'down'

  // 가격축 눈금 5개 — 값은 지수 크기에 맞춰 반올림
  const ticks = Array.from({ length: 5 }, (_, i) => lo + span * i / 4)
  const fmtTick = (v: number) => v >= 10000 ? Math.round(v).toLocaleString('en-US') : v.toFixed(0)

  return (
    <div className="fv-chart">
      <div className="fv-chart-head">
        <span className="fv-chart-name">{data.name}</span>
        <span className="fv-chart-date">{dateLabel}</span>
        <span className={`fv-chart-chg ${cls}`}>
          {data.change === null || data.change_pct === null ? '—' : <>
            {data.change > 0 ? '+' : ''}{data.change.toFixed(2)} ({data.change_pct > 0 ? '+' : ''}{data.change_pct.toFixed(2)}%)</>}
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label={`${data.name} intraday chart`}>
        {/* 격자 */}
        {ticks.map((t, i) => (
          <g key={i}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="fv-grid" />
            <text x={W - PAD.right + 4} y={y(t) + 3} className="fv-axis">{fmtTick(t)}</text>
          </g>
        ))}
        {/* 거래량 축 (좌측, 상대값) */}
        {[0.5, 1, 1.5, 2].map(v => (
          <text key={v} x={PAD.left - 4} y={PAD.top + PRICE_H * (1 - v / 2.2) + 3}
                className="fv-axis" textAnchor="end">{v.toFixed(1)}</text>
        ))}
        {/* 시간축 */}
        {TIMES.map((t, i) => {
          // 09:30 개장 → 10AM은 6번째 5분봉, 이후 매시 12봉
          const x = PAD.left + (6 + i * 12) * step
          return <text key={t} x={x} y={H - 6} className="fv-axis" textAnchor="middle">{t}</text>
        })}
        {/* 거래량 막대 */}
        {cs.map((c, i) => {
          const h = c.v / vmax * VOL_H
          return <rect key={i} x={PAD.left + i * step + 0.5} y={volTop + VOL_H - h}
                       width={Math.max(step - 1, 1)} height={h}
                       className={`fv-vol ${c.c >= c.o ? 'up' : 'down'}`} />
        })}
        {/* 캔들 */}
        {cs.map((c, i) => {
          const x = PAD.left + i * step + step / 2
          const bodyTop = y(Math.max(c.o, c.c)), bodyBot = y(Math.min(c.o, c.c))
          return (
            <g key={i} className={`fv-candle ${c.c >= c.o ? 'up' : 'down'}`}>
              <line x1={x} x2={x} y1={y(c.h)} y2={y(c.l)} />
              <rect x={x - Math.max(step * 0.35, 0.8)} y={bodyTop}
                    width={Math.max(step * 0.7, 1.6)} height={Math.max(bodyBot - bodyTop, 0.8)} />
            </g>
          )
        })}
        {/* 마지막가 라벨 */}
        <g transform={`translate(${W - PAD.right}, ${y(data.last ?? cs[cs.length - 1].c) - 7})`}>
          <rect width={PAD.right - 2} height={14} rx={2} className={`fv-last ${cls}`} />
          <text x={(PAD.right - 2) / 2} y={10} textAnchor="middle" className="fv-last-text">
            {fmtTick(data.last ?? cs[cs.length - 1].c)}</text>
        </g>
      </svg>
    </div>
  )
}
