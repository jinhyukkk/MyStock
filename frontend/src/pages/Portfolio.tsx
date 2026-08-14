import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { del, get, post, put } from '../api'
import type { Portfolio as PF } from '../types'

const PIE_COLORS = ['#4f8ef7', '#2ecc71', '#f7c948', '#b06ef7', '#ff8a65']
const fmt = (n: number | null) => n === null ? '—' : n.toLocaleString('ko-KR', { maximumFractionDigits: 2 })
const cur = (c: string, n: number | null) => n === null ? '—' : (c === 'USD' ? '$' : '₩') + fmt(n)

interface Trade { id: number; symbol: string; side: string; quantity: number;
                  price: number; trade_date: string;
                  note: string | null; grade_at_trade: string | null }

export default function Portfolio() {
  const [pf, setPf] = useState<PF | null>(null)
  const [trades, setTrades] = useState<Trade[]>([])
  const [form, setForm] = useState({ symbol: '', side: 'BUY', quantity: '', price: '',
    trade_date: new Date().toISOString().slice(0, 10), note: '' })
  const [msg, setMsg] = useState<string | null>(null)
  const [cashInput, setCashInput] = useState<string>('')

  const saveCash = async () => {
    const amount = Number(cashInput)
    if (!(amount >= 0)) { setMsg('예수금은 0 이상이어야 합니다'); return }
    try { await put('/api/cash', { amount }); setMsg(null); load() }
    catch (e) { setMsg(String(e)) }
  }

  const load = () => Promise.all([
    get<PF>('/api/portfolio').then(setPf),
    get<Trade[]>('/api/trades').then(setTrades),
  ]).catch(e => setMsg(String(e)))
  useEffect(() => { load() }, [])

  const addTrade = async () => {
    const quantity = Number(form.quantity), price = Number(form.price)
    if (!form.symbol.trim() || !(quantity > 0) || !(price > 0)) {
      setMsg('심볼·수량·단가를 확인하세요 (0 이하 불가)'); return
    }
    try {
      await post('/api/trades', { ...form, symbol: form.symbol.trim().toUpperCase(),
                                  quantity, price, note: form.note.trim() || null })
      setMsg(null); setForm({ ...form, quantity: '', price: '', note: '' }); load()
    } catch (e) { setMsg(String(e)) }
  }

  if (!pf) return (
    <div className="grid">
      <div className="grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
        <div className="card skeleton" style={{ minHeight: 180 }} />
        <div className="card skeleton" style={{ minHeight: 180 }} />
      </div>
      <div className="card skeleton" style={{ minHeight: 200 }} />
    </div>
  )
  const t = pf.totals
  return (
    <div className="grid">
      <div className="grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
        <div className="card">
          <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>총자산 (평가액 + 예수금, KRW 환산)</div>
          <div style={{ fontSize: 26, fontWeight: 700 }}>₩{fmt(t.total_asset_krw)}</div>
          <div className={t.total_pnl_krw >= 0 ? 'pos' : 'neg'} style={{ fontSize: 16 }}>
            {t.total_pnl_krw >= 0 ? '+' : ''}₩{fmt(t.total_pnl_krw)} ({t.total_pnl_pct}%)</div>
          <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 6 }}>
            평가액 ₩{fmt(t.total_value_krw)} · 현금 ₩{fmt(t.cash_krw)} ({t.cash_pct}%)</div>
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <input type="number" placeholder="예수금 (KRW)" value={cashInput}
                   onChange={e => setCashInput(e.target.value)} style={{ width: 150 }} />
            <button onClick={saveCash}>저장</button>
          </div>
        </div>
        <div className="card" style={{ height: 180 }}>
          {pf.allocation.length > 0 ? (
            <ResponsiveContainer>
              <PieChart>
                <Pie data={pf.allocation} dataKey="value_krw" nameKey="label"
                     innerRadius={40} outerRadius={65}>
                  {pf.allocation.map((_, i) =>
                    <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
                </Pie>
                <Tooltip formatter={(v: any) => `₩${fmt(typeof v === 'number' ? v : null)}`} />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          ) : <div style={{ color: 'var(--text-dim)' }}>보유 종목 없음</div>}
        </div>
      </div>

      <div className="card">
        <strong>보유 종목</strong>
        <table>
          <thead><tr><th>종목</th><th>수량</th><th>평단가</th><th>현재가</th>
            <th>평가액</th><th>손익</th><th>수익률</th></tr></thead>
          <tbody>
            {pf.holdings.map(h => (
              <tr key={h.symbol}>
                <td><Link to={`/ticker/${h.symbol}`}><strong>{h.name}</strong>
                  <span style={{ color: 'var(--text-dim)', fontSize: 12 }}> {h.currency}</span></Link></td>
                <td>{fmt(h.quantity)}</td>
                <td>{cur(h.currency, h.avg_price)}</td>
                <td>{cur(h.currency, h.close)}</td>
                <td>{cur(h.currency, h.value)}</td>
                <td className={(h.pnl ?? 0) >= 0 ? 'pos' : 'neg'}>{cur(h.currency, h.pnl)}</td>
                <td className={(h.pnl_pct ?? 0) >= 0 ? 'pos' : 'neg'}>
                  {h.pnl_pct === null ? '—' : `${h.pnl_pct >= 0 ? '+' : ''}${h.pnl_pct}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {pf.risk && <div className="card">
        <strong>계좌 리스크</strong>
        <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
          {' '}최근 {pf.risk.days}거래일 · 현재 보유 수량 기준 근사 (환율 고정)</span>
        <div style={{ display: 'flex', gap: 32, marginTop: 10, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>연환산 변동성</div>
            <div style={{ fontWeight: 700, fontSize: 18 }}>{pf.risk.volatility_pct}%</div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>계좌 최대 낙폭 (MDD)</div>
            <div className="neg" style={{ fontWeight: 700, fontSize: 18 }}>{pf.risk.mdd_pct}%</div>
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
        {pf.risk.corr && <>
          <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 12 }}>
            보유 종목 간 일간수익률 상관계수 — 0.7 이상이면 사실상 같은 포지션</div>
          <table style={{ marginTop: 6 }}>
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
        </>}
      </div>}

      {pf.realized && pf.realized.stats.count > 0 && <div className="card">
        <strong>실현손익 · 매매 복기</strong>
        <div style={{ display: 'flex', gap: 32, marginTop: 10, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>총 실현손익 (KRW 환산)</div>
            <div className={pf.realized.stats.total_pnl_krw >= 0 ? 'pos' : 'neg'}
                 style={{ fontWeight: 700, fontSize: 18 }}>
              {pf.realized.stats.total_pnl_krw >= 0 ? '+' : ''}₩{fmt(pf.realized.stats.total_pnl_krw)}</div>
          </div>
          <div>
            <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>승률</div>
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
        <table style={{ marginTop: 12 }}>
          <thead><tr><th>매도일</th><th>심볼</th><th>수량</th><th>평단</th><th>매도가</th>
            <th>실현손익</th><th>수익률</th><th>진입 등급</th><th>메모</th></tr></thead>
          <tbody>
            {pf.realized.entries.map((r, i) => (
              <tr key={i}>
                <td style={{ textAlign: 'left' }}>{r.trade_date}</td>
                <td>{r.symbol}</td>
                <td>{fmt(r.quantity)}</td>
                <td>{fmt(r.buy_price)}</td>
                <td>{fmt(r.sell_price)}</td>
                <td className={r.pnl >= 0 ? 'pos' : 'neg'}>{fmt(r.pnl)}</td>
                <td className={r.pnl_pct >= 0 ? 'pos' : 'neg'}>
                  {r.pnl_pct >= 0 ? '+' : ''}{r.pnl_pct}%</td>
                <td>{r.entry_grade ?? '—'}</td>
                <td style={{ textAlign: 'left', maxWidth: 200, overflow: 'hidden',
                             textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    title={r.note ?? ''}>{r.note ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>}

      <div className="card">
        <strong>매매 입력</strong>
        <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
          <input placeholder="심볼 (예: 005930, AAPL, KRW-BTC)" value={form.symbol}
                 onChange={e => setForm({ ...form, symbol: e.target.value })} style={{ width: 200 }} />
          <select value={form.side} onChange={e => setForm({ ...form, side: e.target.value })}>
            <option value="BUY">매수</option><option value="SELL">매도</option>
          </select>
          <input type="number" placeholder="수량" value={form.quantity}
                 onChange={e => setForm({ ...form, quantity: e.target.value })} style={{ width: 100 }} />
          <input type="number" placeholder="단가" value={form.price}
                 onChange={e => setForm({ ...form, price: e.target.value })} style={{ width: 130 }} />
          <input type="date" value={form.trade_date}
                 onChange={e => setForm({ ...form, trade_date: e.target.value })} />
          <input placeholder="메모 (진입/청산 근거)" value={form.note}
                 onChange={e => setForm({ ...form, note: e.target.value })} style={{ flex: 1, minWidth: 180 }} />
          <button onClick={addTrade}>추가</button>
        </div>
        {msg && <div style={{ color: 'var(--sell)', marginTop: 8 }}>{msg}</div>}
        <table style={{ marginTop: 12 }}>
          <thead><tr><th>날짜</th><th>심볼</th><th>구분</th><th>수량</th><th>단가</th>
            <th>체결 시 등급</th><th>메모</th><th></th></tr></thead>
          <tbody>
            {trades.slice().reverse().map(tr => (
              <tr key={tr.id}>
                <td style={{ textAlign: 'left' }}>{tr.trade_date}</td>
                <td>{tr.symbol}</td>
                <td className={tr.side === 'BUY' ? 'pos' : 'neg'}>
                  {tr.side === 'BUY' ? '매수' : '매도'}</td>
                <td>{fmt(tr.quantity)}</td>
                <td>{fmt(tr.price)}</td>
                <td>{tr.grade_at_trade ?? '—'}</td>
                <td style={{ textAlign: 'left', maxWidth: 220, overflow: 'hidden',
                             textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    title={tr.note ?? ''}>{tr.note ?? ''}</td>
                <td><button className="ghost"
                  onClick={() => del(`/api/trades/${tr.id}`).then(load)}>삭제</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
