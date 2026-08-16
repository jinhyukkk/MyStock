# 포트폴리오 페이지 분할 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 862줄짜리 `frontend/src/pages/Portfolio.tsx`를 계좌 데이터를 공유하는 5개 하위 탭 화면으로 나눈다.

**Architecture:** `/portfolio`에 중첩 라우트를 두고 `PortfolioLayout`이 API 4개를 한 번만 호출해 `Outlet context`로 하위 화면에 내려준다. 레이아웃 상단에는 총자산 스트립과 하위 탭바가 고정된다. 각 태스크는 블록을 하나씩 떼어내며, 매 커밋마다 앱이 동작해야 한다.

**Tech Stack:** React 19, react-router-dom v7, TypeScript, Vite. 프론트엔드에 테스트 러너가 없다.

**Spec:** [docs/superpowers/specs/2026-08-17-portfolio-page-split-design.md](../specs/2026-08-17-portfolio-page-split-design.md)

## Global Constraints

- **동작은 바뀌지 않는다.** 이번 작업은 이동과 분리다. 표시 숫자·경고 문구·계산 로직·주석을 바꾸지 않는다. 예외는 Task 7에 명시된 세 가지(설정 접기, Risk 빈 상태, Journal 안내 링크)뿐이다.
- **주석을 함께 옮긴다.** 원본의 한글 설명 주석은 그 코드가 왜 그렇게 생겼는지를 담고 있다. 코드를 옮길 때 바로 위 주석도 같이 옮긴다.
- **백엔드를 건드리지 않는다.** `backend/` 아래 파일은 이 계획에서 수정 대상이 아니다.
- **검증 명령:** `cd frontend && npm run build` — `tsc -b`가 포함되어 타입 오류가 있으면 실패한다. 모든 태스크의 마지막 검증은 이 명령이다.
- **프론트엔드 테스트 러너가 없다.** 이 계획은 TDD 대신 `tsc -b` + 실화면 확인으로 검증한다. 러너를 새로 도입하지 않는다 (범위 밖).
- **줄 번호는 `84c766c` 시점의 `frontend/src/pages/Portfolio.tsx` 기준이다.** 앞 태스크가 파일을 줄이므로, 각 태스크는 줄 번호가 아니라 **명시된 시작·끝 마커 문자열**로 대상을 찾는다.

---

### Task 1: 공통 모듈 추출

Portfolio.tsx 안에만 있던 포맷 함수·도넛 컴포넌트·Trade 타입을 밖으로 꺼낸다. 이 태스크가 끝나도 화면은 완전히 동일하다.

**Files:**
- Create: `frontend/src/format.ts`
- Create: `frontend/src/components/AllocationDonut.tsx`
- Modify: `frontend/src/types.ts` (파일 끝에 추가)
- Modify: `frontend/src/pages/Portfolio.tsx` (9–56줄 제거, import 추가)

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `format.ts` → `fmt(n: number | null): string`, `cur(c: string, n: number | null): string`
  - `components/AllocationDonut.tsx` → `export default function AllocationDonut({ allocation }: { allocation: { label: string; value_krw: number }[] })`
  - `types.ts` → `export interface Trade`

- [ ] **Step 1: `frontend/src/format.ts` 생성**

```ts
/** 화면 전역 숫자 포맷. null은 "값 없음"이며 0과 구분해서 보여야 한다 —
 *  0으로 찍으면 "데이터가 없다"가 "손익이 없다"로 읽힌다. */
export const fmt = (n: number | null) =>
  n === null ? '—' : n.toLocaleString('ko-KR', { maximumFractionDigits: 2 })

export const cur = (c: string, n: number | null) =>
  n === null ? '—' : (c === 'USD' ? '$' : '₩') + fmt(n)
```

- [ ] **Step 2: `frontend/src/components/AllocationDonut.tsx` 생성**

`Portfolio.tsx`의 9–48줄(`const PIE_COLORS = [` 부터 `AllocationDonut` 함수 닫는 `}` 까지)을 **주석 포함 그대로** 옮긴다. 파일 맨 위에 아래 두 줄을 넣고, 함수 선언에 `export default`를 붙인다.

```ts
import { fmt } from '../format'
```

- [ ] **Step 3: `frontend/src/types.ts` 끝에 `Trade` 추가**

