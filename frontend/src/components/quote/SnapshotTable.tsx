import type { ReactNode } from 'react'

/** 스냅샷 표의 한 칸. tone은 값의 방향(양수/음수/주의)을 색으로 덧붙인다. */
export interface SnapCell {
  label: string
  value: ReactNode
  /** 한 칸에 두 값을 놓을 때의 보조값(52주 고가 `126.71 -36.75%`, 변동성 주/월).
   *  finviz도 같은 칸에 두 숫자를 쓴다 — 칸을 늘리면 84칸 격자가 깨진다. */
  sub?: string | null
  tone?: 'pos' | 'neg' | 'warn' | null
  title?: string
}

/** finviz의 snapshot-table2: 라벨·값 쌍을 6열로 채운 격자.
 *  행 단위 마크업 없이 평면으로 깔고 줄무늬는 CSS nth-child로 만든다 —
 *  좁은 화면에서 열 수가 바뀌어도 칸이 깨지지 않는다. */
export default function SnapshotTable({ cells, id }: { cells: SnapCell[]; id?: string }) {
  const pad = (6 - cells.length % 6) % 6
  const all: (SnapCell | null)[] = [...cells, ...Array.from({ length: pad }, () => null)]
  return (
    <div className="snapshot" id={id}>
      {all.map((c, i) => c === null
        ? <div key={i} className="snap-cell" aria-hidden="true" />
        : <div key={i} className="snap-cell" title={c.title}>
            <span className="snap-label">{c.label}</span>
            <span className={`snap-value${c.tone ? ` ${c.tone}` : ''}`}>{c.value}
              {/* 구분자를 문자로 넣는다 — 여백만으로는 '172,043 9.94%'가 한 숫자로 읽힌다 */}
              {c.sub && <small>{` · ${c.sub}`}</small>}</span>
          </div>)}
    </div>
  )
}
