import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { get, post } from '../api'
import type { Dashboard, SearchResult } from '../types'

interface Item {
  symbol: string; name: string; market: string; tracked: boolean
  raw?: SearchResult          // 미등록 종목이면 워치리스트 추가에 사용
}

export default function CommandPalette() {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [items, setItems] = useState<Item[]>([])
  const [sel, setSel] = useState(0)
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState(false)   // 검색 API 응답 대기 중
  const [searchErr, setSearchErr] = useState(false)
  const [tracked, setTracked] = useState<Map<string, Item>>(new Map())
  const inputRef = useRef<HTMLInputElement>(null)
  const navigate = useNavigate()

  // Ctrl/Cmd+K 토글, Esc 닫기
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault(); setOpen(o => !o)
      } else if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // 열릴 때: 입력 초기화 + 포커스 + 등록 종목 목록 로드
  useEffect(() => {
    if (!open) return
    setQ(''); setSel(0)
    inputRef.current?.focus()
    get<Dashboard>('/api/dashboard').then(d => {
      const m = new Map(d.signals.map(s => [s.symbol,
        { symbol: s.symbol, name: s.name, market: s.market, tracked: true }]))
      setTracked(m)
      setItems([...m.values()])
    }).catch(() => {})
  }, [open])

  // 검색어 디바운스 → 전체 검색 (빈 검색어면 등록 종목 목록)
  useEffect(() => {
    if (!open) return
    setSearchErr(false)
    if (!q.trim()) { setItems([...tracked.values()]); setSel(0); setPending(false); return }
    setPending(true)   // 응답 전까지는 이전 목록으로 Enter 이동을 막는다
    const t = setTimeout(() => {
      get<SearchResult[]>(`/api/search?q=${encodeURIComponent(q)}`).then(rs => {
        setItems(rs.map(r => tracked.get(r.symbol) ??
          { symbol: r.symbol, name: r.name, market: r.market, tracked: false, raw: r }))
        setSel(0); setPending(false)
      }).catch(() => { setItems([]); setPending(false); setSearchErr(true) })
    }, 300)
    return () => clearTimeout(t)
  }, [q, open, tracked])

  const pick = async (it: Item) => {
    if (busy) return
    if (!it.tracked && it.raw) {
      setBusy(true)
      try {
        await post('/api/watchlist', it.raw)
        await post(`/api/refresh?symbol=${encodeURIComponent(it.symbol)}`)
      }
      catch { setBusy(false); return }
      setBusy(false)
    }
    setOpen(false)
    navigate(`/ticker/${it.symbol}`)
  }

  const onInputKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setSel(s => Math.min(s + 1, items.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setSel(s => Math.max(s - 1, 0)) }
    else if (e.key === 'Enter' && !pending && items[sel]) pick(items[sel])
  }

  if (!open) return null
  return (
    <div className="palette-overlay" onClick={() => setOpen(false)}>
      <div className="palette" onClick={e => e.stopPropagation()}>
        <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)}
               onKeyDown={onInputKey} disabled={busy}
               placeholder={busy ? '종목 추가 중…' : '종목 이름 또는 심볼 검색'} />
        <div className="palette-list">
          {pending && <div className="palette-item" style={{ color: 'var(--text-dim)' }}>검색 중…</div>}
          {!pending && searchErr &&
            <div className="palette-item" style={{ color: 'var(--sell)' }}>검색 실패 — 네트워크를 확인하세요</div>}
          {!pending && items.map((it, i) => (
            <div key={it.market + it.symbol}
                 className={`palette-item${i === sel ? ' sel' : ''}`}
                 onMouseEnter={() => setSel(i)} onClick={() => pick(it)}>
              <span><strong>{it.name}</strong>
                <span style={{ color: 'var(--text-dim)', fontSize: 12 }}> {it.symbol} · {it.market}</span>
              </span>
              <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
                {it.tracked ? '이동 ↵' : '추가 후 이동 ↵'}</span>
            </div>
          ))}
          {!pending && !searchErr && q.trim() && items.length === 0 &&
            <div className="palette-item" style={{ color: 'var(--text-dim)' }}>검색 결과 없음</div>}
        </div>
      </div>
    </div>
  )
}
