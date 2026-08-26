# 횡단면 모멘텀 프리셋 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 유니버스 내 모멘텀 상대 랭킹으로 진입·청산하는 `xs_momentum` 프리셋을 추가하고, krx300 워크포워드로 채택/기각을 판정한다.

**Architecture:** `strategy.PRESETS`에 `kind` 태그를 도입한다. 시계열 프리셋은 지금처럼 `fn(df, params)`를 노출하고, 횡단면 프리셋만 `universe_fn(frames, params, eligible)`를 노출한다. `engine.run`은 준비 루프에서 선언된 쪽을 호출하고, 그 뒤 자료구조(`prepared[sym]["sig"]`)부터는 한 줄도 바뀌지 않는다 — 벡터화된 일별 루프와 골든 픽스처를 건드리지 않는 유일한 방법이다. 자동매매는 시계열 프리셋만 실행하도록 막는다.

**Tech Stack:** Python 3.11, pandas, pytest / React 19 + TypeScript (Vite)

**Spec:** `docs/superpowers/specs/2026-08-26-cross-sectional-momentum-design.md`

## Global Constraints

- **작업 디렉터리:** 백엔드 명령은 `backend/`에서, 프론트 명령은 `frontend/`에서 실행한다. venv는 `backend/.venv/bin/`.
- **테스트 게이트:** 백엔드 `.venv/bin/pytest -q` (네트워크 없이 전부 통과). 프론트 `npx tsc -b && npm run lint`.
- **착수 시점 기준선:** 백엔드 484 passed, 6 deselected. 프론트 lint는 `src/finviz/Sections.tsx`의 기존 warning 2건만 허용(에러 0).
- **골든 픽스처 재생성 금지:** `backend/tests/fixtures/engine_golden.json`을 절대 다시 만들지 않는다. `abs_momentum`·`donchian` 결과가 비트 단위로 같아야 한다 — 이 작업에서 유일한 회귀 안전망이다.
- **응답 필드는 추가만.** 지우거나 이름을 바꾸지 않는다 (빌드본이 구버전일 수 있다).
- **주석은 한국어로 "왜"를 쓴다.** "안 그러면 무엇이 깨지는지"까지. 코드베이스 전체 관례.
- **`costs.py`에 새 상수를 만들지 않는다.** 이 작업은 비용 로직을 건드리지 않는다.
- **커밋 메시지 말미:** `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `backend/app/strategy.py` | `xs_momentum` 순수 함수, `kind` 상수, `PRESETS` 항목 | 수정 |
| `backend/app/engine.py` | 준비 루프에서 프리셋 종류에 따라 시그널 계산 분기 | 수정 (`run` 내부만) |
| `backend/app/autotrade.py` | 시계열 프리셋만 실행하도록 방어 | 수정 |
| `backend/app/service.py` | 프리셋 목록에 `kind`·`autotrade_capable`, 작은 유니버스 경고 | 수정 |
| `backend/tests/test_strategy.py` | `xs_momentum` 단위 테스트 | 수정 |
| `backend/tests/test_engine.py` | 횡단면 프리셋 통합 + 신호 정렬 | 수정 |
| `backend/tests/test_autotrade.py` | 횡단면 거부·폴백 | 수정 |
| `backend/tests/test_api.py` | 프리셋 응답 필드 | 수정 |
| `frontend/src/types.ts` | `StrategyPreset`에 두 필드 | 수정 |
| `frontend/src/pages/Autotrade.tsx` | 드롭다운을 `autotrade_capable`로 필터 | 수정 |
| `_workspace/strategy-validation/baseline.md` | 실측 결과 기록 | 수정 |

---

### Task 1: `xs_momentum` 순수 함수와 프리셋 등록

**Files:**
- Modify: `backend/app/strategy.py`
- Test: `backend/tests/test_strategy.py`

**Interfaces:**
- Consumes: 기존 `strategy.momentum(close, lookback, skip)`
- Produces:
  - `strategy.TIMESERIES = "timeseries"`, `strategy.CROSS_SECTIONAL = "cross_sectional"`
  - `strategy.xs_momentum(frames: dict[str, pd.DataFrame], params: dict, eligible: dict[str, pd.Series] | None = None) -> dict[str, pd.DataFrame]` — 각 값은 `enter`(bool)·`exit`(bool)·`strength`(float) 컬럼을 갖고 `frames[sym].index`에 정렬된 DataFrame
  - `strategy.PRESETS["abs_momentum"]["kind"] == TIMESERIES`, `["donchian"]["kind"] == TIMESERIES`
  - `strategy.PRESETS["xs_momentum"]` — `"kind": CROSS_SECTIONAL`, `"universe_fn": xs_momentum`, `"fn"` 키는 **없음**

**설계 결정 — 공통 달력에서 모멘텀을 계산한다.** `abs_momentum`은 종목 자기 인덱스에서 `shift(lookback)`을 하지만, `xs_momentum`은 전 종목 close를 outer-join한 공통 달력에서 계산한다. 종목마다 휴장일 수가 달라 자기 인덱스에서 재면 같은 "252봉"이 서로 다른 실제 기간이 되고, 그러면 랭킹이 비교 불가능한 값들을 줄 세우게 된다. 룩어헤드 위험은 없다 — shift는 과거만 본다. 결측을 ffill하지 않는 것도 의도다: 합성 가격으로 랭킹하면 거래정지 종목이 살아 있는 것처럼 순위에 남는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/tests/test_strategy.py` 끝에 추가:

