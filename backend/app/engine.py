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


def _one_way_cost(t: dict, df: pd.DataFrame, fx: float) -> float:
    """이 종목의 편도 비용(비율). 왕복값을 절반으로 나눠 진입·청산에 각각 건다."""
    recent = df.tail(60)
    turnover = float((recent["close"] * recent["volume"]).median()) if len(recent) else 0.0
    if t.get("currency") == "USD":
        turnover *= fx
    return costs.backtest_cost_pct(t.get("market", ""), t.get("is_etf", 0),
                                   turnover) / 2 / 100


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
        enriched = indicators.compute_indicators(df)
        prepared[sym] = {
            "df": enriched, "sig": fn(enriched, params),
            "rate": fx if tickers.get(sym, {}).get("currency") == "USD" else 1.0,
            "cost": _one_way_cost(tickers.get(sym, {}), df, fx),
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

        # ② 진입 — 자리가 남아 있고 계좌 총 리스크가 한도 안일 때만.
        # 미결 리스크 = 모든 보유가 동시에 손절에 닿았을 때의 손실 합
        open_risk = sum((p["entry_price"] - p["stop"]) * p["qty"] * p["rate"]
                        for p in open_pos.values())
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
            if not entry or pd.isna(atr) or not atr:
                continue
            stop = entry - STOP_ATR_MULT * float(atr)
            market = tickers.get(sym, {}).get("market", "")
            qty = position_size(equity, entry, stop, pr["rate"], market)
            if qty <= 0:
                continue
            # 이 포지션을 더했을 때 계좌 총 리스크가 한도를 넘으면 진입하지 않는다
            add_risk = (entry - stop) * qty * pr["rate"]
            if equity > 0 and (open_risk + add_risk) / equity * 100 > MAX_ACCOUNT_RISK_PCT:
                continue
            open_risk += add_risk
            bars = df.iloc[i + 1:]
            exit_i, exit_px, reason = resolve_exit(
                bars, 0, stop, pr["sig"]["exit"].iloc[i + 1:].tolist())
            notional = entry * qty * pr["rate"]
            open_pos[sym] = {
                "entry_date": df.index[i + 1], "entry_price": entry,
                "exit_date": bars.index[exit_i], "exit_price": exit_px,
                "exit_reason": reason, "qty": qty, "rate": pr["rate"],
                "stop": stop,  # 계좌 총 리스크 합산에 필요하다
                # 진입·청산 각각 편도 비용. 청산 노셔널로 재계산하지 않는 것은
                # 근사지만, 왕복을 통째로 빼먹는 것보다 훨씬 정확하다
                "cost_krw": notional * pr["cost"] * 2,
            }
        max_concurrent = max(max_concurrent, len(open_pos))

        # ③ 그날의 자본 — 확정 자본 + 미결 포지션 평가손익
        unrealized = 0.0
        for sym, p in open_pos.items():
            df = prepared[sym]["df"]
            if day in df.index:
                unrealized += (float(df["close"].at[day]) - p["entry_price"]) \
                    * p["qty"] * p["rate"]
        curve.append({"date": day.strftime("%Y-%m-%d"),
                      "equity_krw": round(equity + unrealized, 0)})

    return {
        "equity_curve": curve,
        "trades": trades,
        "metrics": metrics([c["equity_krw"] for c in curve], trades),
        "max_concurrent": max_concurrent,
        "universe_size": len(price_frames),
        "preset": preset,
        "params": params,
    }
