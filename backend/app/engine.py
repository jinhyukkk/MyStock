"""포트폴리오 백테스트 엔진 — 시그널을 자본곡선으로 바꾼다.

strategy.py가 "언제"를 답하면 여기가 "얼마나"를 답한다. 두 관심사를 섞지 않는
이유는 전략이 앞으로 늘어나기 때문이다 — 엔진은 전략을 몰라야 하고, 전략은
자본을 몰라야 한다.

사이징·손절·비용은 앱이 화면에서 권하는 규칙을 그대로 쓴다. 검증한 전략과
실행할 전략이 다르면 이 백테스트는 아무것도 증명하지 못한다.
"""
import math

import pandas as pd

from app import backtest, costs, indicators, strategy

RISK_PCT = 0.01  # 거래 1건이 계좌에서 잃을 수 있는 비율 — service._risk_block과 동일
# service.MAX_WEIGHT와 같은 값. import 하면 service → engine 순환이 생겨 다시 선언한다.
# 한쪽을 바꾸면 다른 쪽도 함께 바꿔야 한다.
MAX_WEIGHT = 0.20
MAX_POSITIONS = 7  # portfolio.DEFAULT_TARGET_POSITIONS[1]과 동일
# 주의: 실제로는 이 상한에 거의 안 닿는다 — 비중+현금 제약(코드 내
# held_notional 체크)과 계좌리스크 상한(MAX_ACCOUNT_RISK_PCT)이 먼저 막는다.
# 도달하려면 포지션별 리스크가 6%/7 ≈ 0.857% 미만이면서 노셔널 평균이
# 14.3%(=100%/7) 미만인 저리스크·저비중 혼합 상황이어야 한다.
# 모든 보유가 동시에 손절에 닿았을 때의 손실 합 상한 — portfolio.MAX_ACCOUNT_RISK_PCT와 동일.
# 종목별 1%만 지키면 7종목에서 총 7%가 되는데, 합산을 안 보면 그 사실이 어디에도 안 남는다.
MAX_ACCOUNT_RISK_PCT = 6.0
STOP_ATR_MULT = backtest.STOP_ATR_MULT
TRADING_DAYS = 252


def position_size(equity_krw: float, entry: float, stop: float, fx: float,
                  market: str, max_weight: float = MAX_WEIGHT) -> float:
    """1% 룰 수량 — 진입가에서 손절가까지 맞았을 때 계좌의 1%를 잃는 수량.

    entry·stop은 종목 통화 기준, fx로 원화 환산한다. 두 상한을 함께 건다:
      - 리스크 상한: 손실이 계좌의 RISK_PCT
      - 노셔널 상한: 한 종목이 계좌의 max_weight를 넘지 않게
    저변동성 종목은 손절폭이 좁아 리스크 상한만으로는 수량이 폭발한다.
    """
    per_share_loss = (entry - stop) * fx
    if per_share_loss <= 0 or entry <= 0 or equity_krw <= 0:
        return 0.0
    risk_qty = equity_krw * RISK_PCT / per_share_loss
    cap_qty = equity_krw * max_weight / (entry * fx)
    # 내림 — 올리면 계산해 둔 리스크 한도를 넘는다
    return costs.round_to_lot(min(risk_qty, cap_qty), market)


def resolve_exit(bars: pd.DataFrame, entry_i: int, stop: float | None,
                 exit_signal) -> tuple[int, float, str]:
    """진입봉(entry_i) 이후 언제·얼마에 나가는지. (인덱스, 가격, 사유)를 돌려준다.

    사유는 stop|signal|end. 손절로 끝난 비율이 안 보이면 전략이 규칙대로
    굴러간 것인지 알 수 없어서 사유를 함께 남긴다.

    우선순위는 시간순이다 — 손절이 먼저 닿았으면 뒤의 청산 신호는 무의미하다.
    """
    o = bars["open"].to_numpy(dtype=float)
    low = bars["low"].to_numpy(dtype=float)
    close = bars["close"].to_numpy(dtype=float)
    n = len(bars)
    for d in range(entry_i, n):
        # 손절 먼저 — 갭 하락이면 시가가 이미 손절선 아래다
        if stop is not None and low[d] <= stop:
            return d, min(o[d], stop), "stop"
        # 청산 신호는 그날 종가에 낼 수 없다 — 익일 시가
        if exit_signal[d] and d + 1 < n:
            return d + 1, o[d + 1], "signal"
    return n - 1, close[n - 1], "end"


