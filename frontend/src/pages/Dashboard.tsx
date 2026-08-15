import { Fragment, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { get, post } from '../api'
import type { Dashboard as DashboardData } from '../types'
import SentimentGauge from '../components/SentimentGauge'
import SignalBadge from '../components/SignalBadge'
import ScoreBar from '../components/ScoreBar'

const fmt = (n: number | null, cur = 'KRW') =>
  n === null ? '—' : (cur === 'USD' ? '$' : '₩') + n.toLocaleString('ko-KR', {
    maximumFractionDigits: cur === 'USD' ? 2 : 0 })

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = () => get<DashboardData>('/api/dashboard')
    .then(d => { setData(d); setError(null) }).catch(e => setError(String(e)))
  useEffect(() => { load() }, [])

  const refresh = async () => {
    setBusy(true)
    try { await post('/api/refresh'); await load() }
    catch (e) { setError(String(e)) }
    finally { setBusy(false) }
  }

  if (error) return (
    <div className="card">
      <div style={{ color: 'var(--sell)' }}>불러오기 실패: {error}</div>
      <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 6 }}>
        표시된 숫자가 없으므로 판단 근거로 쓰지 마세요.</div>
      <button style={{ marginTop: 10 }} onClick={() => { setError(null); load() }}>다시 시도</button>
    </div>
  )
  if (!data) return (
    <div className="grid">
      <div className="grid" style={{ gridTemplateColumns: '2fr 1fr' }}>
        <div className="card skeleton" style={{ minHeight: 130 }} />
        <div className="card skeleton" style={{ minHeight: 130 }} />
      </div>
      <div className="card skeleton" style={{ minHeight: 240 }} />
    </div>
  )
  const { sentiment: s, portfolio_summary: pf } = data
  const pnlCls = pf.total_pnl_krw >= 0 ? 'pos' : 'neg'

  return (
    <div className="grid">
      <div className="grid" style={{ gridTemplateColumns: '2fr 1fr' }}>
        <div className="card" style={{ display: 'flex', justifyContent: 'space-around' }}>
          <SentimentGauge label="주식 공포탐욕" value={s.cnn_fg} valueLabel={s.cnn_fg_label} />
          <SentimentGauge label="크립토 공포탐욕" value={s.crypto_fg} valueLabel={s.crypto_fg_label} />
          <div style={{ textAlign: 'center', alignSelf: 'center' }}>
            <div style={{ fontSize: 22, fontWeight: 700 }}>{s.vix?.toFixed(1) ?? '—'}</div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>VIX</div>
            {s.vkospi && <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
              VKOSPI {s.vkospi.toFixed(1)}</div>}
          </div>
        </div>
        <div className="card">
          <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>총자산 (평가액+예수금, KRW 환산)</div>
          <div style={{ fontSize: 24, fontWeight: 700 }}>{fmt(pf.total_asset_krw)}</div>
          <div className={pnlCls}>
            {pf.total_pnl_krw >= 0 ? '+' : ''}{fmt(pf.total_pnl_krw)} ({pf.total_pnl_pct}%)
          </div>
          {/* 현금은 원화+달러 합산(cash_pct와 같은 기준) — 포트폴리오 화면과 숫자가 달라지면
              어느 쪽을 믿어야 할지 판단이 멈춘다 */}
          <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 4 }}>
            평가액 {fmt(pf.total_value_krw)} · 현금 {fmt(pf.cash_krw + (pf.cash_usd_krw ?? 0))} ({pf.cash_pct}%) · 보유 {pf.holdings_count}종목</div>
        </div>
      </div>

      {data.rule_alerts.length > 0 && (
        <div className="card" style={{ borderColor: 'var(--accent)' }}>
          <strong>알림</strong>
          {data.rule_alerts.map((a, i) => (
            <div key={i} style={{ marginTop: 6 }}>
              <Link to={`/ticker/${a.symbol}`}>🔔 {a.message}</Link>
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
          <strong>오늘의 시그널</strong>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            {data.failed_sources.length > 0 &&
              <span style={{ color: 'var(--sell)', fontSize: 12 }}>
                일부 소스 갱신 실패: {data.failed_sources.join(', ')}</span>}
            <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
              기준: {data.last_refresh ?? '—'}</span>
            <button onClick={refresh} disabled={busy}>{busy ? '갱신 중…' : '새로고침'}</button>
          </div>
        </div>
        {data.signals.length === 0 &&
          <div style={{ color: 'var(--text-dim)' }}>
            워치리스트에 종목을 추가하면 시그널이 표시됩니다.</div>}
        <table>
          <thead><tr>
            <th>종목</th><th>현재가</th><th>등락</th><th>평단 대비</th><th>스윙</th><th>중장기</th>
          </tr></thead>
          <tbody>
            {data.signals.map((sig, idx) => {
              const tooltip = `${sig.summary ?? ''}${sig.context_note ? ` · ${sig.context_note}` : ''}`
              // 보유 → 관심 경계에 구분선. 보유 종목이 먼저 오도록 백엔드가 정렬한다.
              const boundary = !sig.is_holding && idx > 0 && data.signals[idx - 1].is_holding
              return (
              <Fragment key={sig.symbol}>
              {boundary && <tr><td colSpan={6} style={{ padding: '10px 0 4px', textAlign: 'left',
                fontSize: 11, color: 'var(--text-dim)', borderBottom: '1px solid var(--border)' }}>
                관심 종목</td></tr>}
              <tr>
                <td>
                  <Link to={`/ticker/${sig.symbol}`}>
                    <strong>{sig.name}</strong>
                    {sig.is_holding && <span style={{ color: 'var(--accent)', fontSize: 11 }}> 보유</span>}
                    {sig.grade_changed && <span style={{ color: 'var(--buy-strong)', fontSize: 11 }}> 등급변경</span>}
                    <div className="sig-tags" title={tooltip}>
                      {sig.summary_tags?.length
                        ? sig.summary_tags.map((t, i) => (
                            <span key={i} className={
                              `sig-tag ${t.score > 0 ? 'buy' : 'sell'}${Math.abs(t.score) >= 60 ? ' strong' : ''}`}>
                              {t.score > 0 ? '▲' : '▼'} {t.label}{t.warn && ' ⚠'}
                            </span>
                          ))
                        : <span className="signal-summary">{sig.summary ?? '뚜렷한 시그널 없음'}</span>}
                      {sig.context_note &&
                        <span className="sig-tag note">{sig.context_note}</span>}
                    </div>
                  </Link>
                </td>
                <td>{fmt(sig.close, sig.currency)}</td>
                <td className={(sig.change_pct ?? 0) >= 0 ? 'pos' : 'neg'}>
                  {sig.change_pct === null ? '—' : `${sig.change_pct >= 0 ? '+' : ''}${sig.change_pct}%`}</td>
                <td className={sig.holding_pnl_pct === null ? '' : sig.holding_pnl_pct >= 0 ? 'pos' : 'neg'}>
                  {sig.holding_pnl_pct === null ? '—' : <>
                    <strong>{sig.holding_pnl_pct >= 0 ? '+' : ''}{sig.holding_pnl_pct}%</strong>
                    <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                      평단 {fmt(sig.avg_price, sig.currency)}</div></>}</td>
                <td><div className="signal-cell">
                  <SignalBadge grade={sig.swing_grade} /><ScoreBar score={sig.swing_score} />
                </div></td>
                <td><div className="signal-cell">
                  <SignalBadge grade={sig.longterm_grade} /><ScoreBar score={sig.longterm_score} />
                </div></td>
              </tr>
              </Fragment>
            )})}
          </tbody>
        </table>
      </div>
    </div>
  )
}
