import { useEffect, useState } from 'react'
import { post } from '../api'

/** 종목 상세에서 바로 매매를 기록하는 모달.
 *  기록이 포트폴리오 탭 최하단에만 있으면 "판단 → 주문 → 기록" 사이에 탭 이동과
 *  심볼 재입력이 끼어든다. 그 마찰이 기록 누락을 만들고, 기록이 없으면
 *  실현손익·진입 등급별 성과 같은 이 앱의 복기 기능이 통째로 비어버린다. */
export default function TradeDialog({ symbol, name, currency, defaultPrice, onClose, onSaved }: {
  symbol: string
  name: string
  currency: string
  defaultPrice: number | null
  onClose: () => void
  onSaved: () => void
}) {
  const [side, setSide] = useState('BUY')
  const [quantity, setQuantity] = useState('')
  const [price, setPrice] = useState(defaultPrice !== null ? String(defaultPrice) : '')
  const [tradeDate, setTradeDate] = useState(new Date().toISOString().slice(0, 10))
  const [note, setNote] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const save = async () => {
    const q = Number(quantity), p = Number(price)
    if (!(q > 0) || !(p > 0)) { setMsg('수량·단가를 확인하세요 (0 이하 불가)'); return }
    setBusy(true)
    try {
      await post('/api/trades', { symbol, side, quantity: q, price: p,
                                  trade_date: tradeDate, note: note.trim() || null })
      onSaved(); onClose()
    } catch (e) { setMsg(String(e)) }
    finally { setBusy(false) }
  }

  const unit = currency === 'USD' ? '$' : '₩'
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <strong>매매 기록 — {name}</strong>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 2 }}>{symbol}</div>

        <div className="modal-row">
          <label htmlFor="td-side">구분</label>
          <select id="td-side" value={side} onChange={e => setSide(e.target.value)}>
            <option value="BUY">매수</option><option value="SELL">매도</option>
          </select>
        </div>
        <div className="modal-row">
          <label htmlFor="td-qty">수량</label>
          <input id="td-qty" type="number" autoFocus value={quantity}
                 onChange={e => setQuantity(e.target.value)} />
        </div>
        <div className="modal-row">
          <label htmlFor="td-price">체결 단가 ({unit}) — 현재가로 채워둠</label>
          <input id="td-price" type="number" value={price}
                 onChange={e => setPrice(e.target.value)} />
        </div>
        <div className="modal-row">
          <label htmlFor="td-date">체결일</label>
          <input id="td-date" type="date" value={tradeDate}
                 onChange={e => setTradeDate(e.target.value)} />
        </div>
        <div className="modal-row">
          <label htmlFor="td-note">메모 — 진입/청산 근거를 남기면 나중에 복기할 수 있다</label>
          <input id="td-note" value={note} onChange={e => setNote(e.target.value)}
                 placeholder="예: 20일선 돌파, 손절 -5%" />
        </div>

        {msg && <div style={{ color: 'var(--sell)', fontSize: 12, marginTop: 10 }}>{msg}</div>}
        <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
          <button className="ghost" onClick={onClose}>취소</button>
          <button onClick={save} disabled={busy}>{busy ? '저장 중…' : '기록'}</button>
        </div>
      </div>
    </div>
  )
}
