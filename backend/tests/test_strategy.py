import pandas as pd
import pytest

from app import strategy


def _series(values: list[float]) -> pd.Series:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype=float)


def _frame(closes: list[float]) -> pd.DataFrame:
    """종가만 의미 있는 최소 일봉. 고가·저가는 종가와 같게 둔다."""
    s = _series(closes)
    return pd.DataFrame({"open": s, "high": s, "low": s, "close": s,
                         "volume": 1000.0}, index=s.index)


def test_momentum_skips_recent_window():
    """12-1 모멘텀은 최근 skip일을 제외한다 — 단기 반전이 신호를 오염시킨다.

    lookback=5, skip=2 이면 i 시점 수익률은 close[i-2] / close[i-7] - 1 이다.
    """
    close = _series([100, 110, 120, 130, 140, 150, 160, 170, 180, 190])
    m = strategy.momentum(close, lookback=5, skip=2)
    # i=7: close[5]=150, close[0]=100 → 0.5
    assert m.iloc[7] == pytest.approx(0.5)
    # 앞쪽 lookback+skip 구간은 값이 없다
    assert m.iloc[:7].isna().all()


def test_abs_momentum_enters_on_positive_momentum_above_trend():
    """진입 조건 = 모멘텀 양(+) AND 종가 > 추세선."""
    df = _frame([100 + i for i in range(30)])
    out = strategy.abs_momentum(df, {"lookback": 10, "skip": 2, "trend_ma": 5})
    assert out["enter"].iloc[-1]
    assert not out["exit"].iloc[-1]


def test_abs_momentum_exits_when_momentum_turns_negative():
    """모멘텀이 음(-)으로 돌면 청산 신호."""
    df = _frame([100 + i for i in range(20)] + [120 - 4 * i for i in range(20)])
    out = strategy.abs_momentum(df, {"lookback": 10, "skip": 2, "trend_ma": 5})
    assert out["exit"].iloc[-1]
    assert not out["enter"].iloc[-1]


def test_signals_have_no_lookahead():
    """미래 봉을 붙여도 과거 시그널이 바뀌면 안 된다.

    이게 깨지면 백테스트 전체가 거짓이 된다 — 가장 중요한 테스트다.
    """
    full = _frame([100 + (i % 7) * 3 for i in range(60)])
    out_full = strategy.abs_momentum(full, {"lookback": 10, "skip": 2, "trend_ma": 5})
    cut = full.iloc[:40]
    out_cut = strategy.abs_momentum(cut, {"lookback": 10, "skip": 2, "trend_ma": 5})
    pd.testing.assert_frame_equal(out_full.iloc[:40], out_cut)


def _ohlc(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """(open, high, low, close) 튜플 목록 → 일봉."""
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(
        {"open": [r[0] for r in rows], "high": [r[1] for r in rows],
         "low": [r[2] for r in rows], "close": [r[3] for r in rows],
         "volume": 1000.0}, index=idx)


def test_donchian_enters_on_breakout_of_prior_high():
    """N일 최고가를 넘어서면 진입. 비교 대상은 **어제까지의** 최고가다."""
    rows = [(100, 110, 90, 100)] * 3 + [(100, 116, 95, 115)]
    out = strategy.donchian(_ohlc(rows), {"entry_n": 3, "exit_n": 2})
    assert out["enter"].iloc[3]


def test_donchian_does_not_use_todays_high_in_its_own_breakout():
    """오늘 고가를 오늘 돌파 판정에 넣으면 매일 진입 신호가 뜬다.

    .shift(1) 누락 회귀를 잡는 테스트다.
    """
    rows = [(100, 110, 90, 100), (100, 120, 90, 105),
            (100, 130, 90, 115), (100, 140, 90, 125)]
    out = strategy.donchian(_ohlc(rows), {"entry_n": 2, "exit_n": 2})
    assert not out["enter"].any()


def test_donchian_exits_below_prior_low():
    """M일 최저가를 이탈하면 청산."""
    rows = [(100, 110, 95, 100)] * 3 + [(100, 105, 80, 90)]
    out = strategy.donchian(_ohlc(rows), {"entry_n": 3, "exit_n": 3})
    assert out["exit"].iloc[3]


def test_donchian_registered_in_presets():
    assert "donchian" in strategy.PRESETS
    assert strategy.PRESETS["donchian"]["fn"] is strategy.donchian


def test_both_presets_expose_a_continuous_strength():
    """동시 진입 후보를 자를 때 쓸 연속값. 없으면 엔진이 심볼 이름순으로 자른다.

    - 절대 모멘텀: 모멘텀 값 그 자체
    - 돈치안: 돌파 폭 비율 (종가 − 직전 최고가) / 직전 최고가
    """
    df = _frame([100 + i for i in range(20)])
    mom = strategy.abs_momentum(df, {"lookback": 5, "skip": 2, "trend_ma": 3})
    expected = strategy.momentum(df["close"], 5, 2).fillna(0.0)
    pd.testing.assert_series_equal(mom["strength"], expected, check_names=False)

    rows = [(100, 110, 90, 100)] * 3 + [(100, 116, 95, 115)]
    don = strategy.donchian(_ohlc(rows), {"entry_n": 3, "exit_n": 2})
    # 직전 3일 최고가 110 → (115 − 110) / 110
    assert don["strength"].iloc[3] == pytest.approx(5 / 110)
    # 지표가 안 찬 앞부분은 0 — NaN을 남기면 정렬에서 튄다
    assert don["strength"].iloc[0] == 0.0


# ── 시장 레짐 ──────────────────────────────────────────────────────────────
# 이 함수가 검증(service.run_walkforward)과 실행(autotrade.plan)의 단일 진실
# 원천이다. 두 곳이 각자 200일선을 계산하면 정합성은 다시 깨진다.

def test_regime_series_is_true_only_above_the_moving_average():
    """지수가 이동평균 위인 날만 True — 신규 진입을 허용하는 날의 정의."""
    closes = list(range(100, 130)) + [90] * 5
    reg = strategy.regime_series(_series(closes), ma=5)
    assert bool(reg.iloc[20]) is True     # 상승 구간 — 종가 > 5일선
    assert bool(reg.iloc[-1]) is False    # 급락 구간 — 종가 < 5일선


def test_regime_series_is_false_while_the_moving_average_is_unfilled():
    """MA가 안 찬 앞 구간은 False — 판단 근거가 없을 때는 진입을 막는 쪽이 보수적이다."""
    reg = strategy.regime_series(_series([100, 101, 102, 103, 104]), ma=5)
    assert list(reg.iloc[:4]) == [False, False, False, False]
    assert reg.dtype == bool  # NaN이 남으면 engine이 NaN을 참으로 읽을 여지가 생긴다


def test_regime_series_defaults_to_the_validated_200_day_window():
    """기본 창은 워크포워드에서 검증한 200일 — 기본값이 다르면 검증과 실행이 갈린다."""
    assert strategy.REGIME_MA == 200
    closes = list(range(100, 400))
    default = strategy.regime_series(_series(closes))
    explicit = strategy.regime_series(_series(closes), ma=200)
    pd.testing.assert_series_equal(default, explicit)


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
