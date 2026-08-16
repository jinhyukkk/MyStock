import { useEffect, useState } from 'react'
import { post } from '../api'
import { cashClampWarning, type TradeResult } from '../trade'
import type { ExitPlan } from '../types'

/** 종목 상세에서 바로 매매를 기록하는 모달.
 *  기록이 포트폴리오 탭 최하단에만 있으면 "판단 → 주문 → 기록" 사이에 탭 이동과
 *  심볼 재입력이 끼어든다. 그 마찰이 기록 누락을 만들고, 기록이 없으면
 *  실현손익·진입 등급별 성과 같은 이 앱의 복기 기능이 통째로 비어버린다. */
export default function TradeDialog({ symbol, name, currency, defaultPrice, defaultSide,
                                      defaultQuantity, costRates, exitPlan, suggestedQuantity,
                                      cash, onClose, onSaved }: {
  symbol: string
  name: string
  currency: string
  defaultPrice: number | null
  /** 어느 쪽으로 열지 — 청산 플랜에서 열었는데 매수로 시작하면 그 자체가 오조작을 부른다 */
  defaultSide?: 'BUY' | 'SELL'
  /** 비용 추정 요율 (%) — 없으면 프리뷰에서 비용 줄을 생략한다 */
  costRates?: { fee_pct: number; sell_tax_pct: number }
  /** 보유 정보 — 매도 시 예상 실현손익을 계산한다 */
  exitPlan?: ExitPlan | null
  /** 상세 화면이 계산해 둔 제안 수량 — 옮겨 적다 틀리는 마찰을 없앤다 */
  suggestedQuantity?: number | null
  /** 청산 플랜의 특정 비중(1/3·1/2)에서 열었을 때 그 수량으로 시작한다 */
  defaultQuantity?: number | null
  /** 예수금 — 체결 후 잔액을 미리 보여준다 */
  cash?: { krw: number; usd: number }
  onClose: () => void
  onSaved: () => void
}) {
  const [side, setSide] = useState<string>(defaultSide ?? 'BUY')
  const [quantity, setQuantity] = useState(
    defaultQuantity && defaultQuantity > 0 ? String(defaultQuantity) : '')
  const [price, setPrice] = useState(defaultPrice !== null ? String(defaultPrice) : '')
  const [tradeDate, setTradeDate] = useState(new Date().toISOString().slice(0, 10))
  const [executedAt, setExecutedAt] = useState('')
  const [note, setNote] = useState('')
  const [fee, setFee] = useState('')
  const [tax, setTax] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [clamp, setClamp] = useState<string | null>(null)  // 예수금이 0으로 잘렸다는 사실

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  // 빈 값은 "미기록" → 서버가 시장 요율로 추정한다. 0으로 보내면 비용 없는 매매가 되어
  // 승률·손익비가 gross로 되돌아간다.
  const optionalCost = (raw: string): number | null => {
    const s = raw.trim()
    if (s === '') return null
    const n = Number(s)
    return Number.isFinite(n) && n >= 0 ? n : null
  }

  const save = async () => {
    const q = Number(quantity), p = Number(price)
    if (!(q > 0) || !(p > 0)) { setMsg('수량·단가를 확인하세요 (0 이하 불가)'); return }
    setBusy(true)
    try {
      const res = await post<TradeResult>('/api/trades',
                                { symbol, side, quantity: q, price: p,
                                  trade_date: tradeDate, note: note.trim() || null,
                                  fee: optionalCost(fee), tax: optionalCost(tax),
                                  executed_at: executedAt || null })
      onSaved()
      // 예수금이 잘렸으면 닫지 않는다 — 모달이 사라지면 그 사실이 어디에도 남지 않고,
      // 작아진 총자산이 이후 모든 종목의 제안 수량을 조용히 줄인다.
      const warn = cashClampWarning(res)
      if (warn) { setClamp(warn); setMsg(null) } else onClose()
    } catch (e) { setMsg(String(e)) }
    finally { setBusy(false) }
  }

  const unit = currency === 'USD' ? '$' : '₩'
  const fmt = (n: number) => n.toLocaleString('ko-KR', { maximumFractionDigits: 2 })
  // 주문 프리뷰 — 사이즈 오류는 기록 버튼을 누른 뒤에 알면 이미 늦다
  const q = Number(quantity), p = Number(price)
  const notional = q > 0 && p > 0 ? q * p : null
  const estCost = notional !== null && costRates
    ? notional * (costRates.fee_pct + (side === 'SELL' ? costRates.sell_tax_pct : 0)) / 100
    : null
  const held = exitPlan?.held_quantity ?? 0
  const sellPnl = side === 'SELL' && notional !== null && exitPlan
    ? (p - exitPlan.avg_price) * Math.min(q, held) - (estCost ?? 0)
    : null
  const oversell = side === 'SELL' && q > 0 && q > held
  // 체결 후 예수금 — 초과를 사후 클램프 경고로 알면 이미 원장이 틀어진 뒤다.
  // 백엔드와 같은 계산(매수는 대금+비용이 나가고, 매도는 비용을 뺀 만큼 들어온다).
  const cashNow = cash ? (currency === 'USD' ? cash.usd : cash.krw) : null
  const cashAfter = cashNow !== null && notional !== null
    ? cashNow + (side === 'BUY' ? -(notional + (estCost ?? 0)) : notional - (estCost ?? 0))
    : null
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
          <label htmlFor="td-qty">수량
            {side === 'SELL' && held > 0 && <span style={{ color: 'var(--text-dim)' }}>
              {' '}— 보유 {fmt(held)} · 평단 {unit}{fmt(exitPlan!.avg_price)}</span>}</label>
          <div style={{ display: 'flex', gap: 8 }}>
            <input id="td-qty" type="number" autoFocus value={quantity}
                   onChange={e => setQuantity(e.target.value)}
                   style={{ flex: 1, minWidth: 0 }} />
            {/* 상세 화면에 이미 계산된 수량을 손으로 옮겨 적다 틀리는 일을 없앤다 */}
            {side === 'BUY' && (suggestedQuantity ?? 0) > 0 && (
              <button className="ghost" type="button"
                      onClick={() => setQuantity(String(suggestedQuantity))}>
                제안 {fmt(suggestedQuantity!)}</button>)}
            {/* 부분 청산은 이 앱이 권장하는 행동인데 유독 손으로 계산해야 했다 */}
            {side === 'SELL' && held > 0 && exitPlan?.slices.map(s => (
              <button key={s.label} className="ghost" type="button"
                      onClick={() => setQuantity(String(s.quantity))}>{s.label}</button>))}
            {side === 'SELL' && held > 0 && !exitPlan?.slices.length && (
              <button className="ghost" type="button"
                      onClick={() => setQuantity(String(held))}>전량</button>)}
          </div>
        </div>
        <div className="modal-row">
          <label htmlFor="td-price">체결 단가 ({unit}) — 현재가로 채워둠</label>
          <input id="td-price" type="number" value={price}
                 onChange={e => setPrice(e.target.value)} />
        </div>
        <div className="modal-row">
          {/* 같은 날 매도 후 재매수는 순서가 뒤바뀌면 평단이 잘못 만들어진다 */}
          <label htmlFor="td-date">체결일 / 시각 — 같은 날 여러 번 체결했다면 시각을 남기세요</label>
          <div style={{ display: 'flex', gap: 8 }}>
            <input id="td-date" type="date" value={tradeDate}
                   onChange={e => setTradeDate(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
            <input type="time" value={executedAt}
                   onChange={e => setExecutedAt(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
          </div>
        </div>
        <div className="modal-row">
          <label htmlFor="td-fee">수수료 / 세금 ({unit}) — 비우면 시장 기본 요율로 추정</label>
          <div style={{ display: 'flex', gap: 8 }}>
            <input id="td-fee" type="number" value={fee} placeholder="수수료"
                   onChange={e => setFee(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
            <input type="number" value={tax} placeholder="세금"
                   onChange={e => setTax(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
          </div>
        </div>
        <div className="modal-row">
          <label htmlFor="td-note">메모 — 진입/청산 근거를 남기면 나중에 복기할 수 있다</label>
          <input id="td-note" value={note} onChange={e => setNote(e.target.value)}
                 placeholder="예: 20일선 돌파, 손절 -5%" />
        </div>

        {/* 주문 프리뷰 — 체결금액과 비용을 기록 전에 보여주지 않으면
            사이즈 오류를 원장에 남긴 뒤에야 알게 된다. */}
        {notional !== null && <div style={{ marginTop: 12, padding: '8px 10px',
          background: 'var(--bg)', borderRadius: 6, fontSize: 12 }}>
          <div><strong>체결금액 {unit}{fmt(notional)}</strong>
            {estCost !== null && <span style={{ color: 'var(--text-dim)' }}>
              {' · '}추정 비용 {unit}{fmt(estCost)}
              {' → '}{side === 'BUY' ? '예수금 차감' : '순회수'}
              {' '}{unit}{fmt(side === 'BUY' ? notional + estCost : notional - estCost)}</span>}</div>
          {sellPnl !== null && <div className={sellPnl >= 0 ? 'pos' : 'neg'} style={{ marginTop: 4 }}>
            예상 실현손익 {sellPnl >= 0 ? '+' : '-'}{unit}{fmt(Math.abs(sellPnl))}
            <span style={{ color: 'var(--text-dim)' }}> (비용 차감 후 · 평단 기준)</span>
            {/* 이 숫자에는 이듬해 5월에 낼 양도세가 아직 들어 있다 */}
            {exitPlan?.taxable_overseas && sellPnl > 0 && <span style={{ color: 'var(--text-dim)' }}>
              {' '}· 해외 양도세 22%는 미차감</span>}</div>}
          {cashAfter !== null && <div style={{ marginTop: 4,
            color: cashAfter < 0 ? 'var(--warn)' : 'var(--text-dim)' }}>
            체결 후 {currency === 'USD' ? '달러 ' : '원화 '}예수금
            {' '}{unit}{fmt(Math.max(cashAfter, 0))}
            <span> (현재 {unit}{fmt(cashNow!)})</span>
            {/* 음수면 기록 시 0으로 잘린다 — 잘린 뒤에 알면 총자산이 이미 틀어져 있다 */}
            {cashAfter < 0 && <> — 예수금보다 {unit}{fmt(-cashAfter)} 많습니다.
              {' '}이대로 기록하면 예수금은 0으로 잘립니다.</>}</div>}
        </div>}
        {oversell && <div className="warn-box" style={{ marginTop: 8, fontSize: 12 }}>
          ⚠ 보유 {fmt(held)}보다 많은 수량입니다 — 이대로는 기록되지 않습니다.</div>}

        <div style={{ color: 'var(--text-dim)', fontSize: 11, marginTop: 10 }}>
          기록하면 예수금이 체결 대금만큼 자동으로 증감합니다 (입출금·배당은 예수금을 직접 수정).</div>
        {clamp && <div className="warn-box" style={{ marginTop: 10, fontSize: 12 }}>⚠ {clamp}</div>}
        {msg && <div style={{ color: 'var(--sell)', fontSize: 12, marginTop: 10 }}>{msg}</div>}
        <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
          {clamp
            ? <button onClick={onClose}>확인</button>
            : <>
                <button className="ghost" onClick={onClose}>취소</button>
                <button onClick={save} disabled={busy}>{busy ? '저장 중…' : '기록'}</button>
              </>}
        </div>
      </div>
    </div>
  )
}
