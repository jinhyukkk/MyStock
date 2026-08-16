import SignalBadge from './SignalBadge'
import type { Backtest, BacktestGrade } from '../types'

/** horizon 접미사가 붙은 필드를 꺼낸다 (`avg_fwd` + 20 → `avg_fwd20`). */
const pick = (g: BacktestGrade, key: string, h: number) => g[`${key}${h}`]
const num = (v: unknown): number | null => (typeof v === 'number' ? v : null)
const signed = (v: number, unit = '%') => `${v >= 0 ? '+' : ''}${v}${unit}`
const backtestSpan = (bt: Backtest) => `${bt.start}~${bt.end}`

/** 등급별 성과 표.
 *
 *  숫자를 그냥 보여주면 "+4%"와 "+4% ± 1%p (독립 표본 202)"를 구분할 수 없다.
 *  그래서 평균 옆에 항상 ±1 표준오차를 붙이고, 표준오차는 신호일 수가 아니라
 *  **비중첩 에피소드 수**로 계산된 값을 쓴다. 에피소드가 하한 미만이면 수치를
 *  아예 감춘다 — 표본 6개 평균에 색까지 입히면 강한 사실처럼 읽힌다.
 */
export default function BacktestTable({ bt, grades, horizons, missing, caption }: {
  bt: Backtest
  grades: BacktestGrade[]
  horizons: number[]
  missing: string[]
  caption: string
}) {
  if (grades.length === 0) return (
    <div style={{ color: 'var(--text-dim)', fontSize: 13, marginTop: 8 }}>
      {caption} — 검증 구간을 채울 데이터가 아직 없습니다.</div>
  )
  // 관측 기간이 만들 수 있는 비중첩 표본 상한이 하한보다 작으면, 데이터가 더 쌓여서
  // 채워질 칸이 아니다. 그 구분을 안 하면 오지 않을 숫자를 기다리게 된다.
  const unverifiable = horizons.filter(h => (bt.max_episodes?.[String(h)] ?? Infinity) < bt.min_episodes)
  return (
    <>
      <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 12 }}>{caption}</div>
      {unverifiable.length > 0 && <div className="warn" style={{ fontSize: 12, marginTop: 4 }}>
        ⚠ {unverifiable.join('·')}일 구간은 이 관측 기간
        ({backtestSpan(bt)})으로 만들 수 있는 독립 표본이 최대{' '}
        {unverifiable.map(h => bt.max_episodes[String(h)]).join('·')}개뿐이라
        <strong> 통계적으로 검증할 수 없습니다</strong> — 시간이 지나도 자동으로 채워지지 않습니다.
        아래 손절률·초과수익은 서술적 참고치로만 보세요.</div>}
      {missing.length > 0 && <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 4 }}>
        ⓘ {missing.join(' · ')} 등급은 관측 기간({bt.start}~{bt.end}) 중{' '}
        <strong>한 번도 발생하지 않았습니다</strong> — 데이터 부족이 아니라 조건이 성립하지 않은 것입니다.</div>}
      <div className="table-scroll" style={{ marginTop: 6 }}>
        <table>
          <thead><tr>
            <th>등급</th><th>신호 일수</th><th>독립 표본</th>
            {horizons.map(h => <th key={h}>{h}일 평균 (±1σ)</th>)}
            {horizons.map(h => <th key={h}>{h}일 승률</th>)}
            {horizons.map(h => <th key={h}>{h}일 손절률</th>)}
            {bt.bench_label && horizons.map(h => <th key={h}>{h}일 초과</th>)}
          </tr></thead>
          <tbody>
            {grades.map(g => {
              return (
                <tr key={g.grade}>
                  <td><SignalBadge grade={g.grade} /></td>
                  <td>{g.n}</td>
                  <td title="20일 구간이 겹치지 않는 신호 묶음 수 — 통계적으로 독립인 표본">
                    {horizons.map(h => num(pick(g, 'episodes', h))).join(' / ')}</td>

                  {horizons.map(h => {
                    const avg = num(pick(g, 'avg_fwd', h))
                    const se = num(pick(g, 'se', h))
                    const net = num(pick(g, 'avg_net', h))
                    const stress = num(pick(g, 'avg_stress', h))
                    const hold = num(pick(g, 'avg_hold', h))
                    if (pick(g, 'insufficient', h) === true) return (
                      <td key={h} style={{ color: 'var(--text-dim)' }}
                          title={`독립 표본 ${num(pick(g, 'episodes', h))}개 — 최소 ${bt.min_episodes}개 필요`}>
                        {unverifiable.includes(h) ? '검증 불가' : '표본 부족'}</td>
                    )
                    return (
                      <td key={h} className={(avg ?? 0) >= 0 ? 'pos' : 'neg'}
                          title={hold === null ? '' : `손절 없이 보유했다면 ${signed(hold)}`}>
                        {avg === null ? '—' : signed(avg)}
                        {se !== null && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
                          {' '}± {se}%p</span>}
                        {net !== null && <div style={{ color: 'var(--text-dim)', fontSize: 11 }}>
                          순 {signed(net)}</div>}
                        {/* 비용 가정이 2배 틀렸을 때도 살아남는 엣지인지 — 순수익이
                            플러스라도 여기서 마이너스면 실집행에서 사라질 수 있다 */}
                        {stress !== null && <div style={{ fontSize: 11 }}
                             className={stress >= 0 ? 'pos' : 'warn'}
                             title={`왕복 비용을 ${bt.cost_breakdown.stress_pct}%p로 가정한 결과`}>
                          스트레스 {signed(stress)}</div>}
                      </td>
                    )
                  })}

                  {horizons.map(h => {
                    const win = num(pick(g, 'win', h))
                    if (pick(g, 'insufficient', h) === true)
                      return <td key={h} style={{ color: 'var(--text-dim)' }}>—</td>
                    return (
                      <td key={h} title={`비용 차감 전 ${num(g[`win${h}_gross`]) ?? '—'}%`}>
                        {win === null ? '—' : `${win}%`}</td>
                    )
                  })}

                  {horizons.map(h => {
                    const rate = num(pick(g, 'stop_rate', h))
                    return (
                      <td key={h} style={{ color: 'var(--text-dim)' }}
                          title="보유 중 2×ATR 손절선을 건드려 조기 청산된 표본 비율">
                        {rate === null ? '—' : `${rate}%`}</td>
                    )
                  })}

                  {bt.bench_label && horizons.map(h => {
                    const ex = num(pick(g, 'avg_excess', h))
                    if (pick(g, 'insufficient', h) === true)
                      return <td key={h} style={{ color: 'var(--text-dim)' }}>—</td>
                    return (
                      <td key={h} className={(ex ?? 0) >= 0 ? 'pos' : 'neg'}>
                        {ex === null ? '—' : signed(ex, '%p')}</td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </>
  )
}
