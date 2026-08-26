"""자동매매 파이프라인 — 백테스트와 같은 규칙으로 "오늘 낼 주문"을 만든다.

engine.run이 과거에 대해 하는 판단을 마지막 봉 하나에 대해 반복한다:
진입은 신호 익일 시가(= 오늘 아침 시장가), 손절은 진입 시점 2×ATR,
사이징은 1% 룰 + 비중 20% 상한, 계좌리스크 6% 상한, 최대 7종목,
그리고 지수가 200일선 위일 때만 신규 진입(레짐 게이트).
여기서 규칙 하나라도 바꾸면 백테스트·최적화로 검증한 것과 다른 전략을
실행하게 된다 — 수치 상수는 전부 engine 것, 레짐 식은 strategy 것을 쓴다.

검증과 실행이 여전히 다른 지점은 응답에 명시적으로 실어 보낸다(universe,
warnings) — 조용히 두면 krx300 워크포워드 수치를 관심종목 매매의 근거로
읽게 된다. 그 격차가 실측에서 55%p였다.

plan()은 주문을 만들기만 하고(dry-run), execute()만 KIS로 발송한다.
장 시작 전(08:00~09:00)에 실행하는 것을 전제로 한다 — 마지막 일봉이
어제 종가로 확정된 상태여야 신호가 확정이다.
"""
import json
from datetime import datetime, timedelta

import pandas as pd

from app import db, engine, indicators, kis, strategy

PRICE_DAYS = 400  # 신호 계산에 필요한 이력 — 최장 롤링(252+21)보다 넉넉히
STALE_DAYS = 5    # 마지막 일봉이 이보다 오래됐으면 신호를 믿을 수 없다
BENCH_SYMBOL = "BENCH:KR"  # 레짐 판정 기준 지수(KOSPI) — service가 같은 키로 저장한다
REGIME_DAYS = 400  # 200일선을 채우고도 남을 이력
# 계좌 평단과 이보다 더 벌어지면 진입가를 보정한다. 0으로 두면 부동소수 오차마다
# 보정 경고가 뜨고, 크게 두면 손절선이 그만큼 어긋난 채로 남는다.
FILL_TOLERANCE = 0.001
UNIVERSE_MISMATCH = (
    "신호 스캔 대상은 관심종목 {n}개입니다. 검증(krx300, 폐지 포함 964종목)과 "
    "다른 모집단이며, 백테스트 성과의 큰 몫이 이 차이에서 나왔습니다.")
REGIME_OFF_WARNING = (
    "레짐 필터 OFF — 이 구성은 krx300 워크포워드에서 5폴드 전패"
    "(초과수익 중앙값 -16.3%p)했습니다.")


def settings(conn) -> dict:
    """자동매매가 실행할 전략·파라미터 — 화면에서 저장, meta에 보관."""
    preset = db.get_meta(conn, "autotrade_preset") or "abs_momentum"
    # 프리셋이 삭제·개명돼도, 횡단면 프리셋이 저장돼 있어도 자동매매가 죽으면 안 된다.
    # 횡단면은 _signals가 쓰는 fn이 없고, 애초에 관심종목 모집단에서는 상대
    # 랭킹의 의미가 달라져 실행 대상이 아니다.
    if preset not in strategy.PRESETS or \
            strategy.PRESETS[preset]["kind"] != strategy.TIMESERIES:
        preset = "abs_momentum"
    defaults = {k: v["default"]
                for k, v in strategy.PRESETS[preset]["params"].items()}
    try:
        saved = json.loads(db.get_meta(conn, "autotrade_params") or "{}")
    except ValueError:
        saved = {}
    params = {**defaults, **{k: int(v) for k, v in saved.items() if k in defaults}}
    # 키가 없으면 ON. 워크포워드에서 유효성이 확인된 유일한 구성이라 기본값을
    # 여기로 둔다 — 기본이 OFF면 데이터가 반대하는 설정이 계속 기본으로 남는다.
    raw = db.get_meta(conn, "autotrade_regime_filter")
    return {"preset": preset, "params": params,
            "regime_filter": True if raw is None else raw == "1"}


def save_settings(conn, preset: str, params: dict,
                  regime_filter: bool = True) -> None:
    if preset not in strategy.PRESETS:
        raise ValueError(f"알 수 없는 전략: {preset}")
    if strategy.PRESETS[preset]["kind"] != strategy.TIMESERIES:
        # 상대 랭킹은 모집단이 바뀌면 다른 지표다 — 관심종목 18종목 사이의
        # 상위 20%(3.6종목)를 krx300 검증 결과의 근거로 쓸 수 없다
        raise ValueError(
            f"{strategy.PRESETS[preset]['label']}은 유니버스 상대 랭킹 전략이라 "
            "자동매매에서 실행할 수 없습니다. 전략 연구실에서만 검증하세요.")
    db.set_meta(conn, "autotrade_preset", preset)
    db.set_meta(conn, "autotrade_params", json.dumps(params or {}))
    db.set_meta(conn, "autotrade_regime_filter", "1" if regime_filter else "0")


