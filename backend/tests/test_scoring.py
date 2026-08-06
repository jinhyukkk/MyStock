import pytest
from app import indicators as ind
from app import scoring

def test_grade_thresholds():
    assert scoring.grade(75) == "강력매수"
    assert scoring.grade(60) == "강력매수"
    assert scoring.grade(30) == "매수"
    assert scoring.grade(0) == "중립"
    assert scoring.grade(-30) == "매도"
    assert scoring.grade(-60) == "강력매도"

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
    # 하락 추세에서 평균회귀 지표의 양(+) 점수는 반감 + 경고 문구
    for item in result["indicator_scores"]:
        if item["name"] in ("RSI", "볼린저밴드", "스토캐스틱") and item["score"] > 0:
            assert "신뢰도 반감" in item["reason"]

def test_insufficient_data_raises(ohlcv_up):
    with pytest.raises(ValueError):
        scoring.score_ticker(ind.compute_indicators(ohlcv_up.head(50)))
