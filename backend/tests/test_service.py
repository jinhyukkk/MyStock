import json
from datetime import datetime

import pandas as pd
import pytest
from app import db, service, fetchers, portfolio, scoring, sentiment

FAKE_SENTI = {"vix": 20.0, "vkospi": None, "cnn_fg": 40, "crypto_fg": 55,
              "usdkrw": 1300.0, "failed": ["vkospi"]}

@pytest.fixture
def conn(tmp_path, ohlcv_up, monkeypatch):
    c = db.get_conn(str(tmp_path / "t.db"))
    db.upsert_ticker(c, "005930", "KR", "삼성전자", in_watchlist=1, yf_symbol="005930.KS")
    db.upsert_ticker(c, "AAPL", "US", "Apple", in_watchlist=1, yf_symbol="AAPL", currency="USD")
    monkeypatch.setattr(fetchers, "fetch_ohlcv", lambda *a, **k: ohlcv_up)
    monkeypatch.setattr(fetchers, "fetch_fundamentals", lambda *a, **k: {"per": 15.0})
    monkeypatch.setattr(sentiment, "fetch_sentiment", lambda: dict(FAKE_SENTI))
    yield c
    c.close()

def test_refresh_all_stores_signals(conn):
    out = service.refresh_all(conn)
    assert out["refreshed"] is True
    assert db.get_latest_signal(conn, "005930") is not None
    assert db.get_meta(conn, "last_refresh")
    assert json.loads(db.get_meta(conn, "sentiment"))["cnn_fg"] == 40

def test_refresh_survives_single_ticker_failure(conn, monkeypatch):
    orig = fetchers.fetch_ohlcv
    monkeypatch.setattr(fetchers, "fetch_ohlcv",
        lambda symbol, market, **k: (_ for _ in ()).throw(RuntimeError("down"))
        if symbol == "AAPL" else orig(symbol, market, **k))
    out = service.refresh_all(conn)
    assert "AAPL" in out["failed_tickers"]
    assert db.get_latest_signal(conn, "005930") is not None

def test_dashboard_shape(conn):
    service.refresh_all(conn)
    d = service.get_dashboard(conn)
    assert d["sentiment"]["cnn_fg_label"] == "공포"
    assert len(d["signals"]) == 2
    s = d["signals"][0]
    for key in ["symbol", "name", "market", "close", "change_pct", "swing_score",
                "swing_grade", "longterm_score", "longterm_grade",
                "grade_changed", "is_holding"]:
        assert key in s
    assert d["last_refresh"]

def test_summary_tags_shortened_and_ranked():
    details = {"indicator_scores": [
        {"name": "RSI", "score": 80, "reason": "RSI 28 — 과매도 구간 (반등 가능성)"},
        {"name": "MACD", "score": -40,
         "reason": "MACD 히스토그램 음(-) — 하락 모멘텀 유지 ⚠ 상승 추세 중 조정 신호 — 신뢰도 반감"},
        {"name": "거래량", "score": 0, "reason": "거래량 평균 수준 (100%)"},
        {"name": "볼린저밴드", "score": 30, "reason": "볼린저밴드 하단 근접"},
        {"name": "스토캐스틱", "score": 40, "reason": "스토캐스틱 15 — 과매도권"},
        {"name": "이평선 배열", "score": 70, "reason": "주가 > 60일선 > 120일선 — 중장기 정배열"},
    ]}
    tags = service.summary_tags(details)
    assert len(tags) == 3  # 0점 제외, |score| 상위 3개만
    assert tags[0] == {"label": "RSI: 과매도 구간", "score": 80, "warn": False}
    assert tags[1]["label"] == "이평선 배열: 중장기 정배열"
    assert tags[2]["warn"] is True  # 국면 반감 경고 분리
    assert service.summary_tags({}) == []  # 과거 데이터 폴백


def test_dashboard_includes_summary_tags(conn):
    service.refresh_all(conn)
    d = service.get_dashboard(conn)
    for s in d["signals"]:
        assert isinstance(s["summary_tags"], list) and len(s["summary_tags"]) <= 3