`Portfolio.tsx` 52–56줄의 인터페이스를 그대로 옮기되 `export`를 붙인다.

```ts
export interface Trade {
  id: number; symbol: string; side: string; quantity: number
  price: number; trade_date: string; executed_at: string | null
  fee: number | null; tax: number | null
  note: string | null; grade_at_trade: string | null
  exclude_from_stats: number
}
```

- [ ] **Step 4: `Portfolio.tsx`에서 옮긴 코드 제거 후 import**

9–56줄(PIE_COLORS ~ Trade 인터페이스)을 지우고 상단 import를 아래로 맞춘다.

```ts
import type { CashFlow, Portfolio as PF, Trade } from '../types'
import { cur, fmt } from '../format'
import AllocationDonut from '../components/AllocationDonut'
```

- [ ] **Step 5: 빌드 확인**

```bash
cd frontend && npm run build
```
Expected: `✓ built` — 타입 오류 0.

- [ ] **Step 6: 커밋**

```bash
git add frontend/src/format.ts frontend/src/components/AllocationDonut.tsx frontend/src/types.ts frontend/src/pages/Portfolio.tsx
git commit -m "refactor: 포트폴리오 공통 조각을 밖으로 — 포맷·도넛·Trade 타입"
```

---

### Task 2: 레이아웃 · 컨텍스트 · 총자산 스트립

데이터 로딩을 레이아웃으로 올리고, 현재 화면 내용 전체를 `Holdings.tsx`로 옮긴다. 이 태스크가 끝나면 URL과 화면은 그대로이되 소유 구조가 바뀐다. 하위 탭바는 아직 없다 (자식이 하나뿐이므로).

**Files:**
- Create: `frontend/src/pages/portfolio/context.ts`
- Create: `frontend/src/pages/portfolio/PortfolioLayout.tsx`
- Create: `frontend/src/pages/portfolio/Holdings.tsx`
- Delete: `frontend/src/pages/Portfolio.tsx`
- Modify: `frontend/src/App.tsx:8`, `frontend/src/App.tsx:21-22`

**Interfaces:**
- Consumes: Task 1의 `fmt`, `cur`, `AllocationDonut`, `Trade`
- Produces:
  - `context.ts` → `interface PortfolioContext`, `usePortfolio(): PortfolioContext`
  - `PortfolioLayout.tsx` → default export, `<Outlet context={...}>` 제공
  - `Holdings.tsx` → default export

- [ ] **Step 1: `frontend/src/pages/portfolio/context.ts` 생성**

```ts
import { useOutletContext } from 'react-router-dom'
import type { CashFlow, Portfolio as PF, Trade } from '../../types'

export interface PortfolioContext {
  /** 레이아웃이 로딩·에러를 먼저 처리하므로 하위 화면에서는 항상 non-null */
  pf: PF
  trades: Trade[]
  flows: CashFlow[]
  posRule: { min: string; max: string }
  setPosRule: (u: (r: { min: string; max: string }) => { min: string; max: string }) => void
  /** 기준시각 계산용 — isStale/relativeTime에 넘긴다 */
  now: number
  /** 입력·삭제 후 4개 API를 다시 불러 모든 탭을 함께 갱신한다 */
  reload: () => void
  /** 예수금 클램프 경고 — 총자산에 관한 내용이라 스트립 아래에 뜬다 */
  setCashWarn: (msg: string | null) => void
}

export const usePortfolio = () => useOutletContext<PortfolioContext>()
```

- [ ] **Step 2: `frontend/src/pages/portfolio/PortfolioLayout.tsx` 생성**

`Portfolio.tsx`에서 아래를 그대로 가져온다: 상태 `pf/trades/flows/error/now/cashWarn/posRule`, `load()`, `useEffect`, 에러 카드, 스켈레톤. `msg`·`form`·`flowForm`·`cashInput`·`cashUsdInput`·`parseCash`·`saveCash`·`savePositionRule`·`addTrade`·`addFlow`·`optionalCost`는 **가져오지 않는다** (각 화면 소유).

