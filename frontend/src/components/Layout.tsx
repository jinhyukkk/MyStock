import { NavLink, Outlet } from 'react-router-dom'

const tabs = [
  { to: '/', label: '대시보드' }, { to: '/portfolio', label: '포트폴리오' },
  { to: '/watchlist', label: '워치리스트' },
]
export default function Layout() {
  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', padding: '20px 16px 60px' }}>
      <header style={{ display: 'flex', alignItems: 'center', gap: 24, marginBottom: 20 }}>
        <h1 style={{ fontSize: 20 }}>MyStock</h1>
        <nav style={{ display: 'flex', gap: 4 }}>
          {tabs.map(t => (
            <NavLink key={t.to} to={t.to} end={t.to === '/'}
              style={({ isActive }) => ({
                padding: '6px 14px', borderRadius: 6,
                color: isActive ? 'var(--text)' : 'var(--text-dim)',
                background: isActive ? 'var(--bg-card)' : 'transparent',
              })}>{t.label}</NavLink>
          ))}
        </nav>
      </header>
      <Outlet />
      <footer style={{ marginTop: 40, color: 'var(--text-dim)', fontSize: 12,
                       textAlign: 'center' }}>
        본 시그널은 지표 기반 참고 정보이며 투자 자문이 아닙니다.
      </footer>
    </div>
  )
}
