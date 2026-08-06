export default function ScoreBar({ score }: { score: number }) {
  const pct = Math.min(Math.abs(score), 100) / 2
  const color = score >= 0 ? 'var(--buy)' : 'var(--sell)'
  const grad = score >= 0
    ? 'linear-gradient(90deg, var(--buy), var(--buy-strong))'
    : 'linear-gradient(270deg, var(--sell), var(--sell-strong))'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ position: 'relative', width: 120, height: 6,
                    background: 'var(--border)', borderRadius: 3 }}>
        <div className="bar-fill"
             style={{ position: 'absolute', height: 6, borderRadius: 3, background: grad,
                      left: score >= 0 ? '50%' : `${50 - pct}%`, width: `${pct}%`,
                      transformOrigin: score >= 0 ? 'left' : 'right' }} />
      </div>
      <span style={{ color, fontVariantNumeric: 'tabular-nums', minWidth: 36,
                     textAlign: 'right' }}>{score.toFixed(0)}</span>
    </div>
  )
}
