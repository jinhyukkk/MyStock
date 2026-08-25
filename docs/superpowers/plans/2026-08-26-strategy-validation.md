# 전략 측정 신뢰성 재구축 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 백테스트 결과를 신뢰할 수 있게 만든다 — 엔진 벡터화(성능), 생존편향 없는 유니버스(선택편향 제거), 워크포워드 검증(레짐 착시 제거). 그 위에서 수익률 개선 실험(레짐 필터)을 판정한다.

**Architecture:** engine.run의 일별 루프를 공통 달력 정렬 numpy 배열로 교체(결과 불변이 하드 요건). 유니버스는 price_cache와 분리된 universe_prices/universe_meta 테이블 + 시점별 거래대금 상위 300 멤버십. 검증은 anchored 워크포워드를 백그라운드 잡으로 돌리고 화면은 폴링.

**Tech Stack:** FastAPI, SQLite, pandas/numpy, FinanceDataReader, React 19 + recharts

**Spec:** `docs/superpowers/specs/2026-08-26-strategy-validation-design.md`

## Global Constraints

- DB 연결은 `_conn(request)` 또는 `ThreadLocalDB.conn()`만. 백그라운드 스레드는 자기 연결을 얻는다.
- API 응답 기존 필드는 지우거나 이름 바꾸지 않는다. 추가만.
- 금액·비율 단위를 이름에 남긴다(`_krw`, `_pct`).
- 주석은 한국어로 "왜"를 쓴다.
- 커밋은 리더(메인 세션)가 한다.
- `cd backend && .venv/bin/pytest -q`가 네트워크 없이 통과해야 한다. 네트워크 필요 테스트는 `smoke` 마커.
- 프론트 게이트: `npx tsc -b && npm run lint`.

---

### Task 1: 골든 픽스처 회귀 테스트 (벡터화 전 결과 고정)

**Files:**
- Create: `backend/tests/fixtures/engine_golden.json` (생성 스크립트로)
- Create: `backend/tests/test_engine_golden.py`

**Interfaces:**
- Produces: 합성 일봉 생성기 `_synth_frames(n_symbols, n_days, seed)` — Task 2가 같은 픽스처로 결과 불변을 증명한다.

실 DB(27종목)가 아니라 **합성 데이터**로 고정한다 — 실 DB는 개인 금융 데이터라 픽스처로 저장하면 안 되고, 시세가 갱신되면 테스트가 깨진다. 합성 생성기는 시드 고정 랜덤워크 + 일부 종목에 NaN 행(거래정지 시나리오)과 서로 다른 캘린더(휴장 시나리오)를 섞는다. 두 프리셋 × 대표 파라미터로 `run()`을 돌려 `metrics`·`trades` 전체·`equity_curve` 앞뒤 5개를 JSON으로 저장한다.

- [x] **Step 1: 생성기 + 덤프 스크립트 작성, 픽스처 생성**
- [x] **Step 2: 픽스처와 현재 엔진 출력이 일치하는 테스트 작성, 통과 확인**
- [x] **Step 3: 전체 pytest 통과 확인 후 커밋**

### Task 2: engine.run 일별 루프 벡터화

**Files:**
- Modify: `backend/app/engine.py` (run 내부의 prepared 구성 + 일별 루프)
- Test: 기존 `backend/tests/test_engine.py` + Task 1 골든 테스트

**Interfaces:**
- Consumes: Task 1 골든 픽스처.
- Produces: `run()` 시그니처·반환 불변. 내부에 `_prepare_arrays(prepared, calendar)` — 종목별 own-index numpy 배열(open/high/low/close/atr/dates, enter/exit/strength)과 calendar→own 위치 매핑 `cal_to_own`(int, 휴장 -1), 달력 정렬 enter/strength/close 2D 행렬.

핵심: 로직을 바꾸지 않고 **조회 방식만** 바꾼다. 진입은 지금처럼 "그 종목 자기 인덱스의 다음 봉"이고, resolve_exit도 자기 인덱스 배열 위에서 돈다(달력 정렬 배열로 돌리면 휴장 NaN이 끼어 손절 판정일이 달라진다 — 스펙 주의점). 일별 루프의 pandas `.at`/`get_loc`/`in index`를 전부 배열 인덱싱으로 교체.

- [x] **Step 1: _prepare_arrays 구현, 일별 루프 교체**
- [x] **Step 2: 골든 테스트 + 기존 test_engine 전체 통과 (결과 불변 증명)**
- [x] **Step 3: 성능 실측 — 540종목(27×20 복제) 1회 run 목표 2초 이하**
- [x] **Step 4: 커밋**

### Task 3: universe 테이블 + db 헬퍼

**Files:**
- Modify: `backend/app/schema.sql`, `backend/app/db.py`
- Test: `backend/tests/test_db_universe.py`

**Interfaces:**
- Produces:
  - `db.save_universe_prices(conn, symbol, df)` — DELETE 후 INSERT (재수집 멱등)
  - `db.load_universe_prices(conn, symbol, limit=3000) -> pd.DataFrame` (load_prices와 같은 형태)
  - `db.upsert_universe_meta(conn, symbol, name, market, listing_date, delisting_date, is_etf)`
  - `db.list_universe_meta(conn) -> list[Row]`