```tsx
import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import { get } from '../../api'
import type { CashFlow, Portfolio as PF, Trade } from '../../types'
import { isStale, relativeTime } from '../../time'
import { fmt } from '../../format'

export default function PortfolioLayout() {
  const [pf, setPf] = useState<PF | null>(null)
  const [trades, setTrades] = useState<Trade[]>([])
  const [flows, setFlows] = useState<CashFlow[]>([])
  const [posRule, setPosRule] = useState({ min: '', max: '' })
  const [cashWarn, setCashWarn] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [now, setNow] = useState(Date.now())

  const load = () => Promise.all([
    get<PF>('/api/portfolio'),
    get<Trade[]>('/api/trades'),
    get<CashFlow[]>('/api/cash-flows'),
    get<{ min: number; max: number }>('/api/position-rule'),
  ]).then(([p, tr, fl, pr]) => {
    setPf(p); setTrades(tr); setFlows(fl); setError(null); setNow(Date.now())
    setPosRule({ min: String(pr.min), max: String(pr.max) })
  }).catch(e => setError(String(e)))
  useEffect(() => { load() }, [])

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
      {/* 계좌 규모가 화면에서 사라지면 포지션 사이즈 판단이 끊긴다 — 모든 탭에 고정한다 */}
      <div className="card pf-strip">
        <div>
          <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>총자산 (KRW 환산)</div>
          <div style={{ fontSize: 22, fontWeight: 700 }}>₩{fmt(t.total_asset_krw)}</div>
        </div>
        <div>
          <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>평가손익</div>
          <div className={t.total_pnl_krw >= 0 ? 'pos' : 'neg'} style={{ fontSize: 18, fontWeight: 700 }}>
            {t.total_pnl_krw >= 0 ? '+' : ''}₩{fmt(t.total_pnl_krw)}
            <span style={{ fontSize: 12 }}> (원금 대비 {t.total_pnl_pct}%)</span></div>
        </div>
        <div>
          <div style={{ color: 'var(--text-dim)', fontSize: 12 }}>현금</div>
          <div style={{ fontSize: 18, fontWeight: 700 }}>
            ₩{fmt(t.cash_krw + (t.cash_usd_krw ?? 0))}
            <span style={{ fontSize: 12, color: 'var(--text-dim)' }}> ({t.cash_pct}%)</span></div>
        </div>
        <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
          <div className={stale ? 'warn' : ''} style={{ fontSize: 11,
                 color: stale ? undefined : 'var(--text-dim)' }} title={pf.last_refresh ?? ''}>
            {stale && '⚠ '}기준: {relativeTime(pf.last_refresh, now)}</div>
          {/* 환율이 추정값이면 USD 종목의 원화 숫자는 어느 탭에서 봐도 참고용이다 */}
          <div className={t.usdkrw_estimated ? 'warn' : ''} style={{ fontSize: 11,
                 color: t.usdkrw_estimated ? undefined : 'var(--text-dim)' }}>
            {t.usdkrw_estimated ? '⚠ 환율 수집 실패 — 기본값 ' : '적용 환율 '}₩{fmt(t.usdkrw)}/$</div>
        </div>
      </div>
      {/* 예수금이 조용히 0으로 잘리면 총자산과 1% 리스크 수량이 함께 어긋난다 */}
      {cashWarn && <div className="warn-box">⚠ {cashWarn}
        <button className="ghost" style={{ marginLeft: 8 }}
                onClick={() => setCashWarn(null)}>확인</button></div>}
      <Outlet context={{ pf, trades, flows, posRule, setPosRule, now,
                         reload: load, setCashWarn }} />
    </div>
  )
}
```

- [ ] **Step 3: `frontend/src/theme.css`에 스트립 스타일 추가 (`.tab.active` 규칙 아래, 143줄 뒤)**

```css
/* 포트폴리오 총자산 스트립 — 모든 하위 탭 상단에 고정 */
.pf-strip { display: flex; gap: 28px; flex-wrap: wrap; align-items: flex-start; }
@media (max-width: 640px) { .pf-strip { gap: 14px; } }
```

- [ ] **Step 4: `frontend/src/pages/portfolio/Holdings.tsx` 생성**

`Portfolio.tsx`의 나머지 전부를 이 파일로 옮긴다.

