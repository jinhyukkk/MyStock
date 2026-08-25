import json
import os
import re
from datetime import datetime, timedelta

import requests

import pandas as pd

from app import (backtest, company, costs, db, engine, fetchers, indicators,
                 portfolio, scoring, sentiment, strategy, universe)

BACKTEST_DAYS = 1100  # 약 3년 — 한 국면짜리 400일 검증은 상승장 착시를 못 거른다


def _active_tickers(conn):
    """워치리스트에 있거나 현재 보유 중인 종목 (보유 종목 + 관심 종목)."""
    holdings = _holdings_map(conn)
    watch = {t["symbol"]: t for t in db.list_tickers(conn, watchlist_only=True)}
    for t in db.list_tickers(conn):
        if t["symbol"] in holdings:
            watch.setdefault(t["symbol"], t)
    return list(watch.values())


def refresh_all(conn, symbol: str | None = None, force_company: bool = False) -> dict:
    """symbol 지정 시 해당 종목만 갱신 — 종목 추가 직후 전체 갱신(수 초) 대신 사용.

    `force_company=True`는 사용자가 새로고침 버튼을 눌렀을 때만 준다. TTL을 무시하고
    회사 자료 6블록을 지금 받아온다(최대 10초). 기본값이 False인 이유는, 증권사 동기화가
    새로 편입된 종목마다 이 함수를 부르기 때문이다 — 거기서 강제 갱신이 걸리면
    잔고 한 번 맞추는 데 종목 수 × 6콜이 동기로 붙는다.
    """
    if symbol is None:
        senti = sentiment.fetch_sentiment()
        db.set_meta(conn, "sentiment", json.dumps(senti))
        targets = _active_tickers(conn)
    else:
        senti = get_sentiment_view(conn)  # 심리지표는 저장분 재사용
        t = db.get_ticker(conn, symbol)
        targets = [t] if t else []
    failed_tickers = []
    for t in targets:
        try:
            df = fetchers.fetch_ohlcv(t["symbol"], t["market"],
                                      yf_symbol=t["yf_symbol"], days=BACKTEST_DAYS)
            db.save_prices(conn, t["symbol"], df)
            _compute_and_store_signal(conn, t, senti)
            if t["yf_symbol"]:
                fund = fetchers.fetch_fundamentals(t["yf_symbol"])
                if fund:
                    db.set_meta(conn, f"fund:{t['symbol']}", json.dumps(fund))
        except Exception:
            failed_tickers.append(t["symbol"])
    if symbol is None:
        for market in {t["market"] for t in targets}:
            try:
                _refresh_benchmark(conn, market)
            except Exception:
                failed_tickers.append(f"BENCH:{market}")
    if symbol is None:  # 단일 갱신은 전체 기준 시각을 건드리지 않는다
        db.set_meta(conn, "last_refresh", datetime.now().isoformat(timespec="seconds"))
        bars = _latest_bars(conn, [t["symbol"] for t in targets])
        holdings = _holdings_map(conn)
        avg_prices = {s: h["avg_price"] for s, h in holdings.items()}
        _notify_telegram(conn, check_rules(conn, bars, avg_prices))
    # 회사 자료는 시세·시그널이 끝난 뒤에 받는다. 네이버·다음은 비공식 API라 언제든
    # 죽을 수 있는데, 그 실패가 시세 갱신이나 알림까지 끌고 내려가면 안 된다.
    failed_company = []
    try:
        held = set(_holdings_map(conn)) if symbol is None else set()
        failed_company = company.refresh_company_blocks(
            conn, targets, force=force_company, held=held)
    except Exception as e:
        failed_company = [f"ALL:{type(e).__name__}"]
    return {"refreshed": True, "failed_sources": senti.get("failed", []),
            "failed_tickers": failed_tickers,
            # 시세 실패(failed_tickers)와 섞지 않는다 — 회사 자료가 비는 것과
            # 시그널이 낡는 것은 사용자가 해야 할 일이 다르다
            "failed_company": failed_company}


def _is_partial_bar(df) -> bool:
    """마지막 봉이 오늘 것이면 아직 마감 전 — 그 봉으로 만든 등급은 종가에 뒤집힐 수 있다.

    KR/US/CRYPTO 모두 소스가 장중에 당일 미완성 봉을 돌려준다. 11시에 본 "매수"가
    15시 30분에 "중립"이 되면 사용자는 백테스트가 검증한 적 없는 신호로 주문한 것이다.
    """
    return df.index[-1].date() >= datetime.now().date()


def _compute_and_store_signal(conn, ticker_row, senti):
    df = db.load_prices(conn, ticker_row["symbol"])
    if df.empty:
        return
    enriched = indicators.compute_indicators(df)
    result = scoring.score_ticker(enriched)
    result["context_note"] = sentiment.context_note(
        result["swing_score"], ticker_row["market"], senti)
    result["bar_complete"] = not _is_partial_bar(df)
    date_str = df.index[-1].strftime("%Y-%m-%d")
    result["bar_date"] = date_str
    db.save_signal(conn, ticker_row["symbol"], date_str,
                   result["swing_score"], result["longterm_score"],
                   result["swing_grade"], json.dumps(result, ensure_ascii=False))


def _latest_bar(conn, symbol) -> dict | None:
    """최신 봉의 종가·전일 대비·고가·저가. 룰 판정에 고저가 필요 — 종가만 보면
    장중에 손절선을 관통했다가 회복한 날을 알림 0건으로 넘긴다."""
    df = db.load_prices(conn, symbol, limit=2)
    if df.empty:
        return None
    last = df.iloc[-1]
    change = None
    if len(df) >= 2:
        change = round((float(last["close"]) / float(df.iloc[-2]["close"]) - 1) * 100, 2)
    return {"close": float(last["close"]), "change_pct": change,
            "high": float(last["high"]), "low": float(last["low"])}


def _latest_close_and_change(conn, symbol):
    bar = _latest_bar(conn, symbol)
    return (bar["close"], bar["change_pct"]) if bar else (None, None)


def _latest_bars(conn, symbols) -> dict:
    bars = {}
    for s in symbols:
        bar = _latest_bar(conn, s)
        if bar is not None:
            bars[s] = bar
    return bars


def _tickers_map(conn):
    return {t["symbol"]: dict(t) for t in db.list_tickers(conn)}


def _holdings_map(conn):
    """평단은 수수료 포함 비용 기준 — tickers를 넘겨야 시장별 요율 추정이 붙는다.

    원장(trades)이 보유의 유일한 근거다. 화면·비중·리스크·포지션 사이징이
    모두 이 함수 하나에서 나온다.
    """
    trades = [dict(r) for r in db.list_trades(conn)]
    fx = get_sentiment_view(conn).get("usdkrw")
    return portfolio.compute_holdings(trades, _tickers_map(conn), fx)


def get_cash_krw(conn) -> float:
    raw = db.get_meta(conn, "cash_krw")
    return float(raw) if raw else 0.0