```sql
CREATE TABLE IF NOT EXISTS universe_prices (
  symbol TEXT NOT NULL, date TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  PRIMARY KEY (symbol, date));
CREATE TABLE IF NOT EXISTS universe_meta (
  symbol TEXT PRIMARY KEY, name TEXT NOT NULL, market TEXT NOT NULL,
  listing_date TEXT, delisting_date TEXT, is_etf INTEGER NOT NULL DEFAULT 0);
```

- [x] **Step 1: 실패 테스트 작성 → 스키마·헬퍼 구현 → 통과 → 커밋**

### Task 4: universe.py — 후보 선정·수집·시점별 멤버십

**Files:**
- Create: `backend/app/universe.py`
- Test: `backend/tests/test_universe.py` (멤버십은 합성 데이터, 수집은 smoke 마커)

**Interfaces:**
- Produces:
  - `universe.candidate_symbols() -> list[dict]` — 현재 상장 거래대금 상위 `CANDIDATE_TOP=600` + 2021년 이후 폐지 주권(둘 다 fdr, 네트워크)
  - `universe.collect(conn, progress_cb=None) -> dict` — 시세 수집·저장, `{"ok": n, "failed": [symbol...]}` (실패는 조용히 버리지 않는다 — 그게 곧 생존편향)
  - `universe.monthly_membership(frames: dict[str, pd.DataFrame], top_n=300, window=60) -> dict[str, pd.Series]` — 심볼별 bool Series(달력=자기 인덱스). 매월 첫 거래일에 직전 60거래일 거래대금(close×volume) 중앙값 상위 top_n 재선정, 다음 재선정까지 유지. **순수 함수, 네트워크 없음.**
  - `universe.load_frames(conn) -> (frames, tickers)` — tickers에 `delisting_date` 포함, `market="KR"`, `currency="KRW"`

멤버십 계산은 룩어헤드 금지: 재선정일 판정에 쓰는 60일 창은 재선정일 **이전** 봉만(`shift(1)` 후 rolling). START_DATE="2019-01-01"로 수집해 2021년 이후 멤버십의 워밍업을 확보.

- [x] **Step 1: monthly_membership 실패 테스트(합성: 나중에만 거래대금 커진 종목이 이른 시점 멤버십에 없는지) → 구현 → 통과**
- [x] **Step 2: collect/candidate_symbols 구현 + smoke 테스트 → 커밋**

### Task 5: engine 멤버십 게이트 + 상장폐지 청산

**Files:**
- Modify: `backend/app/engine.py`
- Test: `backend/tests/test_engine.py`에 추가

**Interfaces:**
- Produces: `run(..., membership: dict[str, pd.Series] | None = None)` — 진입 후보 조건에 "그날 멤버십 True" AND. 청산은 멤버십과 무관(보유는 신호·손절로만 끝난다). 폐지 종목(tickers에 delisting_date 있음)이 데이터 끝까지 보유되면 `exit_reason="delisted"`(기존 "end" 대신).

- [x] **Step 1: 실패 테스트 2건(멤버십 밖 진입 금지 / delisted 사유) → 구현 → 통과 → 커밋**

### Task 6: engine.walkforward — anchored 폴드 검증

**Files:**
- Modify: `backend/app/engine.py`
- Test: `backend/tests/test_engine.py`에 추가

**Interfaces:**
- Produces:
```python
def walkforward(price_frames, tickers, preset, *, initial_capital_krw, fx,
                membership=None, bench_frame=None, folds=5,
                min_train_frac=0.4, progress_cb=None) -> dict
# 반환: {folds: [{fold, train_end, valid_start, valid_end, params,
#                 valid: metrics, bench_cagr, excess_pct, }...],
#        summary: {median_excess_pct, positive_folds, total_folds,
#                  param_stability: {distinct_combos, note}},
#        stitched_curve: [{date, equity_krw}...], stitched_metrics: metrics,
#        stitched_bench: [{date, equity_krw}...]}
```
- 달력의 앞 min_train_frac는 최소 학습 구간, 나머지를 folds 등분해 검증 구간으로.
- 폴드 k: 학습 = frames를 valid_start 미만으로 절단해 그리드 전체 run → 학습 샤프 1등(None 최하). 검증 = frames를 valid_end 이하로 절단해 `run(trade_start=valid_start)` — 워밍업은 valid_start 이전 전체 이력이 담당.
- bench_cagr: bench_frame을 같은 검증 달력으로 buy_and_hold → metrics.cagr. excess_pct = valid.cagr − bench_cagr.
- stitched: 폴드 검증 곡선을 시간순 연결, 각 폴드를 직전 폴드 종료자본/초기자본 배율로 체인링크.
- progress_cb(done, total): 잡 진행률용 (total = folds × (조합수+1)).

