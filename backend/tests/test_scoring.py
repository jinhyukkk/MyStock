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

def test_insufficient_data_raises(ohlcv_up):
    with pytest.raises(ValueError):
        scoring.score_ticker(ind.compute_indicators(ohlcv_up.head(50)))