def get_cash_usd(conn) -> float:
    raw = db.get_meta(conn, "cash_usd")
    return float(raw) if raw else 0.0


def get_target_positions(conn) -> tuple[int, int]:
    """목표 보유 종목 수 (최소, 최대). 미설정이면 집중 투자 기본값."""
    lo = db.get_meta(conn, "target_positions_min")
    hi = db.get_meta(conn, "target_positions_max")
    default_lo, default_hi = portfolio.DEFAULT_TARGET_POSITIONS
    return (int(lo) if lo else default_lo, int(hi) if hi else default_hi)


def set_target_positions(conn, target_min: int, target_max: int) -> tuple[int, int]:
    db.set_meta(conn, "target_positions_min", str(int(target_min)))
    db.set_meta(conn, "target_positions_max", str(int(target_max)))
    return get_target_positions(conn)


def apply_trade_to_cash(conn, trade: dict, ticker_row, reverse: bool = False) -> dict:
    """체결 금액만큼 예수금을 증감한다 (매수 −, 매도 +). 삭제 시 reverse=True로 되돌린다.

    예수금이 수동 입력값에만 의존하면 매매를 반복할수록 총자산이 어긋나고,
    그 총자산이 1% 리스크 사이징의 분모라 사이즈까지 함께 틀어진다.
    입출금·배당처럼 매매가 아닌 변동은 예수금을 직접 수정해 반영하면 된다.
    """
    info = dict(ticker_row) if ticker_row is not None else {}
    fee, tax, _ = portfolio._trade_costs(trade, info)
    notional = trade["price"] * trade["quantity"]
    # 매수는 대금+비용이 나가고, 매도는 대금에서 비용을 뺀 만큼 들어온다
    delta = -(notional + fee + tax) if trade["side"] == "BUY" else (notional - fee - tax)
    if reverse:
        delta = -delta
    usd = info.get("currency") == "USD"
    key = "cash_usd" if usd else "cash_krw"
    current = get_cash_usd(conn) if usd else get_cash_krw(conn)
    # 예수금이 음수로 내려가는 것은 막는다 — 과거 매매를 뒤늦게 입력하는 흔한 경우다
    updated = max(current + delta, 0.0)
    db.set_meta(conn, key, str(updated))
    return {"currency": "USD" if usd else "KRW", "delta": round(delta, 4),
            "applied": round(updated - current, 4),
            "cash_krw": get_cash_krw(conn), "cash_usd": get_cash_usd(conn),
            "clamped": abs((updated - current) - delta) > 1e-9}


def _cost_basis_krw(holdings: dict, tickers: dict, usdkrw) -> dict:
    """보유 종목의 현재 원가(원화) — 배당수익률의 분모."""
    fx = usdkrw or portfolio.DEFAULT_USDKRW
    out = {}
    for s, h in holdings.items():
        rate = fx if tickers.get(s, {}).get("currency") == "USD" else 1.0
        out[s] = h["avg_price"] * h["quantity"] * rate
    return out


def apply_flow_to_cash(conn, flow: dict, reverse: bool = False) -> dict:
    """현금흐름을 예수금에 반영한다.

    배당을 원장에만 적고 예수금에 넣지 않으면 총자산이 실제보다 작아지고,
    그 총자산을 분모로 쓰는 1% 리스크 사이징이 계속 작은 수량을 제시한다.
    반대로 예수금을 손으로도 올리면 배당이 두 번 계상된다 — 한쪽만 진실이어야 한다.
    """
    amount, tax = float(flow.get("amount") or 0.0), float(flow.get("tax") or 0.0)
    ftype = flow.get("flow_type")
    # 배당·이자는 원천징수 후 들어온 순액만 계좌에 찍힌다
    delta = -amount if ftype == "WITHDRAW" else (amount - tax)
    if reverse:
        delta = -delta
    usd = (flow.get("currency") or "KRW") == "USD"
    key = "cash_usd" if usd else "cash_krw"
    current = get_cash_usd(conn) if usd else get_cash_krw(conn)
    updated = max(current + delta, 0.0)
    db.set_meta(conn, key, str(updated))
    return {"currency": "USD" if usd else "KRW", "delta": round(delta, 4),
            "applied": round(updated - current, 4),
            "cash_krw": get_cash_krw(conn), "cash_usd": get_cash_usd(conn),
            "clamped": abs((updated - current) - delta) > 1e-9}


STOP_DISCLAIMER = "이 손절가는 자동 예약주문이 아니며 일봉 기준으로만 감시됩니다"


def _fmt_price(v: float) -> str:
    """가격대에 맞는 자릿수 — 고정 소수 0자리는 USD 종목(150.4→"150")과
    저가 알트코인(0.8→"1")에서 어떤 가격인지 알 수 없게 만든다."""
    a = abs(v)
    if a >= 1000:
        return f"{v:,.0f}"
    if a >= 1:
        return f"{v:,.2f}"
    return f"{v:,.4f}"


def check_rules(conn, bars: dict, avg_prices: dict) -> list:
    """룰 도달 판정. 목표가·손절가는 **일중 고저가**로 터치 여부를 본다.

    종가만 보면 장중 -9%까지 밀렸다가 -3%로 마감한 날이 알림 0건이 된다.
    사용자는 손절선이 지켜졌다고 믿지만 실제로는 관통 후 회복이었다.
    """
    alerts = []
    for r in db.list_rules(conn):
        symbol = r["symbol"]
        bar = bars.get(symbol)
        if bar is None:
            continue
        close, v = bar["close"], r["value"]
        t = db.get_ticker(conn, symbol)
        name = t["name"] if t else symbol
        if r["rule_type"] == "TARGET" and bar["high"] >= v:
            intraday = close < v
            msg = (f"{name} 목표가 {_fmt_price(v)} 장중 터치 "
                   f"(고가 {_fmt_price(bar['high'])}, 종가 {_fmt_price(close)}로 되밀림)"
                   if intraday
                   else f"{name} 목표가 {_fmt_price(v)} 도달 (현재 {_fmt_price(close)})")
            alerts.append({"symbol": symbol, "name": name, "rule_type": "TARGET",
                           "value": v, "intraday_only": intraday, "message": msg})
        elif r["rule_type"] == "STOP" and bar["low"] <= v:
            intraday = close > v
            msg = (f"{name} 손절가 {_fmt_price(v)} 장중 이탈 "
                   f"(저가 {_fmt_price(bar['low'])}, 종가 {_fmt_price(close)}로 회복)"
                   if intraday
                   else f"{name} 손절가 {_fmt_price(v)} 이탈 (현재 {_fmt_price(close)})")
            alerts.append({"symbol": symbol, "name": name, "rule_type": "STOP",
                           "value": v, "intraday_only": intraday, "message": msg})
        elif r["rule_type"] == "AVG_PCT":
            avg = avg_prices.get(symbol)
            if not avg:
                continue
            change = (close / avg - 1) * 100
            if (v > 0 and change >= v) or (v < 0 and change <= v):
                alerts.append({"symbol": symbol, "name": name, "rule_type": "AVG_PCT",
                               "value": v, "intraday_only": False,
                               "message": f"{name} 평단 대비 {change:+.1f}% (조건 {v:+.0f}%)"})
    return alerts


