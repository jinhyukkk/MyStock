"""자동매매 파이프라인 — 백테스트와 같은 규칙으로 "오늘 낼 주문"을 만든다.

engine.run이 과거에 대해 하는 판단을 마지막 봉 하나에 대해 반복한다:
진입은 신호 익일 시가(= 오늘 아침 시장가), 손절은 진입 시점 2×ATR,
사이징은 1% 룰 + 비중 20% 상한, 계좌리스크 6% 상한, 최대 7종목.
여기서 규칙 하나라도 바꾸면 백테스트·최적화로 검증한 것과 다른 전략을
실행하게 된다 — 수치 상수는 전부 engine 것을 그대로 쓴다.

plan()은 주문을 만들기만 하고(dry-run), execute()만 KIS로 발송한다.
장 시작 전(08:00~09:00)에 실행하는 것을 전제로 한다 — 마지막 일봉이
어제 종가로 확정된 상태여야 신호가 확정이다.
"""
import json
from datetime import datetime, timedelta

from app import db, engine, indicators, kis, strategy

PRICE_DAYS = 400  # 신호 계산에 필요한 이력 — 최장 롤링(252+21)보다 넉넉히
STALE_DAYS = 5    # 마지막 일봉이 이보다 오래됐으면 신호를 믿을 수 없다


def settings(conn) -> dict:
    """자동매매가 실행할 전략·파라미터 — 화면에서 저장, meta에 보관."""
    preset = db.get_meta(conn, "autotrade_preset") or "abs_momentum"
    if preset not in strategy.PRESETS:
        preset = "abs_momentum"  # 프리셋이 삭제·개명돼도 자동매매가 죽으면 안 된다
    defaults = {k: v["default"]
                for k, v in strategy.PRESETS[preset]["params"].items()}
    try:
        saved = json.loads(db.get_meta(conn, "autotrade_params") or "{}")
    except ValueError:
        saved = {}
    params = {**defaults, **{k: int(v) for k, v in saved.items() if k in defaults}}
    return {"preset": preset, "params": params}


def save_settings(conn, preset: str, params: dict) -> None:
    if preset not in strategy.PRESETS:
        raise ValueError(f"알 수 없는 전략: {preset}")
    db.set_meta(conn, "autotrade_preset", preset)
    db.set_meta(conn, "autotrade_params", json.dumps(params or {}))


def _signals(conn, cfg: dict) -> dict:
    """국내 종목별 마지막 봉의 신호 — {symbol: {enter, exit, strength, close, low, atr, date, name}}.

    KR만 다루는 이유 — v1 주문 실행이 KIS 국내주식 TR뿐이다. 미국까지 자동으로
    내려면 해외주문·환전이 별도 작업이라 스펙에서 다음 단계로 미뤘다.
    """
    fn = strategy.PRESETS[cfg["preset"]]["fn"]
    out = {}
    for row in db.list_tickers(conn):
        t = dict(row)
        if t["market"] != "KR":
            continue
        df = db.load_prices(conn, t["symbol"], limit=PRICE_DAYS)
        if df.empty:
            continue
        clean = df.dropna(subset=["open", "high", "low", "close"])
        if len(clean) < 30:
            continue
        enriched = indicators.compute_indicators(clean)
        sig = fn(enriched, cfg["params"])
        last = enriched.index[-1]
        atr = enriched["atr14"].iloc[-1]
        out[t["symbol"]] = {
            "name": t["name"],
            "date": last.strftime("%Y-%m-%d"),
            "close": float(enriched["close"].iloc[-1]),
            "low": float(enriched["low"].iloc[-1]),
            "atr": None if atr != atr else float(atr),  # NaN 가드
            "enter": bool(sig["enter"].iloc[-1]),
            "exit": bool(sig["exit"].iloc[-1]),
            "strength": float(sig["strength"].iloc[-1]),
        }
    return out


