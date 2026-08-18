import { useState } from 'react'
import { del, post, put } from '../../api'
import type { BrokerAccount, BrokerFlowResult, BrokerStatus, BrokerSyncResult } from '../../types'

// CODEF 기관코드. 잔고조회가 열려 있는 증권사만 추렸다 — 목록에 없으면
// 코드를 직접 넣을 수 있게 입력도 함께 둔다.
const ORGS: [string, string][] = [
  ['0264', '키움증권'], ['0243', '한국투자증권'], ['0240', '삼성증권'],
  ['0238', '미래에셋증권'], ['0247', 'NH투자증권'], ['1247', '모바일증권 나무'],
  ['0218', 'KB증권'], ['0278', '신한투자증권'], ['0270', '하나증권'],
  ['0267', '대신증권'], ['1267', '크레온(대신)'], ['0265', 'LS증권'],
  ['0269', '한화투자증권'], ['0209', '유안타증권'], ['0266', 'SK증권'],
  ['0261', '교보증권'], ['0280', '유진투자증권'], ['0287', '메리츠증권'],
]

// 조회 가능 기간이 증권사마다 다르다(키움 3개월 등) — 기본은 안전한 90일
const ymd = (daysAgo: number) => {
  const d = new Date()
  d.setDate(d.getDate() - daysAgo)
  return d.toISOString().slice(0, 10)
}

const readBase64 = (f: File) => new Promise<string>((resolve, reject) => {
  const r = new FileReader()
  // data URL의 헤더를 떼면 CODEF가 요구하는 순수 base64가 된다
  r.onload = () => resolve(String(r.result).split(',')[1] ?? '')
  r.onerror = () => reject(new Error('파일을 읽지 못했습니다'))
  r.readAsDataURL(f)
})

