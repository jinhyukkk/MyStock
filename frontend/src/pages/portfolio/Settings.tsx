import { useEffect, useState } from 'react'
import { get, post, put } from '../../api'
import BrokerPanel from './BrokerPanel'
import { fmt } from '../../format'
import type { NotifyStatus } from '../../types'
import { usePortfolio } from './context'

/** 계좌 설정 — 예수금 · 목표 종목 수 · 증권사 연동.
 *  보유 표와 같은 카드에 접혀 있으면 매일 보는 화면에 매달 한 번 쓰는 입력이 섞인다. */
export default function Settings() {
  const { pf, posRule, setPosRule, reload } = usePortfolio()
  const [msg, setMsg] = useState<string | null>(null)
  const [cashInput, setCashInput] = useState<string>('')
  const [cashUsdInput, setCashUsdInput] = useState<string>('')
  // 알림은 .env에만 있어 화면에서 켜졌는지조차 알 수 없었다 — 룰을 걸어두고
  // 안 울리는 이유를 서버 파일을 열어야 알 수 있으면 알림을 신뢰할 수 없다.
  const [notify, setNotify] = useState<NotifyStatus | null>(null)
  const [token, setToken] = useState('')
  const [chatId, setChatId] = useState('')
  const [notifyMsg, setNotifyMsg] = useState<{ text: string; error?: boolean } | null>(null)

  useEffect(() => {
    get<NotifyStatus>('/api/notify')
      .then(n => { setNotify(n); setChatId(n.chat_id) })
      .catch(e => setNotifyMsg({ text: String(e), error: true }))
  }, [])

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

    const prevKrw = pf.totals.cash_krw ?? 0
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

  const saveNotify = async (clear = false) => {
    if (clear && !confirm('알림을 끕니다. 룰에 도달해도 텔레그램 메시지가 오지 않습니다.')) return
    try {
      // 토큰은 빈 칸이면 '변경 없음' — 채팅 ID만 고치려다 알림이 통째로 꺼지지 않게
      const body = clear ? { bot_token: '', chat_id: '' }
        : { bot_token: token || undefined, chat_id: chatId }
      const n = await put<NotifyStatus>('/api/notify', body)
      setNotify(n); setToken(''); setChatId(n.chat_id)
      setNotifyMsg({ text: clear ? '알림을 껐습니다' : '저장했습니다' })
    } catch (e) { setNotifyMsg({ text: String(e), error: true }) }
  }

  const testNotify = async () => {
    setNotifyMsg({ text: '보내는 중…' })
    try {
      await post('/api/notify/test')
      setNotifyMsg({ text: '테스트 메시지를 보냈습니다 — 텔레그램을 확인하세요' })
    } catch (e) { setNotifyMsg({ text: String(e), error: true }) }
  }

  return (
    <>
      <div className="card">
        <strong>예수금</strong>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 4 }}>
          총자산의 분모이자 1% 리스크 수량의 기준입니다 — 실제와 다르면 포지션 사이즈가 함께 틀어집니다.</div>
        <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center',
                      flexWrap: 'wrap' }}>
          <input type="number" placeholder="예수금 (KRW)" value={cashInput}
                 onChange={e => setCashInput(e.target.value)}
                 style={{ flex: '1 1 140px', minWidth: 0 }} />
          <input type="number" placeholder="달러 예수금 (USD)" value={cashUsdInput}
                 onChange={e => setCashUsdInput(e.target.value)}
                 style={{ flex: '1 1 140px', minWidth: 0 }} />
          <button onClick={saveCash}>저장</button>
          <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>
            비우면 변경 없음{pf.broker.accounts.length > 0 &&
              ' — 증권사 동기화 시 실제 잔고로 덮어씁니다'}</span>
        </div>
      </div>

      {/* 목표 종목 수 — 비중 상한도 총 리스크도 지키면서 종목 수만 두 배가 된
          계좌는 어떤 한도에도 걸리지 않는다. 추적 가능한 개수가 규율의 전제다. */}
      <div className="card">
        <strong>목표 종목 수</strong>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 4 }}>
          범위를 벗어나면 대시보드가 정리 후보를 표시합니다.</div>
        <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center',
                      flexWrap: 'wrap' }}>
          <input type="number" min={1} value={posRule.min} aria-label="목표 종목 수 최소"
                 onChange={e => setPosRule(r => ({ ...r, min: e.target.value }))}
                 style={{ width: 64 }} />
          <span style={{ color: 'var(--text-dim)' }}>~</span>
          <input type="number" min={1} value={posRule.max} aria-label="목표 종목 수 최대"
                 onChange={e => setPosRule(r => ({ ...r, max: e.target.value }))}
                 style={{ width: 64 }} />
          <button className="ghost" onClick={savePositionRule}>저장</button>
          <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>현재 {pf.holdings.length}종목</span>
        </div>
      </div>

      {msg && <div className="warn-box">⚠ {msg}</div>}

      <div className="card">
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <strong>알림 (텔레그램)</strong>
          <span style={{ fontSize: 12, color: notify?.enabled ? 'var(--buy)' : 'var(--text-dim)' }}>
            {notify === null ? '' : notify.enabled ? '● 켜짐' : '○ 꺼짐'}
            {notify?.enabled && notify.source === 'env' && ' (.env 설정)'}</span>
        </div>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginTop: 4 }}>
          손절·목표가 룰에 도달하면 메시지를 보냅니다. 같은 룰은 하루 한 번만 갑니다.</div>
        <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center',
                      flexWrap: 'wrap' }}>
          <input type="password" autoComplete="off" value={token}
                 placeholder={notify?.token_set ? '봇 토큰 (저장됨 — 바꿀 때만 입력)' : '봇 토큰'}
                 onChange={e => setToken(e.target.value)} style={{ flex: '1 1 200px', minWidth: 0 }} />
          <input value={chatId} placeholder="채팅 ID" autoComplete="off"
                 onChange={e => setChatId(e.target.value)} style={{ flex: '1 1 140px', minWidth: 0 }} />
          <button onClick={() => saveNotify()}>저장</button>
          {/* 룰이 걸릴 때까지 기다려서 설정 오류를 알면, 그동안 놓친 알림은 되돌릴 수 없다 */}
          <button className="ghost" onClick={testNotify} disabled={!notify?.enabled}>테스트 발송</button>
          {notify?.enabled && <button className="ghost" onClick={() => saveNotify(true)}>알림 끄기</button>}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 6 }}>
          @BotFather로 봇을 만들면 토큰이 나오고, 그 봇에게 아무 메시지나 보낸 뒤{' '}
          <code>api.telegram.org/bot&lt;토큰&gt;/getUpdates</code>의 <code>chat.id</code>가 채팅 ID입니다.</div>
        {notifyMsg && <div style={{ fontSize: 12, marginTop: 6,
               color: notifyMsg.error ? 'var(--sell)' : 'var(--text-dim)' }}>
          {notifyMsg.error && '⚠ '}{notifyMsg.text}</div>}
      </div>

      <div className="card">
        <BrokerPanel status={pf.broker} reload={reload}
                     totalAssetKrw={pf.totals.total_asset_krw} />
      </div>
    </>
  )
}