def metrics(equity: list[float], trades: list[dict]) -> dict:
    """자본곡선과 거래 목록에서 성과 지표.

    샤프의 무위험수익률은 0으로 둔다 — 화면에 그 가정을 함께 표시한다.
    승률은 비용 차감 후 손익 기준이다(0원은 승이 아니다).
    """
    n = len(equity)
    start, end = (equity[0], equity[-1]) if n else (0.0, 0.0)
    cagr = 0.0
    if n > 1 and start > 0:
        cagr = ((end / start) ** (TRADING_DAYS / (n - 1)) - 1) * 100
    # MDD — 최고점 대비 최대 낙폭. 시작점 대비로 재면 중간에 오른 뒤의 하락을 놓친다
    peak, mdd = start or 1.0, 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, (v / peak - 1) * 100)
    rets = [equity[i] / equity[i - 1] - 1
            for i in range(1, n) if equity[i - 1] > 0]
    sharpe = None
    if len(rets) > 1:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        sd = math.sqrt(var)
        sharpe = mean / sd * math.sqrt(TRADING_DAYS) if sd > 0 else None
    wins = sum(1 for t in trades if t["pnl_krw"] > 0)
    return {
        "cagr": round(cagr, 2),
        "mdd": round(mdd, 2),
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "win_rate": round(wins / len(trades) * 100, 1) if trades else None,
        "trade_count": len(trades),
        "final_equity_krw": round(end, 0),
    }


def _cost_pct(t: dict, df: pd.DataFrame, fx: float) -> float:
    """이 종목의 왕복 비용(비율). 실제로는 진입 노셔널(entry * qty * rate)에만

    곱해 cost_krw를 낸다 — 청산 시점 노셔널로 다시 계산하지 않는다. 진입가와
    청산가가 크게 벌어지면(추세추종이 노리는 상황) 비용이 과소·과대평가될 수
    있는 근사다. 왕복 비율을 한 번만 곱하는 것이지, 진입·청산 양쪽에 각각
    곱하는 게 아니다.
    """
    recent = df.tail(60)
    turnover = float((recent["close"] * recent["volume"]).median()) if len(recent) else 0.0
    if t.get("currency") == "USD":
        turnover *= fx
    return costs.backtest_cost_pct(t.get("market", ""), t.get("is_etf", 0),
                                   turnover) / 100


