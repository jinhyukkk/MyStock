---
name: mystock-dev
description: MyStock 코드베이스에서 구현 작업을 시작하기 전에 반드시 읽는 개발 규약. 기술 스택, 실행·테스트·빌드 명령, 화면→라우트→컴포넌트→API 지도, 백엔드 모듈 지도, 공용 헬퍼(fmt/cur/time/costs), DB 연결 규칙, 주석·커밋 관례를 담는다. frontend-engineer·backend-engineer·screen-architect가 착수 전 로드한다. "MyStock 어떻게 실행해", "테스트 어떻게 돌려", "이 화면 파일이 어디", "API 어디서 정의" 같은 질문에도 이 스킬을 먼저 본다.
---

# MyStock 개발 규약

개인 투자자용 주식 시그널·포트폴리오 앱. 로컬 단일 사용자, FastAPI가 Vite 빌드본을 같이 서빙한다.

## 스택

| 층 | 기술 | 위치 |
|---|---|---|
| 백엔드 | Python 3.11+, FastAPI, SQLite(thread-local), pandas, FinanceDataReader/yfinance | `backend/app/` |
| 프론트 | React 19, TypeScript 6, Vite 8, react-router 7, recharts, lightweight-charts, oxlint | `frontend/src/` |
| 테스트 | pytest(+httpx TestClient) — 프론트 단위 테스트는 없음(tsc + lint + 브라우저 계측으로 대체) | `backend/tests/` |

## 실행·검증 명령

브라우저 확인은 Bash가 아니라 `preview_start`로 띄운다 (`.claude/launch.json`):

| 이름 | 용도 | 포트 |
|---|---|---|
| `mystock` | `run.sh` — 백엔드 + 정적 빌드본(운영과 같은 형태) | 8722 |
| `mystock-win` | Windows용 uvicorn 직접 실행 | 8722 |
| `mystock-frontend` | Vite dev 서버(HMR). `/api`를 `API_ORIGIN`(launch.json이 8722로 지정)으로 프록시 — 백엔드가 떠 있어야 화면에 데이터가 나온다 | 5173 |

포트가 이미 쓰이고 있으면 다른 세션의 서버다 — `tabs_context`/`navigate`로 재사용한다.
**빌드본(8722)과 dev(5173)는 다른 버전을 보여줄 수 있다.** 소스 변경을 확인할 땐 5173,
"사용자가 실제로 보는 화면"을 확인할 땐 `npm run build` 후 8722.

```bash
# 백엔드 테스트 (네트워크 없이 통과해야 정상. smoke 마커는 기본 제외)
cd backend && .venv/bin/pytest -q
```

```bash
# 프론트 타입·린트 (단위 테스트 대신 이 둘이 게이트)
cd frontend && npx tsc -b && npm run lint
```

```bash
# 프론트 빌드본 갱신 (8722가 서빙하는 것)
cd frontend && npm run build
```

```bash
# API 실응답 확인
curl -s http://127.0.0.1:8722/api/dashboard | head -c 600
```

Windows venv는 `backend/.venv/Scripts/`. `.env`는 루트에 있고 `backend/app/env.py`가 로드한다
(API 키 등 — 절대 출력·커밋하지 않는다).

## 화면 지도

| 화면 | 라우트 | 컴포넌트 | 주 API |
|---|---|---|---|
| Dashboard | `/` | `pages/Dashboard.tsx` | `GET /api/dashboard`, `POST /api/refresh` |
| TickerDetail | `/ticker/:symbol` | `pages/TickerDetail.tsx` | `GET /api/tickers/{symbol}`, `.../backtest`, `POST /api/trades` |
| Watchlist | `/watchlist` | `pages/Watchlist.tsx` | `GET /api/dashboard`, `POST/DELETE /api/watchlist` (검색은 `components/SymbolInput` → `/api/search`) |
| Holdings | `/portfolio` | `pages/portfolio/Holdings.tsx` | context만 (자체 호출 없음) |
| Risk | `/portfolio/risk` | `pages/portfolio/Risk.tsx` | context만 (자체 호출 없음) |
| Realized | `/portfolio/realized` | `pages/portfolio/Realized.tsx` | context만 (자체 호출 없음) |
| Income | `/portfolio/income` | `pages/portfolio/Income.tsx` | context + `POST/PATCH/DELETE /api/cash-flows` |
| Journal | `/portfolio/journal` | `pages/portfolio/Journal.tsx` | context + `DELETE /api/trades` |
| Settings | `/portfolio/settings` | `pages/portfolio/Settings.tsx` | `PUT /api/cash`, `/api/notify*`, `PUT /api/position-rule` |
| 전략 연구실 | `/strategy` | `pages/Strategy.tsx`, `components/EquityCurve.tsx` | `GET /api/strategy/presets`, `POST /api/strategy/backtest` |