export default function BrokerPanel({ status, reload }:
  { status: BrokerStatus; reload: () => void }) {
  const [org, setOrg] = useState('0264')
  const [loginType, setLoginType] = useState<'0' | '1'>('0')
  const [password, setPassword] = useState('')
  const [userId, setUserId] = useState('')
  const [der, setDer] = useState<File | null>(null)
  const [key, setKey] = useState<File | null>(null)
  const [found, setFound] = useState<BrokerAccount[] | null>(null)
  const [picked, setPicked] = useState<Record<string, string>>({})  // account → 계좌비번
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [result, setResult] = useState<BrokerSyncResult | null>(null)
  const [from, setFrom] = useState(ymd(90))
  const [to, setTo] = useState(ymd(0))
  const [flows, setFlows] = useState<BrokerFlowResult | null>(null)

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label); setErr(null)
    try { await fn() } catch (e) { setErr(String(e instanceof Error ? e.message : e)) }
    finally { setBusy(null) }
  }

  const connect = () => run('연결 중', async () => {
    if (loginType === '0' && !(der && key)) throw new Error('인증서 der/key 파일을 선택하세요')
    const body = {
      organization: org, login_type: loginType, password,
      user_id: userId || null,
      der_file: der ? await readBase64(der) : null,
      key_file: key ? await readBase64(key) : null,
    }
    const out = await post<{ accounts: BrokerAccount[] }>('/api/broker/connect', body)
    setPassword('')  // 비밀번호는 화면에도 남기지 않는다
    setFound(out.accounts)
    if (out.accounts.length === 0) setErr('조회된 계좌가 없습니다')
  })

  const saveAccounts = () => run('저장 중', async () => {
    const accounts = (found ?? []).filter(a => a.account in picked).map(a => ({
      organization: a.organization, account: a.account, display: a.display, name: a.name,
      account_password: picked[a.account] || null,
    }))
    if (accounts.length === 0) throw new Error('동기화할 계좌를 선택하세요')
    await put('/api/broker/accounts', { accounts })
    setFound(null); setPicked({})
    reload()
  })

  const sync = () => run('조회 중', async () => {
    setResult(await post<BrokerSyncResult>('/api/broker/sync'))
    reload()
  })

  const importFlows = () => run('가져오는 중', async () => {
    setFlows(await post<BrokerFlowResult>('/api/broker/flows', {
      start_date: from.replaceAll('-', ''), end_date: to.replaceAll('-', ''),
    }))
    reload()
  })

  const disconnect = () => run('해제 중', async () => {
    if (!confirm('증권사 연동을 해제합니다. 보유 종목이 다시 매매 기록(원장) 기준으로 돌아갑니다.')) return
    await del('/api/broker')
    setFound(null); setResult(null)
    reload()
  })

  if (!status.configured) return (
    <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 8 }}>
      증권사 실시간 연동을 쓰려면 <code>.env</code>에 <code>CODEF_CLIENT_ID</code>,{' '}
      <code>CODEF_CLIENT_SECRET</code>, <code>CODEF_PUBLIC_KEY</code>를 넣고 서버를 다시 시작하세요.{' '}
      키는 <a href="https://codef.io" target="_blank" rel="noreferrer">codef.io</a> 마이페이지 &gt;
      키 관리에서 발급받습니다.
    </div>
  )

  return (
    <div style={{ marginTop: 10, borderTop: '1px solid var(--line)', paddingTop: 10 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <strong style={{ fontSize: 13 }}>증권사 연동</strong>
        {status.env === 'demo' && <span className="warn" style={{ fontSize: 11 }}
          title="CODEF 데모 환경입니다. 실제 계좌 데이터가 아닐 수 있습니다.">데모 환경</span>}
        {status.accounts.length > 0 && <>
          <button onClick={sync} disabled={!!busy}>{busy === '조회 중' ? '조회 중…' : '지금 동기화'}</button>
          <button className="ghost" onClick={disconnect} disabled={!!busy}>연동 해제</button>
        </>}
      </div>

      {status.accounts.length > 0 && (
        <div style={{ fontSize: 12, color: 'var(--text-dim)', marginTop: 6 }}>
          {status.accounts.map(a => a.display).join(', ')} · 보유 {status.holdings_count}종목
          {/* 언제 기준인지 없으면 낡은 잔고로 포지션 사이즈를 정하게 된다 */}
          {status.synced_at
            ? ` · 마지막 동기화 ${status.synced_at.replace('T', ' ')}`
            : ' · 아직 동기화하지 않았습니다'}
        </div>
      )}

      {status.accounts.length > 0 && (
        <div style={{ marginTop: 10, display: 'grid', gap: 6 }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <strong style={{ fontSize: 12 }}>입출금·배당 가져오기</strong>
            <input type="date" value={from} max={to} aria-label="조회 시작일"
                   onChange={e => setFrom(e.target.value)} />
            <span style={{ color: 'var(--text-dim)' }}>~</span>
            <input type="date" value={to} min={from} aria-label="조회 종료일"
                   onChange={e => setTo(e.target.value)} />
            <button onClick={importFlows} disabled={!!busy}>
              {busy === '가져오는 중' ? '가져오는 중…' : '가져오기'}</button>
          </div>
          <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
            매매 대금은 가져오지 않습니다 — 체결은 매매 기록이 진실이라 함께 넣으면
            같은 돈이 두 번 잡힙니다. 같은 기간을 다시 눌러도 중복되지 않습니다.
            {status.flow_synced_at && ` · 마지막 ${status.flow_synced_at.replace('T', ' ')}`}
          </div>
          {flows && (
            <div style={{ fontSize: 12 }}>
              <span style={{ color: 'var(--text-dim)' }}>
                입금 {flows.added.DEPOSIT} · 출금 {flows.added.WITHDRAW} ·
                배당 {flows.added.DIVIDEND} · 이자 {flows.added.INTEREST} 건 추가
                (중복 {flows.duplicates} · 매매 제외 {flows.skipped_trades})</span>
              {flows.no_symbol.length > 0 && (
                <div className="warn" style={{ marginTop: 4 }}>
                  ⚠ 종목을 확정하지 못한 배당이 있습니다 — {flows.no_symbol.join(', ')}.
                  배당 화면에 '미지정'으로 잡히니 종목을 직접 지정하세요.</div>
              )}
            </div>
          )}
        </div>
      )}

      {/* 연결 폼 — 계좌를 아직 고르지 않았을 때만 */}
      {status.accounts.length === 0 && found === null && (
        <div style={{ marginTop: 8, display: 'grid', gap: 8 }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <select value={org} onChange={e => setOrg(e.target.value)} aria-label="증권사">
              {ORGS.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
            </select>
            <select value={loginType} aria-label="로그인 방식"
                    onChange={e => setLoginType(e.target.value as '0' | '1')}>
              <option value="0">공동인증서</option>
              <option value="1">아이디/비밀번호</option>
            </select>
          </div>
          {loginType === '0' ? (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
              {/* "der/key"만 쓰면 인증서 폴더의 어떤 파일인지 모른다 — 실제 파일명으로 안내 */}
              <label style={{ fontSize: 12 }}>인증서 (signCert.der){' '}
                <input type="file" accept=".der" onChange={e => setDer(e.target.files?.[0] ?? null)} /></label>
              <label style={{ fontSize: 12 }}>개인키 (signPri.key){' '}
                <input type="file" accept=".key" onChange={e => setKey(e.target.files?.[0] ?? null)} /></label>
            </div>
          ) : (
            <input placeholder="로그인 아이디" value={userId} autoComplete="off"
                   onChange={e => setUserId(e.target.value)} style={{ maxWidth: 240 }} />
          )}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <input type="password" autoComplete="off" value={password}
                   placeholder={loginType === '0' ? '인증서 비밀번호' : '로그인 비밀번호'}
                   onChange={e => setPassword(e.target.value)} style={{ maxWidth: 240 }} />
            <button onClick={connect} disabled={!!busy || !password}>
              {busy === '연결 중' ? '연결 중…' : '연결'}</button>
          </div>
          {/* 무엇이 어디에 남는지 밝히지 않으면 인증서를 넣을 이유가 없다 */}
          <div style={{ fontSize: 11, color: 'var(--text-dim)' }}>
            인증서와 비밀번호는 CODEF로 한 번 전달되고 이 서버에는 저장되지 않습니다.
            이후 조회는 발급받은 커넥티드 아이디로만 이뤄집니다.
          </div>
        </div>
      )}

      {/* 계좌 선택 */}
      {found !== null && found.length > 0 && (
        <div style={{ marginTop: 8, display: 'grid', gap: 6 }}>
          <div style={{ fontSize: 12, color: 'var(--text-dim)' }}>
            동기화할 계좌를 고르세요. 계좌비밀번호를 요구하는 증권사는 함께 입력해야 합니다
            (암호화된 값만 저장됩니다).</div>
          {found.map(a => (
            <div key={a.account} style={{ display: 'flex', gap: 8, alignItems: 'center',
                                          flexWrap: 'wrap' }}>
              <label style={{ fontSize: 13 }}>
                <input type="checkbox" checked={a.account in picked}
                       onChange={e => setPicked(p => {
                         const next = { ...p }
                         if (e.target.checked) next[a.account] = ''
                         else delete next[a.account]
                         return next
                       })} />
                {' '}{a.display} {a.name && <span style={{ color: 'var(--text-dim)' }}>({a.name})</span>}
              </label>
              {a.account in picked && (
                <input type="password" placeholder="계좌비밀번호 (필요한 경우)" autoComplete="off"
                       value={picked[a.account]} style={{ maxWidth: 200 }}
                       onChange={e => setPicked(p => ({ ...p, [a.account]: e.target.value }))} />
              )}
            </div>
          ))}
          <div><button onClick={saveAccounts} disabled={!!busy}>
            {busy === '저장 중' ? '저장 중…' : '선택한 계좌 저장'}</button></div>
        </div>
      )}

      {/* 동기화 결과 — 빠진 종목을 말하지 않으면 총자산이 조용히 작아진다 */}
      {result && (
        <div style={{ fontSize: 12, marginTop: 8 }}>
          <span style={{ color: 'var(--text-dim)' }}>
            {result.holdings}종목 · 예수금 ₩{Math.round(result.cash_krw).toLocaleString()}
            {result.cash_usd > 0 && ` + $${result.cash_usd.toLocaleString()}`} 반영</span>
          {result.unmapped.length > 0 && (
            <div className="warn" style={{ marginTop: 4 }}>
              ⚠ 종목코드를 확정하지 못해 제외된 보유가 있습니다 —{' '}
              {result.unmapped.map(u => `${u.name}(${u.raw_code})`).join(', ')}.
              총자산·비중이 실제보다 작게 나옵니다.</div>
          )}
          {result.basis_missing.length > 0 && (
            <div className="warn" style={{ marginTop: 4 }}>
              ⚠ 증권사가 평균매입가를 주지 않은 종목: {result.basis_missing.join(', ')} —
              해당 행의 손익 0은 '본전'이 아니라 '평단 모름'입니다.</div>
          )}
        </div>
      )}

      {err && <div style={{ color: 'var(--sell)', fontSize: 12, marginTop: 6 }}>{err}</div>}
    </div>
  )
}
