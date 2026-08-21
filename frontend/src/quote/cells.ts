import type { SnapCell } from '../components/quote/SnapshotTable'

/** 부호 있는 퍼센트 칸 — null은 '—', 0은 중립색. */
export const pctCell = (label: string, v: number | null, title?: string): SnapCell => ({
  label, title,
  value: v === null ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(2)}%`,
  tone: v === null || v === 0 ? null : v > 0 ? 'pos' : 'neg',
})
