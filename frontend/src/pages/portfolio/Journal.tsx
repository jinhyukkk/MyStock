import { useState } from 'react'
import { Link } from 'react-router-dom'
import { del, post } from '../../api'
import { cashClampWarning, type TradeResult } from '../../trade'
import SymbolInput from '../../components/SymbolInput'
import { fmt } from '../../format'
import { usePortfolio } from './context'

export default function Journal() {
  const { trades, reload, setCashWarn } = usePortfolio()
  const [form, setForm] = useState({ symbol: '', side: 'BUY', quantity: '', price: '',
    trade_date: new Date().toISOString().slice(0, 10), executed_at: '',
    note: '', fee: '', tax: '', exclude_from_stats: false })
  const [msg, setMsg] = useState<string | null>(null)

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
      reload()
    } catch (e) { setMsg(String(e)) }
  }

  return (
    <>
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
          입출금·배당은 <Link to="/portfolio/income"><strong>배당 · 현금흐름</strong></Link> 탭에
          기록하세요 — 예수금 칸을 직접 고치면 원장에 근거가 남지 않습니다.</div>
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
                    del(`/api/trades/${tr.id}`).then(reload).catch(e => setMsg(String(e)))
                }}>삭제</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>
    </>
  )
}