NOTIFY_TOKEN = "telegram_bot_token"
NOTIFY_CHAT = "telegram_chat_id"


def notify_creds(conn) -> tuple[str, str]:
    """화면 설정이 우선, 미설정(None)이면 .env. 화면에서 비운 값("")은 '해제'라
    .env 값이 되살아나지 않는다 — 껐는데 계속 오는 알림은 신뢰를 잃는다."""
    token = db.get_meta(conn, NOTIFY_TOKEN)
    chat_id = db.get_meta(conn, NOTIFY_CHAT)
    return (os.getenv("TELEGRAM_BOT_TOKEN", "") if token is None else token,
            os.getenv("TELEGRAM_CHAT_ID", "") if chat_id is None else chat_id)


def notify_status(conn) -> dict:
    """토큰은 돌려주지 않는다 — 설정 화면에 봇 토큰 평문을 다시 그리지 않는다."""
    token, chat_id = notify_creds(conn)
    from_env = db.get_meta(conn, NOTIFY_TOKEN) is None and bool(os.getenv("TELEGRAM_BOT_TOKEN"))
    return {"enabled": bool(token and chat_id), "token_set": bool(token),
            "chat_id": chat_id, "source": "env" if from_env else "설정"}


def set_notify(conn, token: str | None, chat_id: str | None) -> dict:
    """None = 변경 없음, "" = 해제. 토큰을 매번 다시 입력하게 하면 설정을 안 건드리게 된다."""
    if token is not None:
        db.set_meta(conn, NOTIFY_TOKEN, token.strip())
    if chat_id is not None:
        db.set_meta(conn, NOTIFY_CHAT, chat_id.strip())
    return notify_status(conn)


def send_telegram(token: str, chat_id: str, text: str) -> None:
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat_id, "text": text}, timeout=10)
    # 텔레그램은 실패 사유를 본문에 준다 — 상태코드만 올리면 화면에서 원인을 못 본다
    if not r.ok:
        raise RuntimeError(r.json().get("description") if r.headers.get(
            "content-type", "").startswith("application/json") else r.text)


def notify_test(conn) -> dict:
    """설정이 실제로 도달하는지 지금 확인한다 — 룰이 걸릴 때까지 기다려서
    알아채면, 그동안 울리지 않은 알림이 몇 건인지 알 방법이 없다."""
    token, chat_id = notify_creds(conn)
    if not token or not chat_id:
        raise ValueError("봇 토큰과 채팅 ID를 모두 입력하세요")
    send_telegram(token, chat_id, "[MyStock] 알림 테스트 — 이 메시지가 보이면 설정이 정상입니다.")
    return {"sent": True}


def _notify_telegram(conn, alerts: list) -> None:
    """룰 도달 알림을 텔레그램으로 발송. 같은 룰은 하루 한 번만 (중복 방지)."""
    token, chat_id = notify_creds(conn)
    if not token or not chat_id or not alerts:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    for a in alerts:
        key = f"tg_sent:{a['symbol']}:{a['rule_type']}:{a['value']}"
        if db.get_meta(conn, key) == today:
            continue
        text = f"[MyStock] {a['message']}"
        if a["rule_type"] == "STOP":
            text += f"\n※ {STOP_DISCLAIMER}"
        try:
            send_telegram(token, chat_id, text)
            db.set_meta(conn, key, today)
        except Exception:
            pass  # 발송 실패는 다음 갱신 때 재시도


def get_sentiment_view(conn) -> dict:
    raw = db.get_meta(conn, "sentiment")
    senti = json.loads(raw) if raw else {"vix": None, "vkospi": None,
                                         "cnn_fg": None, "crypto_fg": None,
                                         "usdkrw": None, "failed": []}
    senti["cnn_fg_label"] = sentiment.fg_label(senti.get("cnn_fg"))
    senti["crypto_fg_label"] = sentiment.fg_label(senti.get("crypto_fg"))
    return senti


def summary_tags(details: dict) -> list[dict]:
    """저장된 indicator_scores에서 상위 3개 근거를 짧은 태그로 가공.
    reason 형식 "지표값 — 해석 (부연)" 에서 해석만 남긴다."""
    tags = []
    for it in sorted(details.get("indicator_scores", []),
                     key=lambda x: -abs(x["score"])):
        if it["score"] == 0 or len(tags) >= 3:
            continue
        base, *warn = it["reason"].split(" ⚠ ")
        if " — " in base:
            tail = base.split(" — ", 1)[1]
            # 해석문이 지표명으로 시작하면 접두어 생략 ("장기 추세: 장기 상승 추세" 방지)
            base = tail if it["name"].split()[0] in tail else f"{it['name']}: {tail}"
        base = re.sub(r"\s*\([^)]*\)$", "", base)
        tags.append({"label": base, "score": it["score"], "warn": bool(warn)})
    return tags


def grade_change_dir(prev: str | None, cur: str) -> int:
    """등급 변화의 방향 (+1 상향 / -1 하향 / 0 변화 없음).

    "등급변경"을 불리언으로만 내려보내면 화면이 색을 고를 수 없어 강등에도
    상승색 배지가 붙는다. 나쁜 소식이 좋은 소식으로 읽히는 건 배지의 실패다.
    강력매도→매도처럼 강도가 누그러진 것도 상향으로 본다.
    """
    order = backtest.GRADE_ORDER[::-1]  # 강력매도 … 강력매수 (낮을수록 약세)
    if prev is None or prev == cur or prev not in order or cur not in order:
        return 0
    return 1 if order.index(cur) > order.index(prev) else -1


def _signal_sort_key(s: dict):
    """보유 종목 우선, 그다음 관심 종목은 매수 신호 순.

    보유가 먼저인 이유: 장중 가장 먼저 확인해야 할 것은 "내가 들고 있는 것 중
    매도 신호"다. 워치리스트가 길면 점수순 정렬만으로는 보유가 스크롤 아래로 밀린다.
    보유 구간은 절대값 정렬을 유지한다 — 강한 매도도 똑같이 급한 소식이다.

    관심 종목 구간은 점수 내림차순이다. 절대값으로 정렬하면 살 수도 없고 팔
    수도 없는 강력매도 종목이 강력매수와 같은 높이로 올라온다.
    """
    if s["is_holding"]:
        return (0, -abs(s["swing_score"]))
    return (1, -s["swing_score"])


