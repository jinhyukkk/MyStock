import { NavLink, Outlet } from 'react-router-dom'
import CommandPalette from './CommandPalette'

const tabs = [
  { to: '/', label: '대시보드' }, { to: '/portfolio', label: '포트폴리오' },
  { to: '/watchlist', label: '워치리스트' },
]
export default function Layout() {
  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '20px 16px 60px' }}>
      <header className="topbar">
        <h1 className="logo">MyStock</h1>
        <nav style={{ display: 'flex', gap: 4 }}>
          {tabs.map(t => (
            <NavLink key={t.to} to={t.to} end={t.to === '/'}
              className={({ isActive }) => isActive ? 'tab active' : 'tab'}>
              {t.label}</NavLink>
          ))}
        </nav>
        <button className="ghost" style={{ marginLeft: 'auto', fontSize: 12 }}
          onClick={() => window.dispatchEvent(
            new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }))}>
          검색 <kbd style={{ fontFamily: 'inherit' }}>Ctrl K</kbd>
        </button>
      </header>
      <CommandPalette />
      <Outlet />
      <footer style={{ marginTop: 40, color: 'var(--text-dim)', fontSize: 12,
                       textAlign: 'center' }}>
        본 시그널은 지표 기반 참고 정보이며 투자 자문이 아닙니다.
      </footer>
    </div>
  )
}
