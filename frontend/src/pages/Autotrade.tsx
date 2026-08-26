import { useEffect, useState } from 'react'
import { get, post, put } from '../api'
import type { AutotradePlan, AutotradeStatus, StrategyPreset } from '../types'

const fmt = (n: number) => Math.round(n).toLocaleString()
const REASON = { enter: '진입', exit_signal: '청산 시그널', stop: '손절' } as const

export default function Autotrade() {
  const [status, setStatus] = useState<AutotradeStatus | null>(null)
  const [presets, setPresets] = useState<StrategyPreset[]>([])
  const [preset, setPreset] = useState('')
  const [params, setParams] = useState<Record<string, number>>({})
  const [regimeFilter, setRegimeFilter] = useState(true)
  const [plan, setPlan] = useState<AutotradePlan | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')

  async function reload() {
    const s = await get<AutotradeStatus>('/api/autotrade/status')
    setStatus(s)
    setPreset(s.settings.preset)
    setParams(s.settings.params)
    setRegimeFilter(s.settings.regime_filter)
  }

  useEffect(() => {
    Promise.all([
      reload(),
      get<StrategyPreset[]>('/api/strategy/presets')
        // 횡단면 전략은 관심종목 모집단에서 상대 랭킹의 의미가 달라져
        // 자동매매 대상이 아니다 — 애초에 고를 수 없게 한다
        .then(ps => setPresets(ps.filter(p => p.autotrade_capable))),
    ]).catch(e => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  const current = presets.find(p => p.key === preset)
  const live = status?.mode === 'live'

  async function saveSettings() {
    setBusy('save'); setError('')
    try {
      await put('/api/autotrade/settings',
                { preset, params, regime_filter: regimeFilter })
      await reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally { setBusy('') }
  }

  async function makePlan() {
    setBusy('plan'); setError('')
    try {
      setPlan(await post<AutotradePlan>('/api/autotrade/plan'))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally { setBusy('') }
  }

  async function execute() {
    // 실전 모드는 브라우저 확인창을 한 번 더 거친다 — 클릭 실수가 실제 주문이 되면 안 된다
    if (live && !window.confirm(
      '실전 계좌로 실제 주문이 나갑니다. 계속하시겠습니까?')) return
    setBusy('exec'); setError('')
    try {
      setPlan(await post<AutotradePlan>('/api/autotrade/execute', { confirm: true }))
      await reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally { setBusy('') }
  }

  if (!status) return <div className="card skeleton" style={{ minHeight: 200 }} />

  return (
    <>
      <div className="card">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <strong>자동매매</strong>
          <span className={live ? 'neg' : 'pos'}
                style={{ fontSize: 12, fontWeight: 700,
                         border: '1px solid currentColor', borderRadius: 4,
                         padding: '1px 8px' }}>
            {live ? '실전투자' : '모의투자'}
          </span>
        </div>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 4 }}>
          전략 연구실에서 검증한 규칙 그대로 오늘의 주문을 만듭니다(국내 종목만).
          장 시작 전에 계획을 확인하고 실행하세요. 진입은 시장가, 손절은 진입가
          −2×ATR, 사이징은 1% 룰, 신규 진입은 KOSPI가 200일선 위일 때만입니다.
          수익을 보장하지 않습니다.
        </div>
        {!status.configured && (
          <div className="warn" style={{ marginTop: 8, fontSize: 12 }}>
            ⚠ KIS API 키가 없습니다. 한국투자증권 개발자센터에서 키를 발급받아
            루트 <code>.env</code>에 KIS_APP_KEY / KIS_APP_SECRET / KIS_ACCOUNT를
            넣고 서버를 재시작하세요. (KIS_MODE=paper가 모의투자입니다)
          </div>
        )}
      </div>

      <div className="card">
        <strong>실행 전략</strong>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap',
                      alignItems: 'center', marginTop: 10 }}>
          <select value={preset} onChange={e => {
            const p = presets.find(x => x.key === e.target.value)
            if (!p) return
            setPreset(p.key)
            setParams(Object.fromEntries(
              Object.entries(p.params).map(([k, m]) => [k, m.default])))
          }}>
            {presets.map(p => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select>
          {current && Object.entries(current.params).map(([k, meta]) => (
            <label key={k} style={{ fontSize: 12, color: 'var(--text-dim)' }}>
              {meta.label}{' '}
              <input type="number" value={params[k] ?? meta.default}
                     min={meta.min} max={meta.max} style={{ width: 78 }}
                     onChange={e => setParams(
                       { ...params, [k]: Number(e.target.value) })} />
            </label>
          ))}
          <label style={{ fontSize: 12, display: 'flex', alignItems: 'center', gap: 4 }}>
            <input type="checkbox" checked={regimeFilter}
                   onChange={e => setRegimeFilter(e.target.checked)} />
            레짐 필터 (KOSPI 200일선 위에서만 진입)
          </label>
          <button onClick={saveSettings} disabled={busy !== ''}>
            {busy === 'save' ? '저장 중…' : '설정 저장'}</button>
        </div>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 6 }}>
          파라미터는 전략 연구실의 최적화에서 검증 성과가 좋았던 조합을 쓰세요.
        </div>
        {!regimeFilter && (
          <div className="warn" style={{ marginTop: 6, fontSize: 12 }}>
            ⚠ 레짐 필터를 끈 구성은 krx300 워크포워드 검증에서 5폴드 전패
            (초과수익 중앙값 −16.3%p, MDD −56%)했습니다. 켜면 MDD가 절반
            (−28%)으로 줄어듭니다.
          </div>
        )}
      </div>

      <div className="card">
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <strong>오늘의 주문</strong>
          <button onClick={makePlan} disabled={busy !== '' || !status.configured}>
            {busy === 'plan' ? '계산 중…' : '계획 생성 (주문 안 나감)'}</button>
          {plan && plan.orders.length > 0 && !plan.orders[0].status && (
            <button onClick={execute} disabled={busy !== ''}
                    className={live ? 'neg' : undefined}>
              {busy === 'exec' ? '발송 중…'
                : live ? '실전 주문 실행' : '모의 주문 실행'}</button>
          )}
        </div>
        {error && <div className="warn" style={{ marginTop: 8 }}>⚠ {error}</div>}
        {plan && (
          <>
            <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 8 }}>
              신호 기준일 {plan.as_of ?? '—'} · 총평가 ₩{fmt(plan.equity_krw)} ·
              예수금 ₩{fmt(plan.cash_krw)} · {plan.preset}{' '}
              {Object.entries(plan.params).map(([k, v]) => `${k}=${v}`).join(' ')}
            </div>
            <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 2 }}>
              스캔 {plan.universe.size}종목(관심종목) · 레짐{' '}
              {!plan.regime.enabled ? 'OFF'
                : plan.regime.ok === null ? <span className="neg">판정 불가 — 신규 진입 차단</span>
                : plan.regime.ok
                  ? <span className="pos">통과 (지수 {fmt(plan.regime.bench_close!)} &gt;{' '}
                      {plan.regime.ma}일선 {fmt(plan.regime.bench_ma!)})</span>
                  : <span className="neg">차단 (지수 {fmt(plan.regime.bench_close!)} &lt;{' '}
                      {plan.regime.ma}일선 {fmt(plan.regime.bench_ma!)})</span>}
            </div>
            {plan.warnings.map((w, i) => (
              <div key={i} className="warn" style={{ marginTop: 6, fontSize: 12 }}>⚠ {w}</div>
            ))}
            {plan.orders.length === 0
              ? <div className="empty">오늘은 낼 주문이 없습니다.</div>
              : <div className="table-scroll" style={{ marginTop: 8 }}>
                  <table>
                    <thead><tr>
                      <th>구분</th><th>종목</th><th>수량</th><th>기준가</th>
                      <th>손절선</th><th>사유</th><th>상태</th>
                    </tr></thead>
                    <tbody>
                      {plan.orders.map((o, i) => (
                        <tr key={i}>
                          <td className={o.side === 'BUY' ? 'pos' : 'neg'}>
                            {o.side === 'BUY' ? '매수' : '매도'}</td>
                          <td>{o.name}</td>
                          <td>{fmt(o.qty)}</td>
                          <td>₩{fmt(o.price_ref)}</td>
                          <td>{o.stop === null ? '—' : `₩${fmt(o.stop)}`}</td>
                          <td>{REASON[o.reason]}</td>
                          <td>{o.status === 'sent' ? `발송 (${o.order_no})`
                            : o.status === 'failed' ? <span className="neg">실패: {o.error}</span>
                            : '계획'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>}
          </>
        )}
      </div>

      <div className="card">
        <strong>자동 포지션 ({status.positions.length})</strong>
        {status.positions.length === 0
          ? <div className="empty">자동매매로 보유 중인 종목이 없습니다.</div>
          : <div className="table-scroll" style={{ marginTop: 8 }}>
              <table>
                <thead><tr>
                  <th>종목</th><th>수량</th><th>진입가</th><th>손절선</th><th>진입일</th>
                </tr></thead>
                <tbody>
                  {status.positions.map(p => (
                    <tr key={p.symbol}>
                      <td>{p.symbol}</td>
                      <td>{fmt(p.qty)}</td>
                      <td>₩{fmt(p.entry_price)}
                        {!p.fill_synced && <span style={{ color: 'var(--text-dim)' }}> (근사)</span>}</td>
                      <td>₩{fmt(p.stop)}</td>
                      <td>{p.entry_date}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>}
      </div>

      <div className="card">
        <strong>주문 이력</strong>
        {status.orders.length === 0
          ? <div className="empty">아직 발송한 주문이 없습니다.</div>
          : <div className="table-scroll" style={{ marginTop: 8 }}>
              <table>
                <thead><tr>
                  <th>시각</th><th>모드</th><th>구분</th><th>종목</th>
                  <th>수량</th><th>사유</th><th>상태</th>
                </tr></thead>
                <tbody>
                  {status.orders.map(o => (
                    <tr key={o.id}>
                      <td>{o.created_at}</td>
                      <td>{o.mode === 'live' ? '실전' : '모의'}</td>
                      <td className={o.side === 'BUY' ? 'pos' : 'neg'}>
                        {o.side === 'BUY' ? '매수' : '매도'}</td>
                      <td>{o.name ?? o.symbol}</td>
                      <td>{fmt(o.qty)}</td>
                      <td>{REASON[o.reason]}</td>
                      <td>{o.status === 'sent' ? `발송 (${o.order_no ?? '—'})`
                        : <span className="neg">실패: {o.error ?? '—'}</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>}
      </div>
    </>
  )
}