```python
# ── 횡단면 모멘텀 ───────────────────────────────────────────────────────────
# 랭킹 분모가 이 전략의 전부다. 비적격 종목이 분모에 남으면 "상위 20%"가
# 실제로는 상위 30%가 되고, 그 오류는 예외 없이 조용히 틀린 결과를 만든다.

def _xs_frames(specs: dict[str, list[float]]) -> dict:
    """{심볼: 종가 리스트} → xs_momentum이 받는 frames. 전부 같은 달력."""
    return {sym: _frame(closes) for sym, closes in specs.items()}


def _rising(start: float, n: int = 30, step: float = 1.0) -> list[float]:
    return [start + i * step for i in range(n)]


def test_xs_momentum_enters_only_the_top_slice_of_the_universe():
    """모멘텀 상위 enter_pct%만 진입. 10종목·상위 20% → 정확히 2종목."""
    # step이 클수록 모멘텀이 크다 — 종목 순위를 결정적으로 만든다
    frames = _xs_frames({f"S{i:02d}": _rising(100, 30, 0.5 + i) for i in range(10)})
    sig = strategy.xs_momentum(
        frames, {"lookback": 5, "skip": 1, "enter_pct": 20, "exit_pct": 50})
    last = {sym: bool(s["enter"].iloc[-1]) for sym, s in sig.items()}
    assert sum(last.values()) == 2
    # step이 가장 큰 두 종목이 상위다
    assert last["S09"] and last["S08"]


def test_xs_momentum_drops_ineligible_symbols_from_the_denominator():
    """비적격 종목은 분모에서 빠진다 — 10종목 중 5개 비적격이면 상위 20%는 1종목.

    분모를 10으로 두면 2종목이 진입해 실제로는 유효 종목의 상위 40%를 산다.
    """
    frames = _xs_frames({f"S{i:02d}": _rising(100, 30, 0.5 + i) for i in range(10)})
    # 강한 쪽 5종목(S05~S09)을 비적격으로 만든다 — 분모가 S00~S04로 줄어든다
    eligible = {sym: pd.Series(int(sym[1:]) < 5, index=df.index)
                for sym, df in frames.items()}
    sig = strategy.xs_momentum(
        frames, {"lookback": 5, "skip": 1, "enter_pct": 20, "exit_pct": 50},
        eligible)
    last = {sym: bool(s["enter"].iloc[-1]) for sym, s in sig.items()}
    assert sum(last.values()) == 1, "분모가 5종목이어야 상위 20%가 1종목이다"
    assert last["S04"], "적격 종목 중 모멘텀 1위"
    assert not any(v for k, v in last.items() if int(k[1:]) >= 5)


def test_xs_momentum_treats_an_unrankable_symbol_as_an_exit():
    """랭킹을 계산할 수 없는 종목(모멘텀 NaN)은 진입 후보가 아니고 청산 신호다.

    False로 두면 그 종목은 손절이나 데이터 끝까지 절대 안 팔린다.
    """
    frames = _xs_frames({"A": _rising(100, 30, 2.0), "B": _rising(100, 30, 1.0)})
    sig = strategy.xs_momentum(
        frames, {"lookback": 5, "skip": 1, "enter_pct": 50, "exit_pct": 80})
    # 앞 6봉은 lookback+skip이 안 차 모멘텀이 NaN이다
    assert not sig["A"]["enter"].iloc[0]
    assert bool(sig["A"]["exit"].iloc[0]) is True


def test_xs_momentum_requires_hysteresis():
    """enter_pct >= exit_pct면 경계에서 매일 들락날락해 비용만 먹는다."""
    frames = _xs_frames({"A": _rising(100), "B": _rising(100, 30, 2.0)})
    with pytest.raises(ValueError):
        strategy.xs_momentum(
            frames, {"lookback": 5, "skip": 1, "enter_pct": 50, "exit_pct": 50})


def test_xs_momentum_aligns_signals_to_each_symbols_own_index():
    """engine이 신호를 종목 인덱스 위치로 색인하므로 길이·순서가 정확히 같아야 한다.

    어긋나면 예외 없이 신호가 한 칸씩 밀린 자본곡선이 나온다.
    """
    frames = _xs_frames({"A": _rising(100, 30, 2.0), "B": _rising(100, 30, 1.0)})
    # B에서 중간 5봉을 빼 달력을 어긋나게 한다(휴장·거래정지 재현)
    frames["B"] = frames["B"].drop(frames["B"].index[10:15])
    sig = strategy.xs_momentum(
        frames, {"lookback": 5, "skip": 1, "enter_pct": 50, "exit_pct": 80})
    for sym, df in frames.items():
        assert len(sig[sym]) == len(df)
        pd.testing.assert_index_equal(sig[sym].index, df.index)
        assert sig[sym]["enter"].dtype == bool
        assert sig[sym]["exit"].dtype == bool


def test_xs_momentum_has_no_lookahead():
    """뒤쪽 데이터를 잘라내도 마지막 남은 날의 신호가 같아야 한다."""
    frames = _xs_frames({f"S{i}": _rising(100, 40, 0.5 + i) for i in range(6)})
    params = {"lookback": 5, "skip": 1, "enter_pct": 30, "exit_pct": 60}
    full = strategy.xs_momentum(frames, params)
    cut_at = frames["S0"].index[25]
    truncated = strategy.xs_momentum(
        {s: df[df.index <= cut_at] for s, df in frames.items()}, params)
    for sym in frames:
        assert bool(full[sym]["enter"].at[cut_at]) == \
               bool(truncated[sym]["enter"].at[cut_at])
        assert bool(full[sym]["exit"].at[cut_at]) == \
               bool(truncated[sym]["exit"].at[cut_at])


def test_all_presets_declare_their_kind():
    """태그를 기본값에 의존하면 새 프리셋에서 빼먹은 것이 조용히 지나간다."""
    for key, meta in strategy.PRESETS.items():
        assert meta["kind"] in (strategy.TIMESERIES, strategy.CROSS_SECTIONAL), key
        if meta["kind"] == strategy.CROSS_SECTIONAL:
            assert callable(meta["universe_fn"]) and "fn" not in meta
        else:
            assert callable(meta["fn"]) and "universe_fn" not in meta


def test_xs_momentum_grid_never_violates_hysteresis():
    """그리드가 만드는 모든 조합이 enter_pct < exit_pct를 만족해야 한다."""
    import itertools
    grids = {k: v["grid"] for k, v in strategy.PRESETS["xs_momentum"]["params"].items()}
    for combo in itertools.product(*grids.values()):
        p = dict(zip(grids.keys(), combo))
        assert p["enter_pct"] < p["exit_pct"], p
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `cd backend && .venv/bin/pytest tests/test_strategy.py -q`
Expected: FAIL — `AttributeError: module 'app.strategy' has no attribute 'xs_momentum'` (또는 `TIMESERIES`)

- [ ] **Step 3: 최소 구현**

`backend/app/strategy.py`의 `donchian` 함수 뒤, `PRESETS` 앞에 추가:

```python
TIMESERIES = "timeseries"          # fn(df, params) — 종목 하나로 계산된다
CROSS_SECTIONAL = "cross_sectional"  # universe_fn(frames, params, eligible)