def regime(conn, as_of: str | None) -> dict:
    """신호일(as_of) 기준 레짐 판정 — {ok, bench_close, bench_ma, as_of, ma}.

    ok=None은 "판정 불가"다(지수 이력 없음·200봉 미달). 그때는 호출부가 진입을
    막는다 — 근거 없이 사는 쪽이 근거 없이 쉬는 쪽보다 위험하다.

    마지막 봉이 아니라 as_of 기준으로 읽는 이유 — 지수 갱신이 종목보다 하루
    앞서 있으면 아직 오지 않은 날의 레짐으로 오늘 주문을 내게 된다.
    """
    out = {"ma": strategy.REGIME_MA, "ok": None, "bench_close": None,
           "bench_ma": None, "as_of": None}
    bench = db.load_prices(conn, BENCH_SYMBOL, limit=REGIME_DAYS)
    if bench.empty or len(bench) < strategy.REGIME_MA:
        return out
    reg = strategy.regime_series(bench["close"])
    ma = bench["close"].rolling(strategy.REGIME_MA).mean()
    idx = reg.index
    if as_of is not None:
        # 지수 휴장일은 직전 값을 이어받는다(engine의 ffill과 같은 규칙)
        usable = idx[idx <= pd.Timestamp(as_of)]
        if not len(usable):
            return out
        idx = usable
    day = idx[-1]
    return {"ma": strategy.REGIME_MA, "ok": bool(reg.at[day]),
            "bench_close": round(float(bench["close"].at[day]), 2),
            "bench_ma": round(float(ma.at[day]), 2),
            "as_of": day.strftime("%Y-%m-%d")}


def _reconcile_fills(conn, auto_pos: dict, kis_held: dict) -> list[str]:
    """진입가를 계좌 평단(실체결)으로 한 번 보정한다. 경고 문구 목록을 돌려준다.

    entry_price는 주문 시점엔 직전 종가 근사다 — 실제 체결은 시가라 몇 %
    어긋나고, 그만큼 손절선도 어긋나 1% 룰의 1%가 1%가 아니게 된다.

    손절 **폭**을 보존한다(진입 시점 2×ATR). 오늘 ATR로 다시 계산하면
    계산해 둔 리스크 한도가 사후에 바뀐다.

    auto_pos는 제자리에서 갱신한다 — 호출부의 청산 판정이 보정된 손절선을
    봐야 백테스트와 같은 손절이 된다.
    """
    notes = []
    for sym, p in auto_pos.items():
        if p.get("fill_synced"):
            continue
        held = kis_held.get(sym)
        avg = float((held or {}).get("avg_price") or 0)
        old_entry = float(p["entry_price"])
        if avg <= 0 or old_entry <= 0:
            continue
        if abs(avg - old_entry) / old_entry <= FILL_TOLERANCE:
            continue
        new_stop = avg - (old_entry - float(p["stop"]))
        db.sync_auto_fill(conn, sym, avg, new_stop)
        p["entry_price"], p["stop"], p["fill_synced"] = avg, new_stop, 1
        notes.append(f"{sym}: 진입가를 실체결 평단으로 보정"
                     f"({old_entry:,.0f} → {avg:,.0f}), 손절선 재계산.")
    return notes


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

    # 검증(krx300)과 실행(관심종목)의 모집단이 다르다는 사실을 항상 고지한다 —
    # 조용히 두면 워크포워드 수치를 이 주문의 근거로 읽게 된다
    warnings.append(UNIVERSE_MISMATCH.format(n=len(sigs)))

    # ⓪ 진입가 보정을 청산 판정보다 **먼저** — 보정된 손절선으로 low<=stop을
    # 봐야 백테스트와 같은 손절이 된다. 뒤에 두면 이 손절이 하루 늦게 나간다.
    warnings.extend(_reconcile_fills(conn, auto_pos, kis_held))

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

    # ②-a 레짐 게이트 — 지수가 200일선 아래면 신규 진입만 막는다. 청산·손절은
    # 위에서 이미 처리했다(하락장에서 못 파는 필터는 리스크 장치가 아니라 족쇄다).
    reg = regime(conn, as_of)
    reg["enabled"] = cfg["regime_filter"]
    entries_open = True
    if not cfg["regime_filter"]:
        warnings.append(REGIME_OFF_WARNING)
    elif reg["ok"] is None:
        entries_open = False
        warnings.append(
            f"지수({BENCH_SYMBOL}) 이력이 없거나 {reg['ma']}일선을 채우지 못해 "
            "레짐을 판정할 수 없습니다. 벤치마크 갱신 전까지 신규 진입을 막습니다.")
    elif not reg["ok"]:
        entries_open = False
        warnings.append(
            f"레짐 필터: 지수 {reg['bench_close']:,.0f}이 {reg['ma']}일선 "
            f"{reg['bench_ma']:,.0f} 아래입니다({reg['as_of']}). 신규 진입을 막습니다.")

    # ② 진입 — 신호 강도 내림차순, engine과 같은 게이트를 같은 순서로 통과
    cands = sorted(
        ((sym, s) for sym, s in sigs.items()
         if s["enter"] and sym not in auto_pos and sym not in kis_held),
        key=lambda x: x[1]["strength"], reverse=True) if entries_open else []
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
            "regime": reg,
            "universe": {"kind": "watchlist", "size": len(sigs)},
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
