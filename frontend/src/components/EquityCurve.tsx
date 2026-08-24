import { useLayoutEffect, useRef, useState } from 'react'
import type { EquityPoint } from '../types'

// 자본곡선은 5분봉 캔들(finviz/IndexChart)과 형태가 달라 재사용하지 않는다.
// 차트 라이브러리를 넣는 대신 꺾은선 하나를 직접 그린다.
const PAD = { top: 12, right: 68, bottom: 22, left: 12 }
const PLOT_H = 220
const H = PAD.top + PLOT_H + PAD.bottom

export interface Series { label: string; color: string; points: EquityPoint[] }

export default function EquityCurve({ series }: { series: Series[] }) {
  const box = useRef<HTMLDivElement>(null)
  const [w, setW] = useState(720)
  // 카드 실폭을 재서 좌표계로 쓴다 — viewBox를 고정폭으로 두면 넓은 화면에서 늘어진다
  useLayoutEffect(() => {
    const el = box.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setW(Math.max(320, e.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const drawn = series.filter(s => s.points.length > 1)
  if (drawn.length === 0)
    return <div className="empty">표시할 자본곡선이 없습니다.</div>

  const all = drawn.flatMap(s => s.points.map(p => p.equity_krw))
  const lo = Math.min(...all), hi = Math.max(...all)
  const span = hi - lo || 1
  const plotW = w - PAD.left - PAD.right
  const x = (i: number, len: number) =>
    PAD.left + (len > 1 ? (i / (len - 1)) * plotW : 0)
  const y = (v: number) => PAD.top + PLOT_H - ((v - lo) / span) * PLOT_H
  const fmtKrw = (v: number) => `₩${Math.round(v / 10_000).toLocaleString()}만`
  const first = drawn[0].points

  return (
    <div ref={box}>
      <svg width={w} height={H} role="img" aria-label="전략 자본곡선">
        {/* 가로 격자 3줄 — 없으면 곡선의 기울기를 눈으로 못 잰다 */}
        {[0, 0.5, 1].map(f => {
          const v = lo + span * f
          return (
            <g key={f}>
              <line x1={PAD.left} x2={PAD.left + plotW} y1={y(v)} y2={y(v)}
                    stroke="var(--border)" strokeWidth={1} />
              <text x={PAD.left + plotW + 6} y={y(v) + 4} fontSize={11}
                    fill="var(--text-dim)">{fmtKrw(v)}</text>
            </g>
          )
        })}
        {drawn.map(s => (
          <polyline key={s.label} fill="none" stroke={s.color} strokeWidth={1.6}
            points={s.points
              .map((p, i) => `${x(i, s.points.length)},${y(p.equity_krw)}`)
              .join(' ')} />
        ))}
        <text x={PAD.left} y={H - 6} fontSize={11} fill="var(--text-dim)">
          {first[0].date}</text>
        <text x={PAD.left + plotW} y={H - 6} fontSize={11}
              fill="var(--text-dim)" textAnchor="end">
          {first[first.length - 1].date}</text>
      </svg>
      <div style={{ display: 'flex', gap: 14, fontSize: 12, marginTop: 4,
                    flexWrap: 'wrap' }}>
        {drawn.map(s => (
          <span key={s.label} style={{ color: 'var(--text-dim)' }}>
            <span style={{ display: 'inline-block', width: 10, height: 2,
                           background: s.color, marginRight: 5,
                           verticalAlign: 'middle' }} />
            {s.label}</span>
        ))}
      </div>
    </div>
  )
}