def test_rule_alerts(conn):
    service.refresh_all(conn)
    close = db.load_prices(conn, "005930").iloc[-1]["close"]
    db.insert_rule(conn, "005930", "TARGET", close * 0.9)   # 이미 도달
    db.insert_rule(conn, "005930", "STOP", close * 0.5)     # 미도달
    d = service.get_dashboard(conn)
    assert len(d["rule_alerts"]) == 1
    assert d["rule_alerts"][0]["rule_type"] == "TARGET"

def test_stop_rule_fires_on_intraday_low(conn):
    """ML-5: 장중 손절선을 관통했다가 회복한 날을 종가만 보면 알림 0건으로 넘긴다."""
    service.refresh_all(conn)
    bar = db.load_prices(conn, "005930").iloc[-1]
    db.insert_rule(conn, "005930", "STOP", (float(bar["low"]) + float(bar["close"])) / 2)
    alerts = service.get_dashboard(conn)["rule_alerts"]
    assert len(alerts) == 1
    a = alerts[0]
    assert a["rule_type"] == "STOP" and a["intraday_only"] is True
    assert "장중 이탈" in a["message"] and "회복" in a["message"]


def test_stop_rule_below_low_does_not_fire(conn):
    service.refresh_all(conn)
    low = float(db.load_prices(conn, "005930").iloc[-1]["low"])
    db.insert_rule(conn, "005930", "STOP", low * 0.5)
    assert service.get_dashboard(conn)["rule_alerts"] == []


def test_target_rule_fires_on_intraday_high(conn):
    service.refresh_all(conn)
    bar = db.load_prices(conn, "005930").iloc[-1]
    db.insert_rule(conn, "005930", "TARGET", (float(bar["high"]) + float(bar["close"])) / 2)
    a = service.get_dashboard(conn)["rule_alerts"][0]
    assert a["rule_type"] == "TARGET" and a["intraday_only"] is True
    assert "장중 터치" in a["message"]


def test_price_format_keeps_meaning_across_magnitudes():
    """ML-16: 소수 0자리는 USD 종목과 저가 코인에서 어떤 가격인지 알 수 없게 만든다."""
    assert service._fmt_price(70000) == "70,000"
    assert service._fmt_price(150.4) == "150.40"
    assert service._fmt_price(0.8) == "0.8000"


