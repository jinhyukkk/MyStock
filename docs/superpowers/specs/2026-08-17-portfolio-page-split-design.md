# 포트폴리오 페이지 분할 설계

작성일: 2026-08-17

## 배경

`frontend/src/pages/Portfolio.tsx`는 862줄 한 파일에 성격이 다른 8개 블록이 세로로
쌓여 있다. 계좌 현황, 리스크 진단, 매매 복기, 배당 원장, 체결 입력이 한 스크롤에
섞여 있어 세 가지 문제가 있다.

- **찾는 데 스크롤이 필요하다.** 매도를 기록하려면 리스크·복기·배당 표를 전부
  지나쳐야 한다.
- **한 파일이 너무 많은 일을 한다.** 상태 12개, 폼 2개, API 4개가 한 컴포넌트에 있어
  한 블록을 고칠 때 나머지 전부를 읽어야 한다.
- **화면이 늘어날 자리가 없다.** 블록을 하나 더 붙이면 스크롤만 길어진다.

## 목표

1. 포트폴리오를 질문 단위 5개 화면으로 나눈다.
2. 데이터는 그룹 레이아웃에서 한 번만 불러 하위 화면이 공유한다.
3. 화면 전환 중에도 계좌 규모(총자산·손익·현금·기준시각)가 시야에서 사라지지 않는다.

**목표가 아닌 것:** 표시하는 숫자·문구·계산 로직 변경, 백엔드 변경, 무관한 리팩터링.
이번 작업은 **이동과 분리**이며 동작은 동일해야 한다.

## 정보구조

최상위 탭은 **대상**, 하위 탭은 그 대상의 **관점**으로 나눈다. 최상위 탭
(대시보드 / 포트폴리오 / 워치리스트)은 그대로 3개를 유지한다.

| 경로 | 하위 탭 | 담는 블록 (현재 줄 번호) | 답하는 질문 |
|---|---|---|---|
| `/portfolio` | 보유 | 총자산 카드 208–277, 도넛 278–282, 보유 종목 표 285–356 | 지금 뭘 얼마나 들고 있나 |
| `/portfolio/risk` | 리스크 | 계좌 리스크 358–435, 총 미결 리스크 439–485 | 지금 얼마나 위험한가 |
| `/portfolio/realized` | 복기 | 실현손익·양도세·등급별 성과·매도 내역 490–628 | 내 매매는 돈을 벌고 있나 |
| `/portfolio/income` | 배당·현금흐름 | 배당 요약·종목별 표·입력 폼·원장 632–770 | 현금이 얼마나 들어왔나 |
| `/portfolio/journal` | 매매 기록 | 매매 입력 폼·체결 원장 772–859 | 체결을 남긴다 |

### 최상위로 올리지 않는 이유

평면 7탭(대시보드·보유·리스크·복기·배당·매매기록·워치리스트)도 검토했으나 채택하지
않았다. 얻는 것은 클릭 한 번이고 잃는 것은 분류 규칙이다.

- *대상*(워치리스트)과 *관점*(리스크)이 한 줄에 섞이면, "리스크"가 내 계좌의
  리스크인지 워치리스트 종목의 리스크인지 탭 이름만으로 구분되지 않는다.
- 다섯 화면은 전부 같은 계좌 데이터의 뷰다. 최상위 형제 탭은 서로 독립이라는 신호를
  주므로, 총자산 헤더를 다섯 페이지에 각각 붙이게 된다 — 그건 그룹이 이미 있다는 뜻이다.
- 모바일에서 7탭은 가로 스크롤이고, 잘리는 쪽이 워치리스트다. 3 + 5는 두 줄 모두
  넘치지 않는다.
- 배당·매매기록은 입력 화면이다. 조회 화면인 대시보드·워치리스트와 같은 층에 두면
  탭바가 "볼 곳"과 "적을 곳"을 구분하지 못한다.

## 구조

### 라우팅

`App.tsx`의 `/portfolio` 단일 라우트를 중첩 라우트로 교체한다. lazy 로딩은
`PortfolioLayout` 한 곳에서만 하고, 하위 5개는 같은 청크에 포함시킨다 — 탭을 옮길
때마다 청크를 새로 받으면 전환이 눈에 띄게 끊긴다.