- `return (<div className="grid"> … </div>)` 안의 205–860줄 JSX를 그대로 가져온다. 단 **최상위 `<div className="grid">` 래퍼는 제거한다** — 레이아웃이 이미 감싸고 있다. 프래그먼트 `<>…</>`로 감싼다.
- 총자산 카드(208–277)에서 **스트립으로 옮겨간 4줄을 지운다**: 총자산 라벨+금액(210, 217), 평가손익 줄(220–222), 기준시각 줄(211–215), 환율 줄(238–244). 나머지(총자산 대비 %, 배당 포함 총수익, 평가액·현금 상세, 예수금 입력, 목표 종목 수, `msg`)는 남긴다.
- `cashWarn` 렌더(273–275)를 지운다 — 레이아웃이 표시한다. `setCashWarn`은 컨텍스트에서 받아 계속 호출한다.
- 상태·핸들러는 그대로 가져온다: `form`, `flowForm`, `msg`, `flowMsg`, `cashInput`, `cashUsdInput`, `parseCash`, `saveCash`, `savePositionRule`, `optionalCost`, `addTrade`, `addFlow`, `needsSymbol`.
- `load()` 호출을 전부 `reload()`로 바꾼다.
- 파일 상단은 아래와 같다.

```tsx
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { del, post, put } from '../../api'
import { cashClampWarning, type TradeResult } from '../../trade'
import SymbolInput from '../../components/SymbolInput'
import AllocationDonut from '../../components/AllocationDonut'
import { cur, fmt } from '../../format'
import { usePortfolio } from './context'

const FLOW_LABEL: Record<string, string> = {
  DIVIDEND: '배당', INTEREST: '이자', DEPOSIT: '입금', WITHDRAW: '출금' }

export default function Holdings() {
  const { pf, trades, flows, posRule, setPosRule, reload, setCashWarn } = usePortfolio()
  // …상태·핸들러…
}
```

- 예수금 입력칸 프리필: 원본은 `load()` 안에서 했지만 이제 레이아웃 소유라 여기서 한다.

```tsx
  useEffect(() => {
    setCashInput(String(pf.totals.cash_krw))
    setCashUsdInput(String(pf.totals.cash_usd ?? 0))
  }, [pf.totals.cash_krw, pf.totals.cash_usd])
```

- [ ] **Step 5: `frontend/src/pages/Portfolio.tsx` 삭제**

```bash
git rm frontend/src/pages/Portfolio.tsx
```

- [ ] **Step 6: `frontend/src/App.tsx` 라우트 교체**

8줄의 lazy import를 바꾸고, 21–22줄의 라우트를 중첩 라우트로 교체한다.

```tsx
const PortfolioLayout = lazy(() => import('./pages/portfolio/PortfolioLayout'))
```

```tsx
          <Route path="/portfolio" element={
            <Suspense fallback={fallback}><PortfolioLayout /></Suspense>}>
            <Route index element={<Holdings />} />
          </Route>
```

`Holdings`는 lazy가 아니라 정적 import로 넣는다 — 탭을 옮길 때마다 청크를 새로 받으면 전환이 끊긴다.

```tsx
import Holdings from './pages/portfolio/Holdings'
```

- [ ] **Step 7: 빌드 확인**

```bash
cd frontend && npm run build
```
Expected: `✓ built` — 타입 오류 0.

- [ ] **Step 8: 실화면 확인**

개발 서버에서 `/portfolio`를 연다. 확인 항목:
- 총자산 스트립에 총자산·평가손익·현금·기준시각·환율이 보인다
- 그 아래 기존 카드 8개가 전부 그대로 있다
- 콘솔 에러 0
- 예수금을 저장하면 스트립 금액이 갱신된다
- 매매를 하나 기록하면 스트립과 보유 종목 표가 함께 갱신된다

- [ ] **Step 9: 커밋**

```bash
git add -A
git commit -m "refactor: 포트폴리오에 레이아웃 라우트 — 데이터를 한 곳에서 불러 내려준다"
```

---

### Task 3: 하위 탭바 + 리스크 탭 분리

**Files:**
- Create: `frontend/src/pages/portfolio/Risk.tsx`
- Modify: `frontend/src/pages/portfolio/PortfolioLayout.tsx` (탭바 추가)
- Modify: `frontend/src/pages/portfolio/Holdings.tsx` (리스크 두 카드 제거)
- Modify: `frontend/src/App.tsx` (라우트 추가)
- Modify: `frontend/src/theme.css` (`.subtab`)

