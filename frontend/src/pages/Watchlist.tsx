import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { del, get, post } from '../api'
import type { Dashboard, SearchResult } from '../types'
import SignalBadge from '../components/SignalBadge'

export default function Watchlist() {
  const [q, setQ] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [dash, setDash] = useState<Dashboard | null>(null)
  const [busy, setBusy] = useState(false)

  const load = () => get<Dashboard>('/api/dashboard').then(setDash)
  useEffect(() => { load() }, [])

  const search = async () => {
    if (!q.trim()) return
    setBusy(true)
    try { setResults(await get<SearchResult[]>(`/api/search?q=${encodeURIComponent(q)}`)) }
    finally { setBusy(false) }
  }

  const add = async (r: SearchResult) => {
    await post('/api/watchlist', r)
    await post('/api/refresh')     // 새 종목 시세·시그널 즉시 계산
    setResults([]); setQ(''); load()
  }

  return (
    <div className="grid">
      <div className="card">
        <strong>종목 검색</strong>
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <input placeholder="이름 또는 심볼 (삼성전자 / AAPL / 비트코인)" value={q}
                 onChange={e => setQ(e.target.value)}
                 onKeyDown={e => e.key === 'Enter' && search()} style={{ flex: 1 }} />
          <button onClick={search} disabled={busy}>{busy ? '검색 중…' : '검색'}</button>
        </div>
        {results.map(r => (
          <div key={r.market + r.symbol}
               style={{ display: 'flex', justifyContent: 'space-between',
                        padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
            <span>{r.name} <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
              {r.symbol} · {r.market}{r.is_etf ? ' · ETF' : ''}</span></span>
            <button className="ghost" onClick={() => add(r)}>+ 추가</button>
          </div>
        ))}
      </div>

      <div className="card">
        <strong>워치리스트</strong>
        <table>
          <thead><tr><th>종목</th><th>스윙</th><th>중장기</th><th></th></tr></thead>
          <tbody>
            {dash?.signals.map(s => (
              <tr key={s.symbol}>
                <td><Link to={`/ticker/${s.symbol}`}><strong>{s.name}</strong>
                  <span style={{ color: 'var(--text-dim)', fontSize: 12 }}> {s.symbol}</span></Link></td>
                <td><SignalBadge grade={s.swing_grade} /></td>
                <td><SignalBadge grade={s.longterm_grade} /></td>
                <td><button className="ghost"
                  onClick={() => del(`/api/watchlist/${s.symbol}`).then(load)}>제거</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