```
<Route path="/portfolio" element={<Suspense fallback={fallback}><PortfolioLayout /></Suspense>}>
  <Route index element={<Holdings />} />
  <Route path="risk" element={<Risk />} />
  <Route path="realized" element={<Realized />} />
  <Route path="income" element={<Income />} />
  <Route path="journal" element={<Journal />} />
</Route>
```

`/portfolio`는 index 라우트로 "보유"가 열리므로 기존 링크는 그대로 동작한다.
커맨드 팔레트는 `/ticker/:symbol`만 사용하므로 영향이 없다.

### 데이터 로딩 — 레이아웃 단일 소유

`PortfolioLayout`이 현재 `load()`가 하는 일을 그대로 가져간다.

```
Promise.all([
  get<PF>('/api/portfolio'),
  get<Trade[]>('/api/trades'),
  get<CashFlow[]>('/api/cash-flows'),
  get<{min, max}>('/api/position-rule'),
])
```

로딩·에러·스켈레톤 처리도 레이아웃이 소유한다. **에러 검사를 스켈레톤보다 먼저**
하는 현재 순서를 유지한다 — 순서가 뒤집히면 실패 시 영원히 로딩 화면으로 보인다.

하위 화면은 `useOutletContext()`로 아래 계약을 받는다.

```ts
interface PortfolioContext {
  pf: Portfolio           // 항상 non-null (레이아웃이 로딩·에러를 먼저 처리)
  trades: Trade[]
  flows: CashFlow[]
  posRule: { min: string; max: string }
  setPosRule: (updater: (r: {min: string; max: string}) => {min: string; max: string}) => void
  now: number             // 기준시각 계산용 (isStale/relativeTime)
  reload: () => void      // 입력/삭제 후 전체 재로드
  setCashWarn: (msg: string | null) => void   // 예수금 클램프 경고를 레이아웃 배너로
}
```

`reload()`는 레이아웃의 `load()`다. 어느 탭에서 매매를 기록하든 총자산 스트립과 나머지
탭의 값이 함께 갱신된다.

`cashWarn`(예수금이 0으로 잘렸다는 경고)은 **레이아웃이 소유한다.** 이 경고는
매매 기록(journal)과 현금흐름(income) 양쪽에서 발생하는데 내용은 총자산에 관한
것이므로, 발생한 탭이 아니라 총자산 스트립 아래에 뜨는 것이 맞다.

폼 상태(`form`, `flowForm`)와 그 에러 메시지(`msg`, `flowMsg`)는 각 화면이 소유한다.
탭을 옮기면 입력 중이던 폼이 초기화되는데, 이는 의도된 동작이다.

### 총자산 스트립

레이아웃 상단, 하위 탭바 위에 한 줄로 고정한다.

- 총자산 (KRW), 평가손익(원금 대비 %), 현금 및 비중, 기준시각(`relativeTime`,
  `isStale`이면 ⚠)
- 환율 경고(`usdkrw_estimated`)는 스트립에 남긴다 — USD 종목의 원화 숫자가
  참고용이라는 사실은 어느 탭에서 보든 유효하다.
- 배당 포함 총수익, 예수금 입력, 목표 종목 수 입력은 스트립에 넣지 않는다.
  보유 탭에 남긴다.

### 화면별 상세

**Holdings (`/portfolio`)** — 총자산 카드의 상세 줄(배당 포함 총수익, 평가액·현금
내역), 자산배분 도넛, 보유 종목 표. 예수금·목표 종목 수 설정은 카드 하단으로 내리고
`<details>`로 접는다 (기본 접힘). 매일 보는 값이 아니라 총자산 카드 안에서 시선을
뺏고 있었다.

**Risk (`/portfolio/risk`)** — 계좌 리스크 카드와 총 미결 리스크 카드. 두 카드 모두
`pf.risk` / `pf.open_risk`가 null이면 렌더하지 않는데, 둘 다 null이면 탭이 빈
화면이 된다. 이때는 "보유 종목이 2개 이상이고 가격 이력이 쌓이면 변동성·상관·총
리스크가 여기에 계산됩니다"라는 빈 상태를 보여준다.