**Interfaces:**
- Consumes: Task 2의 `usePortfolio()`
- Produces: `Risk.tsx` → default export

- [ ] **Step 1: `theme.css`에 `.subtab` 추가 (`.pf-strip` 아래)**

최상위 탭과 시각적으로 구분되지 않으면 두 줄 중 어느 쪽이 상위인지 읽히지 않는다.

```css
/* 포트폴리오 하위 탭 — 최상위 탭보다 한 단계 작고 밑줄로 구분 */
.subtabs { display: flex; gap: 2px; flex-wrap: wrap; border-bottom: 1px solid var(--border);
           margin-bottom: 4px; }
.subtab { padding: 6px 12px; font-size: 13px; color: var(--text-dim);
          border-bottom: 2px solid transparent; margin-bottom: -1px;
          transition: color 0.15s ease, border-color 0.15s ease; }
.subtab:hover { color: var(--text); }
.subtab.active { color: var(--text); border-bottom-color: var(--accent); }
@media (max-width: 640px) {
  .subtabs { overflow-x: auto; flex-wrap: nowrap; }
  .subtab { padding: 6px 9px; font-size: 12px; white-space: nowrap; }
}
```

- [ ] **Step 2: `PortfolioLayout.tsx`에 탭바 추가**

`NavLink`를 import하고, `SUBTABS` 상수를 파일 상단에 둔다. 다음 태스크마다 항목이 하나씩 늘어난다.

```tsx
const SUBTABS = [
  { to: '/portfolio', label: '보유', end: true },
  { to: '/portfolio/risk', label: '리스크', end: false },
]
```

`{cashWarn && …}` 블록 바로 뒤, `<Outlet …>` 앞에 넣는다.

```tsx
      <nav className="subtabs">
        {SUBTABS.map(s => (
          <NavLink key={s.to} to={s.to} end={s.end}
            className={({ isActive }) => isActive ? 'subtab active' : 'subtab'}>
            {s.label}</NavLink>
        ))}
      </nav>
```

- [ ] **Step 3: `Risk.tsx` 생성**

`Holdings.tsx`에서 두 카드를 잘라 옮긴다 — `{pf.risk && <div className="card">` 로 시작해 `<strong>계좌 리스크</strong>`를 담는 블록 전체, 그리고 `{pf.open_risk && <div className="card">` 로 시작해 `<strong>계좌 총 미결 리스크</strong>`를 담는 블록 전체. **주석 포함** 그대로 옮긴다.

```tsx
import { fmt } from '../../format'
import { usePortfolio } from './context'

export default function Risk() {
  const { pf } = usePortfolio()
  return (
    <>
      {/* 여기에 두 카드 */}
    </>
  )
}
```

- [ ] **Step 4: `Holdings.tsx`에서 두 카드 제거**

- [ ] **Step 5: `App.tsx`에 라우트 추가**

```tsx
import Risk from './pages/portfolio/Risk'
```
```tsx
            <Route path="risk" element={<Risk />} />
```

- [ ] **Step 6: 빌드 + 실화면 확인**

```bash
cd frontend && npm run build
```
`/portfolio`와 `/portfolio/risk`를 열어 두 탭이 각자 내용을 보이고, 탭 전환 시 스트립이 유지되며 콘솔 에러가 없는지 확인한다.

- [ ] **Step 7: 커밋**

```bash
git add -A
git commit -m "refactor: 리스크를 별도 탭으로 — 하위 탭바 추가"
```

---

### Task 4: 복기(실현손익) 탭 분리

**Files:**
- Create: `frontend/src/pages/portfolio/Realized.tsx`
- Modify: `frontend/src/pages/portfolio/Holdings.tsx`, `PortfolioLayout.tsx`, `frontend/src/App.tsx`

**Interfaces:**
- Consumes: Task 2의 `usePortfolio()`
- Produces: `Realized.tsx` → default export

- [ ] **Step 1: `Realized.tsx` 생성**

`Holdings.tsx`에서 `{pf.realized && <div className="card">` 로 시작해 `<strong>실현손익 · 매매 복기</strong>`를 담는 카드 전체를 **주석 포함** 옮긴다. 여기에는 실현손익 4지표, 해외 양도세 박스, 비용 추정 안내, 보정 제외 경고, 진입 등급별 성과 표, 매도 내역 표가 포함된다.

