import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { del, get, post, put } from '../api'
import type { Portfolio as PF } from '../types'
import { cashClampWarning, type TradeResult } from '../trade'
import { isStale, relativeTime } from '../time'
import SymbolInput from '../components/SymbolInput'

const PIE_COLORS = ['#4f8ef7', '#2ecc71', '#f7c948', '#b06ef7', '#ff8a65']

// recharts v3의 PieChart+Legend 조합이 이 프로젝트에서 섹터를 그리지 못하는 문제(빈 <g> 렌더)가 있어
// 겹침 걱정 없는 순수 SVG 도넛 + 별도 범례 목록으로 대체.
function AllocationDonut({ allocation }: { allocation: { label: string; value_krw: number }[] }) {
  const total = allocation.reduce((s, a) => s + a.value_krw, 0)
  const r = 40, cx = 50, cy = 50, circumference = 2 * Math.PI * r
  let offset = 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 20, height: '100%' }}>
      <svg viewBox="0 0 100 100" style={{ width: 140, height: 140, flexShrink: 0 }}>
        {allocation.map((a, i) => {
          const pct = total ? a.value_krw / total : 0
          const dash = pct * circumference
          const el = (
            <circle key={a.label} r={r} cx={cx} cy={cy} fill="none"
                    stroke={PIE_COLORS[i % PIE_COLORS.length]} strokeWidth={18}
                    strokeDasharray={`${dash} ${circumference - dash}`}
                    strokeDashoffset={-offset * circumference}
                    transform={`rotate(-90 ${cx} ${cy})`}>
              <title>{a.label} ₩{fmt(a.value_krw)} ({(pct * 100).toFixed(1)}%)</title>
            </circle>
          )
          offset += pct
          return el
        })}
      </svg>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
        {allocation.map((a, i) => (
          <div key={a.label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: PIE_COLORS[i % PIE_COLORS.length], flexShrink: 0 }} />
            <span>{a.label}</span>
            <span style={{ color: 'var(--text-dim)' }}>
              {total ? (a.value_krw / total * 100).toFixed(1) : 0}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}
const fmt = (n: number | null) => n === null ? '—' : n.toLocaleString('ko-KR', { maximumFractionDigits: 2 })
const cur = (c: string, n: number | null) => n === null ? '—' : (c === 'USD' ? '$' : '₩') + fmt(n)

interface Trade { id: number; symbol: string; side: string; quantity: number;
                  price: number; trade_date: string; executed_at: string | null;
                  fee: number | null; tax: number | null;
                  note: string | null; grade_at_trade: string | null
                  exclude_from_stats: number }

export default function Portfolio() {
  const [pf, setPf] = useState<PF | null>(null)
  const [trades, setTrades] = useState<Trade[]>([])
  const [form, setForm] = useState({ symbol: '', side: 'BUY', quantity: '', price: '',
    trade_date: new Date().toISOString().slice(0, 10), executed_at: '',
    note: '', fee: '', tax: '', exclude_from_stats: false })
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cashInput, setCashInput] = useState<string>('')
  const [cashUsdInput, setCashUsdInput] = useState<string>('')
  const [cashWarn, setCashWarn] = useState<string | null>(null)
  const [now, setNow] = useState(Date.now())

  // 빈 입력은 "변경 없음". 빈 값을 0으로 보내면 예수금이 소리 없이 사라지고,
  // 총자산을 분모로 쓰는 1% 리스크 포지션 사이징까지 틀어진다.
  const parseCash = (raw: string, label: string): number | null | 'error' => {
    if (raw.trim() === '') return null
    const n = Number(raw)
    if (!Number.isFinite(n) || n < 0) { setMsg(`${label}은 0 이상이어야 합니다`); return 'error' }
    return n
  }

  const saveCash = async () => {
    const krw = parseCash(cashInput, '예수금')
    if (krw === 'error') return
    const usd = parseCash(cashUsdInput, '달러 예수금')
    if (usd === 'error') return
    if (krw === null && usd === null) { setMsg('변경할 예수금을 입력하세요'); return }

    const prevKrw = pf?.totals.cash_krw ?? 0
    if (krw !== null && prevKrw > 0 && krw < prevKrw / 2 &&
        !confirm(`원화 예수금을 ₩${fmt(prevKrw)} → ₩${fmt(krw)} 로 줄입니다. 계속할까요?`)) return

    const body: { amount?: number; amount_usd?: number } = {}
    if (krw !== null) body.amount = krw
    if (usd !== null) body.amount_usd = usd
    try { await put('/api/cash', body); setMsg(null); load() }
    catch (e) { setMsg(String(e)) }
  }

  const load = () => Promise.all([
    get<PF>('/api/portfolio'),
    get<Trade[]>('/api/trades'),
  ]).then(([p, tr]) => {
    setPf(p); setTrades(tr); setError(null); setNow(Date.now())
    // 현재 저장된 값을 프리필 — 한쪽만 고치려다 다른 쪽을 날리는 일이 없게
    setCashInput(String(p.totals.cash_krw))
    setCashUsdInput(String(p.totals.cash_usd ?? 0))
  }).catch(e => setError(String(e)))
  useEffect(() => { load() }, [])

  // 빈 비용 입력은 "미기록" — 0으로 보내면 비용 0짜리 매매로 원장에 남아
  // 승률·손익비가 gross로 되돌아간다. null로 보내야 서버가 시장 요율로 추정한다.
  const optionalCost = (raw: string): number | null => {
    const s = raw.trim()
    if (s === '') return null
    const n = Number(s)
    return Number.isFinite(n) && n >= 0 ? n : null
  }

  const addTrade = async () => {
    const quantity = Number(form.quantity), price = Number(form.price)
    if (!form.symbol.trim() || !(quantity > 0) || !(price > 0)) {
      setMsg('심볼·수량·단가를 확인하세요 (0 이하 불가)'); return
    }
    try {
      const res = await post<TradeResult>('/api/trades',
                                { ...form, symbol: form.symbol.trim().toUpperCase(),
                                  quantity, price, note: form.note.trim() || null,
                                  fee: optionalCost(form.fee), tax: optionalCost(form.tax),
                                  executed_at: form.executed_at || null })
      setMsg(null)
      setCashWarn(cashClampWarning(res))
      // 보정 체크는 매번 해제한다 — 켜둔 채로 다음 실거래를 넣으면 그 건까지 집계에서 빠진다
      setForm({ ...form, quantity: '', price: '', note: '', fee: '', tax: '',
                executed_at: '', exclude_from_stats: false })
      load()
    } catch (e) { setMsg(String(e)) }
  }

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
      <div className="grid-2">
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>총자산 (평가액 + 예수금, KRW 환산)</div>
            {/* 이 계좌 숫자가 언제 가격 기준인지 — 낡은 값으로 사이즈를 정하면 안 된다 */}
            <div className={stale ? 'warn' : ''} style={{ fontSize: 11,
                   color: stale ? undefined : 'var(--text-dim)' }}
                 title={pf.last_refresh ?? ''}>
              {stale && '⚠ '}기준: {relativeTime(pf.last_refresh, now)}</div>
          </div>
          <div style={{ fontSize: 26, fontWeight: 700 }}>₩{fmt(t.total_asset_krw)}</div>
          {/* 같은 손익을 두 분모로 나눠 함께 보여준다 — 하나만 두면 현금 비중이 큰 계좌에서
              체감 손실이 부풀려 읽히고 포지션 사이즈 판단이 통째로 틀어진다. */}
          <div className={t.total_pnl_krw >= 0 ? 'pos' : 'neg'} style={{ fontSize: 16 }}>
            {t.total_pnl_krw >= 0 ? '+' : ''}₩{fmt(t.total_pnl_krw)}
            <span style={{ fontSize: 13 }}> (원금 대비 {t.total_pnl_pct}%)</span></div>
          <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>
            총자산 대비 {t.total_pnl_pct_of_asset >= 0 ? '+' : ''}{t.total_pnl_pct_of_asset}%
            {' · '}보유 종목 평가손익이며 실현손익은 아래 카드에 따로 있습니다</div>
          <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 6 }}>
            평가액 ₩{fmt(t.total_value_krw)} · 현금 ₩{fmt(t.cash_krw + (t.cash_usd_krw ?? 0))} ({t.cash_pct}%)
            {(t.cash_usd ?? 0) > 0 && <> — ₩{fmt(t.cash_krw)} + ${fmt(t.cash_usd)}</>}</div>
          <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center',
                        flexWrap: 'wrap' }}>
            <input type="number" placeholder="예수금 (KRW)" value={cashInput}
                   onChange={e => setCashInput(e.target.value)}
                   style={{ flex: '1 1 140px', minWidth: 0 }} />
            <input type="number" placeholder="달러 예수금 (USD)" value={cashUsdInput}
                   onChange={e => setCashUsdInput(e.target.value)}
                   style={{ flex: '1 1 140px', minWidth: 0 }} />
            <button onClick={saveCash}>저장</button>
            <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>비우면 변경 없음</span>
          </div>
          {/* 예수금이 조용히 0으로 잘리면 총자산과 1% 리스크 수량이 함께 어긋난다 */}
          {cashWarn && <div className="warn-box" style={{ marginTop: 8 }}>⚠ {cashWarn}
            <button className="ghost" style={{ marginLeft: 8 }}
                    onClick={() => setCashWarn(null)}>확인</button></div>}
          {msg && <div style={{ color: 'var(--sell)', fontSize: 12, marginTop: 6 }}>{msg}</div>}
        </div>
        <div className="card" style={{ height: 180 }}>
          {pf.allocation.length > 0 ? (
            <AllocationDonut allocation={pf.allocation} />
          ) : <div style={{ color: 'var(--text-dim)' }}>보유 종목 없음</div>}
        </div>
      </div>

      <div className="card">
        <strong>보유 종목</strong>
        {pf.holdings.length === 0 && <div className="empty">
          보유 종목이 없습니다.<br />
          아래 <strong>매매 입력</strong>에 체결 내역을 기록하면 평단·수익률·실현손익이 계산됩니다.
        </div>}
        <div className="table-scroll">
        <table>
          <thead><tr><th>종목</th><th>수량</th><th>평단가</th><th>현재가</th>
            <th>평가액</th><th>KRW 환산</th><th>비중</th><th>손익</th><th>수익률</th></tr></thead>
          <tbody>
            {pf.holdings.map(h => (
              <tr key={h.symbol}>
                <td><Link to={`/ticker/${h.symbol}`}><strong>{h.name}</strong>
                  <span style={{ color: 'var(--text-dim)', fontSize: 12 }}> {h.currency}</span></Link></td>
                <td>{fmt(h.quantity)}</td>
                <td>{cur(h.currency, h.avg_price)}</td>
                <td>{cur(h.currency, h.close)}</td>
                <td>{cur(h.currency, h.value)}</td>
                {/* 통화가 섞이면 종목 통화만으로는 포지션 크기를 나란히 볼 수 없다 */}
                <td>₩{fmt(h.value_krw)}</td>
                <td className={(h.weight_pct ?? 0) >= 20 ? 'neg' : ''}>
                  {h.weight_pct === null ? '—' : `${h.weight_pct}%`}</td>
                <td className={(h.pnl ?? 0) >= 0 ? 'pos' : 'neg'}>{cur(h.currency, h.pnl)}</td>
                <td className={(h.pnl_pct ?? 0) >= 0 ? 'pos' : 'neg'}>
                  {h.pnl_pct === null ? '—' : `${h.pnl_pct >= 0 ? '+' : ''}${h.pnl_pct}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>

      {pf.risk && <div className="card">
        <strong>계좌 리스크</strong>
        <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
          {' '}현재 보유 수량 기준 근사 (환율 고정) · {pf.risk.calendar_note}</span>
        <div style={{ display: 'flex', gap: 32, marginTop: 10, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>연환산 변동성</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}>{pf.risk.volatility_pct}%</div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
              연 {Math.round(pf.risk.periods_per_year)}회 관측 기준</div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>계좌 최대 낙폭 (MDD)</div>
            <div className="neg" style={{ fontWeight: 700, fontSize: 18 }}>{pf.risk.mdd_pct}%</div>
            {/* 실제 계좌가 겪은 낙폭이 아니다 — 라벨이 없으면 실적으로 읽힌다 */}
            <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>{pf.risk.mdd_note}</div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>최대 종목 비중</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}
                 className={(pf.risk.max_weight_pct ?? 0) >= 30 ? 'neg' : ''}>
              {pf.risk.max_weight_pct}%
              {(pf.risk.max_weight_pct ?? 0) >= 30 && <span style={{ fontSize: 12 }}> ⚠ 집중</span>}</div>
          </div>
        </div>
        <table style={{ marginTop: 12 }}>
          <thead><tr><th>종목</th><th>총자산 대비 비중</th></tr></thead>
          <tbody>
            {pf.risk.weights.map(w => (
              <tr key={w.symbol}>
                <td style={{ textAlign: 'left' }}>{w.name}</td>
                <td className={w.weight_pct >= 30 ? 'neg' : ''}>{w.weight_pct}%</td>
              </tr>
            ))}
          </tbody>
        </table>
        {/* 최대 종목 비중 9.3%는 안전해 보이지만 상관 0.7+ 로 묶인 종목들이
            동반 하락하면 계좌가 맞는 타격은 그 합에 가깝다. */}
        {pf.risk.clusters.length > 0 && <div style={{ marginTop: 14 }}>
          <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            상관 {pf.risk.cluster_threshold} 이상으로 묶인 그룹 — 사실상 하나의 포지션</div>
          <table style={{ marginTop: 6 }}>
            <thead><tr><th>그룹</th><th>합산 비중</th></tr></thead>
            <tbody>
              {pf.risk.clusters.map(c => (
                <tr key={c.symbols.join()}>
                  <td style={{ textAlign: 'left' }}>{c.names.join(' · ')}</td>
                  <td className={c.weight_pct >= 30 ? 'neg' : ''}>{c.weight_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          {(pf.risk.max_cluster_pct ?? 0) >= 30 && <div className="warn-box" style={{ marginTop: 8 }}>
            ⚠ 가장 큰 그룹이 총자산의 {pf.risk.max_cluster_pct}%입니다 — 종목별 비중은
            분산돼 보여도 동반 하락 시에는 한 종목에 그만큼 걸어둔 것과 같습니다.</div>}
        </div>}
        {pf.risk.corr && <>
          <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 12 }}>
            보유 종목 간 일간수익률 상관계수 — 0.7 이상이면 사실상 같은 포지션</div>
          <div className="table-scroll" style={{ marginTop: 6 }}>
          <table>
            <thead><tr><th></th>
              {pf.risk.corr.symbols.map(s => <th key={s}>{s}</th>)}</tr></thead>
            <tbody>
              {pf.risk.corr.symbols.map((s, i) => (
                <tr key={s}>
                  <td style={{ textAlign: 'left' }}><strong>{s}</strong></td>
                  {pf.risk!.corr!.matrix[i].map((v, j) => (
                    <td key={j} className={i !== j && v >= 0.7 ? 'neg' : ''}>
                      {v.toFixed(2)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </>}
      </div>}

      {/* 종목마다 1% 룰을 지켜도 합산하면 몇 %인지는 어디에도 안 나온다.
          사이즈 오류는 한 번에 계좌를 날리므로 총합을 상시 노출한다. */}
      {pf.open_risk && <div className="card">
        <strong>계좌 총 미결 리스크</strong>
        <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
          {' '}모든 보유가 각자 2×ATR 손절에 닿았을 때의 손실 합계</span>
        <div style={{ display: 'flex', gap: 32, marginTop: 10, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>총 리스크</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}
                 className={pf.open_risk.over_limit ? 'neg' : ''}>
              {pf.open_risk.total_risk_pct ?? '—'}%
              <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
                {' '}(₩{fmt(pf.open_risk.total_risk_krw)})</span></div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>권장 상한</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}>{pf.open_risk.limit_pct}%</div>
          </div>
        </div>
        {pf.open_risk.over_limit && <div className="warn-box" style={{ marginTop: 10 }}>
          ⚠ 총 리스크가 상한 {pf.open_risk.limit_pct}%를 넘었습니다. 신규 진입보다 기존 포지션
          축소를 먼저 검토하세요. 보유 종목 상관계수가 높으면 실제 동시 손실은 이 합계에 더 가깝습니다.</div>}
        <table style={{ marginTop: 12 }}>
          <thead><tr><th>종목</th><th>2×ATR 손실액</th><th>총자산 대비</th></tr></thead>
          <tbody>
            {pf.open_risk.rows.map(r => (
              <tr key={r.symbol}>
                <td style={{ textAlign: 'left' }}>{r.name}</td>
                <td>₩{fmt(r.risk_krw)}</td>
                <td className={(r.risk_pct ?? 0) >= 2 ? 'neg' : ''}>{r.risk_pct ?? '—'}%</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 8 }}>
          손절가는 자동 예약주문이 아니며 갭 하락 시 계획보다 더 잃을 수 있습니다.</div>
      </div>}

      {/* count > 0 일 때만 렌더하면 매도 기록이 없는 계좌에서 카드가 통째로 사라져
          "이 앱에는 실현손익 기능이 없다"로 읽힌다. 시스템이 돈을 벌고 있는지
          확인할 자리가 있다는 사실 자체가 화면에 남아 있어야 한다. */}
      {pf.realized && <div className="card">
        <strong>실현손익 · 매매 복기</strong>
        {pf.realized.stats.count === 0 ? (
          <div className="empty">
            아직 매도 기록이 없어 확정된 손익이 없습니다.<br />
            매도를 기록하면 <strong>누적 실현손익 · 승률 · 손익비 · 진입 등급별 성과</strong>가
            여기에 집계됩니다 — 위 평가손익은 아직 확정되지 않은 값입니다.
            {pf.realized.stats.excluded_count > 0 &&
              <><br />※ 평단 보정용으로 표시된 {pf.realized.stats.excluded_count}건은
                집계에서 제외됩니다.</>}
          </div>
        ) : <>
        <div style={{ display: 'flex', gap: 32, marginTop: 10, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>총 실현손익 (비용 차감 후)</div>
            <div className={pf.realized.stats.total_pnl_krw >= 0 ? 'pos' : 'neg'}
                 style={{ fontWeight: 700, fontSize: 18 }}>
              {pf.realized.stats.total_pnl_krw >= 0 ? '+' : ''}₩{fmt(pf.realized.stats.total_pnl_krw)}</div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
              수수료·세금 ₩{fmt(pf.realized.stats.cost_krw)} 차감
              {pf.realized.stats.fx_pnl_krw !== 0 &&
                ` · 이 중 환손익 ${pf.realized.stats.fx_pnl_krw >= 0 ? '+' : ''}₩${fmt(pf.realized.stats.fx_pnl_krw)}`}</div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>승률 (비용 차감 후)</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}>{pf.realized.stats.win_rate ?? '—'}%
              <span style={{ color: 'var(--text-dim)', fontSize: 12 }}> ({pf.realized.stats.count}회)</span></div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>평균 수익 / 평균 손실</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}>
              <span className="pos">{pf.realized.stats.avg_win_pct !== null ? `+${pf.realized.stats.avg_win_pct}%` : '—'}</span>
              {' / '}
              <span className="neg">{pf.realized.stats.avg_loss_pct !== null ? `${pf.realized.stats.avg_loss_pct}%` : '—'}</span></div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>손익비</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}>{pf.realized.stats.payoff_ratio ?? '—'}</div>
          </div>
        </div>
        {pf.realized.stats.cost_estimated && <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 8 }}>
          ⓘ 일부 체결의 수수료·세금이 기록돼 있지 않아 <strong>시장 기본 요율로 추정</strong>했습니다.
          정확한 복기를 원하면 매매 입력에서 실제 비용을 넣으세요.</div>}
        {/* 인위적 체결가가 승률에 섞이면 복기 전체가 거짓이 된다. 뺐다는 사실을
            숨기면 이번엔 "왜 건수가 안 맞지"로 신뢰가 깨진다 — 몇 건인지 밝힌다. */}
        {pf.realized.stats.excluded_count > 0 && <div className="warn-box" style={{ marginTop: 8 }}>
          ⚠ 평단 보정용으로 표시된 <strong>{pf.realized.stats.excluded_count}건</strong>은 체결가가
          인위적이라 위 승률·손익비·실현손익 집계에서 제외했습니다. 아래 표에는 「보정」 배지로 남아 있습니다.</div>}
        {pf.realized.stats.by_entry_grade.length > 0 && <>
          <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 12 }}>
            진입 등급별 성과 — 시그널을 따른 매매와 아닌 매매의 성적을 분리해서 보세요</div>
          <table style={{ marginTop: 6 }}>
            <thead><tr><th>진입 시 등급</th><th>횟수</th><th>승률</th><th>평균 수익률</th></tr></thead>
            <tbody>
              {pf.realized.stats.by_entry_grade.map(g => (
                <tr key={g.grade}>
                  <td>{g.grade}</td>
                  <td>{g.count}</td>
                  <td>{g.win_rate}%</td>
                  <td className={g.avg_pnl_pct >= 0 ? 'pos' : 'neg'}>
                    {g.avg_pnl_pct >= 0 ? '+' : ''}{g.avg_pnl_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>}
        <div className="table-scroll" style={{ marginTop: 12 }}>
        <table>
          <thead><tr><th>매도일</th><th>심볼</th><th>수량</th><th>평단</th><th>매도가</th>
            <th>비용</th><th>실현손익 (net)</th><th>수익률</th><th>원화 손익</th>
            <th>진입 등급</th><th>메모</th></tr></thead>
          <tbody>
            {pf.realized.entries.map((r, i) => (
              <tr key={i}>
                <td style={{ textAlign: 'left' }}>{r.trade_date}</td>
                <td>{r.symbol}</td>
                <td>{fmt(r.quantity)}</td>
                <td>{fmt(r.buy_price)}</td>
                <td>{fmt(r.sell_price)}</td>
                <td style={{ color: 'var(--text-dim)' }}
                    title={r.cost_estimated ? '시장 기본 요율로 추정한 값' : '입력된 실제 비용'}>
                  {fmt(r.cost)}{r.cost_estimated && '*'}</td>
                <td className={r.pnl >= 0 ? 'pos' : 'neg'}
                    title={`비용 차감 전 ${fmt(r.pnl_gross)}`}>{fmt(r.pnl)}</td>
                <td className={r.pnl_pct >= 0 ? 'pos' : 'neg'}>
                  {r.pnl_pct >= 0 ? '+' : ''}{r.pnl_pct}%</td>
                {/* 매수·매도 환율을 각각 반영한 값. 환손익을 따로 보여야 "달러 자산이 잘 버텼다"는
                    착시 없이 KR/US 배분을 판단할 수 있다. */}
                <td className={r.pnl_krw >= 0 ? 'pos' : 'neg'}
                    title={`가격 ${fmt(r.price_pnl_krw)} + 환 ${fmt(r.fx_pnl_krw)} `
                           + `(매수 ${fmt(r.buy_fx)} → 매도 ${fmt(r.sell_fx)})`}>
                  ₩{fmt(r.pnl_krw)}
                  {r.fx_pnl_krw !== 0 && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
                    {' '}(환 {r.fx_pnl_krw >= 0 ? '+' : ''}{fmt(r.fx_pnl_krw)})</span>}</td>
                <td>{r.entry_grade ?? '—'}</td>
                <td style={{ textAlign: 'left', maxWidth: 200, overflow: 'hidden',
                             textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    title={r.note ?? ''}>
                  {r.basis_adjusted && <span className="warn" style={{ fontSize: 11 }}
                    title="평단 맞춤용 보정 로트가 원가에 섞여 있어 집계에서 제외된 건입니다">
                    [보정] </span>}{r.note ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
        </>}
      </div>}

      <div className="card">
        <strong>매매 입력</strong>
        <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
          {/* 자유 텍스트 입력은 오타 한 번에 400으로 실패한다 — 등록 종목에서 고르게 한다 */}
          <SymbolInput value={form.symbol} style={{ width: 220 }}
                       onChange={v => setForm({ ...form, symbol: v })} />
          <select value={form.side} onChange={e => setForm({ ...form, side: e.target.value })}>
            <option value="BUY">매수</option><option value="SELL">매도</option>
          </select>
          <input type="number" placeholder="수량" value={form.quantity}
                 onChange={e => setForm({ ...form, quantity: e.target.value })} style={{ width: 100 }} />
          <input type="number" placeholder="단가" value={form.price}
                 onChange={e => setForm({ ...form, price: e.target.value })} style={{ width: 130 }} />
          <input type="date" value={form.trade_date}
                 onChange={e => setForm({ ...form, trade_date: e.target.value })} />
          {/* 같은 날 매도 후 재매수는 순서가 뒤바뀌면 평단이 잘못 만들어진다 */}
          <input type="time" title="체결 시각 (같은 날 여러 번 체결한 경우)"
                 value={form.executed_at}
                 onChange={e => setForm({ ...form, executed_at: e.target.value })} />
          <input type="number" placeholder="수수료" value={form.fee}
                 onChange={e => setForm({ ...form, fee: e.target.value })} style={{ width: 100 }} />
          <input type="number" placeholder="세금" value={form.tax}
                 onChange={e => setForm({ ...form, tax: e.target.value })} style={{ width: 100 }} />
          <input placeholder="메모 (진입/청산 근거)" value={form.note}
                 onChange={e => setForm({ ...form, note: e.target.value })} style={{ flex: 1, minWidth: 180 }} />
          <button onClick={addTrade}>추가</button>
        </div>
        {/* 평단을 시트에 맞추려고 넣는 가짜 체결가가 실거래와 섞이면 승률·손익비가
            통째로 거짓이 된다. 넣을 수 있게 하되 집계에서는 빼야 복기가 산다. */}
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8,
                        fontSize: 12, color: 'var(--text-dim)' }}>
          <input type="checkbox" checked={form.exclude_from_stats}
                 onChange={e => setForm({ ...form, exclude_from_stats: e.target.checked })} />
          평단 맞춤용 보정 로트 — 평단에는 반영하되 승률·실현손익 집계에서 제외
        </label>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 6 }}>
          수수료·세금을 비우면 시장 기본 요율로 추정합니다 — 실제 값을 넣을수록 승률·손익비가 정확해집니다.
          <br />기록하면 예수금이 체결 대금만큼 자동 증감하며, 보유보다 많은 매도는 거부됩니다.
          입출금·배당은 위 예수금 칸에서 직접 수정하세요.</div>
        {msg && <div style={{ color: 'var(--sell)', marginTop: 8 }}>{msg}</div>}
        {trades.length === 0 && <div className="empty">
          기록된 매매가 없습니다. 체결 내역을 남기면 진입 등급별 성과까지 복기할 수 있습니다.</div>}
        <div className="table-scroll" style={{ marginTop: 12 }}>
        <table>
          <thead><tr><th>날짜</th><th>심볼</th><th>구분</th><th>수량</th><th>단가</th>
            <th>비용</th><th>체결 시 등급</th><th>메모</th><th></th></tr></thead>
          <tbody>
            {trades.slice().reverse().map(tr => (
              <tr key={tr.id}>
                <td style={{ textAlign: 'left' }}>{tr.trade_date}
                  {tr.executed_at && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
                    {' '}{tr.executed_at}</span>}</td>
                <td>{tr.symbol}</td>
                <td className={tr.side === 'BUY' ? 'pos' : 'neg'}>
                  {tr.side === 'BUY' ? '매수' : '매도'}
                  {/* 체결가가 인위적인 행은 원장에서 눈으로 구분돼야 한다 */}
                  {tr.exclude_from_stats === 1 && <div className="warn" style={{ fontSize: 10 }}
                    title="평단 맞춤용 보정 로트 — 승률·실현손익 집계에서 제외됩니다">보정</div>}</td>
                <td>{fmt(tr.quantity)}</td>
                <td>{fmt(tr.price)}</td>
                <td style={{ color: 'var(--text-dim)' }}
                    title={tr.fee === null && tr.tax === null ? '미기록 — 시장 요율로 추정' : '입력된 실제 비용'}>
                  {tr.fee === null && tr.tax === null ? '추정' : fmt((tr.fee ?? 0) + (tr.tax ?? 0))}</td>
                <td>{tr.grade_at_trade ?? '—'}</td>
                <td style={{ textAlign: 'left', maxWidth: 220, overflow: 'hidden',
                             textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    title={tr.note ?? ''}>{tr.note ?? ''}</td>
                {/* 매매 삭제는 평단·실현손익 원장까지 되돌린다 — 복구 경로가 없으므로 확인을 받는다 */}
                <td><button className="ghost" onClick={() => {
                  if (confirm(`${tr.trade_date} ${tr.symbol} ${tr.side === 'BUY' ? '매수' : '매도'} `
                    + `${fmt(tr.quantity)}주 기록을 삭제합니다.\n`
                    + '평단·실현손익 원장과 예수금이 함께 되돌아가며, 이 작업은 취소할 수 없습니다.'))
                    del(`/api/trades/${tr.id}`).then(load).catch(e => setMsg(String(e)))
                }}>삭제</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>
    </div>
  )
}