def xs_momentum(frames: dict[str, pd.DataFrame], params: dict,
                eligible: dict[str, pd.Series] | None = None
                ) -> dict[str, pd.DataFrame]:
    """유니버스 내 모멘텀 상대 랭킹 — 상위 enter_pct%에 들면 진입, exit_pct% 밖으로
    밀리면 청산.

    시계열 모멘텀(abs_momentum)이 "자기 과거보다 오르는가"를 묻는 반면 여기는
    "지금 유니버스에서 상대적으로 강한가"를 묻는다. 실측에서 시계열 계열이
    지수 급등 폴드에 -112%p로 뒤처진 이유가 절대 게이트라, 그 게이트를 상대
    랭킹으로 바꾸는 것이 이 프리셋의 존재 이유다.

    **모멘텀을 공통 달력에서 계산한다.** 종목마다 휴장일 수가 달라 자기
    인덱스에서 재면 같은 252봉이 서로 다른 실제 기간이 되고, 비교 불가능한
    값들을 줄 세우게 된다. 결측을 ffill하지 않는 것도 의도다 — 합성 가격으로
    랭킹하면 거래정지 종목이 살아 있는 것처럼 순위에 남는다.

    eligible={심볼: bool Series}는 그날 랭킹 분모에 넣을 자격이다(유니버스
    멤버십). 비적격 칸을 NaN으로 지우면 rank(pct=True)의 분모가 자동으로
    "그날 유효한 종목 수"가 된다. 최하위 순위로 채우면 분모가 부풀어
    "상위 20%"가 실제로는 상위 30%가 된다.
    """
    enter_pct, exit_pct = params["enter_pct"], params["exit_pct"]
    if enter_pct >= exit_pct:
        raise ValueError(
            f"enter_pct({enter_pct})는 exit_pct({exit_pct})보다 작아야 합니다 — "
            "같거나 뒤집히면 히스테리시스가 없어 경계에서 매일 들락날락하며 "
            "비용만 먹는다")
    if not frames:
        return {}

    # 공통 달력(outer join). 그 종목에 봉이 없는 날은 NaN으로 남아 분모에서 빠진다
    wide = pd.DataFrame({sym: df["close"] for sym, df in frames.items()}).sort_index()
    mom = wide.apply(lambda col: momentum(col, params["lookback"], params["skip"]))

    if eligible is not None:
        elig = pd.DataFrame(
            {sym: (eligible[sym].reindex(wide.index, fill_value=False)
                   if sym in eligible
                   else pd.Series(False, index=wide.index))
             for sym in wide.columns})
        mom = mom.where(elig)  # 비적격 = NaN = 분모에서 제외

    # 같은 날 안에서만 줄 세운다 — axis=1이 그 사실을 보장한다
    rank_pct = mom.rank(axis=1, pct=True, ascending=False)
    enter = rank_pct <= enter_pct / 100
    # NaN도 청산이다 — 랭킹을 계산할 수 없게 된 종목(거래정지·폐지 임박)을
    # 계속 보유할 근거가 없다. 빼면 손절이나 데이터 끝까지 절대 안 팔린다.
    exit_ = (rank_pct > exit_pct / 100) | rank_pct.isna()

    out = {}
    for sym, df in frames.items():
        # 종목 자기 인덱스로 되돌린다 — engine이 이 길이·순서를 전제한다
        out[sym] = pd.DataFrame(
            {"enter": enter[sym].reindex(df.index).fillna(False).astype(bool),
             "exit": exit_[sym].reindex(df.index).fillna(False).astype(bool),
             # strength는 모멘텀 원값 — 같은 날 안에서 랭킹과 정렬 순서가
             # 동일하고(단조 변환), 원값이면 다른 프리셋과 비교 가능하다
             "strength": mom[sym].reindex(df.index).fillna(0.0).astype(float)},
            index=df.index)
    return out
```

같은 파일의 `PRESETS`에서 기존 두 항목에 `kind`를 추가하고 새 항목을 넣는다:

```python
PRESETS = {
    "abs_momentum": {
        "label": "절대 모멘텀",
        "kind": TIMESERIES,
        "fn": abs_momentum,
        ...  # params는 그대로
    },
    "donchian": {
        "label": "돈치안 돌파",
        "kind": TIMESERIES,
        "fn": donchian,
        ...  # params는 그대로
    },
    "xs_momentum": {
        "label": "횡단면 모멘텀",
        "kind": CROSS_SECTIONAL,
        "universe_fn": xs_momentum,
        "params": {
            # 조합 12개 — 기존 프리셋과 같은 상한. 워크포워드는 폴드×(조합+1)회
            # run()을 돌리므로 조합이 늘면 실행시간과 다중비교 오버피팅이 함께 오른다.
            "lookback": {"default": 252, "min": 20, "max": 504, "label": "룩백(일)",
                         "grid": [126, 252]},
            # skip은 탐색하지 않는다 — 12-1 모멘텀의 표준값이라 이 구간에서
            # 재탐색할 근거가 약한데, 그리드에 넣으면 조합이 2배가 된다.
            "skip": {"default": 21, "min": 0, "max": 63, "label": "스킵(일)",
                     "grid": [21]},
            "enter_pct": {"default": 20, "min": 1, "max": 50, "label": "진입 상위(%)",
                          "grid": [10, 20, 30]},
            "exit_pct": {"default": 50, "min": 5, "max": 100, "label": "청산 상위(%)",
                         "grid": [40, 60]},
        },
    },
}
```

- [ ] **Step 4: 테스트가 통과하는 것을 확인한다**

Run: `cd backend && .venv/bin/pytest tests/test_strategy.py -q`
Expected: PASS (기존 12건 + 신규 8건 = 20 passed)

- [ ] **Step 5: 전체 스위트로 회귀를 확인한다**

Run: `cd backend && .venv/bin/pytest -q`
Expected: 484 passed 이상, 실패 0. **골든 테스트가 통과해야 한다** — 이 단계에서 실패하면 `PRESETS`의 기존 두 항목에서 `params`를 실수로 건드린 것이다.

- [ ] **Step 6: 커밋**

```bash
git add backend/app/strategy.py backend/tests/test_strategy.py
git commit -m "$(cat <<'EOF'
feat: 횡단면 모멘텀 프리셋 — 유니버스 내 모멘텀 상대 랭킹

