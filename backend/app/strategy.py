"""전략 프리셋 — 일봉을 받아 진입·청산 시점만 답한다.

여기는 **순수 함수만** 둔다(DB·네트워크·현재시각 없음). 자본이 얼마인지,
몇 주를 사는지는 engine.py의 몫이다. 경계를 섞으면 전략을 추가할 때마다
사이징 로직까지 손대게 된다.

룩어헤드 금지가 이 파일의 유일한 하드 규칙이다. rolling 최고/최저에는
반드시 .shift(1)을 건다 — 오늘 고가를 오늘 돌파 판정에 넣으면 그 백테스트는
전부 거짓이 된다.
"""
import pandas as pd


def momentum(close: pd.Series, lookback: int, skip: int) -> pd.Series:
    """12-1 모멘텀 — 최근 skip일을 제외한 lookback 기간 수익률(비율).

    최근 1개월을 빼는 이유는 단기 반전 효과다. 그대로 두면 막 급등한 종목이
    최고 점수를 받고, 그 급등은 다음 달에 되돌려지는 경향이 있다.
    """
    base = close.shift(skip)
    return base / base.shift(lookback) - 1


REGIME_MA = 200  # 시장 레짐 판정 이동평균 — 워크포워드에서 검증한 창


def regime_ma_series(bench_close: pd.Series, ma: int = REGIME_MA) -> pd.Series:
    """레짐 판정에 쓰는 이동평균 그 자체 — 화면 표시값과 판정을 한 식에 묶는다.

    호출부가 자기 rolling()을 따로 돌리면 창 하나만 어긋나도 "지수 X가 200일선
    Y 아래"라는 문구와 실제 진입 차단 판정이 다른 근거를 쓰게 된다.
    """
    return bench_close.rolling(ma).mean()


def regime_series(bench_close: pd.Series, ma: int = REGIME_MA) -> pd.Series:
    """벤치마크가 이동평균 위인 날만 True — 신규 진입을 허용하는 날.

    검증(service.run_walkforward)과 실행(autotrade.plan)이 **같은 함수**를
    불러야 한다. 양쪽이 각자 200일선을 계산하면 창 하나만 어긋나도 검증한
    전략과 주문 내는 전략이 다른 물건이 되고, 그 사실이 어디에도 안 남는다.

    MA가 안 찬 앞 구간은 close > NaN이 False라 자동으로 진입이 막힌다 —
    판단 근거가 없을 때 막는 쪽이 보수적이다. bool로 확정해 돌려주는 이유는
    engine이 NaN을 참으로 읽을 여지를 남기지 않기 위해서다.
    """
    return (bench_close > regime_ma_series(bench_close, ma)).fillna(False).astype(bool)


def abs_momentum(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """절대(시계열) 모멘텀 — 자기 과거 수익률의 부호를 본다.

    횡단면 랭킹과 달리 유니버스가 필요 없다. 종목 하나로 계산된다.

    진입: 모멘텀 > 0 AND 종가 > 추세선
    청산: 모멘텀 < 0

    strength는 모멘텀 값 그 자체다 — 같은 날 진입 후보가 자리보다 많을 때
    엔진이 이 값 내림차순으로 자른다. 연속값이 없으면 심볼 이름순으로
    잘리게 되어 결과가 종목 이름에 의존한다.
    """
    close = df["close"]
    mom = momentum(close, params["lookback"], params["skip"])
    trend = close.rolling(params["trend_ma"]).mean()
    enter = (mom > 0) & (close > trend)
    exit_ = mom < 0
    # NaN 구간(지표가 아직 안 찬 앞부분)은 신호 없음으로 확정한다 —
    # 결측을 그대로 두면 engine이 NaN을 참으로 읽을 여지가 남는다
    return pd.DataFrame({"enter": enter.fillna(False).astype(bool),
                         "exit": exit_.fillna(False).astype(bool),
                         "strength": mom.fillna(0.0).astype(float)},
                        index=df.index)


def donchian(df: pd.DataFrame, params: dict) -> pd.DataFrame:
    """돈치안 채널 돌파 — 가격 자체가 신호다.

    진입: 종가 > 직전 entry_n일 최고가
    청산: 종가 < 직전 exit_n일 최저가

    .shift(1)이 핵심이다. 빼면 오늘 고가가 오늘의 비교 대상에 들어가
    고가를 경신한 날마다 진입 신호가 뜬다.

    strength는 돌파 폭 비율 (종가 - 직전 최고가) / 직전 최고가다. 채널을
    크게 뚫은 종목이 먼저 자리를 가져간다.
    """
    hh = df["high"].rolling(params["entry_n"]).max().shift(1)
    ll = df["low"].rolling(params["exit_n"]).min().shift(1)
    enter = df["close"] > hh
    exit_ = df["close"] < ll
    strength = (df["close"] - hh) / hh.where(hh > 0)
    return pd.DataFrame({"enter": enter.fillna(False).astype(bool),
                         "exit": exit_.fillna(False).astype(bool),
                         "strength": strength.fillna(0.0).astype(float)},
                        index=df.index)


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


PRESETS = {
    "abs_momentum": {
        "label": "절대 모멘텀",
        "kind": TIMESERIES,
        "fn": abs_momentum,
        "params": {
            # grid는 최적화(engine.optimize) 탐색 후보다. 조합 수를 12~15개로
            # 묶어 두는 이유는 두 가지 — 동기 API가 수십 초 안에 끝나야 하고,
            # 후보가 많을수록 우연히 검증 구간까지 맞는 조합이 나올 확률(다중
            # 비교 오버피팅)이 올라간다.
            "lookback": {"default": 252, "min": 20, "max": 504, "label": "룩백(일)",
                         "grid": [63, 126, 252]},
            "skip": {"default": 21, "min": 0, "max": 63, "label": "스킵(일)",
                     "grid": [0, 21]},
            "trend_ma": {"default": 200, "min": 20, "max": 300, "label": "추세필터(일)",
                         "grid": [100, 200]},
        },
    },
    "donchian": {
        "label": "돈치안 돌파",
        "kind": TIMESERIES,
        "fn": donchian,
        "params": {
            "entry_n": {"default": 55, "min": 5, "max": 200, "label": "진입 채널(일)",
                        "grid": [20, 40, 55, 80, 120]},
            "exit_n": {"default": 20, "min": 5, "max": 200, "label": "청산 채널(일)",
                       "grid": [10, 20, 40]},
        },
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
