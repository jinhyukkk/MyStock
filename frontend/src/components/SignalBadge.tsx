const COLORS: Record<string, [string, string]> = {
  '강력매수': ['var(--buy-strong)', 'rgba(0,230,118,.12)'],
  '매수': ['var(--buy)', 'rgba(46,204,113,.12)'],
  '중립': ['var(--neutral)', 'rgba(139,147,163,.12)'],
  '매도': ['var(--sell)', 'rgba(255,82,82,.12)'],
  '강력매도': ['var(--sell-strong)', 'rgba(255,23,68,.12)'],
}
export default function SignalBadge({ grade }: { grade: string }) {
  const [fg, bg] = COLORS[grade] ?? COLORS['중립']
  return <span className="badge" style={{ color: fg, background: bg }}>{grade}</span>
}
