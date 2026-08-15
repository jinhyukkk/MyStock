export default function ScoreBar({ score, label }: { score: number; label?: string }) {
  const pct = Math.min(Math.abs(score), 100) / 2
  const color = score >= 0 ? 'var(--buy)' : 'var(--sell)'
  const grad = score >= 0
    ? 'linear-gradient(90deg, var(--buy), var(--buy-strong))'
    : 'linear-gradient(270deg, var(--sell), var(--sell-strong))'
  const direction = score > 0 ? '매수 우위' : score < 0 ? '매도 우위' : '중립'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      {/* 방향을 색으로만 전달하면 색각이상·스크린리더 사용자에게는 정보가 사라진다.
          부호가 붙은 숫자와 aria 라벨로 색 없이도 읽히게 한다. */}
      <div role="meter" aria-valuenow={Math.round(score)}
           aria-valuemin={-100} aria-valuemax={100}
           aria-label={`${label ? `${label} ` : ''}점수 ${Math.round(score)}, ${direction}`}
           style={{ position: 'relative', width: 120, height: 6,
                    background: 'var(--border)', borderRadius: 3 }}>
        <div className="bar-fill"
             style={{ position: 'absolute', height: 6, borderRadius: 3, background: grad,
                      left: score >= 0 ? '50%' : `${50 - pct}%`, width: `${pct}%`,
                      transformOrigin: score >= 0 ? 'left' : 'right' }} />
      </div>
      <span aria-hidden="true"
            style={{ color, fontVariantNumeric: 'tabular-nums', minWidth: 36,
                     textAlign: 'right' }}>
        {score > 0 ? '+' : ''}{score.toFixed(0)}</span>
    </div>
  )
}
