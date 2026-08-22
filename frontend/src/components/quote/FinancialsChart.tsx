import { useEffect, useRef, useState } from 'react'
import { Bar, BarChart, Cell, LabelList, Tooltip, XAxis, YAxis } from 'recharts'
import type { Financials, FinancialsItem } from '../../types'
import { abbrNum, moneyCell } from '../../quote/fmt'
import BlockEmpty from './BlockEmpty'

/** finviz 재무 막대 3종 — GAAP EPS · 매출 · 발행주식수. 연간/분기 토글.
 *
 *  숫자 표가 아니라 막대로 두는 이유: 사용자가 여기서 읽는 것은 값이 아니라 방향이다.
 *  컨센서스 추정치 막대는 반투명 + `(E)` 라벨로 구분한다 — 추정치를 실적으로 읽으면
 *  "이미 벌었다"와 "번다고들 한다"가 같은 사실이 된다. */
export default function FinancialsChart({ block, currency, loading }: {
  block: Financials | null | undefined
  currency: string
  loading?: boolean
}) {
  const [period, setPeriod] = useState<'annual' | 'quarterly'>('annual')
  const rows: FinancialsItem[] = block ? (period === 'annual' ? block.annual : block.quarterly) : []

  if (!block || block.status !== 'ok' || rows.length === 0)
    return (<>
      <Toggle period={period} onChange={setPeriod} />
      <BlockEmpty block={block} loading={loading} empty="재무 이력이 없습니다." height={140} />
    </>)

  const hasShares = rows.some(r => r.shares_outstanding !== null)
  return (
    <>
      <Toggle period={period} onChange={setPeriod} />
      <div className="fin-charts">
        <MiniBars title="EPS" rows={rows} pick={r => r.eps} currency={currency} money />
        <MiniBars title="매출" rows={rows} pick={r => r.sales} currency={currency} />
        {hasShares
          ? <MiniBars title="발행주식수" rows={rows} pick={r => r.shares_outstanding} currency={currency} />
          : <div className="fin-chart">
              <div className="fin-chart-title">발행주식수</div>
              {/* 왜 비었는지는 백엔드만 안다 — shares_note를 그대로 보여준다 */}
              <div className="quote-note block-empty">
                {block.shares_note ?? '발행주식수 이력이 없습니다.'}</div>
            </div>}
      </div>
    </>
  )
}

function Toggle({ period, onChange }: {
  period: 'annual' | 'quarterly'; onChange: (p: 'annual' | 'quarterly') => void
}) {
  return (
    <div className="quote-chart-bar">
      <button className={`tf-btn${period === 'annual' ? ' on' : ''}`}
              onClick={() => onChange('annual')}>연간</button>
      <button className={`tf-btn${period === 'quarterly' ? ' on' : ''}`}
              onClick={() => onChange('quarterly')}>분기</button>
      <span className="sep" />
      <span className="quote-note">반투명 막대 + (E) = 컨센서스 추정치</span>
    </div>
  )
}

function MiniBars({ title, rows, pick, currency, money }: {
  title: string
  rows: FinancialsItem[]
  pick: (r: FinancialsItem) => number | null
  currency: string
  money?: boolean
}) {
  const [box, width] = useBoxWidth()
  const data = rows.map(r => ({
    // 추정 막대는 x축 라벨에도 (E)를 남긴다 — 색만으로는 인쇄·색각에서 사라진다
    name: r.estimate ? `${r.period}(E)` : r.period,
    v: pick(r), estimate: r.estimate,
  })).filter(d => d.v !== null)
  // recharts 포매터는 undefined도 넘긴다 — 숫자로 못 바꾸면 —로 떨어뜨린다
  const label = (v: unknown) =>
    v === null || v === undefined || Number.isNaN(Number(v)) ? '—'
      : money ? moneyCell(currency, Number(v)) : abbrNum(currency, Number(v))
  if (data.length === 0)
    return <div className="fin-chart"><div className="fin-chart-title">{title}</div>
      <div ref={box} className="quote-note block-empty">값이 없습니다.</div></div>
  return (
    <div className="fin-chart">
      <div className="fin-chart-title">{title}</div>
      <div ref={box}>
        {/* recharts의 ResponsiveContainer는 폭 0에서 마운트되면(숨은 탭·display:none 조상)
            그 뒤 폭이 생겨도 0으로 굳어 막대가 영영 안 그려진다. 폭은 직접 재서 넘긴다. */}
        {width > 0 && <BarChart data={data} width={width} height={150}
                                margin={{ top: 16, right: 4, bottom: 0, left: 4 }}>
          <XAxis dataKey="name" tick={{ fontSize: 10, fill: 'var(--text-dim)' }}
                 axisLine={false} tickLine={false} interval={0} />
          <YAxis hide domain={[(min: number) => Math.min(0, min), 'auto']} />
          <Tooltip cursor={{ fill: 'rgba(148,163,200,0.08)' }}
                   contentStyle={{ background: 'rgba(20,25,36,0.96)', border: '1px solid var(--border)',
                                   borderRadius: 6, fontSize: 12 }}
                   formatter={(v: unknown) => [label(v), title] as [string, string]} />
          <Bar dataKey="v" radius={[2, 2, 0, 0]} isAnimationActive={false}>
            {data.map((d, i) => (
              <Cell key={i} fill={(d.v ?? 0) < 0 ? 'var(--sell)' : 'var(--accent)'}
                    fillOpacity={d.estimate ? 0.35 : 0.9} />))}
            <LabelList dataKey="v" position="top" fontSize={10} fill="var(--text-dim)"
                       formatter={label} />
          </Bar>
        </BarChart>}
      </div>
    </div>
  )
}

/** 부모 폭을 실측해서 돌려준다. 폭이 0→값으로 바뀌는 순간에도 다시 그린다. */
function useBoxWidth() {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = () => setWidth(el.clientWidth)
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width] as const
}