```tsx
import { fmt } from '../../format'
import { usePortfolio } from './context'

export default function Realized() {
  const { pf } = usePortfolio()
  return (
    <>
      {/* 실현손익 카드 */}
    </>
  )
}
```

- [ ] **Step 2: `Holdings.tsx`에서 해당 카드 제거**

- [ ] **Step 3: `PortfolioLayout.tsx`의 `SUBTABS`에 항목 추가**

```tsx
  { to: '/portfolio/realized', label: '복기', end: false },
```

- [ ] **Step 4: `App.tsx`에 라우트 추가**

```tsx
import Realized from './pages/portfolio/Realized'
```
```tsx
            <Route path="realized" element={<Realized />} />
```

- [ ] **Step 5: 빌드 + 실화면 확인**

```bash
cd frontend && npm run build
```
`/portfolio/realized`에서 실현손익 지표와 매도 내역 표가 보이는지, 매도 기록이 없는 계좌에서는 기존 빈 상태 문구가 그대로 나오는지 확인한다.

- [ ] **Step 6: 커밋**

```bash
git add -A
git commit -m "refactor: 실현손익·매매 복기를 별도 탭으로"
```

---

### Task 5: 배당·현금흐름 탭 분리

이 태스크부터는 폼과 상태가 함께 이동한다.

**Files:**
- Create: `frontend/src/pages/portfolio/Income.tsx`
- Modify: `frontend/src/pages/portfolio/Holdings.tsx`, `PortfolioLayout.tsx`, `frontend/src/App.tsx`

**Interfaces:**
- Consumes: Task 2의 `usePortfolio()` — `pf`, `flows`, `reload`, `setCashWarn`
- Produces: `Income.tsx` → default export

- [ ] **Step 1: `Income.tsx` 생성**

`Holdings.tsx`에서 `<strong>배당 · 현금흐름</strong>`을 담은 카드 전체(요약 3지표, 기간 불일치·환율 추정 경고, 종목별 표, 입력 폼, 안내 문구, 현금흐름 원장 표)를 **주석 포함** 옮긴다. 함께 옮길 것: `flowForm`·`flowMsg` 상태, `needsSymbol`, `addFlow`, `FLOW_LABEL` 상수.

```tsx
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
  const div = pf.dividends
  // flowForm / flowMsg / needsSymbol / addFlow …
}
```

`addFlow`의 `load()` 호출은 `reload()`로, `setCashWarn(cashClampWarning(res))`는 그대로 둔다 — 경고는 레이아웃 스트립 아래에 뜬다.

- [ ] **Step 2: `Holdings.tsx`에서 카드·상태·핸들러 제거**

`flowForm`, `flowMsg`, `needsSymbol`, `addFlow`, `FLOW_LABEL`, 그리고 이제 쓰지 않는 import(`SymbolInput`이 매매 입력에서도 쓰이면 남긴다)를 정리한다. `const div = pf.dividends`도 Holdings에서 쓰지 않으면 제거한다 — 단 `hasDiv`는 보유 종목 표의 배당 열 조건이므로 **남긴다**.

- [ ] **Step 3: `PortfolioLayout.tsx`의 `SUBTABS`에 항목 추가**

```tsx
  { to: '/portfolio/income', label: '배당·현금흐름', end: false },
```

- [ ] **Step 4: `App.tsx`에 라우트 추가**

```tsx
import Income from './pages/portfolio/Income'
```
```tsx
            <Route path="income" element={<Income />} />
```

- [ ] **Step 5: 빌드 + 실화면 확인**

```bash
cd frontend && npm run build
```
`/portfolio/income`에서 배당을 한 건 기록해 본다. 확인 항목:
- 원장 표에 행이 추가된다
- 스트립의 현금이 세후 금액만큼 늘어난다
- 보유 탭의 「배당 포함」 열이 함께 갱신된다
- 삭제 확인 다이얼로그가 그대로 뜬다

- [ ] **Step 6: 커밋**

```bash
git add -A
git commit -m "refactor: 배당·현금흐름을 별도 탭으로"
```

---

### Task 6: 매매 기록 탭 분리

