import pytest
from app import indicators as ind
from app import scoring, service

def test_grade_thresholds():
    # 임계값은 실측 재보정으로 바뀐다 — 숫자가 아니라 경계 동작을 고정한다
    sb, b, s, ss = scoring.SWING_CUTS
    assert scoring.grade(sb + 1) == "강력매수"
    assert scoring.grade(sb) == "강력매수"
    assert scoring.grade(b) == "매수"
    assert scoring.grade(b - 0.1) == "중립"
    assert scoring.grade(0) == "중립"
    assert scoring.grade(s) == "매도"
    assert scoring.grade(ss) == "강력매도"
    assert scoring.grade(ss - 1) == "강력매도"


def test_top_grades_are_reachable_within_attainable_score_range():
    """ML-1: 실측 스윙 점수 범위는 [-50, +40] — 임계값이 그 안에 있어야 등급이 산다."""
    lo, hi = -50.0, 40.0
    assert scoring.grade(hi) == "강력매수" and scoring.grade(lo) == "강력매도"
    assert all(lo < c < hi for c in scoring.SWING_CUTS)


def test_longterm_uses_its_own_cuts():
    """중장기 분포는 우편향 — 스윙 임계값을 그대로 쓰면 등급이 위로 쏠린다."""
    assert scoring.SWING_CUTS != scoring.LONGTERM_CUTS
    # 스윙 강력매수 경계 점수를 중장기에 넣으면 아직 최상위가 아니어야 한다
    assert scoring.grade(scoring.SWING_CUTS[0]) == "강력매수"
    assert scoring.grade(scoring.SWING_CUTS[0], "longterm") != "강력매수"

def test_uptrend_scores_positive_longterm(ohlcv_up):
    result = scoring.score_ticker(ind.compute_indicators(ohlcv_up))
    assert result["longterm_score"] > 0  # 정배열 상승 추세
    assert -100 <= result["swing_score"] <= 100

def test_downtrend_scores_negative_longterm(ohlcv_down):
    result = scoring.score_ticker(ind.compute_indicators(ohlcv_down))
    assert result["longterm_score"] < 0

def test_reasons_are_korean_and_present(ohlcv_up):
    result = scoring.score_ticker(ind.compute_indicators(ohlcv_up))
    assert len(result["indicator_scores"]) >= 6
    for item in result["indicator_scores"]:
        assert item["reason"]  # 근거 설명 필수
        assert item["scope"] in ("swing", "longterm")
    assert result["summary"]

def test_regime_detection(ohlcv_up, ohlcv_down):
    up = scoring.score_ticker(ind.compute_indicators(ohlcv_up))
    down = scoring.score_ticker(ind.compute_indicators(ohlcv_down))
    assert up["regime"] == "up" and up["regime_label"] == "상승 추세"
    assert down["regime"] == "down"

def test_regime_dampens_meanrev_against_trend(ohlcv_down):
    result = scoring.score_ticker(ind.compute_indicators(ohlcv_down))
    # 하락 추세에서 평균회귀 팩터의 양(+) 점수는 반감 + 경고 문구
    for item in result["indicator_scores"]:
        if item["name"] == "과매수·과매도" and item["score"] > 0:
            assert "신뢰도 반감" in item["reason"]


def test_meanrev_is_one_composite_factor_not_three():
    """ML-13: RSI·볼린저·스토캐스틱 상호상관 0.70~0.77 — 따로 세면 한 신호에 3배 가중."""
    assert "meanrev" in scoring.SWING_WEIGHTS
    assert not {"rsi", "bollinger", "stoch"} & set(scoring.SWING_WEIGHTS)
    assert round(sum(scoring.SWING_WEIGHTS.values()), 6) == 1.0
    assert round(sum(scoring.LONG_WEIGHTS.values()), 6) == 1.0


def test_meanrev_composite_spans_oversold_to_overbought():
    import pandas as pd
    over = pd.Series({"rsi": 10.0, "bb_upper": 110.0, "bb_lower": 100.0, "close": 100.0,
                      "stoch_k": 5.0})
    under = pd.Series({"rsi": 95.0, "bb_upper": 110.0, "bb_lower": 100.0, "close": 110.0,
                       "stoch_k": 95.0})
    assert scoring._score_meanrev(over)[0] == 70
    assert scoring._score_meanrev(under)[0] == -70
    # 근거 문구에 세부 지표 값이 남아야 판단 재료가 사라지지 않는다
    assert "RSI" in scoring._score_meanrev(over)[1]


def test_pos_52w_high_zone_no_longer_penalized():
    """실측상 고점권 성과가 중간권과 같았다 — 감점할 근거가 없다."""
    import pandas as pd
    assert scoring._score_pos_52w(pd.Series({"pos_52w": 0.95}))[0] == 0
    assert scoring._score_pos_52w(pd.Series({"pos_52w": 0.1}))[0] == 50


def test_pos_52w_uses_high_low_range():
    """52주 신고가는 장중 고가로 정의된다 — 종가 rolling만 쓰면 범위가 좁게 잡힌다."""
    import pandas as pd
    close = pd.Series([100.0] * 100)
    high = pd.Series([120.0] * 100)
    low = pd.Series([80.0] * 100)
    assert ind.pos_52w(close, high, low).iloc[-1] == 0.5   # (100-80)/(120-80)
    assert ind.pos_52w(close).iloc[-1] != 0.5              # 종가만이면 범위가 0

def test_insufficient_data_raises(ohlcv_up):
    with pytest.raises(ValueError):
        scoring.score_ticker(ind.compute_indicators(ohlcv_up.head(50)))


def test_grade_change_direction():
    """'등급변경' 배지가 강등에도 초록이면 나쁜 소식이 좋은 소식으로 읽힌다.
    상향/하향을 숫자로 구분해 화면이 색을 고를 수 있게 한다."""
    assert service.grade_change_dir("중립", "강력매수") == 1
    assert service.grade_change_dir("매수", "매도") == -1
    assert service.grade_change_dir("매수", "매수") == 0
    assert service.grade_change_dir(None, "매수") == 0  # 첫 관측은 '변경'이 아니다


def test_grade_change_direction_uses_severity_not_sign():
    """매수 → 강력매수도 상향이고, 강력매도 → 매도는 완화이므로 상향이다."""
    assert service.grade_change_dir("매수", "강력매수") == 1
    assert service.grade_change_dir("강력매도", "매도") == 1
