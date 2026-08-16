import { Fragment, useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { get, post } from '../api'
import type { Dashboard as DashboardData, SignalRow } from '../types'
import SentimentGauge from '../components/SentimentGauge'
import SignalBadge from '../components/SignalBadge'
import { isStale, relativeTime } from '../time'

const fmt = (n: number | null, cur = 'KRW') =>
  n === null ? '—' : (cur === 'USD' ? '$' : '₩') + n.toLocaleString('ko-KR', {
    maximumFractionDigits: cur === 'USD' ? 2 : 0 })

/** 등급의 방향만 뽑는다 (+1 매수 / 0 중립 / -1 매도). */
const dir = (grade: string) => grade.includes('매수') ? 1 : grade.includes('매도') ? -1 : 0

/** 스윙과 중장기가 반대 방향이면 어느 쪽을 따를지 화면이 알려주지 않아 오독이 생긴다.
 *  어느 쪽이 옳다고 말하는 대신, 판단에 필요한 질문(보유 기간)을 돌려준다. */
function conflictHint(sig: SignalRow): string | null {
  const s = dir(sig.swing_grade), l = dir(sig.longterm_grade)
  if (s === 0 || l === 0 || s === l) return null
  return s > 0
    ? '단기 매수 · 장기 매도 — 짧게 볼 자리인지 먼저 정하세요'
    : '단기 매도 · 장기 매수 — 눌림목인지 추세 이탈인지 먼저 정하세요'
}

type FilterKey = 'all' | 'holding' | 'buy' | 'sell' | 'changed'
const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'all', label: '전체' },
  { key: 'holding', label: '보유' },
  { key: 'buy', label: '매수 신호' },
  { key: 'sell', label: '매도 신호' },
  { key: 'changed', label: '등급변경' },
]
const matches: Record<FilterKey, (s: SignalRow) => boolean> = {
  all: () => true,
  holding: s => s.is_holding,
  buy: s => dir(s.swing_grade) > 0,
  sell: s => dir(s.swing_grade) < 0,
  changed: s => s.grade_changed,
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [now, setNow] = useState(Date.now())
  // 종목이 늘면 20행을 눈으로 훑게 된다 — 오늘 볼 것만 남기는 필터
  const [filter, setFilter] = useState<'all' | 'holding' | 'buy' | 'sell' | 'changed'>('all')

  const load = useCallback(() => get<DashboardData>('/api/dashboard')
    .then(d => { setData(d); setError(null); setNow(Date.now()) })
    .catch(e => setError(String(e))), [])
  useEffect(() => { load() }, [load])

  // 백엔드는 백그라운드로 갱신되지만 열어둔 탭은 그 사실을 모른다.
  // 탭으로 돌아올 때 다시 받고, 머무는 동안에도 "몇 분 전" 표기를 흘려보낸다.
  useEffect(() => {
    const onFocus = () => { if (document.visibilityState === 'visible') load() }
    document.addEventListener('visibilitychange', onFocus)
    window.addEventListener('focus', onFocus)
    const tick = setInterval(() => setNow(Date.now()), 30_000)
    return () => {
      document.removeEventListener('visibilitychange', onFocus)
      window.removeEventListener('focus', onFocus)
      clearInterval(tick)
    }
  }, [load])

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
      <div className="grid-2to1">
        <div className="card skeleton" style={{ minHeight: 130 }} />
        <div className="card skeleton" style={{ minHeight: 130 }} />
      </div>
      <div className="card skeleton" style={{ minHeight: 240 }} />
    </div>
  )
  const { sentiment: s, portfolio_summary: pf } = data
  const pnlCls = pf.total_pnl_krw >= 0 ? 'pos' : 'neg'
  const stale = isStale(data.last_refresh, now)
  const shown = data.signals.filter(matches[filter])

  return (
    <div className="grid">
      <div className="grid-2to1">
        <div className="card" style={{ display: 'flex', justifyContent: 'space-around',
                                       flexWrap: 'wrap', gap: 12 }}>
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
          {/* 분모를 밝히지 않으면 이 %가 총자산 등락률로 읽힌다. 현금 비중이 큰 계좌에서는
              두 값이 몇 배씩 벌어져 손실 체감이 부풀고 멀쩡한 포지션을 조기 청산하게 된다. */}
          <div className={pnlCls}>
            {pf.total_pnl_krw >= 0 ? '+' : ''}{fmt(pf.total_pnl_krw)}
            <span style={{ fontSize: 13 }}> (원금 대비 {pf.total_pnl_pct}%)</span>
          </div>
          <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>
            총자산 대비 {pf.total_pnl_pct_of_asset >= 0 ? '+' : ''}{pf.total_pnl_pct_of_asset}%
            {' · '}평가손익 (실현손익 제외)</div>
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
              {/* 장중 관통 후 회복은 종가만 보면 잡히지 않는다. 손절선이 지켜졌다고
                  믿는 것과 관통 사실을 아는 것은 다음 주문 크기를 바꾼다. */}
              {a.intraday_only && <span className="warn" style={{ fontSize: 11 }}> · 종가는 되돌아옴</span>}
            </div>
          ))}
          <div style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 8 }}>
            일봉 고저가 기준 판정입니다. 손절가는 자동 예약주문이 아니며, 갭 하락 시
            체결가는 손절선보다 낮을 수 있습니다.</div>
        </div>
      )}

      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10,
                      flexWrap: 'wrap', gap: 8 }}>
          <strong>오늘의 시그널</strong>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <span className={stale ? 'warn' : ''} style={{ fontSize: 12,
                    color: stale ? undefined : 'var(--text-dim)' }}
                  title={data.last_refresh ?? ''}>
              {stale && '⚠ '}기준: {relativeTime(data.last_refresh, now)}</span>
            <button onClick={refresh} disabled={busy}>{busy ? '갱신 중…' : '새로고침'}</button>
          </div>
        </div>

        {/* 경고는 시세 색과 다른 축이므로 --warn 으로 분리 */}
        {stale && <div className="warn-box" style={{ marginBottom: 10 }}>
          마지막 갱신이 2시간을 넘겼습니다. 표시된 가격·시그널이 현재 시장과 다를 수 있으니
          새로고침 후 판단하세요.</div>}
        {data.failed_sources.length > 0 && <div className="warn-box" style={{ marginBottom: 10 }}>
          일부 소스 갱신 실패: {data.failed_sources.join(', ')} — 해당 종목 값이 낡았을 수 있습니다.</div>}

        {data.signals.length > 0 && <div className="filter-chips">
          {FILTERS.map(f => {
            const n = data.signals.filter(matches[f.key]).length
            return (
              <button key={f.key} className={`chip${filter === f.key ? ' on' : ''}`}
                      aria-pressed={filter === f.key}
                      onClick={() => setFilter(f.key)}>
                {f.label} <span className="chip-n">{n}</span>
              </button>
            )
          })}
        </div>}

        {data.signals.length === 0 ? (
          <div className="empty">
            아직 추적 중인 종목이 없습니다.<br />
            <Link to="/watchlist">워치리스트</Link>에서 종목을 추가하면
            스윙·중장기 시그널이 여기에 표시됩니다.
          </div>
        ) : (
        <div className="table-scroll">
        <table>
          <thead><tr>
            <th>종목</th><th>현재가</th><th>등락</th><th>평단 대비</th><th>스윙</th><th>중장기</th>
          </tr></thead>
          <tbody>
            {shown.map((sig, idx) => {
              // 보유 → 관심 경계에 구분선. 보유 종목이 먼저 오도록 백엔드가 정렬한다.
              const boundary = !sig.is_holding && idx > 0 && shown[idx - 1].is_holding
              const hint = conflictHint(sig)
              const tags = sig.summary_tags ?? []
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
                    {/* 강등에도 상승색이 붙으면 나쁜 소식이 좋은 소식으로 읽힌다 */}
                    {sig.grade_changed && <span style={{ fontSize: 11,
                      color: sig.grade_change_dir > 0 ? 'var(--buy-strong)'
                           : sig.grade_change_dir < 0 ? 'var(--sell)' : 'var(--text-dim)' }}
                      title={`${sig.prev_grade ?? '—'} → ${sig.swing_grade}`}>
                      {' '}{sig.grade_change_dir > 0 ? '▲' : sig.grade_change_dir < 0 ? '▼' : ''}
                      {sig.prev_grade ?? ''}→{sig.swing_grade}</span>}
                    {/* 장중 미완성 봉 기반 등급 — 마감 때 뒤집힐 수 있다 */}
                    {sig.bar_complete === false && <span className="warn" style={{ fontSize: 11 }}
                      title={`${sig.bar_date} 봉이 마감 전입니다. 종가 확정 시 등급이 바뀔 수 있고, 백테스트는 확정 종가 신호만 검증했습니다.`}> 미확정</span>}
                  </Link>
                  {/* 행 요소를 줄이기 위해 근거는 2개까지만 노출하고 나머지는 접어둔다.
                      title 툴팁은 터치 기기에서 열리지 않으므로 <details> 로 대체. */}
                  <div className="sig-tags">
                    {tags.slice(0, 2).map((t, i) => (
                      <span key={i} className={
                        `sig-tag ${t.score > 0 ? 'buy' : 'sell'}${Math.abs(t.score) >= 60 ? ' strong' : ''}`}>
                        {t.score > 0 ? '▲' : '▼'} {t.label}{t.warn && ' ⚠'}
                      </span>
                    ))}
                    {tags.length === 0 &&
                      <span className="signal-summary">{sig.summary ?? '뚜렷한 시그널 없음'}</span>}
                  </div>
                  {hint && <div className="warn" style={{ fontSize: 11, marginTop: 4 }}>⚠ {hint}</div>}
                  {(sig.summary || sig.context_note || tags.length > 2) && (
                    <details>
                      <summary className="reason-toggle">근거 자세히</summary>
                      <div className="reason-body">
                        {sig.summary}
                        {sig.context_note && <><br />💡 {sig.context_note}</>}
                      </div>
                    </details>
                  )}
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
                  <SignalBadge grade={sig.swing_grade} />
                  <span style={{ color: 'var(--text-dim)', fontSize: 12, minWidth: 28 }}>
                    {sig.swing_score > 0 ? '+' : ''}{sig.swing_score.toFixed(0)}</span>
                </div></td>
                <td><div className="signal-cell">
                  <SignalBadge grade={sig.longterm_grade} />
                  <span style={{ color: 'var(--text-dim)', fontSize: 12, minWidth: 28 }}>
                    {sig.longterm_score > 0 ? '+' : ''}{sig.longterm_score.toFixed(0)}</span>
                </div></td>
              </tr>
              </Fragment>
            )})}
          </tbody>
        </table>
        </div>
        )}
        {/* 필터가 걸린 채 빈 화면이면 "종목이 없다"로 읽힌다 — 필터 탓임을 알린다 */}
        {data.signals.length > 0 && shown.length === 0 && <div className="empty">
          이 조건에 해당하는 종목이 없습니다.{' '}
          <button className="ghost" onClick={() => setFilter('all')}>전체 보기</button>
        </div>}
      </div>
    </div>
  )
}