**Files:**
- Create: `frontend/src/pages/portfolio/Journal.tsx`
- Modify: `frontend/src/pages/portfolio/Holdings.tsx`, `PortfolioLayout.tsx`, `frontend/src/App.tsx`

**Interfaces:**
- Consumes: Task 2의 `usePortfolio()` — `trades`, `reload`, `setCashWarn`
- Produces: `Journal.tsx` → default export

- [ ] **Step 1: `Journal.tsx` 생성**

`Holdings.tsx`에서 `<strong>매매 입력</strong>` 카드 전체(입력 폼, 보정 로트 체크박스, 안내 문구, 체결 원장 표)를 **주석 포함** 옮긴다. 함께 옮길 것: `form`·`msg` 상태, `optionalCost`, `addTrade`.

```tsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { del, post } from '../../api'
import { cashClampWarning, type TradeResult } from '../../trade'
import SymbolInput from '../../components/SymbolInput'
import { fmt } from '../../format'
import { usePortfolio } from './context'

export default function Journal() {
  const { trades, reload, setCashWarn } = usePortfolio()
  // form / msg / optionalCost / addTrade …
}
```

- [ ] **Step 2: 안내 문구의 카드 참조를 링크로 교체**

원본 문구는 같은 화면에 있던 카드를 "위 **배당 · 현금흐름** 카드"로 가리킨다. 이제 다른 탭이므로 링크로 바꾼다. 이 문장만 바뀌고 나머지 문구는 그대로다.

```tsx
          입출금·배당은 <Link to="/portfolio/income"><strong>배당 · 현금흐름</strong></Link> 탭에
          기록하세요 — 예수금 칸을 직접 고치면 원장에 근거가 남지 않습니다.
```

- [ ] **Step 3: `Holdings.tsx`에서 카드·상태·핸들러 제거**

`form`, `optionalCost`, `addTrade`를 지운다. `msg`는 예수금 저장(`saveCash`)·목표 종목 수 저장(`savePositionRule`)에서도 쓰므로 **Holdings에 남긴다** (Journal은 자기 `msg`를 새로 갖는다). `trades`를 더 이상 쓰지 않으면 `usePortfolio()` 구조분해에서 뺀다.

- [ ] **Step 4: `PortfolioLayout.tsx`의 `SUBTABS`에 항목 추가**

```tsx
  { to: '/portfolio/journal', label: '매매 기록', end: false },
```

- [ ] **Step 5: `App.tsx`에 라우트 추가**

```tsx
import Journal from './pages/portfolio/Journal'
```
```tsx
            <Route path="journal" element={<Journal />} />
```

- [ ] **Step 6: 빌드 + 실화면 확인**

```bash
cd frontend && npm run build
```
`/portfolio/journal`에서 매수를 한 건 기록하고 확인한다:
- 원장 표에 행이 추가된다
- 스트립의 총자산·현금이 갱신된다
- 보유 탭의 수량·평단이 갱신된다
- 매도를 기록하면 복기 탭 집계가 갱신된다
- 삭제 확인 다이얼로그가 그대로 뜬다
- 안내 문구의 링크가 `/portfolio/income`으로 이동한다

- [ ] **Step 7: 커밋**

```bash
git add -A
git commit -m "refactor: 매매 입력·체결 원장을 별도 탭으로"
```

---

### Task 7: 마감 — 설정 접기, 리스크 빈 상태, 모바일 확인

스펙이 허용한 세 가지 동작 변경을 여기서 한 번에 한다.

**Files:**
- Modify: `frontend/src/pages/portfolio/Holdings.tsx`
- Modify: `frontend/src/pages/portfolio/Risk.tsx`
- Modify: `frontend/src/theme.css`

**Interfaces:**
- Consumes: Task 2–6의 모든 화면
- Produces: 없음 (마감 태스크)

- [ ] **Step 1: `Holdings.tsx`의 설정을 접이식으로**

예수금 입력과 목표 종목 수 입력을 총자산 카드 하단의 `<details>`로 감싼다. 매일 보는 값이 아니라 카드 안에서 시선을 뺏고 있었다. 두 입력 블록의 내부 마크업은 그대로 두고 바깥만 감싼다.