def get_dashboard(conn) -> dict:
    senti = get_sentiment_view(conn)
    holdings = _holdings_map(conn)
    active = _active_tickers(conn)
    bars = _latest_bars(conn, [t["symbol"] for t in active])
    prices, signals = {s: b["close"] for s, b in bars.items()}, []
    # 룰 알림은 손절선을 **뚫어야** 난다. 그 전에 알 방법이 없으면 -4.7%인 종목을
    # 그냥 지나쳤다가 다음 날 갭 하락을 맞는다 — 남은 거리를 미리 실어 보낸다.
    stops = _holding_stops(conn, holdings, prices)
    for t in active:
        bar = bars.get(t["symbol"])
        close = bar["close"] if bar else None
        change = bar["change_pct"] if bar else None
        sig = db.get_latest_signal(conn, t["symbol"])
        if not sig:
            continue
        details = json.loads(sig["details"]) if sig["details"] else {}
        prev_grade = db.get_prev_grade(conn, t["symbol"])
        # 보유 종목은 평단 대비 위치를 함께 실어 보낸다 — 시그널만으로는
        # "물려 있는데 매도 신호"인지 "수익 중인데 매도 신호"인지 판단할 수 없다.
        held = holdings.get(t["symbol"])
        avg_price = held["avg_price"] if held else None
        signals.append({
            "symbol": t["symbol"], "name": t["name"], "market": t["market"],
            "currency": t["currency"], "close": close, "change_pct": change,
            "swing_score": sig["swing_score"], "swing_grade": sig["grade"],
            "longterm_score": sig["longterm_score"],
            "longterm_grade": scoring.grade(sig["longterm_score"], "longterm"),
            "grade_changed": prev_grade is not None and prev_grade != sig["grade"],
            "grade_change_dir": grade_change_dir(prev_grade, sig["grade"]),
            "prev_grade": prev_grade,
            "is_holding": held is not None,
            "in_watchlist": bool(t["in_watchlist"]),
            "avg_price": avg_price,
            "holding_pnl_pct": (round((close / avg_price - 1) * 100, 2)
                                if avg_price and close else None),
            "stop_price": stops.get(t["symbol"], (None, None))[0],
            "stop_source": stops.get(t["symbol"], (None, None))[1],
            "stop_distance_pct": (
                round((stops[t["symbol"]][0] / close - 1) * 100, 2)
                if close and t["symbol"] in stops else None),
            "context_note": details.get("context_note"),
            "summary": details.get("summary"),
            "summary_tags": summary_tags(details),
            # 장중 미완성 봉으로 계산된 등급은 마감 때 뒤집힐 수 있다 (백테스트 미검증 신호)
            "bar_complete": details.get("bar_complete", True),
            "bar_date": details.get("bar_date", sig["date"]),
        })
    signals.sort(key=_signal_sort_key)
    tickers_map = {t["symbol"]: dict(t) for t in active}
    pf = portfolio.build_portfolio(holdings, prices, tickers_map, senti.get("usdkrw"),
                                   cash_krw=get_cash_krw(conn), cash_usd=get_cash_usd(conn))
    avg_prices = {s: h["avg_price"] for s, h in holdings.items()}
    # 종목 수 룰은 비중·리스크 한도를 모두 통과하는 계좌에서도 깨진다 —
    # 추적할 수 있는 개수를 넘기면 손절 규율이 비중과 무관하게 무너진다.
    swing = {s["symbol"]: s["swing_score"] for s in signals}
    lo, hi = get_target_positions(conn)
    pos_rule = portfolio.position_rule(
        [{"symbol": r["symbol"], "name": r["name"], "weight_pct": r["weight_pct"],
          "swing_score": swing.get(r["symbol"])} for r in pf["holdings"]], lo, hi)
    return {
        "sentiment": senti,
        "portfolio_summary": {**pf["totals"], "holdings_count": len(holdings)},
        "position_rule": pos_rule,
        # 점수만 던지면 -21이 얼마나 나쁜지 화면에 눈금이 없다. 게다가 스윙과
        # 중장기는 컷이 서로 달라(+11 vs +36) 같은 자로 읽으면 반드시 오독된다.
        "score_scale": {k: dict(zip(("strong_buy", "buy", "sell", "strong_sell"), cuts))
                        for k, cuts in (("swing", scoring.SWING_CUTS),
                                        ("longterm", scoring.LONGTERM_CUTS))},
        # 룰을 등록하지 않은 보유는 알림이 울리지 않는다. 종목 옆의 '룰 미등록'
        # 표기만으로는 몇 개가 무방비인지 세어보게 되지 않는다.
        "unstopped": [{"symbol": s, "name": tickers_map.get(s, {}).get("name", s),
                       "atr_stop_price": price}
                      for s, (price, src) in stops.items() if src == "atr"],
        "signals": signals,
        "rule_alerts": check_rules(conn, bars, avg_prices),
        "last_refresh": db.get_meta(conn, "last_refresh"),
        "failed_sources": senti.get("failed", []),
    }


def _holding_stops(conn, holdings: dict, prices: dict) -> dict:
    """보유 종목의 유효 손절선 {symbol: (가격, 'rule'|'atr')}.

    등록된 룰이 있으면 그것 — 알림을 울리는 값과 화면의 값이 갈라지면 안 된다.
    """
    out = {}
    for s in holdings:
        rule = _stop_rule(conn, s)
        if rule is not None:
            out[s] = (round(rule, 4), "rule")
            continue
        close = prices.get(s)
        df = db.load_prices(conn, s, limit=250)
        if close is None or df.empty:
            continue
        atr = indicators.compute_indicators(df)["atr14"].iloc[-1]
        if pd.notna(atr) and atr:
            out[s] = (round(close - 2 * float(atr), 4), "atr")
    return out


def get_portfolio_view(conn) -> dict:
    holdings = _holdings_map(conn)
    prices = {}
    for s in holdings:
        close, _ = _latest_close_and_change(conn, s)
        if close is not None:
            prices[s] = close
    tickers_map = {t["symbol"]: dict(t) for t in db.list_tickers(conn)}
    fx = get_sentiment_view(conn).get("usdkrw")
    flows = [dict(r) for r in db.list_cash_flows(conn)]
    trades = [dict(r) for r in db.list_trades(conn)]
    year = datetime.now().year
    div = portfolio.dividend_view(
        flows, tickers_map, fx, year=year,
        cost_krw=_cost_basis_krw(holdings, tickers_map, fx),
        traded_this_year={t["symbol"] for t in trades
                          if str(t.get("trade_date", "")).startswith(str(year))})
    pf = portfolio.build_portfolio(holdings, prices, tickers_map, fx,
                                   cash_krw=get_cash_krw(conn), cash_usd=get_cash_usd(conn),
                                   dividends={r["symbol"]: r["net_krw"]
                                              for r in div["by_symbol"]})
    pf["dividends"] = div
    realized = portfolio.realized_pnl(trades, tickers_map, fx)
    # 해외 양도세는 5월에 따로 낸다 — 실현손익만 보고 그 돈까지 쓸 수 있다고 믿게 된다
    pf["realized"] = {"entries": realized[::-1][:50],
                      "stats": portfolio.realized_stats(realized, tickers_map, fx),
                      "overseas_tax": portfolio.overseas_tax_view(
                          realized, tickers_map, year=year)}
    price_frames = {s: db.load_prices(conn, s, limit=250) for s in holdings}
    closes = {s: f["close"] for s, f in price_frames.items()}
    # 계좌 리스크는 환율 고정 근사 — 달러 예수금도 현재 환율로 환산해 고정 현금으로 합산
    fx_now = fx or portfolio.DEFAULT_USDKRW
    pf["risk"] = portfolio.account_risk(
        holdings, closes, tickers_map, fx,
        cash_krw=get_cash_krw(conn) + get_cash_usd(conn) * fx_now)
    # 종목별 1% 룰은 합산해서 봐야 의미가 있다 — 5종목이면 총 몇 %인지 화면에 띄운다
    pf["open_risk"] = portfolio.open_risk(
        holdings, _atr_map(price_frames), tickers_map, fx,
        pf["totals"]["total_asset_krw"], prices=prices,
        stops={s: v for s in holdings if (v := _stop_rule(conn, s)) is not None})
    # 이 숫자들이 언제 기준인지 화면이 알 수 있어야 한다
    pf["last_refresh"] = db.get_meta(conn, "last_refresh")
    return pf


