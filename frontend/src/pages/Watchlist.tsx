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
  const [adding, setAdding] = useState<string | null>(null)  // 추가 진행 중인 심볼

  const [error, setError] = useState<string | null>(null)
  const [actionMsg, setActionMsg] = useState<string | null>(null)  // 검색·추가 결과

  const load = () => get<Dashboard>('/api/dashboard')
    .then(d => { setDash(d); setError(null) })
    .catch(e => setError(String(e)))  // catch가 없으면 빈 표만 남아 실패를 알 수 없다
  useEffect(() => { load() }, [])

  // 검색·추가 실패를 삼키면 버튼만 원래대로 돌아온다. 사용자는 "검색 결과가 없다"
  // 또는 "추가됐다"로 읽고 같은 조작을 반복한다.
  const search = async () => {
    if (!q.trim()) return
    setBusy(true); setActionMsg(null)
    try {
      const found = await get<SearchResult[]>(`/api/search?q=${encodeURIComponent(q)}`)
      setResults(found)
      if (found.length === 0) setActionMsg(`'${q}' 검색 결과가 없습니다 — 종목명이나 심볼을 다시 확인하세요`)
    } catch (e) { setResults([]); setActionMsg(`검색 실패: ${e}`) }
    finally { setBusy(false) }
  }

  const add = async (r: SearchResult) => {
    setAdding(r.symbol); setActionMsg(null)
    try {
      await post('/api/watchlist', r)
      // 새 종목만 갱신 — 전체 갱신은 수 초 걸림
      await post(`/api/refresh?symbol=${encodeURIComponent(r.symbol)}`)
      setResults([]); setQ('')
      const d = await get<Dashboard>('/api/dashboard')
      setDash(d); setError(null)
      // 시세를 못 받아오면 시그널이 없어 목록에 나타나지 않는다. 그 사실을 알리지
      // 않으면 "추가가 안 됐다"고 읽고 같은 종목을 반복해서 추가하게 된다.
      if (!d.signals.some(s => s.symbol === r.symbol))
        setActionMsg(`${r.name}을(를) 추가했지만 시세를 받지 못해 아직 목록에 없습니다 — `
          + '대시보드에서 새로고침 후 확인하세요')
    } catch (e) { setActionMsg(`추가 실패: ${e}`) }
    finally { setAdding(null) }
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
        {actionMsg && <div className="warn-box" style={{ marginTop: 10 }}>{actionMsg}</div>}
        {results.map(r => (
          <div key={r.market + r.symbol}
               style={{ display: 'flex', justifyContent: 'space-between',
                        padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
            <span>{r.name} <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
              {r.symbol} · {r.market}{r.is_etf ? ' · ETF' : ''}</span></span>
            <button className="ghost" onClick={() => add(r)} disabled={adding !== null}>
              {adding === r.symbol ? '추가 중…' : '+ 추가'}</button>
          </div>
        ))}
      </div>

      <div className="card">
        <strong>워치리스트</strong>
        {error && <div style={{ color: 'var(--sell)', marginTop: 8 }}>
          불러오기 실패: {error}
          <button style={{ marginLeft: 8 }} onClick={() => { setError(null); load() }}>다시 시도</button>
        </div>}
        {dash && dash.signals.filter(s => s.in_watchlist).length === 0 && !error &&
          <div className="empty">
            워치리스트가 비어 있습니다.<br />
            위 검색창에서 종목을 찾아 추가하면 <Link to="/">대시보드</Link>에 시그널이 표시됩니다.
          </div>}
        <div className="table-scroll">
        <table>
          <thead><tr><th>종목</th><th>스윙</th><th>중장기</th><th></th></tr></thead>
          <tbody>
            {dash?.signals.filter(s => s.in_watchlist).map(s => (
              <tr key={s.symbol}>
                <td><Link to={`/ticker/${s.symbol}`}><strong>{s.name}</strong>
                  <span style={{ color: 'var(--text-dim)', fontSize: 12 }}> {s.symbol}</span></Link></td>
                <td><SignalBadge grade={s.swing_grade} /></td>
                <td><SignalBadge grade={s.longterm_grade} /></td>
                <td><button className="ghost" onClick={() => {
                  if (confirm(`${s.name}을(를) 워치리스트에서 제거합니다.`
                    + (s.is_holding ? '\n보유 중인 종목이라 시그널은 계속 표시됩니다.' : '')))
                    del(`/api/watchlist/${s.symbol}`).then(load).catch(e => setError(String(e)))
                }}>제거</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>
    </div>
  )
}
