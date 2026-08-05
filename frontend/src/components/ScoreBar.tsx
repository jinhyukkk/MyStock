export default function ScoreBar({ score }: { score: number }) {
  const pct = Math.min(Math.abs(score), 100) / 2
  const color = score >= 0 ? 'var(--buy)' : 'var(--sell)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ position: 'relative', width: 120, height: 6,
                    background: 'var(--border)', borderRadius: 3 }}>
        <div style={{ position: 'absolute', height: 6, borderRadius: 3, background: color,
                      left: score >= 0 ? '50%' : `${50 - pct}%`, width: `${pct}%` }} />
      </div>
      <span style={{ color, fontVariantNumeric: 'tabular-nums', minWidth: 36,
                     textAlign: 'right' }}>{score.toFixed(0)}</span>
    </div>
  )
}