def _atr_map(price_frames: dict) -> dict:
    """보유 종목의 최신 ATR(14) — 계좌 총 미결 리스크 합산의 입력."""
    out = {}
    for s, df in price_frames.items():
        if df.empty:
            continue
        atr = indicators.compute_indicators(df)["atr14"].iloc[-1]
        if pd.notna(atr) and atr:
            out[s] = float(atr)
    return out


MAX_WEIGHT = 0.20  # 한 종목이 총자산에서 차지할 수 있는 상한
TARGET_R = 2.0     # 목표가 = 손절 폭의 몇 배 (손익비 2:1)
# 2×ATR 손절이 주가의 이 비율을 넘으면 스윙 타임프레임에 안 맞는다. 화면이 -21%
# 손절을 제시하면 실제로 그걸 지키는 사람은 없고, 결국 손절 없는 매매가 된다.
MAX_STOP_PCT = 15.0
# 등록된 룰과 오늘의 2×ATR 제안이 현재가의 이 비율 이상 벌어지면 룰 갱신을 권한다
STOP_DRIFT_PCT = 2.0


def _stop_rule(conn, symbol: str) -> float | None:
    """등록된 STOP 룰 가격. 여러 건이면 가장 타이트한(높은) 값 — 먼저 닿는 쪽이
    실제로 포지션을 끝내므로, 그것이 사용자가 감수하는 리스크다."""
    if not symbol:
        return None
    vals = [float(r["value"]) for r in db.list_rules(conn, symbol)
            if r["rule_type"] == "STOP"]
    return max(vals) if vals else None


def _target_block(enriched: pd.DataFrame, close: float, atr: float, stop: float) -> dict:
    """목표가와 손익비.

    손절가만 있고 목표가가 없으면 진입 판단의 절반이 비어 있다 — 손익비를 모른 채
    "승률 55%"만 보고 사이즈를 정하게 된다. 두 가지를 함께 낸다:

    - **R배수 목표가**: 손절 폭(2×ATR)의 TARGET_R배. 손익비를 먼저 정하는 방식.
    - **직전 고점(60일)**: 위에 놓인 실제 매물대. R배수 목표가가 이보다 위면
      도달 전에 저항을 만난다는 뜻이므로 그 사실을 알린다.
    """
    risk = close - stop
    target = close + risk * TARGET_R
    highs = enriched["high"].tail(60)
    resistance = float(highs.max()) if len(highs) else None
    # 이미 60일 신고가 위면 저항이 없다 — 참고치로 쓸 수 없다
    if resistance is not None and resistance <= close:
        resistance = None
    return {
        "target_price": round(target, 4),
        "target_pct": round((target / close - 1) * 100, 2),
        "target_r": TARGET_R,
        "reward_risk": round((target - close) / risk, 2) if risk else None,
        "resistance_60d": round(resistance, 4) if resistance else None,
        "resistance_pct": round((resistance / close - 1) * 100, 2) if resistance else None,
        # 목표가가 직전 고점 위면 그 구간을 뚫어야 도달한다
        "target_above_resistance": bool(resistance and target > resistance),
        "resistance_reward_risk": (round((resistance - close) / risk, 2)
                                   if resistance and risk else None),
    }