포트폴리오 하위 화면은 `PortfolioLayout.tsx`가 **4개 API**(`GET /api/portfolio`, `/api/trades`,
`/api/cash-flows`, `/api/position-rule`)를 한 번에 받아 `context.ts`(`usePortfolio()`)로 내려준다.
하위 화면은 읽기용으로 같은 API를 다시 부르지 않고, 쓰기 후에는 `reload()`로 4개를 함께 갱신한다.
포트폴리오 화면의 응답 필드를 바꾸면 `types.ts`의 `Portfolio`/`Trade`/`CashFlow`와 레이아웃의
로딩·에러 처리까지 영향권이다. 공용 컴포넌트는 `components/`
(TradeDialog, SignalBadge, ScoreBar, AllocationDonut, BacktestTable, CommandPalette 등).
수정 전에 `Grep`으로 사용처 수를 센다.

## 백엔드 모듈 지도

| 모듈 | 책임 |
|---|---|
| `api.py` | 모든 라우트(`/api` prefix), pydantic 입력 모델. 비즈니스 로직을 넣지 않는다 |
| `service.py` | 대시보드 조립, 갱신 루프(`refresh_all`), 알림 — 가장 큰 파일, 건드릴 땐 범위를 좁게 |
| `portfolio.py` | 보유·평단·실현손익·현금흐름 계산 |
| `scoring.py` / `indicators.py` | 스윙·장기 점수, 기술 지표 |
| `backtest.py` | 시그널 백테스트 (표본 수·비용 반영 여부가 결과에 같이 나가야 한다) |
| `strategy.py` | 전략 프리셋 — 일봉 → 진입/청산 시그널 (순수 함수) |
| `engine.py` | 포트폴리오 백테스트 — 시그널 → 자본곡선·지표 |
| `costs.py` | 수수료·세금 요율. **새 상수 금지, 여기 것을 쓴다** |
| `db.py` / `schema.sql` | 스키마 + 마이그레이션. 둘 다 고친다 |
| `fetchers.py` / `sentiment.py` | 외부 시세·심리 데이터 (테스트는 `smoke`) |

## 반드시 지키는 규칙

- **DB 연결은 `_conn(request)` 또는 `ThreadLocalDB.conn()`만.** 스레드 간 공유 시
  세그폴트 (`main.py` 주석). 백그라운드 작업은 `asyncio.to_thread` 안에서 자기 연결을 얻는다.
- **API 에러는 `HTTPException(detail=...)`.** 프론트 `api.ts`가 `detail`만 사용자에게 보여준다.
- **응답 필드는 지우거나 이름 바꾸지 않는다.** 추가만 한다. 빌드본이 구버전일 수 있다.
- **금액·비율 단위를 이름에 남긴다.** `_krw`, `_pct`, `_net`(비용 차감 후). 프론트 표시는
  `format.ts`의 `fmt`(숫자)·`cur`(통화) — KRW에 소수점이 찍히면 포맷 결함이다.
- **시각은 `time.ts`** (`parseLocal`, `relativeTime`, `isStale` — 120분 지나면 stale).
- **null은 화면에서 `—`로.** `undefined`/`NaN`/`null` 문자열이 보이면 미완성.
- **주석은 한국어로 "왜"를 쓴다.** "안 그러면 무엇이 깨지는지"까지. 코드베이스 전체 관례.
- **커밋은 리더(메인 세션)가 한다.** 서브 에이전트는 `git add`/`commit`을 하지 않는다.
- **개인 금융 데이터 금지.** `backend/mystock.db`, `backend/raw/`, `docs/거래내역/`, `.env`는
  읽은 내용을 보고서·로그에 옮기지 않는다.

## 설계 문서 위치

- 과거 설계/계획: `docs/superpowers/specs/`, `docs/superpowers/plans/` (날짜 접두)
- 화면 개선 작업 산출물: `_workspace/{screen}/` (`screen-improve` 스킬 참조)
