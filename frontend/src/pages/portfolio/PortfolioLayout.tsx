import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { get } from '../../api'
import type { CashFlow, Portfolio as PF, Trade } from '../../types'
import { isStale, relativeTime } from '../../time'
import { fmt } from '../../format'
import type { PortfolioContext } from './context'

const SUBTABS = [
  { to: '/portfolio', label: '보유', end: true },
  { to: '/portfolio/risk', label: '리스크', end: false },
  { to: '/portfolio/realized', label: '복기', end: false },
  { to: '/portfolio/income', label: '배당·현금흐름', end: false },
  { to: '/portfolio/journal', label: '매매 기록', end: false },
]

export default function PortfolioLayout() {
  const [pf, setPf] = useState<PF | null>(null)
  const [trades, setTrades] = useState<Trade[]>([])
  const [flows, setFlows] = useState<CashFlow[]>([])
  // 목표 종목 수 — 스타일이 바뀌면 룰도 바뀌어야 한다. 상수로 박아두면
  // 화면이 남의 규율을 강요하게 되고, 그런 경고는 며칠 만에 무시된다.
  const [posRule, setPosRule] = useState({ min: '', max: '' })
  const [cashWarn, setCashWarn] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [now, setNow] = useState(Date.now())

  const load = () => Promise.all([
    get<PF>('/api/portfolio'),
    get<Trade[]>('/api/trades'),
    get<CashFlow[]>('/api/cash-flows'),
    get<{ min: number; max: number }>('/api/position-rule'),
  ]).then(([p, tr, fl, pr]) => {
    setPf(p); setTrades(tr); setFlows(fl); setError(null); setNow(Date.now())
    setPosRule({ min: String(pr.min), max: String(pr.max) })
  }).catch(e => setError(String(e)))
  useEffect(() => { load() }, [])

  // 에러를 스켈레톤보다 먼저 검사한다 — 순서가 반대면 실패 시 영원히 로딩 화면으로 보인다.
  if (error) return (
    <div className="card">
      <div style={{ color: 'var(--sell)' }}>불러오기 실패: {error}</div>
      <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 6 }}>
        계좌 숫자를 불러오지 못했습니다. 판단 근거로 쓰지 마세요.</div>
      <button style={{ marginTop: 10 }} onClick={() => { setError(null); load() }}>다시 시도</button>
    </div>
  )
  if (!pf) return (
    <div className="grid">
      <div className="grid-2">
        <div className="card skeleton" style={{ minHeight: 180 }} />
        <div className="card skeleton" style={{ minHeight: 180 }} />
      </div>
      <div className="card skeleton" style={{ minHeight: 200 }} />
    </div>
  )

  const t = pf.totals
  const stale = isStale(pf.last_refresh, now)
  return (
    <div className="grid">
      {/* 계좌 규모가 화면에서 사라지면 포지션 사이즈 판단이 끊긴다 — 모든 탭에 고정한다 */}
      <div className="card pf-strip">
        <div>
          <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>총자산 (평가액 + 예수금, KRW 환산)</div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>₩{fmt(t.total_asset_krw)}</div>
        </div>
        <div>
          <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>평가손익</div>
          <div className={t.total_pnl_krw >= 0 ? 'pos' : 'neg'} style={{ fontSize: 18, fontWeight: 700 }}>
            {t.total_pnl_krw >= 0 ? '+' : ''}₩{fmt(t.total_pnl_krw)}
            <span style={{ fontSize: 12 }}> (원금 대비 {t.total_pnl_pct}%)</span></div>
        </div>
        <div>
          <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>현금</div>
          <div style={{ fontSize: 18, fontWeight: 700 }}>
            ₩{fmt(t.cash_krw + (t.cash_usd_krw ?? 0))}
            <span style={{ fontSize: 12, color: 'var(--text-dim)' }}> ({t.cash_pct}%)</span></div>
        </div>
        <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
          {/* 이 계좌 숫자가 언제 가격 기준인지 — 낡은 값으로 사이즈를 정하면 안 된다 */}
          <div className={stale ? 'warn' : ''} style={{ fontSize: 11,
                 color: stale ? undefined : 'var(--text-dim)' }} title={pf.last_refresh ?? ''}>
            {stale && '⚠ '}기준: {relativeTime(pf.last_refresh, now)}</div>
          {/* 환율이 화면에 없으면 KRW 숫자에서 역산해야 하고, 수집 실패로 기본값을
              쓴 경우와 실제 시세를 쓴 경우가 구분되지 않는다 */}
          <div className={t.usdkrw_estimated ? 'warn' : ''} style={{ fontSize: 11,
                 color: t.usdkrw_estimated ? undefined : 'var(--text-dim)' }}>
            {t.usdkrw_estimated ? '⚠ 환율 수집 실패 — 기본값 ' : '적용 환율 '}₩{fmt(t.usdkrw)}/$
            {t.usdkrw_estimated && ' 로 환산했습니다. USD 종목의 원화 숫자는 참고용입니다.'}</div>
        </div>
      </div>
      {/* 예수금이 조용히 0으로 잘리면 총자산과 1% 리스크 수량이 함께 어긋난다 */}
      {cashWarn && <div className="warn-box">⚠ {cashWarn}
        <button className="ghost" style={{ marginLeft: 8 }}
                onClick={() => setCashWarn(null)}>확인</button></div>}
      <nav className="subtabs">
        {SUBTABS.map(s => (
          <NavLink key={s.to} to={s.to} end={s.end}
            className={({ isActive }) => isActive ? 'subtab active' : 'subtab'}>
            {s.label}</NavLink>
        ))}
      </nav>
      <Outlet context={{ pf, trades, flows, posRule, setPosRule,
                         reload: load, setCashWarn } satisfies PortfolioContext} />
    </div>
  )
}
