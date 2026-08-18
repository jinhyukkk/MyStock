import { Fragment, useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { get, post } from '../api'
import type { Dashboard as DashboardData, SignalRow } from '../types'
import SentimentGauge from '../components/SentimentGauge'
import SignalBadge from '../components/SignalBadge'
import ScoreScale from '../components/ScoreScale'
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

type FilterKey = 'action' | 'all' | 'holding' | 'buy' | 'sell' | 'changed'
// 손절선까지 이 거리 안에 들어오면 "임박"으로 본다. 하루 변동폭 안에 손절선이
// 들어왔다는 뜻이라 다음 장에서 결정을 강요받을 수 있다.
const STOP_NEAR_PCT = 2
// 정리 후보 이름을 다 늘어놓으면 카드 한 장을 넘긴다 — 나머지는 개수로만
const TRIM_SHOWN = 4

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: 'action', label: '액션 필요' },
  { key: 'all', label: '전체' },
  { key: 'holding', label: '보유' },
  { key: 'buy', label: '매수 신호' },
  { key: 'sell', label: '매도 신호' },
  { key: 'changed', label: '등급변경' },
]

/** 필터 술어. '액션 필요'는 오늘의 행동 카드와 같은 근거를 써야 한다 —
 *  위에서 경고한 종목이 아래 표에서 필터에 걸러지면 화면이 자기 말을 뒤집는다. */