def test_telegram_stop_alert_carries_disclaimer(conn, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    sent = []

    class OK:
        ok = True

    monkeypatch.setattr(service.requests, "post",
                        lambda url, json, timeout: (sent.append(json), OK())[1])
    service._notify_telegram(conn, [{"symbol": "005930", "name": "삼성전자",
                                     "rule_type": "STOP", "value": 100,
                                     "intraday_only": False, "message": "손절"}])
    assert service.STOP_DISCLAIMER in sent[0]["text"]


def test_partial_bar_is_flagged(conn, monkeypatch, ohlcv_up):
    """장중 미완성 봉으로 만든 등급은 마감 때 뒤집힐 수 있다 — 그 사실을 실어 보낸다."""
    today = ohlcv_up.copy()
    # 마지막 봉이 "오늘"이어야 한다 — bdate_range는 주말이면 금요일로 물러선다
    today.index = pd.date_range(end=pd.Timestamp.now().normalize(), periods=len(today))
    monkeypatch.setattr(fetchers, "fetch_ohlcv", lambda *a, **k: today)
    service.refresh_all(conn)
    sig = next(s for s in service.get_dashboard(conn)["signals"] if s["symbol"] == "005930")
    assert sig["bar_complete"] is False
    assert sig["bar_date"] == pd.Timestamp.now().strftime("%Y-%m-%d")


def test_complete_bar_is_not_flagged(conn):
    service.refresh_all(conn)  # 픽스처는 과거 날짜로 끝난다
    sig = next(s for s in service.get_dashboard(conn)["signals"] if s["symbol"] == "005930")
    assert sig["bar_complete"] is True


def test_signal_includes_in_watchlist_flag(conn):
    service.refresh_all(conn)
    d = service.get_dashboard(conn)
    for s in d["signals"]:
        assert "in_watchlist" in s
    assert all(s["in_watchlist"] for s in d["signals"])


def test_removed_ticker_drops_from_dashboard(conn):
    service.refresh_all(conn)
    db.remove_from_watchlist(conn, "AAPL")
    d = service.get_dashboard(conn)
    symbols = [s["symbol"] for s in d["signals"]]
    assert "AAPL" not in symbols
    assert "005930" in symbols


def test_removed_ticker_not_polled_on_refresh(conn, monkeypatch):
    service.refresh_all(conn)
    db.remove_from_watchlist(conn, "AAPL")
    calls = []
    orig = fetchers.fetch_ohlcv

    def track(symbol, market, **k):
        calls.append(symbol)
        return orig(symbol, market, **k)

    monkeypatch.setattr(fetchers, "fetch_ohlcv", track)
    service.refresh_all(conn)
    assert "AAPL" not in calls
    assert "005930" in calls


def test_held_but_removed_ticker_still_in_dashboard(conn):
    service.refresh_all(conn)
    db.remove_from_watchlist(conn, "AAPL")
    db.insert_trade(conn, "AAPL", "BUY", 1, 100, "2026-01-01")
    d = service.get_dashboard(conn)
    aapl = next(s for s in d["signals"] if s["symbol"] == "AAPL")
    assert aapl["is_holding"] is True
    assert aapl["in_watchlist"] is False


def test_ticker_detail(conn):
    service.refresh_all(conn)
    detail = service.get_ticker_detail(conn, "005930")
    assert detail["name"] == "삼성전자"
    assert len(detail["candles"]) <= 200
    assert {"date", "open", "close", "sma20", "rsi", "macd"} <= set(detail["candles"][-1])
    assert detail["signal"]["swing_grade"]
    assert detail["fundamentals"] == {"per": 15.0}
    assert service.get_ticker_detail(conn, "NOPE") is None


def test_position_size_capped_by_max_weight(conn, monkeypatch):
    """ML-4: 2×ATR이 주가 대비 작으면 1% 룰 수량은 계좌 전액을 넘는다 — 상한이 잘라야 한다."""
    service.refresh_all(conn)
    db.set_meta(conn, "cash_krw", "100000000")
    full = service.indicators.compute_indicators(db.load_prices(conn, "005930"))
    full.loc[full.index[-1], "atr14"] = full["close"].iloc[-1] * 0.002  # 2×ATR = 주가의 0.4%
    r = service._risk_block(conn, full, "KRW", "005930")
    total = service.get_portfolio_view(conn)["totals"]["total_asset_krw"]
    assert r["position_size_capped"] is True and r["cap_reason"]
    assert r["position_notional_krw"] <= total * service.MAX_WEIGHT + 1


def test_position_size_uncapped_when_atr_wide(conn):
    service.refresh_all(conn)
    db.set_meta(conn, "cash_krw", "100000000")
    full = service.indicators.compute_indicators(db.load_prices(conn, "005930"))
    full.loc[full.index[-1], "atr14"] = full["close"].iloc[-1] * 0.05  # 2×ATR = 주가의 10%
    r = service._risk_block(conn, full, "KRW", "005930")
    assert r["position_size_capped"] is False
    assert r["position_notional_krw"] < service.get_portfolio_view(conn)["totals"]["total_asset_krw"] * 0.2


def test_risk_block_subtracts_existing_holding(conn):
    service.refresh_all(conn)
    db.set_meta(conn, "cash_krw", "100000000")
    detail = service.get_ticker_detail(conn, "005930")
    size = detail["risk"]["position_size_1pct"]
    db.insert_trade(conn, "005930", "BUY", size / 2, 100.0, "2026-01-05", fx_rate=1.0)
    after = service.get_ticker_detail(conn, "005930")["risk"]
    assert after["held_quantity"] == round(size / 2, 4)
    assert after["addable_quantity"] < after["position_size_1pct"]


def test_suggested_quantity_is_orderable(conn):
    """국내주식에 5.095주를 제시하면 그대로 낼 수 없는 주문이다 — 정수로 내린다."""
    service.refresh_all(conn)
    db.set_meta(conn, "cash_krw", "100000000")
    r = service.get_ticker_detail(conn, "005930")["risk"]
    assert r["position_size_1pct"] == int(r["position_size_1pct"])
    assert r["addable_quantity"] == int(r["addable_quantity"])
    assert r["lot_size"] == 1.0
    # 잘리기 전 값도 남긴다 — 얼마가 깎였는지 보이지 않으면 계산이 틀린 것처럼 읽힌다
    assert r["position_size_raw"] >= r["position_size_1pct"]


def test_wide_stop_is_flagged_as_unsuitable_for_swing(conn):
    """2×ATR 손절이 -21%면 그 손절을 지킬 트레이더가 없다 — 결국 손절 없는 매매가 된다."""
    service.refresh_all(conn)
    full = service.indicators.compute_indicators(db.load_prices(conn, "005930"))
    full.loc[full.index[-1], "atr14"] = full["close"].iloc[-1] * 0.09  # 2×ATR = 주가의 18%
    r = service._risk_block(conn, full, "KRW", "005930")
    assert r["stop_too_wide"] is True

    full.loc[full.index[-1], "atr14"] = full["close"].iloc[-1] * 0.02  # 2×ATR = 4%
    assert service._risk_block(conn, full, "KRW", "005930")["stop_too_wide"] is False


def test_risk_block_reports_liquidity_share(conn):
    """중소형주에서 제안 수량이 하루 거래대금 대비 과대하면 체결 자체가 밀린다."""
    service.refresh_all(conn)
    db.set_meta(conn, "cash_krw", "100000000")
    r = service.get_ticker_detail(conn, "005930")["risk"]
    assert r["turnover_krw"] > 0
    # 제안 노셔널이 일평균 거래대금에서 차지하는 비중
    assert r["liquidity_pct"] == pytest.approx(
        r["position_notional_krw"] / r["turnover_krw"] * 100, rel=1e-3)


def test_detail_and_portfolio_carry_last_refresh(conn):
    """갱신시각이 대시보드에만 있으면 상세·포트폴리오에서는 표시된 숫자가
    언제 것인지 알 수 없다 — 낡은 가격으로 주문을 낸다."""
    service.refresh_all(conn)
    stamp = db.get_meta(conn, "last_refresh")
    assert service.get_ticker_detail(conn, "005930")["last_refresh"] == stamp
    assert service.get_portfolio_view(conn)["last_refresh"] == stamp


def test_watchlist_signals_sort_buy_first(conn, monkeypatch):
    """관심 종목 구간을 -abs(점수)로 정렬하면 강력매도가 강력매수와 같은 높이로
    올라온다. 살 자리를 찾는 화면에서 팔 수도 없는 종목이 맨 위에 오면 안 된다."""
    rows = [{"symbol": "S1", "score": -80}, {"symbol": "S2", "score": 30},
            {"symbol": "S3", "score": 75}, {"symbol": "S4", "score": -10}]
    ordered = sorted(rows, key=lambda r: service._signal_sort_key(
        {"is_holding": False, "swing_score": r["score"]}))
    assert [r["symbol"] for r in ordered] == ["S3", "S2", "S4", "S1"]


def test_holdings_still_come_before_watchlist(conn):
    """보유 종목은 방향과 무관하게 먼저 온다 — 장중 가장 먼저 볼 것은 내 포지션이다."""
    held_sell = service._signal_sort_key({"is_holding": True, "swing_score": -80})
    watch_buy = service._signal_sort_key({"is_holding": False, "swing_score": 90})
    assert held_sell < watch_buy


def test_ticker_detail_exposes_cost_rates(conn):
    """주문 프리뷰가 비용을 추정하려면 요율이 필요하다. 프론트에 상수를 복제하면
    요율이 바뀔 때 화면과 원장이 서로 다른 비용을 말하게 된다."""
    service.refresh_all(conn)
    rates = service.get_ticker_detail(conn, "005930")["cost_rates"]
    assert rates["fee_pct"] == 0.015        # KR 위탁수수료 0.015%
    assert rates["sell_tax_pct"] == 0.15    # KR 증권거래세 0.15%


def test_exit_plan_only_appears_when_holding(conn):
    """비보유 종목에 청산 플랜을 띄우면 소음이고, 보유 종목에 없으면
    나가는 판단을 화면이 지원하지 못한다."""
    service.refresh_all(conn)
    db.set_meta(conn, "cash_krw", "100000000")
    assert service.get_ticker_detail(conn, "005930")["risk"]["exit_plan"] is None

    close = float(db.load_prices(conn, "005930").iloc[-1]["close"])
    db.insert_trade(conn, "005930", "BUY", 10, close * 1.25, "2026-01-05", fx_rate=1.0,
                    fee=0, tax=0)  # 평단보다 -20% 물린 상태
    plan = service.get_ticker_detail(conn, "005930")["risk"]["exit_plan"]
    assert plan["held_quantity"] == 10
    assert plan["unrealized_pnl_pct"] == -20.0
    assert [s["label"] for s in plan["slices"]] == ["1/3", "1/2", "전량"]
    # 부분청산 회수액은 매도 비용을 뺀 순액이라 명목 대금보다 작다
    assert plan["slices"][0]["proceeds_krw"] < close * (10 / 3)


def test_risk_block_includes_target_and_reward_risk(conn):
    """손절가만 있고 목표가가 없으면 진입 판단의 절반이 비어 있다."""
    service.refresh_all(conn)
    r = service.get_ticker_detail(conn, "005930")["risk"]
    close = db.load_prices(conn, "005930").iloc[-1]["close"]
    assert r["target_price"] > close > r["stop_price"]
    assert r["reward_risk"] == service.TARGET_R
    # 목표가는 손절 폭의 TARGET_R배 (저장값이 소수 4자리로 반올림돼 오차 허용)
    assert abs((r["target_price"] - close)
               - (close - r["stop_price"]) * service.TARGET_R) < 1e-3


def test_target_flags_overhead_resistance(conn):
    service.refresh_all(conn)
    r = service.get_ticker_detail(conn, "005930")["risk"]
    if r["resistance_60d"] is not None:
        close = db.load_prices(conn, "005930").iloc[-1]["close"]
        assert r["resistance_60d"] > close  # 아래쪽 고점은 저항이 아니다
        assert r["target_above_resistance"] == (r["target_price"] > r["resistance_60d"])


def test_portfolio_view_reports_account_open_risk(conn):
    service.refresh_all(conn)
    db.set_meta(conn, "cash_krw", "10000000")
    db.insert_trade(conn, "005930", "BUY", 10, 100.0, "2026-01-05", fx_rate=1.0)
    orisk = service.get_portfolio_view(conn)["open_risk"]
    assert orisk["total_risk_krw"] > 0
    assert orisk["limit_pct"] == portfolio.MAX_ACCOUNT_RISK_PCT
    assert orisk["rows"][0]["symbol"] == "005930"


def test_notify_telegram_dedupes_per_day(conn, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    sent = []

    class OK:
        ok = True

    monkeypatch.setattr(service.requests, "post",
                        lambda url, json=None, timeout=None: sent.append(json) or OK())
    alerts = [{"symbol": "005930", "rule_type": "TARGET", "value": 100.0,
               "message": "삼성전자 목표가 100 도달"}]
    service._notify_telegram(conn, alerts)
    service._notify_telegram(conn, alerts)  # 같은 날 재호출 → 발송 안 함
    assert len(sent) == 1
    assert "삼성전자" in sent[0]["text"] and sent[0]["chat_id"] == "42"


def test_notify_telegram_noop_without_config(conn, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr(service.requests, "post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("호출되면 안 됨")))
    service._notify_telegram(conn, [{"symbol": "A", "rule_type": "STOP", "value": 1,
                                     "message": "m"}])


def test_risk_block_prefers_registered_stop_rule(conn):
    """화면의 손절선과 알림을 울리는 손절선은 같아야 한다.

    2×ATR은 매일 재계산되므로, 룰로 등록한 다음 날부터 화면이 보여주는
    손절선과 실제 알림 트리거가 갈라진다. 등록 룰이 단일 진실이다.
    """
    service.refresh_all(conn)
    close = float(db.load_prices(conn, "005930").iloc[-1]["close"])
    suggested = service.get_ticker_detail(conn, "005930")["risk"]
    assert suggested["stop_source"] == "atr"

    my_stop = round(close * 0.95, 4)
    db.insert_rule(conn, "005930", "STOP", my_stop)
    r = service.get_ticker_detail(conn, "005930")["risk"]
    assert r["stop_source"] == "rule"
    assert r["stop_price"] == my_stop
    # 2×ATR 제안은 사라지지 않고 '오늘의 제안'으로 함께 남는다
    assert r["atr_stop_price"] == suggested["stop_price"]
    # 목표가·손익비도 실제로 지킬 손절선 기준으로 다시 계산된다
    assert abs((r["target_price"] - close)
               - (close - my_stop) * service.TARGET_R) < 1e-3


def test_risk_block_flags_drift_between_rule_and_todays_atr(conn):
    """한 번 등록한 룰은 변동성이 변해도 그대로 남아 서서히 무의미해진다."""
    service.refresh_all(conn)
    close = float(db.load_prices(conn, "005930").iloc[-1]["close"])
    db.insert_rule(conn, "005930", "STOP", round(close * 0.5, 4))
    r = service.get_ticker_detail(conn, "005930")["risk"]
    assert r["stop_drift_pct"] is not None
    assert r["stop_drift"] is True   # 제안과 크게 벌어짐 → 룰 갱신 안내


def test_risk_block_ignores_stop_rule_above_current_price(conn):
    """현재가 위 손절선은 이미 관통된 상태다 — 사이징 분모가 음수가 된다."""
    service.refresh_all(conn)
    close = float(db.load_prices(conn, "005930").iloc[-1]["close"])
    db.insert_rule(conn, "005930", "STOP", round(close * 1.1, 4))
    r = service.get_ticker_detail(conn, "005930")["risk"]
    assert r["stop_source"] == "atr"
    assert r["stop_price"] < close


def test_open_risk_uses_registered_stops(conn):
    """계좌 총 미결 리스크도 사용자가 실제로 지킬 손절선으로 잰다."""
    service.refresh_all(conn)
    db.set_meta(conn, "cash_krw", "10000000")
    db.insert_trade(conn, "005930", "BUY", 10, 100.0, "2026-01-05", fx_rate=1.0)
    before = service.get_portfolio_view(conn)["open_risk"]
    assert before["unregistered_count"] == 1
    assert before["rows"][0]["stop_source"] == "atr"

    close = float(db.load_prices(conn, "005930").iloc[-1]["close"])
    db.insert_rule(conn, "005930", "STOP", round(close * 0.99, 4))
    after = service.get_portfolio_view(conn)["open_risk"]
    assert after["unregistered_count"] == 0
    assert after["rows"][0]["stop_source"] == "rule"
    assert after["total_risk_krw"] < before["total_risk_krw"]


def test_portfolio_view_reports_overseas_capital_gains_tax(conn):
    """해외 실현이익은 5월에 22%를 따로 낸다 — 화면이 그 자리를 만들어야 한다."""
    service.refresh_all(conn)
    tax = service.get_portfolio_view(conn)["realized"]["overseas_tax"]
    assert tax["rate_pct"] == 22.0
    assert tax["deduction_krw"] == 2_500_000.0
    assert tax["year"] == datetime.now().year


def test_dashboard_reports_distance_to_stop_for_holdings(conn):
    """룰 알림은 손절선을 **뚫어야** 난다 — 그 전에 알 방법이 화면에 있어야 한다."""
    service.refresh_all(conn)
    db.set_meta(conn, "cash_krw", "10000000")
    db.insert_trade(conn, "005930", "BUY", 10, 100.0, "2026-01-05", fx_rate=1.0)
    row = next(r for r in service.get_dashboard(conn)["signals"] if r["symbol"] == "005930")
    assert row["stop_price"] is not None and row["stop_source"] == "atr"
    assert row["stop_distance_pct"] < 0        # 손절선은 현재가 아래
    # 손절선을 현재가 바로 아래로 등록하면 임박이 숫자로 드러난다
    close = float(db.load_prices(conn, "005930").iloc[-1]["close"])
    db.insert_rule(conn, "005930", "STOP", round(close * 0.99, 4))
    row = next(r for r in service.get_dashboard(conn)["signals"] if r["symbol"] == "005930")
    assert row["stop_source"] == "rule"
    assert -1.5 < row["stop_distance_pct"] < -0.5


def test_dashboard_has_no_stop_distance_for_unheld(conn):
    service.refresh_all(conn)
    row = next(r for r in service.get_dashboard(conn)["signals"] if r["symbol"] == "005930")
    assert row["is_holding"] is False and row["stop_distance_pct"] is None


def test_dashboard_reports_position_count_rule(conn):
    """비중 상한도 총 리스크도 통과하면서 종목 수만 두 배가 된 계좌는
    지금까지 아무 경고도 받지 못했다."""
    service.refresh_all(conn)
    db.set_meta(conn, "cash_krw", "10000000")
    db.insert_trade(conn, "005930", "BUY", 10, 100.0, "2026-01-05", fx_rate=1.0)
    db.insert_trade(conn, "AAPL", "BUY", 10, 100.0, "2026-01-05", fx_rate=1300.0)
    r = service.get_dashboard(conn)["position_rule"]
    assert (r["min"], r["max"]) == portfolio.DEFAULT_TARGET_POSITIONS
    assert r["count"] == 2 and r["status"] == "under"

    service.set_target_positions(conn, 1, 1)
    r = service.get_dashboard(conn)["position_rule"]
    assert r["status"] == "over" and r["excess"] == 1
    assert {c["symbol"] for c in r["trim_candidates"]} == {"005930", "AAPL"}


def test_target_positions_survive_a_restart(conn, tmp_path):
    service.set_target_positions(conn, 3, 6)
    assert service.get_target_positions(conn) == (3, 6)


def test_dashboard_lists_holdings_without_a_registered_stop(conn):
    """'룰 미등록'을 종목 옆에 적어두기만 하면 몇 개가 무방비인지 세어보지 않는다."""
    service.refresh_all(conn)
    db.set_meta(conn, "cash_krw", "10000000")
    db.insert_trade(conn, "005930", "BUY", 10, 100.0, "2026-01-05", fx_rate=1.0)
    db.insert_trade(conn, "AAPL", "BUY", 10, 100.0, "2026-01-05", fx_rate=1300.0)
    un = service.get_dashboard(conn)["unstopped"]
    assert {u["symbol"] for u in un} == {"005930", "AAPL"}
    # 등록 버튼이 쓸 값 — 화면이 이미 계산해 둔 2×ATR을 그대로 넘긴다
    assert all(u["atr_stop_price"] > 0 for u in un)

    db.insert_rule(conn, "005930", "STOP", 1.0)
    assert [u["symbol"] for u in service.get_dashboard(conn)["unstopped"]] == ["AAPL"]


def test_entry_review_carries_the_original_reason_and_grade(conn):
    """물타기 판단에 필요한 것은 평단 대비 %가 아니라 '왜 샀는지가 아직 유효한가'다."""
    service.refresh_all(conn)
    db.set_meta(conn, "cash_krw", "10000000")
    db.insert_trade(conn, "005930", "BUY", 10, 100.0, "2026-01-05", fx_rate=1.0,
                    note="20일선 돌파", grade_at_trade="강력매수")
    er = service.get_ticker_detail(conn, "005930")["entry_review"]
    assert er["first_entry_date"] == "2026-01-05"
    assert er["first_entry_price"] == 100.0
    assert er["entry_note"] == "20일선 돌파"
    assert er["entry_grade"] == "강력매수"
    assert er["buy_count"] == 1
    # 진입 시 강력매수였는데 지금 등급이 그보다 낮으면 논리가 약해진 것이다
    assert er["grade_downgraded"] is (er["current_grade"] != "강력매수")


def test_entry_review_says_the_reason_was_never_recorded(conn):
    """메모를 안 남긴 진입을 빈칸으로 두면 근거가 있었던 것처럼 읽힌다."""
    service.refresh_all(conn)
    db.set_meta(conn, "cash_krw", "10000000")
    db.insert_trade(conn, "005930", "BUY", 10, 100.0, "2026-01-05", fx_rate=1.0)
    er = service.get_ticker_detail(conn, "005930")["entry_review"]
    assert er["entry_note"] is None and er["entry_grade"] is None


def test_entry_review_is_absent_for_symbols_never_bought(conn):
    service.refresh_all(conn)
    assert service.get_ticker_detail(conn, "005930")["entry_review"] is None


def test_dashboard_ships_the_scale_behind_the_scores(conn):
    """스윙 -21과 중장기 +39는 눈금이 다른 자로 잰 값이다. 컷을 함께 내려보내지
    않으면 화면은 두 숫자를 같은 자로 그릴 수밖에 없다."""
    service.refresh_all(conn)
    scale = service.get_dashboard(conn)["score_scale"]
    assert scale["swing"]["buy"] == scoring.SWING_CUTS[1]
    assert scale["longterm"]["buy"] == scoring.LONGTERM_CUTS[1]
    assert scale["swing"]["buy"] != scale["longterm"]["buy"]  # 같은 자가 아니다
    for kind in ("swing", "longterm"):
        cuts = scale[kind]
        assert cuts["strong_sell"] < cuts["sell"] < cuts["buy"] < cuts["strong_buy"]


def test_risk_block_exposes_the_denominator_behind_its_own_percentages(conn):
    """물타기 프리뷰가 '체결 후 비중'을 내려면 분모(총자산)와 환율이 필요하다.
    프론트가 risk_budget_krw ÷ 0.01 같은 역산으로 분모를 되찾게 두면, 사이징
    규칙이 바뀌는 순간 화면의 비중만 조용히 틀린 값이 된다."""
    service.refresh_all(conn)
    db.set_meta(conn, "cash_krw", "10000000")
    r = service.get_ticker_detail(conn, "005930")["risk"]
    assert r["total_asset_krw"] == service.get_portfolio_view(conn)["totals"]["total_asset_krw"]
    assert r["fx_rate"] == 1.0
    assert service.get_ticker_detail(conn, "AAPL")["risk"]["fx_rate"] == 1300.0


def test_refresh_reports_company_failures_without_breaking_prices(conn):
    """회사 자료 소스가 전부 막힌 상태(conftest 기본)에서도 시세·시그널은 갱신되고,
    실패는 `failed_tickers`가 아니라 `failed_company`로 따로 보고된다 —
    사용자가 해야 할 일이 다르기 때문이다."""
    out = service.refresh_all(conn)
    assert out["refreshed"] is True
    assert out["failed_tickers"] == []
    assert set(out["failed_company"]) == {"005930", "AAPL"}
    assert db.get_latest_signal(conn, "005930") is not None


def test_detail_exposes_profile_and_snapshot(conn):
    service.refresh_all(conn)
    d = service.get_ticker_detail(conn, "005930")
    # 캐시가 비어 있으면 profile·snapshot 모두 pending 골격 (계약 v2 B1)
    assert d["profile"]["status"] == "pending"
    assert d["profile"]["note"]
    assert d["snapshot"]["status"] == "pending"
    assert d["snapshot"]["note"]
    assert d["fundamentals"] == {"per": 15.0}  # 기존 계약 유지


def test_cross_sectional_backtest_warns_about_a_thin_universe(conn, ohlcv_up):
    """18종목 유니버스에서 상위 20%는 3.6종목 — 수치 옆에 한계가 없으면 근거로 읽힌다."""
    for i in range(3):
        sym = f"00593{i}"
        db.upsert_ticker(conn, sym, "KR", f"종목{i}")
        db.save_prices(conn, sym, ohlcv_up)
    out = service.run_strategy_backtest(conn, "xs_momentum")
    # 부분 문자열("3" in ...)로 재면 문구에 다른 숫자가 들어와도 통과한다.
    # 실제 유니버스 크기와 임계값이 문구에 그대로 실렸는지를 본다.
    assert out["universe_size"] == 3
    assert out["xs_universe_warning"] == service._xs_universe_warning(
        "xs_momentum", 3)
    assert "유니버스가 3종목" in out["xs_universe_warning"]
    assert str(service.XS_MIN_UNIVERSE) in out["xs_universe_warning"]


def test_timeseries_backtest_has_no_thin_universe_warning(conn, ohlcv_up):
    """시계열 프리셋은 유니버스 크기와 무관하다 — 경고로 화면을 채우지 않는다."""
    db.upsert_ticker(conn, "005930", "KR", "삼성전자")
    db.save_prices(conn, "005930", ohlcv_up)
    out = service.run_strategy_backtest(conn, "abs_momentum")
    assert out["xs_universe_warning"] is None
