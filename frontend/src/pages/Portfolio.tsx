import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { del, get, post, put } from '../api'
import type { CashFlow, Portfolio as PF } from '../types'
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

const FLOW_LABEL: Record<string, string> = {
  DIVIDEND: '배당', INTEREST: '이자', DEPOSIT: '입금', WITHDRAW: '출금' }

export default function Portfolio() {
  const [pf, setPf] = useState<PF | null>(null)
  const [trades, setTrades] = useState<Trade[]>([])
  const [flows, setFlows] = useState<CashFlow[]>([])
  const [flowForm, setFlowForm] = useState({ flow_type: 'DIVIDEND', symbol: '',
    amount: '', tax: '', flow_date: new Date().toISOString().slice(0, 10), note: '' })
  const [flowMsg, setFlowMsg] = useState<string | null>(null)
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
    get<CashFlow[]>('/api/cash-flows'),
  ]).then(([p, tr, fl]) => {
    setPf(p); setTrades(tr); setFlows(fl); setError(null); setNow(Date.now())
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

  const needsSymbol = flowForm.flow_type === 'DIVIDEND' || flowForm.flow_type === 'INTEREST'
  const addFlow = async () => {
    const amount = Number(flowForm.amount)
    if (!(amount > 0)) { setFlowMsg('세전 금액을 확인하세요 (0 이하 불가)'); return }
    if (needsSymbol && !flowForm.symbol.trim()) {
      setFlowMsg('배당·이자는 어느 종목에서 나왔는지 지정해야 종목별 수익률에 반영됩니다'); return
    }
    const tax = flowForm.tax.trim() === '' ? 0 : Number(flowForm.tax)
    if (!(tax >= 0) || tax > amount) { setFlowMsg('원천징수액을 확인하세요'); return }
    try {
      const res = await post<TradeResult>('/api/cash-flows', {
        flow_type: flowForm.flow_type, amount, tax,
        flow_date: flowForm.flow_date, note: flowForm.note.trim() || null,
        symbol: needsSymbol ? flowForm.symbol.trim().toUpperCase() : null })
      setFlowMsg(null)
      setCashWarn(cashClampWarning(res))
      setFlowForm({ ...flowForm, amount: '', tax: '', note: '' })
      load()
    } catch (e) { setFlowMsg(String(e)) }
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
  const div = pf.dividends
  // 배당이 한 건도 없는 계좌에 열을 하나 더 세우면, 평가손익과 똑같은 숫자가
  // 두 번 나오면서 표만 넓어진다 — 배당이 실제로 있을 때만 총수익을 세운다.
  const hasDiv = t.dividend_krw > 0
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
          {/* 주가 손익만 총자산 카드에 두면 배당으로 받은 현금은 예수금에 섞여
              사라진다 — 커버드콜·고배당 계좌의 성과가 계속 낮게만 보인다. */}
          {hasDiv && <div style={{ fontSize: 12, marginTop: 4 }}>
            <span style={{ color: 'var(--text-dim)' }}>배당 포함 총수익 </span>
            <strong className={(t.total_return_krw ?? 0) >= 0 ? 'pos' : 'neg'}>
              {(t.total_return_krw ?? 0) >= 0 ? '+' : ''}₩{fmt(t.total_return_krw)}
              {t.total_return_pct !== null && ` (원금 대비 ${t.total_return_pct}%)`}</strong>
            <span style={{ color: 'var(--text-dim)' }}>
              {' '}— 평가손익 + 누적 배당 ₩{fmt(t.dividend_krw)} (세후)</span></div>}
          <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 6 }}>
            평가액 ₩{fmt(t.total_value_krw)} · 현금 ₩{fmt(t.cash_krw + (t.cash_usd_krw ?? 0))} ({t.cash_pct}%)
            {(t.cash_usd ?? 0) > 0 && <> — ₩{fmt(t.cash_krw)} + ${fmt(t.cash_usd)}</>}</div>
          {/* 환율이 화면에 없으면 KRW 숫자에서 역산해야 하고, 수집 실패로 기본값을
              쓴 경우와 실제 시세를 쓴 경우가 구분되지 않는다 */}
          <div className={t.usdkrw_estimated ? 'warn' : ''} style={{ fontSize: 11, marginTop: 4,
                 color: t.usdkrw_estimated ? undefined : 'var(--text-dim)' }}>
            {t.usdkrw_estimated ? '⚠ 환율 수집 실패 — 기본값 ' : '적용 환율 '}
            ₩{fmt(t.usdkrw)}/$
            {t.usdkrw_estimated && ' 로 환산했습니다. USD 종목의 원화 숫자는 참고용입니다.'}</div>
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
        <div className="table-scroll table-cards">
        <table>
          <thead><tr><th>종목</th><th>수량</th><th>평단가</th><th>현재가</th>
            <th>평가액</th><th>KRW 환산</th><th>비중</th>
            {/* 비용 반영 여부를 안 밝히면 -0.13%를 본전으로 읽고 청산해 손실을 확정한다 */}
            <th title="매도 수수료·세금 차감 전">손익 (비용 전)</th>
            <th title="지금 전량 매도했을 때 실제로 들어오는 금액과 확정 손익">
              전량 청산 시</th>
            <th>수익률</th>
            {hasDiv && <th title="누적 배당(세후) 포함 — 매도한 수량에 대해 받은 배당도 이 종목이 준 현금이므로 합산합니다">
              배당 포함</th>}</tr></thead>
          <tbody>
            {pf.holdings.map(h => (
              <tr key={h.symbol}>
                <td><Link to={`/ticker/${h.symbol}`}><strong>{h.name}</strong>
                  <span style={{ color: 'var(--text-dim)', fontSize: 12 }}> {h.currency}</span></Link>
                  {/* 평단이 실거래 산물이 아니면 이 행의 손익·수익률이 전부 그 위에 선다 */}
                  {h.basis_adjusted && <span className="warn" style={{ fontSize: 11 }}
                    title="원가에 평단 맞춤용 보정 로트가 섞여 있습니다. 평단·손익·수익률은 실제 체결가만으로 만든 값이 아닙니다.">
                    {' '}보정 평단</span>}</td>
                <td data-label="수량">{fmt(h.quantity)}</td>
                <td data-label="평단가">{cur(h.currency, h.avg_price)}</td>
                <td data-label="현재가">{cur(h.currency, h.close)}</td>
                <td data-label="평가액">{cur(h.currency, h.value)}</td>
                {/* 통화가 섞이면 종목 통화만으로는 포지션 크기를 나란히 볼 수 없다 */}
                <td data-label="KRW 환산">₩{fmt(h.value_krw)}</td>
                <td data-label="비중" className={(h.weight_pct ?? 0) >= 20 ? 'neg' : ''}>
                  {h.weight_pct === null ? '—' : `${h.weight_pct}%`}</td>
                <td data-label="손익 (비용 전)" className={(h.pnl ?? 0) >= 0 ? 'pos' : 'neg'}
                    title={h.currency === 'USD' && h.fx_pnl_krw !== null
                      ? `원화 손익 ₩${fmt(h.pnl_krw)} = 주가 ₩${fmt(h.price_pnl_krw)} + 환 ₩${fmt(h.fx_pnl_krw)}`
                      : ''}>
                  {cur(h.currency, h.pnl)}
                  {/* 미국주식 비중이 큰 계좌는 원화 손익의 상당 부분이 환이다 —
                      나눠 보지 않으면 '달러 자산이 잘 버텼다'는 착시가 생긴다.
                      매수 환율이 없으면 0이 아니라 '미상'으로 말해야 한다. */}
                  {h.currency === 'USD' && (h.fx_pnl_krw === null
                    ? <div style={{ fontSize: 11, color: 'var(--text-dim)' }}
                           title="매수 시점 환율이 원장에 없어 환 기여를 분리할 수 없습니다 — 환 영향이 없다는 뜻이 아닙니다">
                        환 기여 미상</div>
                    : h.fx_pnl_krw !== 0 && <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                        환 {h.fx_pnl_krw >= 0 ? '+' : ''}₩{fmt(h.fx_pnl_krw)}</div>)}</td>
                <td data-label="전량 청산 시" className={(h.net_pnl ?? 0) >= 0 ? 'pos' : 'neg'}>
                  {cur(h.currency, h.net_pnl)}
                  <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                    회수 {cur(h.currency, h.net_proceeds)}</div></td>
                <td data-label="수익률" className={(h.pnl_pct ?? 0) >= 0 ? 'pos' : 'neg'}>
                  {h.pnl_pct === null ? '—' : `${h.pnl_pct >= 0 ? '+' : ''}${h.pnl_pct}%`}</td>
                {/* 주가로는 마이너스여도 분배금까지 더하면 플러스인 포지션이 있다.
                    배당을 세지 않는 화면은 그 포지션을 팔라고 말하는 것과 같다. */}
                {hasDiv && <td data-label="배당 포함"
                    className={(h.total_return_pct ?? 0) >= 0 ? 'pos' : 'neg'}>
                  {h.dividend_krw === 0
                    ? <span style={{ color: 'var(--text-dim)' }}>배당 없음</span>
                    : <>{h.total_return_pct === null
                        ? <span style={{ color: 'var(--text-dim)' }}
                                title="매수 시점 환율이 원장에 없어 원화 평가손익을 확정할 수 없습니다 — 배당을 더할 기준 자체가 없는 것이지, 배당이 없다는 뜻이 아닙니다">—</span>
                        : `${h.total_return_pct >= 0 ? '+' : ''}${h.total_return_pct}%`}
                      <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                        배당 ₩{fmt(h.dividend_krw)}</div></>}</td>}
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
          {' '}모든 보유가 각자 손절선에 닿았을 때의 손실 합계 — 등록한 손절 룰이 있으면 그 값,
          없으면 2×ATR 가정</span>
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
        {/* 룰이 없는 종목의 리스크는 '이런 손절을 지킨다면'이라는 가정이다.
            몇 건이 가정인지 말하지 않으면 합계 전체가 사실로 읽힌다. */}
        {pf.open_risk.unregistered_count > 0 && <div className="warn-box" style={{ marginTop: 10 }}>
          ⚠ {pf.open_risk.unregistered_count}종목은 손절 룰이 등록돼 있지 않아 2×ATR을 가정한
          값입니다. 알림은 등록된 룰에서만 울리므로, 이 종목들은 손절선이 뚫려도 아무 통지가 없습니다.</div>}
        <div className="table-scroll table-cards">
        <table style={{ marginTop: 12 }}>
          <thead><tr><th>종목</th><th>손절 기준</th><th>손실액</th><th>총자산 대비</th></tr></thead>
          <tbody>
            {pf.open_risk.rows.map(r => (
              <tr key={r.symbol}>
                <td data-label="종목" style={{ textAlign: 'left' }}>{r.name}</td>
                <td data-label="손절 기준" style={{ color: r.stop_source === 'rule' ? undefined : 'var(--warn)' }}>
                  {r.stop_source === 'rule' ? '등록 룰' : '2×ATR 가정'}</td>
                <td data-label="손실액">₩{fmt(r.risk_krw)}</td>
                <td data-label="총자산 대비"
                    className={(r.risk_pct ?? 0) >= 2 ? 'neg' : ''}>{r.risk_pct ?? '—'}%</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
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
        {/* 해외 양도세는 체결 시점에 떼이지 않는다. 위의 '비용 차감 후' 실현손익만
            보면 이듬해 5월에 낼 돈까지 이미 번 돈으로 세고 다시 투입하게 된다. */}
        {pf.realized.overseas_tax.gain_krw !== 0 && <div style={{ marginTop: 12, padding: 12,
              borderRadius: 6, border: '1px solid var(--border)' }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>
            {pf.realized.overseas_tax.year}년 해외주식 양도세 (이듬해 5월 신고·납부)</div>
          <div style={{ display: 'flex', gap: 28, marginTop: 8, flexWrap: 'wrap' }}>
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>올해 해외 실현이익</div>
              <div style={{ fontWeight: 700, fontSize: 16 }}
                   className={pf.realized.overseas_tax.gain_krw >= 0 ? 'pos' : 'neg'}>
                {pf.realized.overseas_tax.gain_krw >= 0 ? '+' : ''}₩{fmt(pf.realized.overseas_tax.gain_krw)}</div>
            </div>
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>기본공제 잔여 (연 250만)</div>
              <div style={{ fontWeight: 700, fontSize: 16 }}>
                ₩{fmt(pf.realized.overseas_tax.deduction_left_krw)}</div>
            </div>
            <div>
              <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
                예상 세액 ({pf.realized.overseas_tax.rate_pct}%)</div>
              <div style={{ fontWeight: 700, fontSize: 16 }}
                   className={pf.realized.overseas_tax.tax_krw > 0 ? 'neg' : ''}>
                ₩{fmt(pf.realized.overseas_tax.tax_krw)}</div>
            </div>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 8 }}>
            위 실현손익은 이 세금을 빼기 전 값입니다 — 연간 통산 후 과세되므로 손실 실현이
            세액을 줄입니다. 환차익도 과세 대상에 포함한 추정이며, 실제 신고는 증권사
            자료를 기준으로 하세요.</div>
        </div>}
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
        <div className="table-scroll table-cards" style={{ marginTop: 12 }}>
        <table>
          <thead><tr><th>매도일</th><th>심볼</th><th>수량</th><th>평단</th><th>매도가</th>
            <th>비용</th><th>실현손익 (net)</th><th>수익률</th><th>원화 손익</th>
            <th>진입 등급</th><th>메모</th></tr></thead>
          <tbody>
            {pf.realized.entries.map((r, i) => (
              <tr key={i}>
                <td style={{ textAlign: 'left' }}>{r.trade_date}</td>
                <td data-label="심볼">{r.symbol}</td>
                <td data-label="수량">{fmt(r.quantity)}</td>
                <td data-label="평단">{fmt(r.buy_price)}</td>
                <td data-label="매도가">{fmt(r.sell_price)}</td>
                <td data-label="비용" style={{ color: 'var(--text-dim)' }}
                    title={r.cost_estimated ? '시장 기본 요율로 추정한 값' : '입력된 실제 비용'}>
                  {fmt(r.cost)}{r.cost_estimated && '*'}</td>
                <td data-label="실현손익 (net)" className={r.pnl >= 0 ? 'pos' : 'neg'}
                    title={`비용 차감 전 ${fmt(r.pnl_gross)}`}>{fmt(r.pnl)}</td>
                <td data-label="수익률" className={r.pnl_pct >= 0 ? 'pos' : 'neg'}>
                  {r.pnl_pct >= 0 ? '+' : ''}{r.pnl_pct}%</td>
                {/* 매수·매도 환율을 각각 반영한 값. 환손익을 따로 보여야 "달러 자산이 잘 버텼다"는
                    착시 없이 KR/US 배분을 판단할 수 있다. */}
                <td data-label="원화 손익" className={r.pnl_krw >= 0 ? 'pos' : 'neg'}
                    title={`가격 ${fmt(r.price_pnl_krw)} + 환 ${fmt(r.fx_pnl_krw)} `
                           + `(매수 ${fmt(r.buy_fx)} → 매도 ${fmt(r.sell_fx)})`}>
                  ₩{fmt(r.pnl_krw)}
                  {r.fx_pnl_krw !== 0 && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
                    {' '}(환 {r.fx_pnl_krw >= 0 ? '+' : ''}{fmt(r.fx_pnl_krw)})</span>}</td>
                <td data-label="진입 등급">{r.entry_grade ?? '—'}</td>
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

      {/* 배당·분배금이 원장에 없으면 커버드콜·고배당 종목의 성과가 주가 하락분만큼만
          보이고, 예수금은 매매와 어긋난 채로 남는다. 실제로 받은 현금을 세는 자리다. */}
      <div className="card">
        <strong>배당 · 현금흐름</strong>
        <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
          {' '}배당소득세는 입금 시점에 이미 원천징수됩니다 — 세전과 세후를 함께 기록하세요</span>
        {div.count === 0 ? (
          <div className="empty">
            기록된 배당이 없습니다.<br />
            분배금을 기록하면 <strong>종목별 배당 수익률 · 배당 포함 총수익</strong>이 계산되고,
            받은 현금이 예수금에 자동 반영됩니다 — 주가만 보면 배당주는 늘 실패한 포지션으로 보입니다.
          </div>
        ) : <>
        <div style={{ display: 'flex', gap: 32, marginTop: 10, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
              {div.year}년 배당 (세후)</div>
            <div className="pos" style={{ fontWeight: 700, fontSize: 18 }}>
              +₩{fmt(div.ytd_net_krw)}</div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
              세전 ₩{fmt(div.ytd_gross_krw)} · {div.ytd_count}건</div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>누적 배당 (세후)</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}>₩{fmt(div.total_net_krw)}</div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
              원천징수 ₩{fmt(div.total_tax_krw)} 차감 · {div.count}건</div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}
                 title="올해 받은 배당 ÷ 배당을 준 종목들의 현재 원가">
              배당 수익률 (원가 대비)</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}>
              {div.yield_on_cost_pct === null ? '—' : `${div.yield_on_cost_pct}%`}</div>
            <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
              {div.yield_on_cost_pct === null
                ? '기간이 맞는 종목이 없어 계산하지 않았습니다'
                : `분모 원가 ₩${fmt(div.yield_basis_krw)}`}</div>
          </div>
        </div>
        {/* 반년만 보유하고 받은 배당을 연간 수익률처럼 읽으면 비중을 잘못 늘린다 */}
        {div.yield_partial && <div className="warn-box note" style={{ marginTop: 8 }}>
          ⓘ 올해 중 매수·매도가 있었거나 이미 정리한 종목은 보유 기간과 배당 기간이 어긋나
          <strong> 위 수익률의 분자·분모에서 함께 제외</strong>했습니다 (아래 표의 「기간 불일치」).
          받은 배당 금액 자체는 전부 포함돼 있습니다.</div>}
        {div.fx_estimated && <div className="warn-box" style={{ marginTop: 8 }}>
          ⚠ 일부 달러 배당에 입금 시점 환율이 없어 <strong>현재 환율로 환산</strong>했습니다 —
          그 건들의 원화 금액은 오늘 환율이 바뀌면 함께 바뀝니다.</div>}
        <div className="table-scroll table-cards" style={{ marginTop: 12 }}>
        <table>
          <thead><tr><th>종목</th><th>{div.year}년 (세후)</th><th>누적 (세후)</th>
            <th>원가 대비</th><th>건수</th><th>최근 입금</th></tr></thead>
          <tbody>
            {div.by_symbol.map(r => (
              <tr key={r.symbol}>
                <td style={{ textAlign: 'left' }}>
                  <Link to={`/ticker/${r.symbol}`}>{r.name}</Link>
                  {/* 이미 판 종목의 배당을 현재 원가로 나눌 수는 없다 */}
                  {!r.held && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
                    {' '}보유 없음</span>}</td>
                <td data-label={`${div.year}년 (세후)`} className="pos">₩{fmt(r.ytd_net_krw)}</td>
                <td data-label="누적 (세후)">₩{fmt(r.net_krw)}</td>
                <td data-label="원가 대비">
                  {r.yield_on_cost_pct !== null ? `${r.yield_on_cost_pct}%`
                    : <span style={{ color: 'var(--text-dim)', fontSize: 11 }}
                            title={r.position_changed
                              ? '올해 이 종목을 사거나 팔았습니다 — 보유 기간과 배당 기간이 달라 현재 원가로 나눈 값은 수익률이 아닙니다'
                              : '현재 보유하지 않아 나눌 원가가 없습니다'}>
                        {r.position_changed ? '기간 불일치' : '—'}</span>}</td>
                <td data-label="건수">{r.count}</td>
                <td data-label="최근 입금">{r.last_date ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
        </>}

        <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap',
                      alignItems: 'center' }}>
          <select value={flowForm.flow_type}
                  onChange={e => setFlowForm({ ...flowForm, flow_type: e.target.value })}>
            <option value="DIVIDEND">배당·분배금</option>
            <option value="INTEREST">이자</option>
            <option value="DEPOSIT">입금</option>
            <option value="WITHDRAW">출금</option>
          </select>
          {needsSymbol && <SymbolInput value={flowForm.symbol} style={{ width: 200 }}
                       onChange={v => setFlowForm({ ...flowForm, symbol: v })} />}
          <input type="number" placeholder="세전 금액" value={flowForm.amount}
                 onChange={e => setFlowForm({ ...flowForm, amount: e.target.value })}
                 style={{ width: 130 }} />
          {needsSymbol && <input type="number" placeholder="원천징수" value={flowForm.tax}
                 onChange={e => setFlowForm({ ...flowForm, tax: e.target.value })}
                 style={{ width: 110 }} />}
          <input type="date" value={flowForm.flow_date}
                 onChange={e => setFlowForm({ ...flowForm, flow_date: e.target.value })} />
          <input placeholder="메모" value={flowForm.note}
                 onChange={e => setFlowForm({ ...flowForm, note: e.target.value })}
                 style={{ flex: 1, minWidth: 140 }} />
          <button onClick={addFlow}>추가</button>
        </div>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 6 }}>
          금액은 <strong>종목 통화 기준</strong>입니다 (미국 종목이면 달러). 기록하면 세후 금액만큼
          예수금이 자동 증감하므로 <strong>예수금 칸을 따로 고치지 마세요</strong> — 두 번 계상됩니다.
          {' '}원천징수를 비우면 0으로 기록되어 세전 금액이 그대로 수익이 됩니다.</div>
        {flowMsg && <div style={{ color: 'var(--sell)', fontSize: 12, marginTop: 6 }}>{flowMsg}</div>}
        {flows.length > 0 && <div className="table-scroll table-cards" style={{ marginTop: 12 }}>
        <table>
          <thead><tr><th>날짜</th><th>구분</th><th>종목</th><th>세전</th><th>원천징수</th>
            <th>실입금</th><th>메모</th><th></th></tr></thead>
          <tbody>
            {flows.map(f => (
              <tr key={f.id}>
                <td style={{ textAlign: 'left' }}>{f.flow_date}</td>
                <td data-label="구분" className={f.flow_type === 'WITHDRAW' ? 'neg' : 'pos'}>
                  {FLOW_LABEL[f.flow_type] ?? f.flow_type}</td>
                <td data-label="종목">{f.symbol ?? '—'}</td>
                <td data-label="세전">{cur(f.currency, f.amount)}</td>
                <td data-label="원천징수" style={{ color: 'var(--text-dim)' }}>
                  {f.tax ? cur(f.currency, f.tax) : '—'}</td>
                <td data-label="실입금">
                  {cur(f.currency, f.flow_type === 'WITHDRAW' ? -f.amount : f.amount - f.tax)}
                  {f.currency === 'USD' && f.fx_rate !== null &&
                    <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
                      ₩{fmt(f.fx_rate)}/$ 기준</div>}</td>
                <td style={{ textAlign: 'left', maxWidth: 200, overflow: 'hidden',
                             textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    title={f.note ?? ''}>{f.note ?? ''}</td>
                <td><button className="ghost" onClick={() => {
                  if (confirm(`${f.flow_date} ${FLOW_LABEL[f.flow_type] ?? f.flow_type}`
                    + ` ${cur(f.currency, f.amount)} 기록을 삭제합니다.\n`
                    + '예수금이 함께 되돌아가며, 이 작업은 취소할 수 없습니다.'))
                    del(`/api/cash-flows/${f.id}`).then(load).catch(e => setFlowMsg(String(e)))
                }}>삭제</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>}
      </div>

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
          입출금·배당은 위 <strong>배당 · 현금흐름</strong> 카드에 기록하세요 — 예수금 칸을
          직접 고치면 원장에 근거가 남지 않습니다.</div>
        {msg && <div style={{ color: 'var(--sell)', marginTop: 8 }}>{msg}</div>}
        {trades.length === 0 && <div className="empty">
          기록된 매매가 없습니다. 체결 내역을 남기면 진입 등급별 성과까지 복기할 수 있습니다.</div>}
        <div className="table-scroll table-cards" style={{ marginTop: 12 }}>
        <table>
          <thead><tr><th>날짜</th><th>심볼</th><th>구분</th><th>수량</th><th>단가</th>
            <th>비용</th><th>체결 시 등급</th><th>메모</th><th></th></tr></thead>
          <tbody>
            {trades.slice().reverse().map(tr => (
              <tr key={tr.id}>
                <td style={{ textAlign: 'left' }}>{tr.trade_date}
                  {tr.executed_at && <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
                    {' '}{tr.executed_at}</span>}</td>
                <td data-label="심볼">{tr.symbol}</td>
                <td data-label="구분" className={tr.side === 'BUY' ? 'pos' : 'neg'}>
                  {tr.side === 'BUY' ? '매수' : '매도'}
                  {/* 체결가가 인위적인 행은 원장에서 눈으로 구분돼야 한다.
                      체크박스가 생기기 전 임포트분은 메모에만 표식이 남아 있다. */}
                  {(tr.exclude_from_stats === 1 || (tr.note ?? '').includes('보정 로트'))
                    && <div className="warn" style={{ fontSize: 10 }}
                    title="평단 맞춤용 보정 로트 — 승률·실현손익 집계에서 제외됩니다">보정</div>}</td>
                <td data-label="수량">{fmt(tr.quantity)}</td>
                <td data-label="단가">{fmt(tr.price)}</td>
                <td data-label="비용" style={{ color: 'var(--text-dim)' }}
                    title={tr.fee === null && tr.tax === null ? '미기록 — 시장 요율로 추정' : '입력된 실제 비용'}>
                  {tr.fee === null && tr.tax === null ? '추정' : fmt((tr.fee ?? 0) + (tr.tax ?? 0))}</td>
                {/* 전 행이 '—'면 기능이 고장난 것처럼 보인다 — 실제로는 시그널을
                    수집하기 전에 임포트된 건이라는 사실을 알린다 */}
                <td data-label="체결 시 등급" title={tr.grade_at_trade ? '' :
                  '이 체결이 기록될 당시 해당 종목의 시그널이 아직 없었습니다 (임포트분 등). '
                  + '앱에서 매매를 기록하면 그 시점 등급이 자동으로 남습니다.'}>
                  {tr.grade_at_trade ?? '—'}</td>
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
