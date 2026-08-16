import { fmt } from '../format'

const PIE_COLORS = ['#4f8ef7', '#2ecc71', '#f7c948', '#b06ef7', '#ff8a65']

// recharts v3의 PieChart+Legend 조합이 이 프로젝트에서 섹터를 그리지 못하는 문제(빈 <g> 렌더)가 있어
// 겹침 걱정 없는 순수 SVG 도넛 + 별도 범례 목록으로 대체.
export default function AllocationDonut({ allocation }: { allocation: { label: string; value_krw: number }[] }) {
  const total = allocation.reduce((s, a) => s + a.value_krw, 0)
  const r = 40, cx = 50, cy = 50, circumference = 2 * Math.PI * r
  let offset = 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 20, height: '100%' }}>
      <svg viewBox="0 0 100 100" style={{ width: 140, height: 140, flexShrink: 0 }}>
        {allocation.map((a, i) => {
          const pct = total ? a.value_krw / total : 0
          const dash = pct * circumference
          const el = (
            <circle key={a.label} r={r} cx={cx} cy={cy} fill="none"
                    stroke={PIE_COLORS[i % PIE_COLORS.length]} strokeWidth={18}
                    strokeDasharray={`${dash} ${circumference - dash}`}
                    strokeDashoffset={-offset * circumference}
                    transform={`rotate(-90 ${cx} ${cy})`}>
              <title>{a.label} ₩{fmt(a.value_krw)} ({(pct * 100).toFixed(1)}%)</title>
            </circle>
          )
          offset += pct
          return el
        })}
      </svg>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
        {allocation.map((a, i) => (
          <div key={a.label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: PIE_COLORS[i % PIE_COLORS.length], flexShrink: 0 }} />
            <span>{a.label}</span>
            <span style={{ color: 'var(--text-dim)' }}>
              {total ? (a.value_krw / total * 100).toFixed(1) : 0}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}