시계열 계열 두 프리셋이 지수 급등 폴드에서 -112%p로 뒤처진 원인이 절대
게이트라, 그 게이트를 상대 랭킹으로 바꾼다. PRESETS에 kind 태그를 두고
횡단면만 universe_fn을 노출한다.

랭킹 분모는 eligible=False를 NaN으로 지워 결정한다 — rank(pct=True)가 그 행의
non-NaN 개수로 정규화하므로 상장 전·거래정지·폐지·멤버십 이탈이 전부 같은
방식으로 빠진다. 최하위 순위로 채우면 분모가 부풀어 상위 20%가 실제로는
상위 30%가 된다.

모멘텀은 공통 달력에서 계산한다 — 종목마다 휴장일 수가 달라 자기 인덱스에서
재면 같은 252봉이 서로 다른 실제 기간이 되고, 비교 불가능한 값을 줄 세운다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `engine.run` 준비 루프 분기

**Files:**
- Modify: `backend/app/engine.py:177-200` (`run` 함수의 `fn` 조회와 `prepared` 루프)
- Test: `backend/tests/test_engine.py`

**Interfaces:**
- Consumes: Task 1의 `strategy.CROSS_SECTIONAL`, `strategy.PRESETS[...]["universe_fn"]`
- Produces: `engine.run(..., preset="xs_momentum", ...)`이 시계열 프리셋과 동일한 반환 계약(`equity_curve`·`trades`·`metrics`·`_used` …)을 지킨다. 시그니처 변경 없음.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/tests/test_engine.py` 끝에 추가:

```python
# ── 횡단면 프리셋 통합 ──────────────────────────────────────────────────────

def _xs_universe(n_symbols=10, n_days=400, seed=11):
    """추세 세기가 종목마다 다른 합성 일봉 — 랭킹이 갈리도록."""
    import numpy as np
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=n_days)
    frames, tickers = {}, {}
    for k in range(n_symbols):
        drift = 0.0002 + k * 0.0002
        close = 10_000 * np.exp(np.cumsum(rng.normal(drift, 0.015, n_days)))
        spread = np.abs(rng.normal(0, 0.01, n_days)) * close
        frames[f"X{k:02d}"] = pd.DataFrame(
            {"open": close, "high": close + spread, "low": close - spread,
             "close": close, "volume": 1e6}, index=idx)
        tickers[f"X{k:02d}"] = {"name": f"X{k:02d}", "market": "KR",
                                "currency": "KRW", "is_etf": 0}
    return frames, tickers


def test_run_supports_a_cross_sectional_preset():
    """횡단면 프리셋으로도 자본곡선과 거래가 나온다."""
    frames, tickers = _xs_universe()
    out = engine.run(frames, tickers, "xs_momentum",
                     {"lookback": 126, "skip": 21, "enter_pct": 20, "exit_pct": 50},
                     initial_capital_krw=10_000_000.0, fx=1300.0)
    assert out["equity_curve"], "자본곡선이 비면 신호가 전혀 안 붙은 것이다"
    assert out["trades"], "거래 0건 결과는 회귀를 못 잡는다"
    assert out["metrics"]["cagr"] is not None
    assert out["universe_size"] == 10


def test_cross_sectional_signals_stay_aligned_with_suspended_bars():
    """거래정지(NaN 행)가 섞여도 신호가 한 칸씩 밀리지 않는다.

    밀리면 예외 없이 틀린 자본곡선이 나오므로, 여기서 잡지 못하면 어디서도
    잡히지 않는다. NaN 행을 심은 종목의 진입가가 그 종목 실제 시가여야 한다.
    """
    frames, tickers = _xs_universe()
    victim = "X09"  # 모멘텀 1위 — 반드시 매수 후보에 든다
    f = frames[victim].copy()
    f.iloc[200:205, :4] = float("nan")  # OHLC만 NaN (거래정지)
    frames[victim] = f
    out = engine.run(frames, tickers, "xs_momentum",
                     {"lookback": 126, "skip": 21, "enter_pct": 30, "exit_pct": 60},
                     initial_capital_krw=10_000_000.0, fx=1300.0)
    valid_opens = set(f["open"].dropna().round(4))
    for t in out["trades"]:
        if t["symbol"] == victim:
            assert t["entry_price"] in valid_opens, \
                "진입가가 그 종목의 실제 시가가 아니면 신호가 밀린 것이다"


def test_cross_sectional_membership_restricts_the_ranking_denominator():
    """멤버십이 랭킹 분모에 반영된다 — 비멤버는 진입하지 않는다."""
    frames, tickers = _xs_universe()
    members = {"X00", "X01", "X02", "X03"}
    membership = {s: pd.Series(s in members, index=df.index)
                  for s, df in frames.items()}
    out = engine.run(frames, tickers, "xs_momentum",
                     {"lookback": 126, "skip": 21, "enter_pct": 30, "exit_pct": 60},
                     initial_capital_krw=10_000_000.0, fx=1300.0,
                     membership=membership)
    traded = {t["symbol"] for t in out["trades"]}
    assert traded, "멤버 안에서는 거래가 나와야 한다"
    assert traded <= members, f"비멤버가 진입했다: {traded - members}"
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `cd backend && .venv/bin/pytest tests/test_engine.py -q -k cross_sectional`
Expected: FAIL — `KeyError: 'fn'` (`engine.run`이 `PRESETS[preset]["fn"]`을 무조건 읽는다)