def run(price_frames: dict, tickers: dict, preset: str, params: dict, *,
        initial_capital_krw: float, fx: float) -> dict:
    """포트폴리오 백테스트 — 시그널을 계좌 단위 자본곡선으로.

    진입은 신호 익일 시가, 손절은 2×ATR, 사이징은 1% 룰. 전부 앱이 화면에서
    권하는 규칙과 같다.
    """
    if preset not in strategy.PRESETS:
        raise ValueError(f"알 수 없는 전략: {preset}")
    fn = strategy.PRESETS[preset]["fn"]

    # 모든 종목의 거래일을 합집합으로 모아 하나의 달력을 만든다 —
    # 종목마다 다른 인덱스로 자본을 합산하면 어느 날의 자본인지 알 수 없다
    calendar = sorted(set().union(*(set(df.index) for df in price_frames.values()))) \
        if price_frames else []

    prepared = {}
    for sym, df in price_frames.items():
        if len(df) < 30:
            continue  # 지표가 안 차는 종목은 신호를 만들 수 없다
        # OHLC에 NaN이 있는 행(거래정지 등)을 드랍한다 — 안 그러면 마지막 봉이
        # NaN일 때 resolve_exit이 NaN 청산가를 돌려주고 equity += NaN으로
        # 이후 전 구간·모든 지표가 오염된다(발견 2). 드랍된 날은 그 종목의
        # 캘린더 밖이 되어 ③ 마킹 루프의 last_mark 이월 로직(발견 1)이
        # 자연스럽게 직전 유효 종가를 이어받는다.
        clean = df.dropna(subset=["open", "high", "low", "close"])
        if len(clean) < 30:
            continue
        enriched = indicators.compute_indicators(clean)
        prepared[sym] = {
            "df": enriched, "sig": fn(enriched, params),
            "rate": fx if tickers.get(sym, {}).get("currency") == "USD" else 1.0,
            "cost": _cost_pct(tickers.get(sym, {}), clean, fx),
        }

    equity = initial_capital_krw
    open_pos: dict[str, dict] = {}
    trades: list[dict] = []
    curve: list[dict] = []
    max_concurrent = 0

    for day in calendar:
        # ① 청산 먼저 — 같은 날 나가고 들어오는 자리를 비워 준다
        for sym in list(open_pos):
            p = open_pos[sym]
            if day < p["exit_date"]:
                continue
            gross = (p["exit_price"] - p["entry_price"]) * p["qty"] * p["rate"]
            equity += gross - p["cost_krw"]
            trades.append({
                "symbol": sym, "name": tickers.get(sym, {}).get("name", sym),
                "entry_date": p["entry_date"].strftime("%Y-%m-%d"),
                "entry_price": round(p["entry_price"], 4),
                "exit_date": p["exit_date"].strftime("%Y-%m-%d"),
                "exit_price": round(p["exit_price"], 4),
                "exit_reason": p["exit_reason"], "qty": p["qty"],
                "cost_krw": round(p["cost_krw"], 0),
                "pnl_krw": round(gross - p["cost_krw"], 0),
            })
            del open_pos[sym]

        # ② 진입 — 자리가 남아 있고 계좌 총 리스크·현금이 한도 안일 때만.
        # 미결 리스크 = 모든 보유가 동시에 손절에 닿았을 때의 손실 합
        open_risk = sum((p["entry_price"] - p["stop"]) * p["qty"] * p["rate"]
                        for p in open_pos.values())
        # 보유 노셔널 합 — 현금 계좌는 마진이 없어 신규 진입 노셔널이 잔여 현금을
        # 넘을 수 없다. position_size가 진입마다 같은 전체 equity로 수량을 정해서,
        # 이 제약이 없으면 동시 진입 시 MAX_WEIGHT×MAX_POSITIONS(140%)까지도
        # 매수된다 — 원 계획서에는 없던 규칙을 여기서 추가한다.
        held_notional = sum(p["notional"] for p in open_pos.values())
        # 현금·리스크 한도로 자리가 모자라면 prepared(=price_frames)의 딕셔너리
        # 삽입 순서가 그대로 우선순위가 된다 — 모멘텀 강도 등 랭킹을 적용하지
        # 않는다. 순서가 결정적이긴 하지만 경제적 근거는 없다(발견 5). 랭킹이
        # 필요하면 이 루프 전에 prepared를 신호 강도로 정렬해야 한다.
        for sym, pr in prepared.items():
            if len(open_pos) >= MAX_POSITIONS:
                break
            if sym in open_pos or day not in pr["sig"].index:
                continue
            if not bool(pr["sig"].at[day, "enter"]):
                continue
            df = pr["df"]
            i = df.index.get_loc(day)
            if i + 1 >= len(df):
                continue  # 마지막 봉에서는 낼 수 있는 주문이 없다
            entry = float(df["open"].iloc[i + 1])
            atr = df["atr14"].iloc[i]
            # NaN 시가(거래정지 등)를 그대로 흘리면 손절가도 NaN이 되고,
            # NaN 비교는 항상 False라 뒤의 <= 0 가드를 다 통과해 버려
            # round_to_lot의 int(NaN) 변환에서 죽는다 — 여기서 먼저 막는다
            if pd.isna(entry) or entry <= 0 or pd.isna(atr) or atr <= 0:
                continue
            stop = entry - STOP_ATR_MULT * float(atr)
            market = tickers.get(sym, {}).get("market", "")
            qty = position_size(equity, entry, stop, pr["rate"], market)
            if qty <= 0:
                continue
            notional = entry * qty * pr["rate"]
            if notional > equity - held_notional:
                continue  # 잔여 현금 초과 — 이 진입은 건너뛴다
            # 이 포지션을 더했을 때 계좌 총 리스크가 한도를 넘으면 진입하지 않는다
            add_risk = (entry - stop) * qty * pr["rate"]
            if equity > 0 and (open_risk + add_risk) / equity * 100 > MAX_ACCOUNT_RISK_PCT:
                continue
            open_risk += add_risk
            held_notional += notional
            bars = df.iloc[i + 1:]
            exit_i, exit_px, reason = resolve_exit(
                bars, 0, stop, pr["sig"]["exit"].iloc[i + 1:].tolist())
            open_pos[sym] = {
                "entry_date": df.index[i + 1], "entry_price": entry,
                "exit_date": bars.index[exit_i], "exit_price": exit_px,
                "exit_reason": reason, "qty": qty, "rate": pr["rate"],
                "stop": stop,  # 계좌 총 리스크 합산에 필요하다
                "notional": notional,  # 보유 노셔널 합산에 필요하다
                "cost_krw": notional * pr["cost"],
                "last_mark": entry,  # 직전 유효 종가 — 휴장일엔 이 값을 이어받는다
            }

        # 실제로 보유 중인 포지션만 — 오늘 막 진입한 포지션은 entry_date가
        # 내일이라 아직 보유가 아니다(룩어헤드 방지, 발견 1)
        held = {sym: p for sym, p in open_pos.items() if p["entry_date"] <= day}
        max_concurrent = max(max_concurrent, len(held))

        # ③ 그날의 자본 — 확정 자본 + 보유 중인 포지션의 평가손익.
        # calendar는 전 종목 거래일의 합집합이라 어떤 종목이 그날 휴장이면
        # day가 그 종목 df.index에 없다. 평가손익을 0으로 놓으면 자본이
        # 미실현손익만큼 튀었다가 다음 날 되돌아오는 가짜 갭이 생긴다
        # (발견 1) — 대신 직전 유효 종가(last_mark)를 이어받는다. last_mark는
        # 항상 그날 이전 종가만 담으므로 룩어헤드가 아니다.
        unrealized = 0.0
        for sym, p in held.items():
            df = prepared[sym]["df"]
            c = df["close"].at[day] if day in df.index else float("nan")
            if not pd.isna(c):
                p["last_mark"] = float(c)
            unrealized += (p["last_mark"] - p["entry_price"]) * p["qty"] * p["rate"]
        curve.append({"date": day.strftime("%Y-%m-%d"),
                      "equity_krw": round(equity + unrealized, 0)})

    return {
        "equity_curve": curve,
        "trades": trades,
        "metrics": metrics([c["equity_krw"] for c in curve], trades),
        "max_concurrent": max_concurrent,
        "universe_size": len(prepared),
        "preset": preset,
        "params": params,
    }


