import { useLayoutEffect, useRef, useState } from 'react'
import type { IndexRow, Session } from './types'

// 세로 배치. 가격 영역을 키운 이유: 지수 장중 변동은 0.5% 안팎이라 캔들 몸통이
// 90px 안에서는 1px 미만으로 뭉개져 "선 하나"로 보였다.
const PAD = { top: 10, right: 54, bottom: 20, left: 10 }
const PRICE_H = 148, VOL_GAP = 10, VOL_H = 38
const H = PAD.top + PRICE_H + VOL_GAP + VOL_H + PAD.bottom
const MIN_W = 300

/** 장 시작~마감 사이 정시 라벨과 그 시각의 실제 시(24h). 미국은 10AM…4PM, 한국은 10…15.
 *  상수로 박아두면 한국 장(09:00–15:30)에 4PM 이 찍힌다. hour 를 같이 들고 있는 이유는
 *  5분봉 인덱스를 "개장 시각과의 분(分) 차이"로 계산해야 해서다 — 미국은 09:30 개장이라
 *  10AM이 6번째 봉이지만, 한국은 09:00 개장이라 10시가 12번째 봉이다(상수 오프셋을 쓰면 어긋난다). */
function hourLabels(s: Session): { hour: number; label: string }[] {
  const h0 = Number(s.open.slice(0, 2)), h1 = Number(s.close.slice(0, 2))
  const us = s.tz.startsWith('America')
  const out: { hour: number; label: string }[] = []
  for (let h = h0 + 1; h <= h1; h++) {
    out.push({ hour: h, label: us ? `${h % 12 === 0 ? 12 : h % 12}${h < 12 ? 'AM' : 'PM'}` : String(h) })
  }
  return out
}

/** 카드 실폭을 재서 그대로 좌표계로 쓴다. viewBox 를 고정폭으로 두면 카드가 넓어져도
 *  차트는 340px 로 가운데 박혀 있고(양옆 여백) 글자도 작은 채로 남는다.
 *  ResizeObserver 만 쓰지 않는 이유: 임베디드 웹뷰 등 콜백이 첫 회만 오는 환경이 있어
 *  창 크기를 줄여도 차트가 예전 폭 그대로 카드를 삐져나온다. resize 이벤트를 같이 듣는다. */
function useWidth(ref: React.RefObject<HTMLDivElement | null>) {
  const [w, setW] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = () => setW(el.clientWidth)
    measure()
    window.addEventListener('resize', measure)
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
    ro?.observe(el)
    return () => { window.removeEventListener('resize', measure); ro?.disconnect() }
  }, [ref])
  return Math.max(w, MIN_W)
}

const fmtVol = (v: number) =>
  v >= 1e9 ? `${(v / 1e9).toFixed(1)}B` : v >= 1e6 ? `${(v / 1e6).toFixed(1)}M`
  : v >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : String(Math.round(v))

/** finviz 홈 상단 지수 미니 차트 — 5분봉 캔들 + 거래량 + 우측 가격축 + 마지막가 라벨.
 *  전일 종가 점선을 같이 그린다: 캔들만 있으면 지금이 플러스인지 마이너스인지
 *  머리글 숫자를 읽어야만 알 수 있다. */