- [ ] **Step 3: 최소 구현**

`backend/app/engine.py`의 `run` 함수에서 **이 줄을 지운다**:

```python
    fn = strategy.PRESETS[preset]["fn"]
```

그리고 `prepared` 루프에서 `"sig": fn(enriched, params)`를 `"sig": None`으로 바꾼 뒤, 루프 **직후**에 시그널 계산 블록을 넣는다. 루프 안의 나머지(30봉 필터, `dropna`, `atr14`, `rate`, `cost`)는 한 글자도 바꾸지 않는다:

```python
        prepared[sym] = {
            "df": enriched, "sig": None,  # 시그널은 루프 뒤에서 한 번에 붙인다
            "rate": fx if tickers.get(sym, {}).get("currency") == "USD" else 1.0,
            "cost": _cost_pct(tickers.get(sym, {}), clean, fx),
        }

    # 시그널 계산 — 프리셋이 선언한 종류에 따라 갈린다. 횡단면은 유니버스
    # 전체를 봐야 랭킹이 나오므로 종목 루프 안에서는 계산할 수 없다.
    # 정리된 프레임(prepared[*]["df"])을 넘기는 것이 계약의 핵심이다 — 원본
    # 프레임으로 계산하면 거래정지 행 하나마다 신호가 한 칸씩 밀리고, 그
    # 오류는 예외 없이 조용히 틀린 자본곡선을 만든다.
    meta = strategy.PRESETS[preset]
    if meta["kind"] == strategy.CROSS_SECTIONAL:
        sig_frames = {s: pr["df"] for s, pr in prepared.items()}
        eligible = None
        if membership is not None:
            # 멤버십이 곧 랭킹 분모 자격이다. 아래 ②의 enter_mat 마스킹은
            # 그대로 남긴다 — 멱등이고, 시계열 프리셋에는 그게 유일한 방어선이다.
            eligible = {
                s: (membership[s].reindex(df.index, fill_value=False)
                    if s in membership
                    else pd.Series(False, index=df.index))
                for s, df in sig_frames.items()}
        sigs = meta["universe_fn"](sig_frames, params, eligible)
    else:
        sigs = {s: meta["fn"](pr["df"], params) for s, pr in prepared.items()}
    for s in list(prepared):
        if sigs.get(s) is None:
            # 신호를 못 만든 종목은 유니버스에서 뺀다 — sig가 None으로 남으면
            # 아래 배열 준비에서 터진다
            del prepared[s]
        else:
            prepared[s]["sig"] = sigs[s]
```

- [ ] **Step 4: 테스트가 통과하는 것을 확인한다**

Run: `cd backend && .venv/bin/pytest tests/test_engine.py -q`
Expected: PASS (신규 3건 포함)

- [ ] **Step 5: 골든 픽스처로 기존 프리셋 결과 불변을 확인한다**

Run: `cd backend && .venv/bin/pytest tests/test_engine_golden.py -q`
Expected: PASS. **실패하면 픽스처를 재생성하지 말고** 준비 루프에서 `fn(enriched, params)`에 넘기는 인자나 `prepared` 딕트 구성이 달라진 것을 찾아 되돌린다.

- [ ] **Step 6: 전체 스위트**

Run: `cd backend && .venv/bin/pytest -q`
Expected: 실패 0

- [ ] **Step 7: 커밋**

```bash
git add backend/app/engine.py backend/tests/test_engine.py
git commit -m "$(cat <<'EOF'
feat: engine.run이 유니버스 시그널 프리셋을 지원

종목 루프 안에서 시그널을 계산하던 것을 루프 뒤로 옮겨, 프리셋이 선언한
kind에 따라 fn(df) 또는 universe_fn(frames, eligible)을 부른다. 그 뒤
prepared[sym]["sig"]부터는 한 줄도 바뀌지 않아 벡터화 일별 루프와 골든
픽스처가 그대로 유효하다.

정리된 프레임(NaN OHLC 드랍 후)을 넘긴다 — 원본으로 랭킹하면 거래정지 행
하나마다 신호가 한 칸씩 밀리고, 그 오류는 예외를 던지지 않는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 자동매매는 시계열 프리셋만 실행한다

**Files:**
- Modify: `backend/app/autotrade.py` (`settings`, `save_settings`)
- Test: `backend/tests/test_autotrade.py`

**Interfaces:**
- Consumes: `strategy.TIMESERIES`, `strategy.PRESETS[preset]["kind"]`
- Produces: `autotrade.save_settings`가 횡단면 프리셋에 `ValueError`를 던진다. `autotrade.settings(conn)`은 저장된 프리셋이 횡단면이면 `abs_momentum`으로 폴백한다.

**왜 막는가:** 관심종목 18종목에서 상위 20%는 3.6종목이다. 상대 랭킹은 모집단이 바뀌면 다른 지표라, 직접 고른 18종목 사이의 순위는 krx300 상위 20%와 다른 물건이다. 직전 작업에서 닫은 "검증한 전략 = 실행하는 전략"을 다시 깨지 않는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/tests/test_autotrade.py` 끝에 추가:

```python
# ── 횡단면 프리셋은 자동매매에서 실행하지 않는다 ─────────────────────────────

def test_save_settings_rejects_a_cross_sectional_preset(conn):
    """관심종목 사이의 상대 랭킹은 krx300 랭킹과 다른 지표다 — 검증/실행 정합성."""
    with pytest.raises(ValueError):
        autotrade.save_settings(conn, "xs_momentum", {})


def test_settings_falls_back_when_the_saved_preset_is_cross_sectional(conn):
    """meta에 횡단면이 남아 있어도(수동 편집·향후 kind 변경) 자동매매가 죽지 않는다."""
    db.set_meta(conn, "autotrade_preset", "xs_momentum")
    cfg = autotrade.settings(conn)
    assert cfg["preset"] == "abs_momentum"
    assert cfg["params"]["lookback"] == 252
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `cd backend && .venv/bin/pytest tests/test_autotrade.py -q -k cross_sectional`
Expected: FAIL — `save_settings`가 예외를 던지지 않고, `settings`가 `"xs_momentum"`을 돌려준다

- [ ] **Step 3: 최소 구현**

`backend/app/autotrade.py`의 `settings()`에서 프리셋 검증 줄을 바꾼다:

```python
    preset = db.get_meta(conn, "autotrade_preset") or "abs_momentum"
    # 프리셋이 삭제·개명돼도, 횡단면 프리셋이 저장돼 있어도 자동매매가 죽으면 안 된다.
    # 횡단면은 _signals가 쓰는 fn이 없고, 애초에 관심종목 모집단에서는 상대
    # 랭킹의 의미가 달라져 실행 대상이 아니다.
    if preset not in strategy.PRESETS or \
            strategy.PRESETS[preset]["kind"] != strategy.TIMESERIES:
        preset = "abs_momentum"
```

`save_settings()`에서 검증을 강화한다:

```python
def save_settings(conn, preset: str, params: dict,
                  regime_filter: bool = True) -> None:
    if preset not in strategy.PRESETS:
        raise ValueError(f"알 수 없는 전략: {preset}")
    if strategy.PRESETS[preset]["kind"] != strategy.TIMESERIES:
        # 상대 랭킹은 모집단이 바뀌면 다른 지표다 — 관심종목 18종목 사이의
        # 상위 20%(3.6종목)를 krx300 검증 결과의 근거로 쓸 수 없다
        raise ValueError(
            f"{strategy.PRESETS[preset]['label']}은 유니버스 상대 랭킹 전략이라 "
            "자동매매에서 실행할 수 없습니다. 전략 연구실에서만 검증하세요.")
    db.set_meta(conn, "autotrade_preset", preset)
    ...  # 이하 그대로
```

- [ ] **Step 4: 테스트가 통과하는 것을 확인한다**

Run: `cd backend && .venv/bin/pytest tests/test_autotrade.py -q`
Expected: PASS (신규 2건 포함)

- [ ] **Step 5: 커밋**

```bash
git add backend/app/autotrade.py backend/tests/test_autotrade.py
git commit -m "$(cat <<'EOF'
feat: 자동매매는 시계열 프리셋만 실행 — 횡단면은 연구실 전용

관심종목 18종목에서 상위 20%는 3.6종목이다. 상대 랭킹은 모집단이 바뀌면
다른 지표라, 직접 고른 종목 사이의 순위를 krx300 검증 결과의 근거로 쓸 수
없다. 방금 닫은 검증/실행 정합성을 다시 깨지 않는다.

settings()는 폴백까지 둔다 — meta에 횡단면이 남아 있어도 자동매매가 죽으면
손절 주문이 안 나가는 쪽이 더 위험하다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 프리셋 응답 필드와 작은 유니버스 경고

**Files:**
- Modify: `backend/app/service.py` (`strategy_presets`, `run_strategy_backtest`, `run_walkforward`)
- Test: `backend/tests/test_api.py`, `backend/tests/test_service.py`

**Interfaces:**
- Consumes: `strategy.PRESETS[...]["kind"]`, `strategy.TIMESERIES`, `strategy.CROSS_SECTIONAL`
- Produces:
  - `GET /api/strategy/presets` 각 항목에 `kind: str`, `autotrade_capable: bool` 추가
  - `service.XS_MIN_UNIVERSE = 50`
  - `run_strategy_backtest`·`run_walkforward` 응답에 `xs_universe_warning: str | None` 추가

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`backend/tests/test_api.py` 끝에 추가:

```python
def test_strategy_presets_declare_autotrade_capability(client):
    """화면이 자동매매 드롭다운에서 횡단면을 걸러낼 수 있어야 한다."""
    presets = {p["key"]: p for p in client.get("/api/strategy/presets").json()}
    assert presets["abs_momentum"]["autotrade_capable"] is True
    assert presets["abs_momentum"]["kind"] == "timeseries"
    assert presets["xs_momentum"]["autotrade_capable"] is False
    assert presets["xs_momentum"]["kind"] == "cross_sectional"
    # 기존 필드는 그대로 — 빌드본이 구버전일 수 있다
    assert presets["xs_momentum"]["label"] and presets["xs_momentum"]["params"]
```

`backend/tests/test_service.py` 끝에 추가:

```python
def test_cross_sectional_backtest_warns_about_a_thin_universe(conn, ohlcv_up):
    """18종목 유니버스에서 상위 20%는 3.6종목 — 수치 옆에 한계가 없으면 근거로 읽힌다."""
    for i in range(3):
        sym = f"00593{i}"
        db.upsert_ticker(conn, sym, "KR", f"종목{i}")
        db.save_prices(conn, sym, ohlcv_up)
    out = service.run_strategy_backtest(conn, "xs_momentum")
    assert out["xs_universe_warning"] is not None
    assert "3" in out["xs_universe_warning"]


def test_timeseries_backtest_has_no_thin_universe_warning(conn, ohlcv_up):
    """시계열 프리셋은 유니버스 크기와 무관하다 — 경고로 화면을 채우지 않는다."""
    db.upsert_ticker(conn, "005930", "KR", "삼성전자")
    db.save_prices(conn, "005930", ohlcv_up)
    out = service.run_strategy_backtest(conn, "abs_momentum")
    assert out["xs_universe_warning"] is None
```

- [ ] **Step 2: 테스트가 실패하는 것을 확인한다**

