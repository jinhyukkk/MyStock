import { NavLink, Outlet } from 'react-router-dom'
import CommandPalette from './CommandPalette'

const tabs = [
  { to: '/', label: '대시보드' }, { to: '/portfolio', label: '포트폴리오' },
  { to: '/watchlist', label: '워치리스트' }, { to: '/strategy', label: '전략' },
]
export default function Layout() {
  // 고정폭(1100px)이면 와이드 모니터에서 양옆이 비어 표가 좁게 눌린다 — 화면 폭을 다 쓰되,
  // 상한이 없으면 초광폭 모니터에서 표·칸이 끝없이 늘어나 오히려 빈 공간이 커진다 — 상한을 둔다
  return (
    <div style={{ width: '100%', maxWidth: 1800, margin: '0 auto', padding: '20px 24px 60px' }}>
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
    </div>
  )
}
