import { useEffect, useMemo, useRef, useState } from 'react'
import { get } from '../api'
import type { Dashboard } from '../types'

export interface SymbolOption { symbol: string; name: string; market: string }

/** 등록 종목 자동완성 입력.
 *  매매 기록은 등록된 심볼만 받으므로(백엔드가 미등록 심볼에 400 응답),
 *  자유 텍스트 입력은 오타 한 번에 실패한다. 후보를 좁혀 고르게 한다. */
export default function SymbolInput({ value, onChange, autoFocus, style }: {
  value: string
  onChange: (symbol: string) => void
  autoFocus?: boolean
  style?: React.CSSProperties
}) {
  const [options, setOptions] = useState<SymbolOption[]>([])
  const [query, setQuery] = useState(value)
  const [open, setOpen] = useState(false)
  const [sel, setSel] = useState(0)
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => { setQuery(value) }, [value])

  useEffect(() => {
    get<Dashboard>('/api/dashboard')
      .then(d => setOptions(d.signals.map(s =>
        ({ symbol: s.symbol, name: s.name, market: s.market }))))
      .catch(() => {})  // 목록을 못 받아도 직접 입력은 계속 가능해야 한다
  }, [])

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [])

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return options.slice(0, 8)
    return options.filter(o =>
      o.symbol.toLowerCase().includes(q) || o.name.toLowerCase().includes(q)).slice(0, 8)
  }, [query, options])

  const pick = (o: SymbolOption) => {
    setQuery(o.symbol); onChange(o.symbol); setOpen(false)
  }

  const onKey = (e: React.KeyboardEvent) => {
    if (!open || matches.length === 0) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setSel(s => Math.min(s + 1, matches.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSel(s => Math.max(s - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); pick(matches[sel]) }
    else if (e.key === 'Escape') setOpen(false)
  }

  return (
    <div className="autocomplete" ref={boxRef} style={style}>
      <input value={query} autoFocus={autoFocus} placeholder="심볼 또는 종목명"
             style={{ width: '100%' }}
             onChange={e => {
               setQuery(e.target.value); onChange(e.target.value); setOpen(true); setSel(0)
             }}
             onFocus={() => setOpen(true)} onKeyDown={onKey} />
      {open && matches.length > 0 && (
        <div className="autocomplete-list">
          {matches.map((o, i) => (
            <div key={o.symbol} className={`autocomplete-item${i === sel ? ' sel' : ''}`}
                 onMouseEnter={() => setSel(i)} onMouseDown={e => { e.preventDefault(); pick(o) }}>
              <strong>{o.name}</strong>
              <span style={{ color: 'var(--text-dim)', fontSize: 12 }}> {o.symbol} · {o.market}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