def plan(conn, balance: dict) -> dict:
    """오늘 낼 주문 목록 — 발송은 하지 않는다(dry-run).

    balance는 KIS 잔고(client.balance()) 형식. 인자로 받는 이유는 테스트에서
    네트워크 없이 파이프라인 전체를 검증하기 위해서다.
    """
    cfg = settings(conn)
    sigs = _signals(conn, cfg)
    auto_pos = {r["symbol"]: dict(r) for r in db.list_auto_positions(conn)}
    kis_held = {h["symbol"]: h for h in balance.get("holdings", [])}
    equity = float(balance.get("total_eval_krw") or 0)
    cash = float(balance.get("cash_krw") or 0)
    orders: list[dict] = []
    warnings: list[str] = []

    today = datetime.now().strftime("%Y-%m-%d")
    stale_cut = (datetime.now() - timedelta(days=STALE_DAYS)).strftime("%Y-%m-%d")
    as_of = max((s["date"] for s in sigs.values()), default=None)
    if as_of is None:
        warnings.append("국내 종목 시세가 없습니다. 대시보드에서 갱신 후 다시 시도하세요.")
    elif as_of < stale_cut:
        warnings.append(f"시세가 오래됐습니다(마지막 {as_of}). 갱신 후 다시 시도하세요.")

    # ① 청산 먼저 — 백테스트와 같은 순서. 자리가 비어야 신규 진입이 들어간다
    for sym, p in list(auto_pos.items()):
        held = kis_held.get(sym)
        if held is None:
            # 수동으로 팔았거나 체결이 안 된 흔적 — 주문을 내면 공매도가 된다
            warnings.append(f"{sym}: 자동 포지션이 계좌에 없습니다. 기록만 정리하세요.")
            continue
        s = sigs.get(sym)
        reason = None
        if s is None:
            warnings.append(f"{sym}: 시세가 없어 청산 판정을 건너뜁니다.")
        elif s["low"] <= p["stop"]:
            reason = "stop"     # 어제 저가가 손절선에 닿음 — 백테스트의 low<=stop과 동일
        elif s["exit"]:
            reason = "exit_signal"
        if reason:
            qty = min(float(p["qty"]), float(held["qty"]))
            orders.append({"symbol": sym, "name": p.get("name") or sym,
                           "side": "SELL", "qty": int(qty), "reason": reason,
                           "price_ref": s["close"], "stop": None})

    selling = {o["symbol"] for o in orders}
    remaining = {s: p for s, p in auto_pos.items() if s not in selling}
    # 미결 리스크 = 남는 포지션이 전부 손절에 닿았을 때 손실 합 — engine ②와 동일
    open_risk = sum((p["entry_price"] - p["stop"]) * p["qty"]
                    for p in remaining.values())

    # ② 진입 — 신호 강도 내림차순, engine과 같은 게이트를 같은 순서로 통과
    cands = sorted(
        ((sym, s) for sym, s in sigs.items()
         if s["enter"] and sym not in auto_pos and sym not in kis_held),
        key=lambda x: x[1]["strength"], reverse=True)
    slots = engine.MAX_POSITIONS - len(remaining)
    committed = 0.0
    for sym, s in cands:
        if slots <= 0:
            break
        if s["atr"] is None or s["atr"] <= 0 or s["close"] <= 0:
            continue
        stop = s["close"] - engine.STOP_ATR_MULT * s["atr"]
        qty = engine.position_size(equity, s["close"], stop, 1.0, "KR")
        if qty <= 0:
            continue
        notional = s["close"] * qty
        if notional + committed > cash:
            continue  # 현금 계좌 — 예수금을 넘는 매수는 미수가 된다
        add_risk = (s["close"] - stop) * qty
        if equity > 0 and \
                (open_risk + add_risk) / equity * 100 > engine.MAX_ACCOUNT_RISK_PCT:
            continue
        open_risk += add_risk
        committed += notional
        slots -= 1
        orders.append({"symbol": sym, "name": s["name"], "side": "BUY",
                       "qty": int(qty), "reason": "enter",
                       "price_ref": s["close"], "stop": round(stop, 2)})

    return {"date": today, "as_of": as_of, "mode": kis.mode(),
            "preset": cfg["preset"], "params": cfg["params"],
            "equity_krw": equity, "cash_krw": cash,
            "orders": orders, "warnings": warnings}


def execute(conn, client) -> dict:
    """plan()의 주문을 KIS로 발송하고 포지션·원장을 갱신한다.

    한 주문이 실패해도 나머지는 계속 낸다 — 청산 주문이 진입 실패에 막히면
    손절이 안 나가는 쪽이 더 위험하다. 실패는 원장에 남겨 화면에 보인다.
    """
    p = plan(conn, client.balance())
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for o in p["orders"]:
        try:
            order_no = client.order(o["symbol"], o["side"], o["qty"])
            o["status"], o["order_no"] = "sent", order_no
            if o["side"] == "BUY":
                # entry_price는 직전 종가 근사 — 실제 체결가는 시가라 다를 수 있다.
                # ponytail: 체결가 확정 조회(주문체결내역 TR)는 다음 단계, 손절선이
                # 수 % 어긋나는 수준이라 v1에서는 근사로 둔다.
                db.upsert_auto_position(conn, o["symbol"], o["qty"],
                                        o["price_ref"], o["stop"], p["date"])
            else:
                db.delete_auto_position(conn, o["symbol"])
        except kis.KisError as e:
            o["status"], o["error"] = "failed", str(e)
        db.insert_auto_order(conn, now, p["mode"], o["symbol"], o["name"],
                             o["side"], o["qty"], o["reason"], o["status"],
                             o.get("order_no"), o.get("error"), o["price_ref"])
    return p