def _risk_block(conn, enriched: pd.DataFrame, currency: str,
                symbol: str | None = None) -> dict | None:
    """ATR 기반 손절 제안 + 계좌 1% 리스크 포지션 사이징 + 종목 MDD.

    1% 룰 수량은 저변동성 종목에서 무한히 커진다(2×ATR이 주가의 0.6%면 노셔널이
    총자산의 167%). 그래서 총자산 대비 노셔널 상한을 함께 걸고, 이미 보유한
    수량을 뺀 '추가 매수 가능 수량'까지 계산해서 내려보낸다.
    """
    last = enriched.iloc[-1]
    atr = last.get("atr14")
    if atr is None or pd.isna(atr) or not atr:
        return None
    close = float(last["close"])
    atr = float(atr)
    atr_stop = close - 2 * atr
    # 알림을 울리는 것은 등록된 STOP 룰뿐이다(check_rules). 화면·사이징·계좌
    # 리스크가 매일 재계산되는 2×ATR을 쓰면, 룰을 등록한 다음 날부터 사용자가
    # 보는 손절선과 실제로 울릴 손절선이 갈라진다. 등록 룰이 단일 진실이고
    # 2×ATR은 '오늘의 제안'으로 함께 남는다.
    rule_stop = _stop_rule(conn, symbol)
    use_rule = rule_stop is not None and 0 < rule_stop < close
    stop = rule_stop if use_rule else atr_stop
    senti = get_sentiment_view(conn)
    fx = (senti.get("usdkrw") or portfolio.DEFAULT_USDKRW) if currency == "USD" else 1.0
    # 리스크 분모는 총자산(평가액+예수금) — 보유 평가액만 쓰면 현금 비중만큼 과소/과대 계상
    pf = get_portfolio_view(conn)
    total = pf["totals"]["total_asset_krw"]
    risk_krw = total * 0.01
    out = {
        "atr": round(atr, 4),
        "atr_pct": round(atr / close * 100, 2),
        "stop_price": round(stop, 4),
        "stop_pct": round((stop / close - 1) * 100, 2),
        "stop_source": "rule" if use_rule else "atr",
        "atr_stop_price": round(atr_stop, 4),
        "atr_stop_pct": round((atr_stop / close - 1) * 100, 2),
        # 등록해 둔 룰과 오늘의 제안이 벌어지면 룰이 서서히 무의미해진다
        "stop_drift_pct": round((atr_stop - stop) / close * 100, 2) if use_rule else None,
        "stop_drift": bool(use_rule and abs(atr_stop - stop) / close * 100 > STOP_DRIFT_PCT),
        "mdd_pct": round(indicators.max_drawdown_pct(enriched["close"]), 2),
        **_target_block(enriched, close, atr, stop),
        "max_weight_pct": round(MAX_WEIGHT * 100, 1),
        # 화면이 '체결 후 비중'을 낼 때 쓸 분모와 환율. 프론트가 다른 값에서
        # 역산하게 두면 사이징 규칙이 바뀌는 순간 비중만 조용히 틀려진다.
        "total_asset_krw": total,
        "fx_rate": round(fx, 4),
        "account_open_risk": pf.get("open_risk"),
        "position_size_1pct": None, "risk_budget_krw": None,
        "position_size_capped": False, "cap_reason": None,
        "position_notional_krw": None, "held_quantity": None, "addable_quantity": None,
        "exit_plan": None,
        # 손절폭이 이 타임프레임에 맞는가 — 안 맞으면 손절 자체가 지켜지지 않는다
        "stop_too_wide": abs((stop / close - 1) * 100) > MAX_STOP_PCT,
        "max_stop_pct": MAX_STOP_PCT,
        "lot_size": None, "position_size_raw": None,
        "turnover_krw": None, "liquidity_pct": None,
    }
    held = next((h["quantity"] for h in pf["holdings"] if h["symbol"] == symbol), 0.0)
    avg = next((h["avg_price"] for h in pf["holdings"] if h["symbol"] == symbol), 0.0)
    # 평단에 보정 로트가 섞였으면 평단·R·손절선·확정손익이 전부 그 위에 서 있다
    out["basis_adjusted"] = next((bool(h.get("basis_adjusted"))
                                  for h in pf["holdings"] if h["symbol"] == symbol), False)
    # 보유 중이면 나가는 쪽 숫자를 함께 낸다 — 진입 정보만 있으면 매도 등급이 뜬
    # 종목에서도 화면이 '추가 매수 가능 수량'만 보여주게 된다
    t = db.get_ticker(conn, symbol) if symbol else None
    if held > 0:
        market_ = t["market"] if t else ""
        out["exit_plan"] = portfolio.exit_plan(
            held, avg, close, stop,
            market=market_, is_etf=(t["is_etf"] if t else 0) or 0, fx=fx,
            # 해외 포지션의 확정손익에는 이듬해 5월 양도세가 남아 있다
            taxable_overseas=costs.taxable_overseas(market_),
            deduction_left_krw=(pf.get("realized", {}).get("overseas_tax", {})
                                .get("deduction_left_krw") or 0.0))
    if total <= 0:
        return out
    # 사이징 분모도 실제로 지킬 손절선까지의 거리 — 룰이 2×ATR보다 타이트하면
    # 같은 1% 리스크로 더 살 수 있고, 헐거우면 덜 사야 한다
    risk_qty = risk_krw / ((close - stop) * fx)
    cap_qty = total * MAX_WEIGHT / (close * fx)
    raw = min(risk_qty, cap_qty)
    # 주문 가능한 단위로 내린다 — 국내주식에 5.095주를 제시하면 사용자가 매번
    # 스스로 잘라야 하고, 그 과정에서 계산해 둔 리스크 한도가 흐려진다
    market = t["market"] if t else ""
    size = costs.round_to_lot(raw, market)
    notional = size * close * fx
    # 일평균 거래대금 대비 주문 크기 — 중소형주에서는 이게 체결가를 밀어버린다
    recent = enriched.tail(20)
    turnover = float((recent["close"] * recent["volume"]).median()) * fx if len(recent) else 0.0
    out.update({
        "position_size_1pct": round(size, 8),
        "position_size_raw": round(raw, 4),
        "lot_size": costs.lot_size(market),
        "risk_budget_krw": round(risk_krw, 0),
        "position_size_capped": cap_qty < risk_qty,
        "cap_reason": (f"1% 룰 수량 {risk_qty:,.2f}주는 총자산의 "
                       f"{risk_qty * close * fx / total * 100:.0f}% — "
                       f"종목 상한 {MAX_WEIGHT * 100:.0f}%로 잘랐습니다"
                       if cap_qty < risk_qty else None),
        "position_notional_krw": round(notional, 0),
        "held_quantity": round(held, 4),
        "addable_quantity": round(costs.round_to_lot(max(size - held, 0.0), market), 8),
        "turnover_krw": round(turnover, 0),
        "liquidity_pct": round(notional / turnover * 100, 2) if turnover else None,
    })
    return out


def _refresh_benchmark(conn, market):
    bench_symbol, _ = fetchers.BENCHMARKS[market]
    bdf = fetchers.fetch_ohlcv(bench_symbol, market, yf_symbol=bench_symbol,
                               days=BACKTEST_DAYS)
    db.save_prices(conn, f"BENCH:{market}", bdf)


def _backtest_cost_pct(conn, symbol, ticker_row, df) -> float:
    """이 종목의 왕복 비용(%p) — 시장별 수수료·세금 + 유동성 기반 스프레드.

    시장 무관 0.3%p는 업비트(과대)와 국내 소형주(과소) 양쪽에서 틀린다.
    """
    if ticker_row is None:
        return backtest.COST_PCT
    turnover = None
    if not df.empty:
        recent = df.tail(60)
        turnover = float((recent["close"] * recent["volume"]).median())
        if ticker_row["currency"] == "USD":
            turnover *= get_sentiment_view(conn).get("usdkrw") or portfolio.DEFAULT_USDKRW
    return costs.backtest_cost_pct(ticker_row["market"], ticker_row["is_etf"], turnover)


def get_backtest(conn, symbol) -> dict | None:
    df = db.load_prices(conn, symbol, limit=BACKTEST_DAYS)
    if df.empty:
        return None
    last_date = df.index[-1].strftime("%Y-%m-%d")
    cached = db.get_meta(conn, f"backtest:{symbol}")
    if cached:
        obj = json.loads(cached)
        if obj.get("end") == last_date and obj.get("version") == backtest.VERSION:
            return obj
    t = db.get_ticker(conn, symbol)
    bench, bench_label = None, None
    if t and t["market"] in fetchers.BENCHMARKS:
        bench_label = fetchers.BENCHMARKS[t["market"]][1]
        bdf = db.load_prices(conn, f"BENCH:{t['market']}", limit=BACKTEST_DAYS)
        # 미수집이거나 종목 데이터보다 짧으면(초과수익 구간 불일치) 1회 재수집
        if bdf.empty or bdf.index[0] > df.index[0]:
            try:
                _refresh_benchmark(conn, t["market"])
                bdf = db.load_prices(conn, f"BENCH:{t['market']}", limit=BACKTEST_DAYS)
            except Exception:
                pass
        # 종목 진입가가 익일 시가이므로 벤치마크도 시가 기준으로 맞춘다
        bench = bdf[["open", "close"]] if not bdf.empty else None
    result = backtest.backtest_ticker(df, bench=bench, bench_label=bench_label,
                                      cost_pct=_backtest_cost_pct(conn, symbol, t, df))
    if result:
        db.set_meta(conn, f"backtest:{symbol}", json.dumps(result, ensure_ascii=False))
    return result


