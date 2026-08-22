import { Link } from 'react-router-dom'
import type { HeatSector } from './types'

interface Rect { x: number; y: number; w: number; h: number }
interface Item { key: string; w: number }

/** squarified treemap — 가중치가 큰 것부터 가로세로비가 1에 가깝게 줄(row)을 채운다.
 *  단순 slice-and-dice로 그리면 NVDA 같은 큰 칸이 길쭉한 띠가 되어 finviz 느낌이 안 난다. */
function squarify(items: Item[], rect: Rect): Map<string, Rect> {
  const out = new Map<string, Rect>()
  const total = items.reduce((s, i) => s + i.w, 0)
  if (total <= 0 || rect.w <= 0 || rect.h <= 0) return out
  const scale = rect.w * rect.h / total
  const sorted = [...items].sort((a, b) => b.w - a.w).map(i => ({ ...i, a: i.w * scale }))
  let { x, y, w, h } = rect
  let row: typeof sorted = []

  const worst = (r: typeof sorted, side: number) => {
    const s = r.reduce((t, i) => t + i.a, 0)
    const mx = Math.max(...r.map(i => i.a)), mn = Math.min(...r.map(i => i.a))
    return Math.max(side * side * mx / (s * s), s * s / (side * side * mn))
  }
  const layoutRow = (r: typeof sorted) => {
    const s = r.reduce((t, i) => t + i.a, 0)
    const vertical = w >= h   // 넓으면 세로 띠를 왼쪽에
    if (vertical) {
      const rw = s / h; let cy = y
      for (const i of r) { const rh = i.a / rw; out.set(i.key, { x, y: cy, w: rw, h: rh }); cy += rh }
      x += rw; w -= rw
    } else {
      const rh = s / w; let cx = x
      for (const i of r) { const rw = i.a / rh; out.set(i.key, { x: cx, y, w: rw, h: rh }); cx += rw }
      y += rh; h -= rh
    }
  }

  for (const it of sorted) {
    const side = Math.min(w, h)
    if (row.length === 0 || worst([...row, it], side) <= worst(row, side)) row.push(it)
    else { layoutRow(row); row = [it] }
  }
  if (row.length) layoutRow(row)
  return out
}

/** 색 스케일: ±3% 에서 앱의 시세 색(--buy/--sell)이 가장 진하고 0 에 가까울수록 카드 바탕에 섞인다.
 *  finviz 고유의 빨강/초록을 박아 넣지 않고 테마 토큰을 쓰는 이유는, 다른 화면의 등락 색과
 *  여기 히트맵 색이 다르면 같은 "하락"이 두 가지 색으로 보이기 때문. */
function color(chg: number | null): string {
  if (chg === null) return 'rgba(148, 163, 200, 0.10)'   // 시세 못 받은 칸은 무채색
  const t = Math.max(-1, Math.min(1, chg / 3))
  const strength = Math.round(12 + Math.abs(t) * 60)   // 12% ~ 72%
  return `color-mix(in srgb, var(${t >= 0 ? '--buy' : '--sell'}) ${strength}%, rgba(23, 28, 39, 0.9))`
}

// 옆 시그널 표(19행)와 키를 맞추려 세로로 조금 길게
const W = 440, H = 560

export default function Heatmap({ sectors: input }: { sectors: HeatSector[] }) {
  const sectors = input.map(s => ({ ...s, w: s.tickers.reduce((t, k) => t + k.weight, 0) }))
  const sectorRects = squarify(sectors.map(s => ({ key: s.name, w: s.w })), { x: 0, y: 0, w: W, h: H })

  return (
    <div className="fv-heatmap" style={{ aspectRatio: `${W} / ${H}` }}>
      {sectors.map(s => {
        const r = sectorRects.get(s.name)
        if (!r) return null
        const inner = { x: 0, y: 0, w: r.w, h: Math.max(r.h - 11, 0) }
        const cells = squarify(s.tickers.map(t => ({ key: t.symbol, w: t.weight })), inner)
        const pct = (v: number, base: number) => `${v / base * 100}%`
        return (
          <div key={s.name} className="fv-sector"
               style={{ left: pct(r.x, W), top: pct(r.y, H), width: pct(r.w, W), height: pct(r.h, H) }}>
            <div className="fv-sector-label">{s.name}</div>
            <div className="fv-sector-body">
              {s.tickers.map(t => {
                const c = cells.get(t.symbol)
                if (!c) return null
                // 칸 크기에 따라 글자 크기·등락 표시 여부를 단계적으로 줄인다
                const px = c.w / W * 440, py = c.h / H * 440
                const size = Math.min(px, py)
                const font = size > 90 ? 22 : size > 60 ? 15 : size > 40 ? 11 : size > 26 ? 8 : 0
                return (
                  <Link key={t.symbol} to={`/ticker/${t.symbol}`} className="fv-cell"
                        title={`${t.name ? t.name + ' ' : ''}${t.symbol} ${t.change_pct === null ? '—' : (t.change_pct > 0 ? '+' : '') + t.change_pct.toFixed(2) + '%'}`}
                        style={{ left: pct(c.x, inner.w), top: pct(c.y, inner.h),
                                 width: pct(c.w, inner.w), height: pct(c.h, inner.h),
                                 background: color(t.change_pct), fontSize: font }}>
                    {font > 0 && <>
                      {/* 한글 이름은 영문 티커보다 넓다 — 글자가 작아지는 칸에서는 코드가 낫다 */}
                      <span className="fv-cell-t">{font >= 11 ? (t.name ?? t.symbol) : t.symbol}</span>
                      {font >= 11 && t.change_pct !== null && <span className="fv-cell-c">
                        {t.change_pct > 0 ? '+' : ''}{t.change_pct.toFixed(2)}%</span>}
                    </>}
                  </Link>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}