function matchers(d: DashboardData): Record<FilterKey, (s: SignalRow) => boolean> {
  const alerted = new Set(d.rule_alerts.map(a => a.symbol))
  const unstopped = new Set(d.unstopped.map(u => u.symbol))
  const trim = new Set(d.position_rule.trim_candidates.map(c => c.symbol))
  return {
    action: s => alerted.has(s.symbol) || trim.has(s.symbol) || unstopped.has(s.symbol)
      || s.grade_changed
      || (s.stop_distance_pct !== null && s.stop_distance_pct > -STOP_NEAR_PCT),
    all: () => true,
    holding: s => s.is_holding,
    buy: s => dir(s.swing_grade) > 0,
    sell: s => dir(s.swing_grade) < 0,
    changed: s => s.grade_changed,
  }
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [now, setNow] = useState(Date.now())
  // 종목이 늘면 20행을 눈으로 훑게 된다 — 오늘 볼 것만 남기는 필터.
  // 기본값이 '전체'면 매일 15행을 다시 훑어야 하고, 그 스캔은 며칠 만에
  // 형식적인 확인으로 바뀐다. 기본은 결정이 필요한 것만 남긴다.
  const [filter, setFilter] = useState<FilterKey>('action')

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
  const { sentiment: s, portfolio_summary: pf, position_rule: pr } = data
  const pnlCls = pf.total_pnl_krw >= 0 ? 'pos' : 'neg'
  const stale = isStale(data.last_refresh, now)
  const matches = matchers(data)
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
          {/* 기타자산을 빼놓으면 평가액+현금이 총자산에 못 미쳐, 화면이 설명하지
              못하는 금액이 남는다 — 발행어음·펀드는 둘 어디에도 안 잡힌다 */}
          <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 4 }}>
            평가액 {fmt(pf.total_value_krw)} · 현금 {fmt(pf.cash_krw + (pf.cash_usd_krw ?? 0))} ({pf.cash_pct}%)
            {pf.other_assets_krw > 0 && ` · 기타자산 ${fmt(pf.other_assets_krw)}`}</div>
          {/* 종목 수는 비중·총리스크 한도를 모두 통과해도 혼자 깨질 수 있는 규율이라
              보유 개수를 목표 범위와 같은 줄에 세운다 — 숫자만 두면 많고 적음이 안 읽힌다. */}
          <div style={{ fontSize: 12, marginTop: 4 }}>
            <span className={pr.status === 'ok' ? '' : 'warn'}>
              {pr.status !== 'ok' && '⚠ '}보유 {pr.count}종목 / 목표 {pr.min}~{pr.max}
              {pr.status === 'over' && ` · ${pr.excess}종목 초과`}
              {pr.status === 'under' && ` · ${pr.shortfall}종목 부족`}</span>
            {/* 초과라고만 하면 무엇을 덜지 사용자가 다시 표를 훑는다 — 이유와 함께 이름을 준다.
                다만 종목명 5개를 이유까지 붙여 늘어놓으면 카드를 넘겨 아무도 안 읽는다:
                식별은 심볼(짧고 정확)로, 이유는 종류만 한 번 모아 쓴다. */}
            {pr.status === 'over' && <span style={{ color: 'var(--text-dim)' }}>
              {' · 정리 후보 '}
              {pr.trim_candidates.slice(0, TRIM_SHOWN).map((c, i) => (
                <span key={c.symbol}>{i > 0 && ', '}
                  <Link to={`/ticker/${c.symbol}`} title={`${c.name} — ${c.reason}`}>
                    {c.symbol}</Link></span>
              ))}
              {pr.trim_candidates.length > TRIM_SHOWN &&
                ` 외 ${pr.trim_candidates.length - TRIM_SHOWN}`}
              {` (${[...new Set(pr.trim_candidates.map(c => c.reason))].join(' · ')})`}</span>}
            {pr.status === 'under' && <span style={{ color: 'var(--text-dim)' }}>
              {' · '}<Link to="/watchlist">워치리스트</Link>에서 매수 후보를 보세요</span>}
          </div>
        </div>
      </div>

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
        {/* 시세는 갱신되는데 잔고만 안 들어오면 화면은 최신처럼 보인다 — 그 상태로
            매도한 종목이 표에 남고, 그 비중 위에서 다음 포지션 크기를 정하게 된다 */}
        {data.broker_failed && <div className="warn-box" style={{ marginBottom: 10 }}>
          ⚠ 증권사 연동 실패: {data.broker_failed}
          <div style={{ fontSize: 12, marginTop: 4 }}>
            보유·예수금은 {data.broker_synced_at
              ? `${data.broker_synced_at.replace('T', ' ')} 잔고`
              : '마지막으로 성공한 잔고'} 기준입니다 — 그 뒤의 매매는 반영되지 않았습니다.{' '}
            <Link to="/portfolio/settings">설정</Link>에서 다시 동기화하세요.</div></div>}

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
        <div className="table-scroll table-cards">
        <table>
          <thead><tr>
            <th>종목</th><th>현재가</th><th>등락</th><th>평단 대비</th><th>손절까지</th>
            <th>스윙</th><th>중장기</th>
          </tr></thead>
          <tbody>
            {shown.map((sig, idx) => {
              // 보유 → 관심 경계에 구분선. 보유 종목이 먼저 오도록 백엔드가 정렬한다.
              const boundary = !sig.is_holding && idx > 0 && shown[idx - 1].is_holding
              const hint = conflictHint(sig)
              const tags = sig.summary_tags ?? []
              return (
              <Fragment key={sig.symbol}>
              {boundary && <tr><td colSpan={7} style={{ padding: '10px 0 4px', textAlign: 'left',
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
                    {tags.length > 0 && <span className="sig-tags-label">근거</span>}
                    {tags.slice(0, 2).map((t, i) => {
                      // 태그는 결론이 아니라 결론에 들어간 재료다. 최종 등급과
                      // 반대 방향인 태그가 같은 무게로 보이면 "MACD 상승 모멘텀"과
                      // "강력매도"가 나란히 서서 어느 쪽이 판단인지 사라진다.
                      const against = dir(sig.swing_grade) !== 0
                        && Math.sign(t.score) !== dir(sig.swing_grade)
                      return (
                      <span key={i} title={against
                              ? `이 근거는 최종 판단(${sig.swing_grade})과 반대 방향입니다 — 다른 지표에 밀린 소수 의견입니다`
                              : undefined}
                            className={`sig-tag ${t.score > 0 ? 'buy' : 'sell'}`
                              + (Math.abs(t.score) >= 60 && !against ? ' strong' : '')
                              + (against ? ' against' : '')}>
                        {against ? '↔ ' : t.score > 0 ? '▲ ' : '▼ '}{t.label}{t.warn && ' ⚠'}
                      </span>
                    )})}
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
                <td data-label="현재가">{fmt(sig.close, sig.currency)}</td>
                <td data-label="등락" className={(sig.change_pct ?? 0) >= 0 ? 'pos' : 'neg'}>
                  {sig.change_pct === null ? '—' : `${sig.change_pct >= 0 ? '+' : ''}${sig.change_pct}%`}</td>
                <td data-label="평단 대비"
                    className={sig.holding_pnl_pct === null ? '' : sig.holding_pnl_pct >= 0 ? 'pos' : 'neg'}>
                  {sig.holding_pnl_pct === null ? '—' : <>
                    <strong>{sig.holding_pnl_pct >= 0 ? '+' : ''}{sig.holding_pnl_pct}%</strong>
                    <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                      평단 {fmt(sig.avg_price, sig.currency)}</div></>}</td>
                {/* 룰 알림은 손절선을 뚫어야 난다 — 남은 거리를 먼저 보여준다 */}
                <td data-label="손절까지"
                    className={sig.stop_distance_pct !== null
                      && sig.stop_distance_pct > -STOP_NEAR_PCT ? 'warn' : ''}>
                  {sig.stop_distance_pct === null ? '—' : <>
                    <strong>{sig.stop_distance_pct}%</strong>
                    <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                      {sig.stop_source === 'rule' ? '' : '2×ATR '}
                      {fmt(sig.stop_price, sig.currency)}</div></>}</td>
                {/* 점수 옆 눈금 — 숫자만 있으면 -21이 얼마나 나쁜지 읽을 수 없고,
                    스윙과 중장기의 컷이 다르다는 사실도 화면에 나타나지 않는다 */}
                <td data-label="스윙"><div className="signal-cell">
                  <SignalBadge grade={sig.swing_grade} />
                  <span style={{ color: 'var(--text-dim)', fontSize: 12, minWidth: 28 }}>
                    {sig.swing_score > 0 ? '+' : ''}{sig.swing_score.toFixed(0)}</span>
                  <ScoreScale score={sig.swing_score} cuts={data.score_scale.swing} kind="swing" />
                </div></td>
                <td data-label="중장기"><div className="signal-cell">
                  <SignalBadge grade={sig.longterm_grade} />
                  <span style={{ color: 'var(--text-dim)', fontSize: 12, minWidth: 28 }}>
                    {sig.longterm_score > 0 ? '+' : ''}{sig.longterm_score.toFixed(0)}</span>
                  <ScoreScale score={sig.longterm_score} cuts={data.score_scale.longterm}
                              kind="longterm" />
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
          {filter === 'action'
            ? '오늘 결정이 필요한 종목이 없습니다 — 룰 도달·손절 임박·등급 변경·손절 룰 미등록 모두 0건.'
            : '이 조건에 해당하는 종목이 없습니다.'}{' '}
          <button className="ghost" onClick={() => setFilter('all')}>전체 보기</button>
        </div>}
      </div>
    </div>
  )
}