**Realized (`/portfolio/realized`)** — 실현손익 카드 전체. `pf.realized`가 null일 때도
탭 자체는 남으므로, 현재 `count === 0`용 빈 상태 문구를 그대로 쓴다.

**Income (`/portfolio/income`)** — 배당 요약 3지표, 기간 불일치/환율 추정 경고,
종목별 표, 현금흐름 입력 폼, 현금흐름 원장(삭제 포함).

**Journal (`/portfolio/journal`)** — 매매 입력 폼(보정 로트 체크박스 포함)과 체결
원장(삭제 포함). 입출금·배당은 income 탭에 기록하라는 안내 문구의 "위 **배당 ·
현금흐름** 카드"라는 표현은 더 이상 같은 화면이 아니므로 **배당·현금흐름 탭**으로
가는 링크(`<Link to="/portfolio/income">`)로 바꾼다.

### 하위 탭바

`Layout.tsx`의 상단 탭과 같은 `tab` / `tab active` 클래스를 재사용하되, 크기가 작은
변형(`subtab`)을 `theme.css`에 추가한다. 최상위 탭과 시각적으로 구분되지 않으면 두
줄 중 어느 쪽이 상위인지 읽히지 않는다. 모바일에서는 5개가 한 줄에 들어가도록 폰트와
패딩을 줄이고, 그래도 넘치면 가로 스크롤을 허용한다.

## 파일

```
frontend/src/pages/portfolio/
  PortfolioLayout.tsx    데이터 로드 + 총자산 스트립 + 하위 탭바 + Outlet
  Holdings.tsx
  Risk.tsx
  Realized.tsx
  Income.tsx
  Journal.tsx
  context.ts             PortfolioContext 타입 + usePortfolio() 훅
frontend/src/components/AllocationDonut.tsx   (Portfolio.tsx 13–48에서 이동)
frontend/src/format.ts                        fmt / cur
```

- `frontend/src/pages/Portfolio.tsx` 삭제.
- `Trade` 인터페이스(현재 Portfolio.tsx 52–56)는 `types.ts`로 옮긴다 —
  Journal과 레이아웃 양쪽에서 필요하다.
- `FLOW_LABEL`은 Income.tsx로 이동.
- `format.ts`에는 **Portfolio.tsx의 `fmt`/`cur`만** 옮긴다. `Dashboard.tsx`,
  `TradeDialog.tsx`, `trade.ts`의 동명 함수는 시그니처가 달라 이번 범위에서 건드리지
  않는다.

## 검증

프론트엔드에 테스트 러너가 없으므로 타입 검사와 실제 화면으로 검증한다.

1. `npm run build` (`tsc -b`) — 타입 오류 0.
2. 개발 서버에서 다섯 경로를 모두 열어 콘솔 에러 0 확인.
3. 분할 전후 화면 비교: 각 블록의 숫자·경고 문구가 동일한지 확인.
4. 기능 확인:
   - 예수금 저장 → 총자산 스트립이 즉시 갱신
   - journal에서 매도 기록 → realized 탭 집계와 스트립이 함께 갱신
   - income에서 배당 기록 → 스트립 현금과 보유 탭 배당 열이 함께 갱신
   - 매매/현금흐름 삭제 확인 다이얼로그가 그대로 동작
   - 예수금 클램프 경고가 스트립 아래에 표시
5. 모바일 폭(375px)에서 두 탭바가 모두 읽히는지 확인.

## 위험

- **회귀 위험이 실질적이다.** 862줄을 옮기는 작업이라 조건부 렌더(`hasDiv`,
  `pf.risk`, `pf.realized`, `div.count === 0`)를 하나만 놓쳐도 화면이 조용히
  사라진다. 분할 커밋을 화면 단위로 쪼개고 각 커밋마다 해당 탭을 눈으로 확인한다.
- **작업 전 현재 변경사항을 커밋해야 한다.** `Portfolio.tsx`에 커밋되지 않은 수정이
  남아 있다. 커밋 후 분할해야 diff가 "이동"으로 읽힌다.

## 후속 (이번 범위 아님)

대시보드에 총 미결 리스크 %와 상한을 한 줄로 띄우고 `/portfolio/risk`로 링크한다.
대시보드는 이미 손절 근접·종목 수 경고를 띄우고 있어 성격이 이어진다.