- [x] **Step 1: 합성 데이터 실패 테스트(폴드 경계 비겹침·검증이 학습 뒤·excess 계산·stitched 연속성) → 구현 → 통과 → 커밋**

### Task 7: 백그라운드 잡 + API

**Files:**
- Create: `backend/app/jobs.py`
- Modify: `backend/app/service.py`, `backend/app/api.py`
- Test: `backend/tests/test_api.py`에 추가

**Interfaces:**
- Produces:
  - `jobs.start(target, *args) -> job_id` / `jobs.get(job_id) -> {status: running|done|error, progress, result?, error?}` — 모듈 레벨 dict + threading.Thread + Lock. 스레드 안에서 `state_db.conn()`으로 자기 연결.
  - `service.run_walkforward(conn, preset, initial_capital_krw, universe, progress_cb) -> dict` — universe="watchlist"(기존 _strategy_universe) 또는 "krx300"(universe.load_frames + monthly_membership). bench는 BENCH:KR.
  - `POST /api/strategy/walkforward {preset, initial_capital_krw?, universe?}` → `{job_id}`
  - `GET /api/strategy/walkforward/{job_id}` → 잡 상태
  - `POST /api/universe/collect` → `{job_id}` / `GET /api/universe/status` → `{symbols, last_date, delisted_count}`
  - `/api/strategy/optimize` 응답에 `warnings: ["단일 홀드아웃은 검증 구간 레짐에 지배될 수 있습니다. 워크포워드 결과를 우선하세요."]` 추가(기존 필드 유지).

- [x] **Step 1: 잡 스토어 단위 테스트 → 구현 → 통과**
- [x] **Step 2: API 테스트(POST→폴링→done, 합성 소형 유니버스) → 라우트 구현 → 통과 → 커밋**

### Task 8: Strategy.tsx 워크포워드 화면

**Files:**
- Modify: `frontend/src/pages/Strategy.tsx`, `frontend/src/types.ts`
- (필요시) Modify: `frontend/src/components/EquityCurve.tsx`

**Interfaces:**
- Consumes: Task 7 API. types.ts에 `WalkforwardResult`/`WalkforwardFold`/`JobStatus` 추가.

- 유니버스 선택(관심종목/KRX300), KRX300 미수집이면 수집 버튼+진행률.
- "워크포워드 검증" 버튼 → job 생성 → 2초 폴링 진행률 → 완료 시:
  - 폴드 표: 검증구간 | 선택 파라미터 | 검증 CAGR | 벤치 CAGR | **초과수익** | MDD | 거래수 (null → `—`)
  - 판정 요약: 초과수익 중앙값, 양수 폴드 n/N, 파라미터 안정성 문구
  - 연결 자본곡선 + 벤치마크 (EquityCurve)
- 기존 "파라미터 최적화" 표는 워크포워드 섹션으로 교체(버튼 제거), API는 유지.

- [x] **Step 1: types.ts + 화면 구현 → tsc·lint 통과 → npm run build → 커밋**

### Task 9: 실측 — 유니버스 수집 + 두 프리셋 워크포워드 (개선 판정의 베이스라인)

**Files:** 없음(실행·기록만). 결과는 `_workspace/strategy-validation/baseline.md`에 기록.

- [x] **Step 1: universe.collect 실행(실 네트워크, 약 2~3분), 실패 목록 확인**
- [x] **Step 2: krx300 워크포워드 두 프리셋 실행, 폴드 표·판정 기록**
- [x] **Step 3: 관심종목 워크포워드도 실행해 유니버스 편향 크기를 수치로 기록**

### Task 10: 수익률 개선 실험 — 시장 레짐 필터

**Files:**
- Modify: `backend/app/engine.py`(run에 `regime: pd.Series | None` — True인 날만 신규 진입), `backend/app/service.py`(BENCH:KR 종가>200일선으로 레짐 시리즈 계산, walkforward에 `regime_filter` 옵션), `backend/app/api.py`, `frontend/src/pages/Strategy.tsx`(토글)
- Test: `backend/tests/test_engine.py`, `test_api.py`

**Interfaces:**
- Produces: `run(..., regime=None)`, walkforward 요청 바디 `regime_filter: bool = False`.

- [x] **Step 1: 실패 테스트(레짐 False인 날 진입 없음) → 구현 → 통과 → 커밋**
- [x] **Step 2: krx300 워크포워드를 레짐 on/off로 실행, 초과수익 중앙값·MDD·양수 폴드 비율 비교 기록**
- [x] **Step 3: 판정 — 개선이 확인되면 autotrade 기본 설정 반영을 제안(자동 반영은 하지 않는다, 실계좌 규칙 변경은 사용자 결정), 아니면 사실대로 기록**

## Self-Review 체크: 스펙 각 섹션 ↔ Task 매핑 — 벡터화(1·2), 유니버스 저장/선정/폐지(3·4·5), 워크포워드/판정/잡/화면(6·7·8), 하지 않는 것 준수(미국·새 프리셋 없음). Task 10은 사용자 후속 지시("수익률 개선 과정 진행")에 따른 추가 범위.
