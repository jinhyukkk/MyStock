from app import sentiment


def test_fg_label():
    assert sentiment.fg_label(10) == "극단적 공포"
    assert sentiment.fg_label(30) == "공포"
    assert sentiment.fg_label(50) == "중립"
    assert sentiment.fg_label(70) == "탐욕"
    assert sentiment.fg_label(90) == "극단적 탐욕"
    assert sentiment.fg_label(None) == "정보 없음"


def test_adjust_extreme_fear_boosts_buy():
    senti = {"vix": 35.0, "vkospi": None, "cnn_fg": 15, "crypto_fg": None, "failed": []}
    adjusted, note = sentiment.adjust_score(40, "US", senti)
    assert adjusted > 40           # 공포 = 역발상 가산
    assert "공포" in note and "VIX" in note


def test_adjust_extreme_greed_dampens_buy():
    senti = {"vix": 12.0, "vkospi": None, "cnn_fg": 85, "crypto_fg": None, "failed": []}
    adjusted, note = sentiment.adjust_score(40, "US", senti)
    assert adjusted < 40
    assert "과열" in note


def test_adjust_crypto_uses_crypto_fg():
    senti = {"vix": None, "vkospi": None, "cnn_fg": None, "crypto_fg": 20, "failed": []}
    adjusted, note = sentiment.adjust_score(0, "CRYPTO", senti)
    assert adjusted == 6.0         # (50-20)/5


def test_adjust_missing_sources_no_change():
    senti = {"vix": None, "vkospi": None, "cnn_fg": None, "crypto_fg": None, "failed": ["cnn"]}
    adjusted, note = sentiment.adjust_score(40, "US", senti)
    assert adjusted == 40 and note is None


def test_fetch_sentiment_survives_all_failures(monkeypatch):
    import requests
    def boom(*a, **k): raise requests.ConnectionError("down")
    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr(sentiment, "_fetch_yf_last", lambda t: (_ for _ in ()).throw(RuntimeError))
    monkeypatch.setattr(sentiment, "_fetch_vkospi", lambda: (_ for _ in ()).throw(RuntimeError))
    out = sentiment.fetch_sentiment()
    assert out["vix"] is None and out["cnn_fg"] is None
    assert len(out["failed"]) >= 3


def test_adjust_extreme_fear_note_for_nonpositive_base():
    senti = {"vix": None, "vkospi": None, "cnn_fg": 10, "crypto_fg": None, "failed": []}
    adjusted, note = sentiment.adjust_score(-30, "US", senti)
    assert note == "시장 극단적 공포 구간"