def buy_and_hold(price_frames: dict, tickers: dict, initial_capital_krw: float,
                 fx: float, calendar: list) -> list[dict]:
    """동일가중 매수보유 비교선.

    전략 CAGR이 12%라도 그냥 들고 있었으면 18%였다면 그 전략은 실패다.
    비교선이 없으면 그 사실이 화면 어디에도 안 나온다. 비용은 첫 진입 1회뿐이라
    생략한다 — 전략 쪽에 불리한 쪽(보수적)이다.
    """
    # run()과 같은 이유로 OHLC NaN 행(거래정지 등)을 드랍한다 — 안 그러면
    # 마킹 루프에서 그날 last[s]가 NaN이 되어 total(비교선 전체)이 NaN으로
    # 오염된다. len<30 필터는 넣지 않는다 — run()의 30일 하한은 지표
    # 롤링 윈도가 차야 신호가 나오기 때문인데, 비교선은 신호를 계산하지
    # 않고 그냥 들고 있을 뿐이라 그 제약이 없다.
    usable = {}
    for s, df in price_frames.items():
        clean = df.dropna(subset=["open", "high", "low", "close"])
        if len(clean):
            usable[s] = clean
    if not usable or not calendar:
        return []
    slot = initial_capital_krw / len(usable)
    units, cash = {}, initial_capital_krw
    for s, df in usable.items():
        rate = fx if tickers.get(s, {}).get("currency") == "USD" else 1.0
        first = float(df["close"].iloc[0])
        market = tickers.get(s, {}).get("market", "")
        raw_qty = slot / (first * rate) if first > 0 else 0.0
        # run()의 position_size와 동일하게 내림 — 소수점 주식 비교선은
        # 실제로 살 수 없는 수량이라 비교 자체가 무의미해진다
        qty = costs.round_to_lot(raw_qty, market)
        units[s] = (qty, rate)
        cash -= qty * first * rate
    out, last = [], {}
    for day in calendar:
        # 내림으로 남은 잔돈은 현금으로 들고 간다 — 버리면 비교선만 초기자본
        # 미만에서 출발해 전략 쪽이 공짜로 유리해진다
        total = cash
        for s, df in usable.items():
            if day in df.index:
                last[s] = float(df["close"].at[day])
            qty, rate = units[s]
            total += qty * last.get(s, float(df["close"].iloc[0])) * rate
        out.append({"date": day.strftime("%Y-%m-%d"), "equity_krw": round(total, 0)})
    return out