Run: `cd backend && .venv/bin/pytest tests/test_api.py tests/test_service.py -q -k "autotrade_capability or universe_warning or thin_universe"`
Expected: FAIL — `KeyError: 'autotrade_capable'`, `KeyError: 'xs_universe_warning'`

- [ ] **Step 3: 최소 구현**

`backend/app/service.py`의 `UNIVERSE_WARNING` 옆에 추가:

```python
# 횡단면 프리셋의 랭킹 분모가 이보다 작으면 "상위 K%"가 사실상 종목 1~2개다.
# 수집 종목 수가 아니라 run()이 실제로 신호를 만든 수(universe_size)를 센다.
XS_MIN_UNIVERSE = 50


def _xs_universe_warning(preset: str, universe_size: int) -> str | None:
    """횡단면 프리셋을 작은 유니버스로 돌렸을 때의 고지. 아니면 None.

    수치 옆에 한계가 없으면 그 수치를 근거로 읽게 된다 — 자동매매의 유니버스
    불일치 고지와 같은 취지다.
    """
    if strategy.PRESETS.get(preset, {}).get("kind") != strategy.CROSS_SECTIONAL:
        return None
    if universe_size >= XS_MIN_UNIVERSE:
        return None
    return (f"유니버스가 {universe_size}종목이라 상대 랭킹의 의미가 약합니다. "
            f"횡단면 전략은 krx300 유니버스({XS_MIN_UNIVERSE}종목 이상)에서 "
            "판정하세요.")
```

`strategy_presets()`를 바꾼다:

```python
def strategy_presets() -> list[dict]:
    return [{"key": k, "label": v["label"], "params": v["params"],
             "kind": v["kind"],
             # 화면이 자동매매 드롭다운에서 걸러낼 수 있게 계산해 내보낸다 —
             # 프론트가 kind 문자열을 직접 해석하면 규칙이 두 곳에 생긴다
             "autotrade_capable": v["kind"] == strategy.TIMESERIES}
            for k, v in strategy.PRESETS.items()]
```

`run_strategy_backtest()`에서 `out["universe_warning"] = UNIVERSE_WARNING` 바로 뒤에 추가:

```python
    out["xs_universe_warning"] = _xs_universe_warning(preset, out["universe_size"])
```

`run_walkforward()`에서 `out["universe_size"] = len(frames)` 바로 뒤에 추가:

```python
    out["xs_universe_warning"] = _xs_universe_warning(preset, out["universe_size"])
```

- [ ] **Step 4: 테스트가 통과하는 것을 확인한다**

Run: `cd backend && .venv/bin/pytest tests/test_api.py tests/test_service.py -q`
Expected: PASS

- [ ] **Step 5: 전체 스위트 + API 실응답 확인**

Run: `cd backend && .venv/bin/pytest -q`
Expected: 실패 0

- [ ] **Step 6: 커밋**

```bash
git add backend/app/service.py backend/tests/test_api.py backend/tests/test_service.py
git commit -m "$(cat <<'EOF'
feat: 프리셋 응답에 kind·autotrade_capable, 작은 유니버스 경고

autotrade_capable을 백엔드에서 계산해 내보낸다 — 프론트가 kind 문자열을
직접 해석하면 "무엇을 자동매매로 돌릴 수 있는가" 규칙이 두 곳에 생긴다.

횡단면 프리셋을 50종목 미만으로 돌리면 상위 K%가 사실상 1~2종목이라
랭킹이 무의미하다. 수집 종목 수가 아니라 run()이 실제로 신호를 만든
universe_size를 세어 경고한다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: 프론트 — 자동매매 드롭다운 필터

**Files:**
- Modify: `frontend/src/types.ts` (`StrategyPreset`)
- Modify: `frontend/src/pages/Autotrade.tsx`

**Interfaces:**
- Consumes: Task 4의 `GET /api/strategy/presets` 응답 필드 `kind`, `autotrade_capable`
- Produces: 없음 (최종 소비자)

- [ ] **Step 1: 타입을 추가한다**

`frontend/src/types.ts`:

```typescript
export interface StrategyPreset {
  key: string; label: string; params: Record<string, StrategyParamMeta>;
  /** 'timeseries' | 'cross_sectional' — 횡단면은 유니버스 전체를 봐야 신호가 나온다 */
  kind: string;
  /** 자동매매에서 실행 가능한지. 백엔드가 판단해 내보낸다(규칙을 두 곳에 두지 않는다) */
  autotrade_capable: boolean;
}
```

- [ ] **Step 2: 드롭다운을 필터한다**

`frontend/src/pages/Autotrade.tsx`에서 `presets`를 받은 직후 필터한다. `Promise.all` 안의 호출을 바꾼다:

```typescript
      get<StrategyPreset[]>('/api/strategy/presets')
        // 횡단면 전략은 관심종목 모집단에서 상대 랭킹의 의미가 달라져
        // 자동매매 대상이 아니다 — 애초에 고를 수 없게 한다
        .then(ps => setPresets(ps.filter(p => p.autotrade_capable)))
```

- [ ] **Step 3: 타입·린트를 확인한다**

Run: `cd frontend && npx tsc -b && npm run lint`
Expected: tsc 에러 0, lint 에러 0 (`src/finviz/Sections.tsx`의 기존 warning 2건만)

- [ ] **Step 4: 빌드하고 실화면에서 확인한다**

Run: `cd frontend && npm run build`

그다음 `preview_start`로 앱을 띄우고 `/autotrade`에서 확인한다 (Bash로 서버를 실행하지 않는다):
- 전략 드롭다운에 "절대 모멘텀"·"돈치안 돌파"만 있고 "횡단면 모멘텀"이 **없다**
- `/strategy`(전략 연구실)에는 "횡단면 모멘텀"이 **있다**
- 콘솔 에러 0 (`read_console_messages`)

- [ ] **Step 5: 커밋**

```bash
git add frontend/src/types.ts frontend/src/pages/Autotrade.tsx frontend/dist
git commit -m "$(cat <<'EOF'
feat: 자동매매 전략 드롭다운에서 횡단면 프리셋을 감춘다

