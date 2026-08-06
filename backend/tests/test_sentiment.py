from app import sentiment


def test_fg_label():
    assert sentiment.fg_label(10) == "극단적 공포"
    assert sentiment.fg_label(30) == "공포"
    assert sentiment.fg_label(50) == "중립"
    assert sentiment.fg_label(70) == "탐욕"
    assert sentiment.fg_label(90) == "극단적 탐욕"
    assert sentiment.fg_label(None) == "정보 없음"


def test_note_extreme_fear_with_buy_signal():
    senti = {"vix": 35.0, "vkospi": None, "cnn_fg": 15, "crypto_fg": None, "failed": []}
    note = sentiment.context_note(40, "US", senti)
    assert "공포" in note and "VIX" in note


def test_note_extreme_greed_with_buy_signal():
    senti = {"vix": 12.0, "vkospi": None, "cnn_fg": 85, "crypto_fg": None, "failed": []}
    note = sentiment.context_note(40, "US", senti)
    assert "과열" in note


def test_note_crypto_uses_crypto_fg():
    senti = {"vix": None, "vkospi": None, "cnn_fg": None, "crypto_fg": 20, "failed": []}
    note = sentiment.context_note(0, "CRYPTO", senti)
    assert note == "시장 극단적 공포 구간"


def test_note_missing_sources_none():
    senti = {"vix": None, "vkospi": None, "cnn_fg": None, "crypto_fg": None, "failed": ["cnn"]}
    assert sentiment.context_note(40, "US", senti) is None


def test_fetch_sentiment_survives_all_failures(monkeypatch):
    import requests
    def boom(*a, **k): raise requests.ConnectionError("down")
    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr(sentiment, "_fetch_yf_last", lambda t: (_ for _ in ()).throw(RuntimeError))
    monkeypatch.setattr(sentiment, "_fetch_vkospi", lambda: (_ for _ in ()).throw(RuntimeError))
    out = sentiment.fetch_sentiment()
    assert out["vix"] is None and out["cnn_fg"] is None
    assert len(out["failed"]) >= 3


def test_note_extreme_fear_for_nonpositive_base():
    senti = {"vix": None, "vkospi": None, "cnn_fg": 10, "crypto_fg": None, "failed": []}
    assert sentiment.context_note(-30, "US", senti) == "시장 극단적 공포 구간"