```tsx
        <details className="pf-settings">
          <summary>계좌 설정 — 예수금 · 목표 종목 수</summary>
          {/* 기존 예수금 입력 블록 */}
          {/* 기존 목표 종목 수 블록 */}
          {msg && <div style={{ color: 'var(--sell)', fontSize: 12, marginTop: 6 }}>{msg}</div>}
        </details>
```

- [ ] **Step 2: `theme.css`에 `.pf-settings` 추가 (`.subtab` 규칙 아래)**

```css
.pf-settings { margin-top: 10px; border-top: 1px solid var(--border); padding-top: 8px; }
.pf-settings > summary { cursor: pointer; font-size: 12px; color: var(--text-dim); }
.pf-settings > summary:hover { color: var(--text); }
```

- [ ] **Step 3: `Risk.tsx`에 빈 상태 추가**

`pf.risk`와 `pf.open_risk`가 둘 다 null이면 탭이 빈 화면이 된다. 기능이 없는 것처럼 보이지 않게 왜 비었는지 말한다.

```tsx
      {!pf.risk && !pf.open_risk && <div className="card">
        <strong>계좌 리스크</strong>
        <div className="empty">
          아직 계산할 수 있는 리스크 지표가 없습니다.<br />
          보유 종목이 2개 이상이고 가격 이력이 쌓이면 <strong>연환산 변동성 · 최대 낙폭 ·
          종목 간 상관 · 계좌 총 미결 리스크</strong>가 여기에 계산됩니다.
        </div>
      </div>}
```

- [ ] **Step 4: 빌드 확인**

```bash
cd frontend && npm run build
```

- [ ] **Step 5: 다섯 탭 전체 점검 (데스크톱)**

`/portfolio`, `/portfolio/risk`, `/portfolio/realized`, `/portfolio/income`, `/portfolio/journal`을 차례로 연다.
- 콘솔 에러 0
- 분할 전 화면(`git show 84c766c:frontend/src/pages/Portfolio.tsx`)과 대조해 사라진 블록·경고·문구가 없는지 확인
- 조건부 블록 점검: `hasDiv`(보유 표 배당 열), `pf.risk`, `pf.open_risk`, `pf.realized`, `div.count === 0`, `trades.length === 0`, `flows.length > 0`

- [ ] **Step 6: 모바일 폭(375px) 확인**

브라우저 폭을 375px로 줄이고 확인한다:
- 최상위 탭 3개가 한 줄에 읽힌다
- 하위 탭 5개가 한 줄에 들어가거나, 넘치면 가로 스크롤로 접근 가능하다
- 총자산 스트립이 세로로 접히며 잘리지 않는다
- 표들이 기존 `table-cards` 카드 레이아웃으로 정상 전환된다

- [ ] **Step 7: 커밋**

```bash
git add -A
git commit -m "feat: 계좌 설정을 접고 리스크 빈 상태를 채운다"
```

---

## 자체 점검 결과

스펙 대비 커버리지를 확인했다.

- 정보구조 5탭 → Task 2~6
- 데이터 단일 소유 + `PortfolioContext` → Task 2 Step 1–2
- 에러 검사가 스켈레톤보다 먼저 → Task 2 Step 2 (원본 순서 유지)
- 총자산 스트립 + 환율 경고 → Task 2 Step 2–3
- `cashWarn` 레이아웃 소유 → Task 2 Step 2, Task 5 Step 1, Task 6 Step 1
- 하위 탭바 `.subtab` → Task 3 Step 1–2
- 설정 접기 → Task 7 Step 1–2
- Risk 빈 상태 → Task 7 Step 3
- Journal 안내 문구 링크화 → Task 6 Step 2
- 파일 구조(`format.ts`, `AllocationDonut`, `types.Trade`) → Task 1
- `Portfolio.tsx` 삭제 → Task 2 Step 5
- 검증(빌드·5경로·기능 4건·모바일) → 각 태스크 + Task 7 Step 5–6
- 회귀 위험 완화(화면 단위 커밋) → 태스크당 1커밋, 총 7커밋

**스펙과 어긋난 점 하나:** 스펙은 `context.ts`를 `pages/portfolio/`에 둔다고 했고 계획도 그렇게 한다. 다만 스펙의 `format.ts` 위치는 `frontend/src/format.ts`이며, 이는 `time.ts`·`trade.ts`와 같은 층이라 기존 패턴과 맞다.
