import { useId } from 'react'

export default function SentimentGauge({ label, value, valueLabel }:
  { label: string; value: number | null; valueLabel: string }) {
  const gid = useId()
  const v = value ?? 50
  const angle = (v / 100) * 180
  const color = value === null ? 'var(--neutral)'
    : v < 45 ? 'var(--sell)' : v > 55 ? 'var(--buy)' : 'var(--neutral)'
  const rad = (Math.PI * (180 - angle)) / 180
  return (
    <div style={{ textAlign: 'center' }}>
      <svg width="120" height="70" viewBox="0 0 120 70">
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="var(--sell)" />
            <stop offset="50%" stopColor="var(--accent-2)" />
            <stop offset="100%" stopColor="var(--buy)" />
          </linearGradient>
        </defs>
        <path d="M 10 65 A 50 50 0 0 1 110 65" fill="none"
              stroke="var(--border)" strokeWidth="10" strokeLinecap="round" />
        <path d="M 10 65 A 50 50 0 0 1 110 65" fill="none" stroke={`url(#${gid})`}
              strokeWidth="10" strokeLinecap="round"
              strokeDasharray={`${(v / 100) * 157} 157`}
              style={{ transition: 'stroke-dasharray 0.6s ease' }} />
        <circle cx={60 + 50 * Math.cos(rad)} cy={65 - 50 * Math.sin(rad)} r="4" fill={color} />
        <text x="60" y="58" textAnchor="middle" fill="var(--text)"
              fontSize="18" fontWeight="700">{value === null ? '—' : Math.round(v)}</text>
      </svg>
      <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>{label}</div>
      <div style={{ fontSize: 13, color }}>{valueLabel}</div>
    </div>
  )
}
