import { useState } from 'react'
import { Link } from 'react-router-dom'
import { del, post } from '../../api'
import { cashClampWarning, type TradeResult } from '../../trade'
import SymbolInput from '../../components/SymbolInput'
import { cur, fmt } from '../../format'
import { usePortfolio } from './context'

const FLOW_LABEL: Record<string, string> = {
  DIVIDEND: '배당', INTEREST: '이자', DEPOSIT: '입금', WITHDRAW: '출금' }

export default function Income() {
  const { pf, flows, reload, setCashWarn } = usePortfolio()
  const [flowForm, setFlowForm] = useState({ flow_type: 'DIVIDEND', symbol: '',
    amount: '', tax: '', flow_date: new Date().toISOString().slice(0, 10), note: '' })
  const [flowMsg, setFlowMsg] = useState<string | null>(null)

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
      reload()
    } catch (e) { setFlowMsg(String(e)) }
  }

  const div = pf.dividends
  return (
    <>
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
          예수금이 자동 증감하므로 <Link to="/portfolio"><strong>보유</strong></Link> 탭의
          <strong> 예수금 칸을 따로 고치지 마세요</strong> — 두 번 계상됩니다.
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
                    del(`/api/cash-flows/${f.id}`).then(reload).catch(e => setFlowMsg(String(e)))
                }}>삭제</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>}
      </div>
    </>
  )
}
