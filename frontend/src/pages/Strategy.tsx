import { useEffect, useState } from 'react'
import { get, post } from '../api'
import EquityCurve from '../components/EquityCurve'
import type { StrategyPreset, StrategyResult } from '../types'

const fmt = (n: number) => Math.round(n).toLocaleString()
const signed = (n: number) => `${n >= 0 ? '+' : ''}${n}%`
const REASON_LABEL = { stop: '손절', signal: '신호', end: '기간종료' } as const

export default function Strategy() {
  const [presets, setPresets] = useState<StrategyPreset[]>([])
  const [key, setKey] = useState('')
  const [params, setParams] = useState<Record<string, number>>({})
  const [capital, setCapital] = useState(10_000_000)
  const [result, setResult] = useState<StrategyResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    get<StrategyPreset[]>('/api/strategy/presets')
      .then(ps => {
        setPresets(ps)
        if (ps.length) applyPreset(ps[0])
      })
      .catch(e => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  function applyPreset(p: StrategyPreset) {
    setKey(p.key)
    setParams(Object.fromEntries(
      Object.entries(p.params).map(([k, meta]) => [k, meta.default])))
    setResult(null)
  }

  const current = presets.find(p => p.key === key)

  async function run() {
    setBusy(true); setError('')
    try {
      setResult(await post<StrategyResult>('/api/strategy/backtest', {
        preset: key, params, initial_capital_krw: capital,
      }))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const m = result?.metrics
  const stopped = result
    ? result.trades.filter(t => t.exit_reason === 'stop').length : 0

  return (
    <>
      <div className="card">
        <strong>전략 연구실</strong>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 4 }}>
          매매 규칙을 계좌 단위로 돌려 자본곡선을 만듭니다. 종목별 등급 검증은
          종목 상세의 백테스트 표에 있습니다.
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap',
                      alignItems: 'center', marginTop: 10 }}>
          <select value={key} onChange={e => {
            const p = presets.find(x => x.key === e.target.value)
            if (p) applyPreset(p)
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
          <label style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            초기자본{' '}
            <input type="number" value={capital} step={1_000_000}
                   style={{ width: 130 }}
                   onChange={e => setCapital(Number(e.target.value))} />
          </label>
          <button onClick={run} disabled={busy || !key}>
            {busy ? '계산 중…' : '실행'}</button>
        </div>
        {error && <div className="warn" style={{ marginTop: 8 }}>⚠ {error}</div>}
      </div>

      {result && (
        <>
          {/* 이 경고를 지우면 숫자만 남고 전제가 사라진다 —
              검증했다고 믿는 상태가 검증 안 한 상태보다 위험하다 */}
          <div className="card warn" style={{ fontSize: 12 }}>
            ⚠ {result.universe_warning} (유니버스 {result.universe_size}종목,
            동시 보유 최대 {result.max_concurrent}종목)
            <div style={{ color: 'var(--text-dim)', marginTop: 4 }}>
              {result.fx_note} 샤프는 무위험수익률 0 가정입니다.</div>
          </div>

          <div className="card">
            <strong>자본곡선</strong>
            <EquityCurve series={[
              { label: '전략', color: 'var(--buy)', points: result.equity_curve },
              { label: `${result.benchmark_label ?? '벤치마크'} 매수보유`,
                color: 'var(--text-dim)', points: result.benchmark },
              { label: `${result.universe_size}종목 동일가중 보유`,
                color: 'var(--sell)', points: result.buy_and_hold },
            ]} />
          </div>

          <div className="card">
            <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
              {m && ([
                ['CAGR', signed(m.cagr)],
                ['MDD', `${m.mdd}%`],
                ['샤프', m.sharpe === null ? '—' : String(m.sharpe)],
                ['승률', m.win_rate === null ? '—' : `${m.win_rate}%`],
                ['거래', `${m.trade_count}회`],
                ['손절종료', m.trade_count
                  ? `${Math.round(stopped / m.trade_count * 100)}%` : '—'],
                ['최종자본', `₩${fmt(m.final_equity_krw)}`],
              ] as const).map(([label, value]) => (
                <div key={label}>
                  <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>{label}</div>
                  <div style={{ fontSize: 18, fontWeight: 700 }}>{value}</div>
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <strong>거래 내역 ({result.trades.length}건)</strong>
            {result.trades.length === 0
              ? <div className="empty">이 파라미터에서는 진입 신호가 없었습니다.</div>
              : <div className="table-scroll">
                  <table>
                    <thead><tr>
                      <th>종목</th><th>진입</th><th>청산</th><th>사유</th>
                      <th>수량</th><th>비용</th><th>손익</th>
                    </tr></thead>
                    <tbody>
                      {result.trades.map((t, i) => (
                        <tr key={`${t.symbol}-${t.entry_date}-${i}`}>
                          <td>{t.name}</td>
                          <td>{t.entry_date}</td>
                          <td>{t.exit_date}</td>
                          <td>{REASON_LABEL[t.exit_reason]}</td>
                          <td>{fmt(t.qty)}</td>
                          <td style={{ color: 'var(--text-dim)' }}>
                            ₩{fmt(t.cost_krw)}</td>
                          <td className={t.pnl_krw >= 0 ? 'pos' : 'neg'}>
                            ₩{fmt(t.pnl_krw)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>}
          </div>
        </>
      )}
    </>
  )
}