export default function IndexChart({ data, asOf, session }:
  { data: IndexRow; asOf: string | null; session: Session }) {
  const box = useRef<HTMLDivElement>(null)
  const W = useWidth(box)
  const TIMES = hourLabels(session)
  const [openH, openM] = [Number(session.open.slice(0, 2)), Number(session.open.slice(3, 5))]
  // 값이 빠진 봉(거래 정지 등)은 그리지 않는다 — NaN 좌표가 하나 있으면 SVG 전체가 안 그려진다
  const cs = data.candles.filter((c): c is { o: number; h: number; l: number; c: number; v: number } =>
    c.o !== null && c.h !== null && c.l !== null && c.c !== null && c.v !== null)
  const dateLabel = asOf
    ? new Date(asOf).toLocaleDateString(session.tz.startsWith('Asia') ? 'ko-KR' : 'en-US',
        { month: 'short', day: 'numeric' })
    : ''
  const head = (
    <div className="fv-chart-head">
      <span className="fv-chart-name">{data.name}</span>
      <span className="fv-chart-date">{dateLabel}</span>
      <span className={`fv-chart-chg ${(data.change ?? 0) >= 0 ? 'up' : 'down'}`}>
        {data.change === null || data.change_pct === null ? '—' : <>
          {data.change > 0 ? '+' : ''}{data.change.toFixed(2)} ({data.change_pct > 0 ? '+' : ''}{data.change_pct.toFixed(2)}%)</>}
      </span>
    </div>
  )
  if (cs.length === 0) return (
    <div className="fv-chart">{head}
      <div className="fv-dim c" style={{ height: H, display: 'grid', placeItems: 'center' }}>장중 데이터 없음</div>
    </div>
  )

  const n = cs.length
  let lo = Math.min(...cs.map(c => c.l)), hi = Math.max(...cs.map(c => c.h))
  const dayRange = hi - lo || Math.abs(hi) * 0.001 || 1
  // 전일 종가가 장중 범위 근처면 축에 포함해 기준선을 보이게 한다. 갭이 큰 날까지
  // 억지로 넣으면 캔들이 다시 납작해지므로 하루 범위의 60% 밖이면 포기한다.
  const prev = data.prev_close
  const showPrev = prev !== null && prev >= lo - dayRange * 0.6 && prev <= hi + dayRange * 0.6
  if (showPrev && prev !== null) { lo = Math.min(lo, prev); hi = Math.max(hi, prev) }
  const pad = (hi - lo || 1) * 0.06   // 위아래 여백 — 고가/저가가 테두리에 붙으면 잘려 보인다
  lo -= pad; hi += pad
  const span = hi - lo || 1
  const vmax = Math.max(...cs.map(c => c.v)) || 1
  const plotW = W - PAD.left - PAD.right
  const step = plotW / n
  const y = (p: number) => PAD.top + (hi - p) / span * PRICE_H
  const volTop = PAD.top + PRICE_H + VOL_GAP
  const up = (data.change ?? 0) >= 0
  const cls = up ? 'up' : 'down'
  const bodyW = Math.max(step * 0.62, 1)

  // 가격축 눈금 5개. 소수 자릿수는 하루 변동폭에 맞춘다 — 6,000 지수에 소수 둘째 자리는 잡음,
  // 100 이하 값에 정수만 찍으면 눈금이 전부 같은 숫자가 된다.
  const dec = span >= 100 ? 0 : span >= 10 ? 1 : 2
  const fmtTick = (v: number) => v.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec })
  const ticks = Array.from({ length: 5 }, (_, i) => lo + span * i / 4)

  return (
    <div className="fv-chart">
      {head}
      {/* 폭 측정용 래퍼 — 카드에 좌우 패딩이 있어 카드를 재면 그만큼 넓게 그려 삐져나온다 */}
      <div className="fv-plot" ref={box}>
        <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img"
             aria-label={`${data.name} 장중 5분봉 차트`}>
          {/* 격자 + 우측 가격축 */}
          {ticks.map((t, i) => (
            <g key={i}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} className="fv-grid" />
              <text x={W - PAD.right + 5} y={y(t) + 4} className="fv-axis">{fmtTick(t)}</text>
            </g>
          ))}
          {/* 전일 종가 기준선 — 이 선 위/아래가 그날의 플러스/마이너스 */}
          {showPrev && prev !== null && (
            <line x1={PAD.left} x2={W - PAD.right} y1={y(prev)} y2={y(prev)} className="fv-prev" />
          )}
          {/* 시간축 — 정시 라벨의 5분봉 인덱스는 "개장 시각과의 분(分) 차이 / 5"로 구한다.
              미국은 09:30 개장이라 10AM이 6번째 봉, 한국은 09:00 개장이라 10시가 12번째 봉이라
              시장마다 오프셋이 다르다. 장중이라 봉이 모자라면 그 라벨은 그리지 않는다. */}
          {TIMES.map(({ hour, label }) => {
            const idx = (hour * 60 - (openH * 60 + openM)) / 5
            if (idx > n) return null
            return <text key={label} x={PAD.left + idx * step} y={H - 6} className="fv-axis"
                         textAnchor="middle">{label}</text>
          })}
          {/* 거래량 막대 + 최대 거래량 라벨 (예전의 0.5~2.0 눈금은 실제 값이 아닌 장식이라 뺐다) */}
          <line x1={PAD.left} x2={W - PAD.right} y1={volTop + VOL_H} y2={volTop + VOL_H} className="fv-grid" />
          <text x={W - PAD.right + 5} y={volTop + 9} className="fv-axis">{fmtVol(vmax)}</text>
          {cs.map((c, i) => {
            const h = Math.max(c.v / vmax * VOL_H, 0.6)
            return <rect key={i} x={PAD.left + i * step + (step - bodyW) / 2} y={volTop + VOL_H - h}
                         width={bodyW} height={h} className={`fv-vol ${c.c >= c.o ? 'up' : 'down'}`} />
          })}
          {/* 캔들 */}
          {cs.map((c, i) => {
            const x = PAD.left + i * step + step / 2
            const bodyTop = y(Math.max(c.o, c.c)), bodyBot = y(Math.min(c.o, c.c))
            return (
              <g key={i} className={`fv-candle ${c.c >= c.o ? 'up' : 'down'}`}>
                <line x1={x} x2={x} y1={y(c.h)} y2={y(c.l)} />
                <rect x={x - bodyW / 2} y={bodyTop} width={bodyW}
                      height={Math.max(bodyBot - bodyTop, 1)} />
              </g>
            )
          })}
          {/* 마지막가 라벨 */}
          <g transform={`translate(${W - PAD.right + 1}, ${y(data.last ?? cs[n - 1].c) - 8})`}>
            <rect width={PAD.right - 3} height={16} rx={3} className={`fv-last ${cls}`} />
            <text x={(PAD.right - 3) / 2} y={11.5} textAnchor="middle" className="fv-last-text">
              {fmtTick(data.last ?? cs[n - 1].c)}</text>
          </g>
        </svg>
      </div>
    </div>
  )
}
