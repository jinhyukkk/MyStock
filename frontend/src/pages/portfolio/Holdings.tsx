import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { del, post, put } from '../../api'
import { cashClampWarning, type TradeResult } from '../../trade'
import SymbolInput from '../../components/SymbolInput'
import AllocationDonut from '../../components/AllocationDonut'
import { cur, fmt } from '../../format'
import { usePortfolio } from './context'

export default function Holdings() {
  const { pf, trades, posRule, setPosRule, reload, setCashWarn } = usePortfolio()
  const [form, setForm] = useState({ symbol: '', side: 'BUY', quantity: '', price: '',
    trade_date: new Date().toISOString().slice(0, 10), executed_at: '',
    note: '', fee: '', tax: '', exclude_from_stats: false })
  const [msg, setMsg] = useState<string | null>(null)
  const [cashInput, setCashInput] = useState<string>('')
  const [cashUsdInput, setCashUsdInput] = useState<string>('')

  // 현재 저장된 값을 프리필 — 한쪽만 고치려다 다른 쪽을 날리는 일이 없게
  useEffect(() => {
    setCashInput(String(pf.totals.cash_krw))
    setCashUsdInput(String(pf.totals.cash_usd ?? 0))
  }, [pf.totals.cash_krw, pf.totals.cash_usd])

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
    try { await put('/api/cash', body); setMsg(null); reload() }
    catch (e) { setMsg(String(e)) }
  }

  const savePositionRule = async () => {
    const min = Number(posRule.min), max = Number(posRule.max)
    if (!Number.isInteger(min) || !Number.isInteger(max) || min < 1 || min > max) {
      setMsg('목표 종목 수는 1 이상이어야 하고 최소 ≤ 최대여야 합니다'); return
    }
    try { await put('/api/position-rule', { min, max }); setMsg(null); reload() }
    catch (e) { setMsg(String(e)) }
  }

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

  const t = pf.totals
  // 배당이 한 건도 없는 계좌에 열을 하나 더 세우면, 평가손익과 똑같은 숫자가
  // 두 번 나오면서 표만 넓어진다 — 배당이 실제로 있을 때만 총수익을 세운다.
  const hasDiv = t.dividend_krw > 0
  return (
    <>
      <div className="grid-2">
        <div className="card">
          {/* 같은 손익을 두 분모로 나눠 함께 보여준다 — 하나만 두면 현금 비중이 큰 계좌에서
              체감 손실이 부풀려 읽히고 포지션 사이즈 판단이 통째로 틀어진다. */}
          <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>
            총자산 대비 {t.total_pnl_pct_of_asset >= 0 ? '+' : ''}{t.total_pnl_pct_of_asset}%
            {' · '}보유 종목 평가손익이며 실현손익은{' '}
            <Link to="/portfolio/realized">복기</Link> 탭에 따로 있습니다</div>
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
          {/* 목표 종목 수 — 비중 상한도 총 리스크도 지키면서 종목 수만 두 배가 된
              계좌는 어떤 한도에도 걸리지 않는다. 추적 가능한 개수가 규율의 전제다. */}
          <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center',
                        flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>목표 종목 수</span>
            <input type="number" min={1} value={posRule.min} aria-label="목표 종목 수 최소"
                   onChange={e => setPosRule(r => ({ ...r, min: e.target.value }))}
                   style={{ width: 64 }} />
            <span style={{ color: 'var(--text-dim)' }}>~</span>
            <input type="number" min={1} value={posRule.max} aria-label="목표 종목 수 최대"
                   onChange={e => setPosRule(r => ({ ...r, max: e.target.value }))}
                   style={{ width: 64 }} />
            <button className="ghost" onClick={savePositionRule}>저장</button>
            <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
              현재 {pf.holdings.length}종목 — 범위를 벗어나면 대시보드가 경고합니다</span>
          </div>
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