autotrade_capable로 필터한다 — 백엔드가 이미 거부하지만, 고를 수 있게 두면
저장 버튼을 누른 뒤에야 에러를 보게 된다. 연구실(/strategy)에는 그대로 노출.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 실측 판정 — krx300 워크포워드

**Files:**
- Modify: `_workspace/strategy-validation/baseline.md`

**Interfaces:**
- Consumes: Task 1~4 전부
- Produces: 채택/기각 판정 (코드 변경 없음)

**이 태스크는 TDD가 아니다** — 측정이다. 코드를 고치는 것이 아니라 이미 만든 것을 재고 기록한다.

- [ ] **Step 1: 유니버스가 수집돼 있는지 확인한다**

```bash
curl -s http://127.0.0.1:8722/api/universe/status
```

`symbols`가 900 이상이어야 한다. 비어 있으면 `POST /api/universe/collect`를 먼저 돌린다(수 분, 네트워크 사용).

- [ ] **Step 2: 레짐 OFF로 워크포워드를 돌린다**

```bash
curl -s -X POST http://127.0.0.1:8722/api/strategy/walkforward \
  -H 'content-type: application/json' \
  -d '{"preset":"xs_momentum","universe":"krx300","regime_filter":false}'
```

돌아온 `job_id`로 완료까지 폴링한다: `GET /api/strategy/walkforward/{job_id}`

- [ ] **Step 3: 레짐 ON으로 워크포워드를 돌린다**

```bash
curl -s -X POST http://127.0.0.1:8722/api/strategy/walkforward \
  -H 'content-type: application/json' \
  -d '{"preset":"xs_momentum","universe":"krx300","regime_filter":true}'
```

- [ ] **Step 4: 결과를 기존 표에 추가한다**

`_workspace/strategy-validation/baseline.md`의 요약 표에 두 행을 추가한다. 열은 기존과 동일: 구성 / 초과수익 중앙값(`summary.median_excess_pct`) / 이긴 폴드(`summary.positive_folds`/`total_folds`) / 연결 CAGR(`stitched_metrics.cagr`) / 연결 MDD(`stitched_metrics.mdd`) / 파라미터 안정성(`summary.param_stability.note`).

**F5(마지막 폴드)의 `excess_pct`를 반드시 함께 적는다** — 기존 레짐 구성이 -112%p였고, 이 전략을 만든 이유가 그 구멍이다. 개선되지 않았다면 그 사실이 표 아래 문장으로 남아야 한다.

- [ ] **Step 5: 사전 확정한 기준으로 판정한다**

> **채택**: 초과수익 중앙값 > +4.6%p **AND** 이긴 폴드 ≥ 3/5 **AND** 파라미터 안정성이 "불안정"이 아님
> **기각**: 그 외

기준을 사후에 바꾸지 않는다. 기각도 결과이므로 같은 형식으로 문서에 남긴다. **자동매매 기본값은 판정과 무관하게 건드리지 않는다.**

- [ ] **Step 6: 커밋**

```bash
git add _workspace/strategy-validation/baseline.md
git commit -m "$(cat <<'EOF'
docs: 횡단면 모멘텀 워크포워드 실측 — <채택|기각>

<초과수익 중앙값·이긴 폴드·연결 CAGR/MDD·파라미터 안정성 요약 한 줄>
<F5(지수 랠리 폴드) 초과수익이 개선됐는지 한 줄>

판정 기준은 착수 전 스펙에 확정한 것을 그대로 적용했다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**1. 스펙 커버리지**

| 스펙 섹션 | 태스크 |
|---|---|
| ① 시그널 계약 (`kind`, `universe_fn`) | Task 1 (계약·프리셋), Task 2 (engine 분기) |
| ② 랭킹·룩어헤드 규칙 | Task 1 (구현 + 룩어헤드 테스트 + 분모 테스트) |
| ③ 파라미터 그리드 | Task 1 (`PRESETS` 항목 + 히스테리시스 그리드 테스트) |
| ④ 소비자 변경 | Task 3 (autotrade), Task 4 (service), Task 5 (프론트). `api.py`는 스펙대로 변경 없음 |
| ④ 작은 유니버스 경고 | Task 4 |
| ⑤ 검증 계획 (단위·엔진·골든) | Task 1 Step 4~5, Task 2 Step 4~6 |
| ⑤ 실측 판정 + 사전 기준 | Task 6 |

**2. 플레이스홀더** — Task 6 Step 6의 커밋 메시지 `<...>`는 측정 결과라 실행 시점에만 채울 수 있는 값이며, 무엇을 넣을지 Step 4~5가 정확히 지정한다. 그 외 플레이스홀더 없음.

**3. 타입 일관성**

- `strategy.xs_momentum(frames, params, eligible)` — Task 1에서 정의, Task 2에서 `meta["universe_fn"](sig_frames, params, eligible)`로 호출. 인자 3개 위치 일치. ✓
- `eligible`의 타입 `dict[str, pd.Series]` — Task 1 테스트가 `pd.Series(bool, index=df.index)`로 만들고, Task 2가 `membership[s].reindex(df.index, fill_value=False)`로 만든다. 동일. ✓
- `strategy.TIMESERIES` / `CROSS_SECTIONAL` 문자열 값 `"timeseries"` / `"cross_sectional"` — Task 1에서 정의, Task 4가 응답에 그대로 싣고 Task 4의 API 테스트가 그 문자열을 단정. ✓
- `service.XS_MIN_UNIVERSE` / `_xs_universe_warning(preset, universe_size)` — Task 4 안에서만 쓰인다. ✓
- `autotrade_capable`(bool) — Task 4가 생산, Task 5의 `StrategyPreset.autotrade_capable`이 소비. ✓
- `out["universe_size"]` — `engine.run`이 이미 반환하는 기존 필드이며 `run_walkforward`는 `len(frames)`로 따로 덮어쓴다. Task 4는 두 함수에서 각각 그 시점의 값을 읽으므로 정의 순서상 문제 없음. ✓