def get_ticker_detail(conn, symbol) -> dict | None:
    t = db.get_ticker(conn, symbol)
    if not t:
        return None
    df = db.load_prices(conn, symbol)
    candles = []
    risk = None
    if not df.empty:
        full = indicators.compute_indicators(df)
        risk = _risk_block(conn, full, t["currency"], symbol)
        enriched = full.tail(200)
        enriched = enriched.astype(object).where(pd.notna(enriched), None)
        for idx, row in enriched.iterrows():
            candles.append({"date": idx.strftime("%Y-%m-%d"), **{
                k: (round(row[k], 4) if row[k] is not None else None)
                for k in ["open", "high", "low", "close", "volume", "sma20", "sma60",
                          "sma120", "bb_upper", "bb_lower", "rsi", "macd",
                          "macd_signal", "macd_hist"]}})
    sig = db.get_latest_signal(conn, symbol)
    signal = json.loads(sig["details"]) if sig and sig["details"] else None
    fund_raw = db.get_meta(conn, f"fund:{symbol}")
    return {
        "symbol": symbol, "name": t["name"], "market": t["market"],
        "currency": t["currency"], "is_etf": t["is_etf"],
        "fundamentals": json.loads(fund_raw) if fund_raw else None,
        "signal": signal, "candles": candles, "risk": risk,
        "last_refresh": db.get_meta(conn, "last_refresh"),
        # 주문 프리뷰가 체결 비용을 추정하는 근거 — 화면과 원장이 같은 요율을 쓰게 한다
        "cost_rates": {
            "fee_pct": round(costs.fee_rate(t["market"]) * 100, 6),
            "sell_tax_pct": round(costs.sell_tax_rate(t["market"], t["is_etf"] or 0) * 100, 6),
        },
        # 주문 프리뷰가 '체결 후 잔액'을 낼 근거 — 예수금 초과를 사후 경고가 아니라
        # 기록 버튼을 누르기 전에 알 수 있어야 한다
        "cash": {"krw": get_cash_krw(conn), "usd": get_cash_usd(conn)},
        # 이 종목이 준 현금. 주가 손익만 보면 배당주는 늘 실패한 포지션으로 읽힌다.
        "dividends": portfolio.dividend_view(
            [dict(r) for r in db.list_cash_flows(conn, symbol=symbol)],
            {symbol: dict(t)}, get_sentiment_view(conn).get("usdkrw"),
            year=datetime.now().year),
        "history": [{"date": r["date"], "swing_score": r["swing_score"],
                     "longterm_score": r["longterm_score"], "grade": r["grade"]}
                    for r in db.load_signal_history(conn, symbol)],
        "rules": [dict(r) for r in db.list_rules(conn, symbol)],
        # 물타기 직전에 필요한 것은 평단 대비 %가 아니라 "왜 샀는지가 아직 유효한가"다
        "entry_review": _entry_review(conn, symbol, sig),
        # 회사 자료는 캐시(company_cache)만 읽는다. 여기서 외부를 부르면 yfinance
        # info 1~3초가 종목상세 첫 페인트에 그대로 얹힌다.
        "profile": company.get_profile(conn, symbol),
        "snapshot": company.get_snapshot(conn, symbol),
    }


def get_company(conn, symbol) -> dict:
    """종목상세 하단 4블록(재무·뉴스·컨센서스·내부자). 조립은 company.py가 한다 —
    service.py는 이미 1300줄이라 화면 하나가 여기서 더 자라면 다른 화면이 같이 흔들린다."""
    return company.get_company(conn, symbol)


def _entry_review(conn, symbol: str, sig) -> dict | None:
    """이 포지션을 처음 열었을 때의 근거와, 그 근거가 지금도 서 있는지.

    추가매수 화면이 평단과 손익률만 보여주면 판단은 "얼마나 물렸나"로 좁혀진다.
    물타기를 결정하는 질문은 그게 아니라 최초 진입 논리가 아직 유효한가이고,
    그 답에 필요한 재료(진입 메모·진입 시 등급)는 이미 원장에 있는데 화면이
    한 번도 꺼내 쓰지 않았다.

    최초 진입은 **현재 포지션이 시작된 시점**이다. 전량 매도했다가 다시 산
    종목의 근거를 몇 달 전 청산된 포지션에서 가져오면 남의 논리로 물타기한다.
    """
    trades = [dict(r) for r in db.list_trades(conn, symbol)]
    qty, first = 0.0, None
    for t in trades:
        if qty <= 1e-9:  # 포지션이 비어 있던 자리에서 새로 열린 진입
            first = t if t["side"] == "BUY" else None
        qty += t["quantity"] if t["side"] == "BUY" else -t["quantity"]
    if qty <= 1e-9 or first is None:
        return None
    buys = [t for t in trades if t["side"] == "BUY"
            and t["trade_date"] >= first["trade_date"]]
    current = sig["grade"] if sig else None
    entry_grade = first.get("grade_at_trade")
    order = backtest.GRADE_ORDER[::-1]  # 강력매도 … 강력매수
    downgraded = bool(entry_grade and current and entry_grade in order and current in order
                      and order.index(current) < order.index(entry_grade))
    return {
        "first_entry_date": first["trade_date"],
        "first_entry_price": first["price"],
        "entry_note": first.get("note") or None,
        "entry_grade": entry_grade,
        "current_grade": current,
        "grade_downgraded": downgraded,
        # 이미 여러 번 탄 포지션이면 이번이 첫 물타기가 아니다
        "buy_count": len(buys),
    }


# ── 전략 연구실 ────────────────────────────────────────────────────────────
# 등급 검증(backtest.py)과 목적이 다르다. 여기는 "이 매매 규칙이 계좌 단위로
# 돈을 버는가"에 답한다 — 자본곡선·사이징·동시보유가 전부 들어간다.

STRATEGY_DAYS = 1500  # 약 6년 — price_cache가 가진 만큼 다 쓴다
UNIVERSE_WARNING = (
    "유니버스는 등록된 보유·관심 종목입니다. 직접 고른 종목이라 전략의 알파와 "
    "종목 선택 효과를 분리할 수 없습니다. 이 수치를 실전 기대값으로 쓰지 마세요.")


def strategy_presets() -> list[dict]:
    return [{"key": k, "label": v["label"], "params": v["params"]}
            for k, v in strategy.PRESETS.items()]


def _strategy_universe(conn) -> tuple[dict, dict, float]:
    """등록 종목 전체의 일봉·메타·환율 — 백테스트와 최적화가 같은 유니버스를 쓴다."""
    frames, tickers = {}, {}
    for row in db.list_tickers(conn):
        t = dict(row)
        df = db.load_prices(conn, t["symbol"], limit=STRATEGY_DAYS)
        if df.empty:
            continue
        frames[t["symbol"]] = df
        tickers[t["symbol"]] = t
    fx = get_sentiment_view(conn).get("usdkrw") or portfolio.DEFAULT_USDKRW
    return frames, tickers, fx


