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


PRESETS = {
    "abs_momentum": {
        "label": "절대 모멘텀",
        "fn": abs_momentum,
        "params": {
            "lookback": {"default": 252, "min": 20, "max": 504, "label": "룩백(일)"},
            "skip": {"default": 21, "min": 0, "max": 63, "label": "스킵(일)"},
            "trend_ma": {"default": 200, "min": 20, "max": 300, "label": "추세필터(일)"},
        },
    },
    "donchian": {
        "label": "돈치안 돌파",
        "fn": donchian,
        "params": {
            "entry_n": {"default": 55, "min": 5, "max": 200, "label": "진입 채널(일)"},
            "exit_n": {"default": 20, "min": 5, "max": 200, "label": "청산 채널(일)"},
        },
    },
}