def run_strategy_optimize(conn, preset: str,
                          initial_capital_krw: float = 10_000_000.0) -> dict:
    """홀드아웃 그리드 서치 — 학습/검증 구간 분리로 파라미터를 줄 세운다."""
    frames, tickers, fx = _strategy_universe(conn)
    out = engine.optimize(frames, tickers, preset,
                          initial_capital_krw=initial_capital_krw, fx=fx)
    out["universe_warning"] = UNIVERSE_WARNING
    # 화면 안내 — 검증에서 무너지는 조합을 고르지 말라는 것이 이 도구의 존재 이유
    out["note"] = ("학습 구간에서 좋고 검증 구간에서 무너지는 조합은 "
                   "과최적화입니다. 검증 성과 기준으로 고르세요.")
    # 단일 홀드아웃의 구조적 한계 — 실측에서 검증 구간 KOSPI가 CAGR 66%라
    # 모든 조합이 이겼다. 워크포워드가 이 도구를 대체한다.
    out["warnings"] = ["단일 홀드아웃은 검증 구간 레짐에 지배될 수 있습니다. "
                       "워크포워드 결과를 우선하세요."]
    return out


def run_strategy_backtest(conn, preset: str, params: dict | None = None,
                          initial_capital_krw: float = 10_000_000.0) -> dict:
    """등록 종목 전체를 유니버스로 전략 백테스트를 돌린다."""
    if preset not in strategy.PRESETS:
        raise ValueError(f"알 수 없는 전략: {preset}")
    # 화면이 일부 파라미터만 보내도 나머지는 기본값으로 채운다
    merged = {k: v["default"] for k, v in strategy.PRESETS[preset]["params"].items()}
    merged.update(params or {})

    frames, tickers, fx = _strategy_universe(conn)

    out = engine.run(frames, tickers, preset, merged,
                     initial_capital_krw=initial_capital_krw, fx=fx)

    # 달력과 유니버스는 engine.run이 실제로 쓴 것을 그대로 받아 쓴다. 여기서
    # 다시 만들면 30봉 미만으로 걸러진 종목이 비교선에만 들어가 "N종목 동일가중"
    # 범례가 거짓이 되고, 길이가 갈라지면 차트가 날짜를 어긋나게 그린다.
    used = out.pop("_used")
    calendar = used["calendar"]
    used_frames = {s: frames[s] for s in used["symbols"]}
    out["buy_and_hold"] = engine.buy_and_hold(
        used_frames, tickers, initial_capital_krw, fx, calendar)
    # 벤치마크는 KOSPI. _refresh_benchmark가 BENCH:KR로 저장해 둔다
    bdf = db.load_prices(conn, "BENCH:KR", limit=STRATEGY_DAYS)
    out["benchmark"] = engine.buy_and_hold(
        {"BENCH:KR": bdf},
        {"BENCH:KR": {"market": "KR", "currency": "KRW", "is_etf": 0}},
        initial_capital_krw, fx, calendar) if not bdf.empty else []
    out["benchmark_label"] = fetchers.BENCHMARKS["KR"][1] if not bdf.empty else None

    # 초과수익 = 전략 CAGR − 벤치마크 CAGR(스펙 지표 정의). 세 곡선을 그려만
    # 놓고 숫자로 비교하지 않으면 "그냥 들고 있었으면 더 벌었다"가 화면에 안 남는다.
    def _cagr(curve: list[dict]) -> float | None:
        return engine.metrics([p["equity_krw"] for p in curve], [])["cagr"]

    m = out["metrics"]
    m["bench_cagr"] = _cagr(out["benchmark"])
    m["buy_and_hold_cagr"] = _cagr(out["buy_and_hold"])
    m["excess_vs_bench"] = (round(m["cagr"] - m["bench_cagr"], 2)
                            if m["cagr"] is not None and m["bench_cagr"] is not None
                            else None)

    out["universe_warning"] = UNIVERSE_WARNING
    out["fx_note"] = f"USD 종목은 현재 환율 {fx:,.0f}원 고정 근사입니다."
    out["initial_capital_krw"] = initial_capital_krw
    return out


def run_walkforward(conn, preset: str, initial_capital_krw: float = 10_000_000.0,
                    universe_kind: str = "watchlist", regime_filter: bool = False,
                    progress_cb=None) -> dict:
    """워크포워드 검증 — 백그라운드 잡에서 돈다(폴드×조합 약 150회 실행).

    universe_kind="krx300"이면 생존편향 없는 유니버스(universe 테이블 + 시점별
    멤버십), "watchlist"면 기존 등록 종목. 후자는 선택편향 경고가 그대로
    유효하다 — 두 결과의 차이가 곧 그 편향의 크기다.
    """
    if universe_kind == "krx300":
        frames, tickers = universe.load_frames(conn)
        if not frames:
            raise ValueError("유니버스가 비어 있습니다. 먼저 수집을 실행하세요.")
        membership = universe.monthly_membership(frames)
        # 전 종목 KRW라 환율은 결과에 안 쓰인다 — 네트워크를 피해 기본값
        fx = portfolio.DEFAULT_USDKRW
    else:
        frames, tickers, fx = _strategy_universe(conn)
        membership = None
    bench = db.load_prices(conn, "BENCH:KR", limit=STRATEGY_DAYS)
    regime = None
    if regime_filter:
        if bench.empty:
            raise ValueError("레짐 필터에는 벤치마크(KOSPI) 이력이 필요합니다. "
                             "대시보드에서 갱신 후 다시 시도하세요.")
        # 지수가 200일선 위일 때만 신규 진입 — MA가 안 찬 초기 구간은 close>NaN이
        # False라 자동으로 진입이 막힌다(판단 근거 없음 = 보수적)
        regime = bench["close"] > bench["close"].rolling(200).mean()
    out = engine.walkforward(
        frames, tickers, preset,
        initial_capital_krw=initial_capital_krw, fx=fx, membership=membership,
        bench_frame=bench if not bench.empty else None, regime=regime,
        progress_cb=progress_cb)
    out["preset"] = preset
    out["universe"] = universe_kind
    out["regime_filter"] = regime_filter
    out["universe_size"] = len(frames)
    out["initial_capital_krw"] = initial_capital_krw
    out["benchmark_label"] = fetchers.BENCHMARKS["KR"][1] if not bench.empty else None
    if universe_kind == "watchlist":
        out["universe_warning"] = UNIVERSE_WARNING
    else:
        out["universe_warning"] = (
            "폐지 종목은 마지막 종가 청산 근사라 실손실(정리매매 급락)을 "
            "과소평가할 수 있습니다.")
    return out


def universe_status(conn) -> dict:
    row = conn.execute(
        "SELECT COUNT(DISTINCT symbol), MAX(date) FROM universe_prices").fetchone()
    delisted = conn.execute(
        "SELECT COUNT(*) FROM universe_meta WHERE delisting_date IS NOT NULL"
    ).fetchone()[0]
    return {"symbols": row[0], "last_date": row[1], "delisted_count": delisted,
            "collected_at": db.get_meta(conn, "universe_collected_at")}
