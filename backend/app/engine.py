"""포트폴리오 백테스트 엔진 — 시그널을 자본곡선으로 바꾼다.

strategy.py가 "언제"를 답하면 여기가 "얼마나"를 답한다. 두 관심사를 섞지 않는
이유는 전략이 앞으로 늘어나기 때문이다 — 엔진은 전략을 몰라야 하고, 전략은
자본을 몰라야 한다.

사이징·손절·비용은 앱이 화면에서 권하는 규칙을 그대로 쓴다. 검증한 전략과
실행할 전략이 다르면 이 백테스트는 아무것도 증명하지 못한다.
"""
import itertools
import math

import numpy as np
import pandas as pd

from app import backtest, costs, indicators, strategy

RISK_PCT = 0.01  # 거래 1건이 계좌에서 잃을 수 있는 비율 — service._risk_block과 동일
# service.MAX_WEIGHT와 같은 값. import 하면 service → engine 순환이 생겨 다시 선언한다.
# 한쪽을 바꾸면 다른 쪽도 함께 바꿔야 한다.
MAX_WEIGHT = 0.20
MAX_POSITIONS = 7  # portfolio.DEFAULT_TARGET_POSITIONS[1]과 동일
# 주의: 초기에는 이 상한에 잘 안 닿는다 — 현금 제약(코드 내 committed 체크)과
# 계좌리스크 상한(MAX_ACCOUNT_RISK_PCT)이 먼저 막는다. 다만 사이징 기준이
# 평가자본이라 계좌가 불어나면 기존 미결 리스크의 비중이 내려가 자리가 열리고,
# 그때부터는 이 상한이 실제로 작동한다.
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


def _resolve_exit_arrays(o, low, close, exit_sig, start: int,
                         stop: float | None) -> tuple[int, float, str]:
    """resolve_exit과 같은 판정을 종목 자기 배열 위에서, 절대 인덱스로 돌려준다.

    벡터화 이후 일별 루프가 쓰는 내부 버전이다. bars 슬라이스(DataFrame 복사)를
    만들지 않는 것이 존재 이유 — 진입마다 iloc 슬라이스를 만들면 그 비용이
    루프 전체를 지배한다. 판정 순서·가격 규칙은 resolve_exit과 한 글자도
    다르면 안 된다(골든 픽스처가 지킨다).
    """
    n = len(o)
    for d in range(start, n):
        if stop is not None and low[d] <= stop:
            return d, min(float(o[d]), stop), "stop"
        if exit_sig[d] and d + 1 < n:
            return d + 1, float(o[d + 1]), "signal"
    return n - 1, float(close[n - 1]), "end"


def metrics(equity: list[float], trades: list[dict]) -> dict:
    """자본곡선과 거래 목록에서 성과 지표.

    샤프의 무위험수익률은 0으로 둔다 — 화면에 그 가정을 함께 표시한다.
    승률은 비용 차감 후 손익 기준이다(0원은 승이 아니다).
    """
    n = len(equity)
    if not n:
        # 자본곡선이 비면 "최종자본 0원"이 아니라 "계산할 게 없음"이다 —
        # 0을 내려보내면 화면이 초기자본을 전액 잃은 것처럼 표시한다
        return {"cagr": None, "mdd": None, "sharpe": None,
                "win_rate": round(sum(1 for t in trades if t["pnl_krw"] > 0)
                                  / len(trades) * 100, 1) if trades else None,
                "trade_count": len(trades), "final_equity_krw": None}
    start, end = equity[0], equity[-1]
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
    """이 종목의 **왕복** 비용(비율). 진입 노셔널(entry * qty * rate)에 곱해
    총 비용을 내고, 엔진이 그것을 진입분/청산분 절반씩으로 갈라 각 시점에
    차감한다(스펙 "진입·청산 각각 차감").

    청산 시점 노셔널로 다시 계산하지 않는 것은 근사다 — 진입가와 청산가가
    크게 벌어지면(추세추종이 노리는 상황) 청산분이 과소·과대평가된다.
    편도 요율 분해가 costs에 없어 총액은 진입 노셔널 기준으로 둔다.
    """
    recent = df.tail(60)
    turnover = float((recent["close"] * recent["volume"]).median()) if len(recent) else 0.0
    if t.get("currency") == "USD":
        turnover *= fx
    return costs.backtest_cost_pct(t.get("market", ""), t.get("is_etf", 0),
                                   turnover) / 100


def run(price_frames: dict, tickers: dict, preset: str, params: dict, *,
        initial_capital_krw: float, fx: float, trade_start=None,
        membership: dict | None = None,
        regime: pd.Series | None = None) -> dict:
    """포트폴리오 백테스트 — 시그널을 계좌 단위 자본곡선으로.

    진입은 신호 익일 시가, 손절은 2×ATR, 사이징은 1% 룰. 전부 앱이 화면에서
    권하는 규칙과 같다.

    trade_start를 주면 그 날짜부터만 거래·자본곡선을 계산한다(홀드아웃 검증용).

    regime은 달력 날짜별 bool Series — False인 날은 전 종목 신규 진입을
    막는다(예: 벤치마크가 200일선 아래). 청산·손절은 레짐과 무관하다 —
    하락장에서 못 파는 필터는 리스크 장치가 아니라 족쇄다. 벤치마크
    휴장일은 직전 값을 이어받는다.

    membership은 {symbol: bool Series} — 그날 시점별 유니버스 멤버인 종목만
    신규 진입을 허용한다(universe.monthly_membership 참조). 멤버십 이탈은
    청산 사유가 아니다 — 이미 산 주식은 유니버스에서 빠져도 계좌에 남는
    실전과 같게, 보유는 신호·손절로만 끝난다.
    시그널·지표는 여전히 전체 이력으로 계산되므로 검증 구간 첫날부터 롤링
    윈도가 차 있다 — frames를 날짜로 잘라 넘기면 워밍업 구간만큼 신호가
    비어 검증이 전략에 불리하게 왜곡된다.
    """
    if preset not in strategy.PRESETS:
        raise ValueError(f"알 수 없는 전략: {preset}")
    fn = strategy.PRESETS[preset]["fn"]

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
        # 전체 지표 세트(RSI·MACD·볼린저…)는 계산하지 않는다 — 엔진이 쓰는
        # 것은 atr14뿐이고 전략 함수는 OHLC만 본다. compute_indicators를 부르면
        # 540종목 기준 run() 시간의 6할이 안 쓰는 지표 계산에 나간다.
        enriched = clean.copy()
        enriched["atr14"] = indicators.atr(clean["high"], clean["low"], clean["close"])
        prepared[sym] = {
            "df": enriched, "sig": fn(enriched, params),
            "rate": fx if tickers.get(sym, {}).get("currency") == "USD" else 1.0,
            "cost": _cost_pct(tickers.get(sym, {}), clean, fx),
        }

    # 실제로 돌린 종목(prepared)의 거래일만 합집합으로 모아 달력을 만든다 —
    # price_frames 기준으로 만들면 30봉 미만으로 걸러진 종목의 날짜까지
    # 곡선에 패딩되어 CAGR 분모(거래일수)가 부풀려진다. 이 달력과 유니버스는
    # 반환값에 담아 service가 비교선에 그대로 넘긴다(단일 진실 원천).
    calendar = sorted(set().union(*(set(pr["df"].index) for pr in prepared.values()))) \
        if prepared else []
    if trade_start is not None:
        # 달력만 자른다 — prepared의 시그널은 전체 이력 그대로다. 진입 후보
        # 스캔이 달력을 돌므로 이 필터만으로 trade_start 이전 거래가 사라지고,
        # 자본곡선·CAGR 분모도 검증 구간 길이로 맞춰진다.
        calendar = [d for d in calendar if d >= trade_start]

    # ── 배열 준비 — 일별 루프의 pandas 스칼라 조회(.at/get_loc/in index)가
    # 전체 시간의 8할이라(540종목 실측 9.3s/11.2s), 종목별 own-index numpy
    # 배열 + 달력→own 위치 매핑으로 펼쳐 둔다. 진입·청산 판정은 여전히
    # "그 종목 자기 봉" 위에서 돈다 — 달력 정렬 배열로 판정하면 휴장 NaN이
    # 끼어 손절 판정일이 달라진다(골든 픽스처가 지키는 불변).
    cal_index = pd.DatetimeIndex(calendar)
    syms = list(prepared)
    n_days = len(calendar)
    enter_mat = np.zeros((n_days, len(syms)), dtype=bool)
    strength_mat = np.full((n_days, len(syms)), -np.inf)
    close_mat = np.full((n_days, len(syms)), np.nan)
    arrs = []
    for j, sym in enumerate(syms):
        pr = prepared[sym]
        df, sig = pr["df"], pr["sig"]
        idxr = df.index.get_indexer(cal_index)  # 휴장일은 -1
        valid = idxr >= 0
        own = {
            "open": df["open"].to_numpy(dtype=float),
            "low": df["low"].to_numpy(dtype=float),
            "close": df["close"].to_numpy(dtype=float),
            "atr": df["atr14"].to_numpy(dtype=float),
            "exit": sig["exit"].to_numpy(dtype=bool),
            "dates": df.index,
            "cal2own": idxr,
            "rate": pr["rate"], "cost": pr["cost"],
        }
        arrs.append(own)
        st = sig["strength"].to_numpy(dtype=float)
        vi = idxr[valid]
        ent = sig["enter"].to_numpy(dtype=bool)
        if membership is not None:
            # 멤버십은 진입만 막는다 — exit 신호·손절 판정에는 걸지 않는다
            mem = membership.get(sym)
            mem_own = mem.reindex(df.index, fill_value=False).to_numpy(dtype=bool) \
                if mem is not None else np.zeros(len(df), dtype=bool)
            ent = ent & mem_own
        enter_mat[valid, j] = ent[vi]
        # NaN 강도는 기존 로직과 동일하게 -inf(최하 순위)로 둔다
        strength_mat[valid, j] = np.where(np.isnan(st[vi]), -np.inf, st[vi])
        close_mat[valid, j] = own["close"][vi]

    if regime is not None and n_days:
        # 벤치 휴장일은 직전 레짐 유지(ffill) — False로 채우면 벤치가 쉰 날마다
        # 전 종목 진입이 이유 없이 막힌다. 이력 시작 전(NaN)은 판단 근거가
        # 없으므로 진입을 막는 쪽(False)이 보수적이다.
        reg = regime.reindex(cal_index).ffill().fillna(False).to_numpy(dtype=bool)
        enter_mat &= reg[:, None]

    equity = initial_capital_krw
    open_pos: dict[str, dict] = {}
    trades: list[dict] = []
    curve: list[dict] = []
    max_concurrent = 0

    for d, day in enumerate(calendar):
        # ⓪ 오늘 체결되는 진입의 편도 비용을 먼저 뺀다. 신호일에 빼면 아직
        # 존재하지 않는 포지션의 비용이 하루 먼저 자본곡선에 찍힌다.
        # ①보다 앞에 둬야 진입 당일 손절로 나가는 포지션도 비용을 낸다.
        for p in open_pos.values():
            if p["entry_date"] == day:
                equity -= p["entry_cost_krw"]

        # ① 청산 먼저 — 같은 날 나가고 들어오는 자리를 비워 준다
        for sym in list(open_pos):
            p = open_pos[sym]
            if day < p["exit_date"]:
                continue
            gross = (p["exit_price"] - p["entry_price"]) * p["qty"] * p["rate"]
            # 진입분은 진입 시점에 이미 뺐다 — 여기서는 청산분만 뺀다
            equity += gross - (p["cost_krw"] - p["entry_cost_krw"])
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

        # ①-b 사이징 기준 자본 = 확정 자본 + 전일 종가 기준 평가손익.
        # equity는 실현 자본이라 보유가 하락 중이어도 그대로다 — 그 값으로 1%를
        # 계산하면 드로다운 중에 계속 크게 산다. last_mark는 항상 그날 이전
        # 종가라 룩어헤드가 아니다.
        mark_equity = equity + sum(
            (p["last_mark"] - p["entry_price"]) * p["qty"] * p["rate"]
            for p in open_pos.values() if p["entry_date"] <= day)

        # ② 진입 — 자리·계좌 총 리스크·현금이 한도 안일 때만.
        open_risk = sum((p["entry_price"] - p["stop"]) * p["qty"] * p["rate"]
                        for p in open_pos.values())
        # 이미 현금에서 나갔거나 나갈 것이 확정된 금액 — 상세는 커밋 이력의
        # 원 구현 주석 참조(취득원가 합 + 미체결 진입 비용, 현금 계좌 제약)
        committed = sum(p["notional"] for p in open_pos.values()) \
            + sum(p["entry_cost_krw"] for p in open_pos.values()
                  if p["entry_date"] > day)
        # 그날의 진입 후보를 신호 강도 내림차순으로 자른다 — 삽입 순서를 쓰면
        # 결과가 종목 이름에 의존한다. 동점은 안정 정렬로 기존 순서 유지.
        cands = [(syms[j], j, strength_mat[d, j])
                 for j in np.nonzero(enter_mat[d])[0] if syms[j] not in open_pos]
        cands.sort(key=lambda c: c[2], reverse=True)

        for sym, j, _strength in cands:
            if len(open_pos) >= MAX_POSITIONS:
                break
            a = arrs[j]
            i = int(a["cal2own"][d])
            if i + 1 >= len(a["open"]):
                continue  # 마지막 봉에서는 낼 수 있는 주문이 없다
            entry = float(a["open"][i + 1])
            atr = float(a["atr"][i])
            # NaN 시가(거래정지 등)를 흘리면 손절가도 NaN이 되고 NaN 비교는
            # 항상 False라 뒤의 가드를 다 통과한다 — 여기서 먼저 막는다
            if math.isnan(entry) or entry <= 0 or math.isnan(atr) or atr <= 0:
                continue
            stop = entry - STOP_ATR_MULT * atr
            market = tickers.get(sym, {}).get("market", "")
            qty = position_size(mark_equity, entry, stop, a["rate"], market)
            if qty <= 0:
                continue
            notional = entry * qty * a["rate"]
            # 비용은 진입분/청산분 절반씩, 각 시점에 차감(타이밍 왜곡 방지 —
            # 원 구현 주석 참조)
            cost_krw = notional * a["cost"]
            entry_cost = cost_krw / 2  # 실제 차감은 진입일(⓪)에 일어난다
            # 현금 게이트만 equity 기준 — 미실현이익은 팔기 전엔 매수 여력이 아니다
            if notional + entry_cost > equity - committed:
                continue  # 잔여 현금 초과 — 이 진입은 건너뛴다
            add_risk = (entry - stop) * qty * a["rate"]
            if mark_equity > 0 and \
                    (open_risk + add_risk) / mark_equity * 100 > MAX_ACCOUNT_RISK_PCT:
                continue
            open_risk += add_risk
            committed += notional + entry_cost
            exit_i, exit_px, reason = _resolve_exit_arrays(
                a["open"], a["low"], a["close"], a["exit"], i + 1, stop)
            if reason == "end" and tickers.get(sym, {}).get("delisting_date"):
                # 폐지 종목의 "데이터 끝" 보유는 만기 보유가 아니라 강제 청산이다.
                # 마지막 종가 청산은 실손실(정리매매 급락·회수불가)을 과소평가하는
                # 근사다 — 방향은 스펙에 기록돼 있다.
                reason = "delisted"
            open_pos[sym] = {
                "entry_date": a["dates"][i + 1], "entry_price": entry,
                "exit_date": a["dates"][exit_i], "exit_price": exit_px,
                "exit_reason": reason, "qty": qty, "rate": a["rate"],
                "stop": stop,  # 계좌 총 리스크 합산에 필요하다
                "notional": notional,  # 보유 노셔널 합산에 필요하다
                "cost_krw": cost_krw, "entry_cost_krw": entry_cost,
                "last_mark": entry,  # 직전 유효 종가 — 휴장일엔 이 값을 이어받는다
                "j": j,  # close_mat 열 위치 — 마킹 루프가 쓴다
            }

        # 실제로 보유 중인 포지션만 — 오늘 막 진입한 포지션은 entry_date가
        # 내일이라 아직 보유가 아니다(룩어헤드 방지)
        held = {sym: p for sym, p in open_pos.items() if p["entry_date"] <= day}
        max_concurrent = max(max_concurrent, len(held))

        # ③ 그날의 자본 — 확정 자본 + 보유 평가손익. 휴장일(NaN)은 직전 유효
        # 종가(last_mark)를 이어받는다 — 0으로 두면 가짜 갭이 생긴다.
        unrealized = 0.0
        for sym, p in held.items():
            c = close_mat[d, p["j"]]
            if not math.isnan(c):
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
        # 비교선이 전략과 같은 달력·같은 종목 집합 위에 서게 하려고 내보낸다.
        # 호출부가 이걸 다시 계산하면 우연히 같을 뿐 계약이 아니고, 길이가
        # 갈라져도 차트는 조용히 날짜를 어긋나게 그린다. service가 pop한다.
        "_used": {"calendar": calendar, "symbols": list(prepared)},
    }


TRAIN_FRAC = 0.7  # 홀드아웃 분리 비율 — 앞 70% 학습, 뒤 30% 검증
MIN_OPTIMIZE_DAYS = 120  # 이보다 짧으면 검증 구간이 통계적으로 무의미하다


def optimize(price_frames: dict, tickers: dict, preset: str, *,
             initial_capital_krw: float, fx: float) -> dict:
    """홀드아웃 그리드 서치 — 학습 구간에서 탐색하고 검증 구간 성과로 줄 세운다.

    학습·검증을 같은 구간으로 두고 CAGR을 최대화하면 과거에만 맞는 조합이
    1등이 된다(오버피팅). 날짜로 갈라 두면 학습에서만 좋고 검증에서 무너지는
    조합이 표에서 그대로 드러난다. 정렬은 검증 샤프 내림차순 — CAGR로 줄
    세우면 변동성을 무시하고 한 방 크게 맞은 조합이 앞에 선다.
    """
    if preset not in strategy.PRESETS:
        raise ValueError(f"알 수 없는 전략: {preset}")
    grids = {k: v["grid"] for k, v in strategy.PRESETS[preset]["params"].items()}

    # split은 전 종목 유효 거래일 합집합에서 잡는다 — 종목 하나 기준으로 잡으면
    # 상장일이 다른 종목들의 학습/검증 비율이 제각각이 된다
    days = sorted(set().union(*(
        set(df.dropna(subset=["close"]).index) for df in price_frames.values()))) \
        if price_frames else []
    if len(days) < MIN_OPTIMIZE_DAYS:
        return {"split_date": None, "train_days": 0, "valid_days": 0, "results": []}
    split_i = int(len(days) * TRAIN_FRAC)
    split, valid_start = days[split_i - 1], days[split_i]

    # 학습 프레임은 split까지 절단 — 검증 구간 가격이 학습 성과에 새어들지 않게.
    # 검증은 전체 프레임 + trade_start — 워밍업 유지 이유는 run() 주석 참조.
    train_frames = {s: df[df.index <= split] for s, df in price_frames.items()}

    results = []
    for combo in itertools.product(*grids.values()):
        params = dict(zip(grids.keys(), combo))
        tr = run(train_frames, tickers, preset, params,
                 initial_capital_krw=initial_capital_krw, fx=fx)
        va = run(price_frames, tickers, preset, params,
                 initial_capital_krw=initial_capital_krw, fx=fx,
                 trade_start=valid_start)
        results.append({"params": params,
                        "train": tr["metrics"], "valid": va["metrics"]})
    # 샤프 None(거래 없음 등)은 최하위로 — 0으로 치면 손실 조합보다 위에 선다
    results.sort(key=lambda r: (r["valid"]["sharpe"] is None,
                                -(r["valid"]["sharpe"] or 0.0)))
    return {
        "split_date": split.strftime("%Y-%m-%d"),
        "valid_start": valid_start.strftime("%Y-%m-%d"),
        "train_days": split_i,
        "valid_days": len(days) - split_i,
        "results": results,
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


def walkforward(price_frames: dict, tickers: dict, preset: str, *,
                initial_capital_krw: float, fx: float, membership=None,
                bench_frame: pd.DataFrame | None = None, folds: int = 5,
                min_train_frac: float = 0.4, regime: pd.Series | None = None,
                progress_cb=None) -> dict:
    """anchored 워크포워드 — 폴드마다 학습에서 고른 조합을 다음 구간에서 실행한다.

    단일 홀드아웃(optimize)은 검증 구간 레짐이 순위를 지배한다 — 실측에서
    검증 구간 KOSPI가 CAGR 66%라 모든 조합이 이겼다. 검증 창을 굴려 상승장·
    하락장을 모두 검증에 넣고, 판정은 절대 CAGR이 아니라 벤치마크 대비
    초과수익과 폴드 간 일관성으로 한다.

    창은 anchored(확장): 학습은 항상 데이터 시작부터, 검증만 뒤로 구른다.
    rolling을 안 쓰는 이유는 이력이 약 6년뿐이라 고정폭 학습창은 폴드당
    표본이 수십 거래로 떨어져 그리드가 다시 노이즈를 고르기 때문이다(스펙).

    검증 구간에 걸친 미청산 포지션은 구간 끝에서 end로 닫힌다 — 다음 폴드로
    이월하지 않는 근사이며, 폴드 수를 늘릴수록 경계 효과가 커진다.
    """
    if preset not in strategy.PRESETS:
        raise ValueError(f"알 수 없는 전략: {preset}")
    grids = {k: v["grid"] for k, v in strategy.PRESETS[preset]["params"].items()}
    combos = [dict(zip(grids.keys(), c))
              for c in itertools.product(*grids.values())]

    days = sorted(set().union(*(
        set(df.dropna(subset=["close"]).index) for df in price_frames.values()))) \
        if price_frames else []
    if len(days) < MIN_OPTIMIZE_DAYS:
        return {"folds": [], "summary": None, "stitched_curve": [],
                "stitched_metrics": metrics([], []), "stitched_bench": []}

    # 앞 min_train_frac는 최소 학습 구간 — 검증 영역을 folds 등분한다
    valid_zone = days[int(len(days) * min_train_frac):]
    segments = [seg for seg in
                (list(a) for a in np.array_split(np.array(valid_zone), folds))
                if len(seg)]
    total_steps = len(segments) * (len(combos) + 1)
    done = 0

    fold_rows = []
    stitched, stitched_bench = [], []
    scale = 1.0
    bench_scale = 1.0
    for k, seg in enumerate(segments):
        valid_start, valid_end = pd.Timestamp(seg[0]), pd.Timestamp(seg[-1])
        train_frames = {s: df[df.index < valid_start]
                        for s, df in price_frames.items()}
        best, best_sharpe = None, None
        for params in combos:
            tr = run(train_frames, tickers, preset, params,
                     initial_capital_krw=initial_capital_krw, fx=fx,
                     membership=membership, regime=regime)
            sh = tr["metrics"]["sharpe"]
            # None(거래 없음)은 후보에서 제외 — 0으로 치면 손실 조합보다 위에 선다
            if sh is not None and (best_sharpe is None or sh > best_sharpe):
                best, best_sharpe = params, sh
            done += 1
            if progress_cb:
                progress_cb(done, total_steps)
        if best is None:
            best = combos[0]  # 전 조합 무거래 — 기본 조합으로 검증만 남긴다
        # 검증 프레임은 valid_end까지 절단 — 다음 폴드 가격이 새어들지 않게.
        # valid_start 이전은 남긴다(워밍업, run 주석 참조).
        va_frames = {s: df[df.index <= valid_end]
                     for s, df in price_frames.items()}
        va = run(va_frames, tickers, preset, best,
                 initial_capital_krw=initial_capital_krw, fx=fx,
                 trade_start=valid_start, membership=membership, regime=regime)
        done += 1
        if progress_cb:
            progress_cb(done, total_steps)
        used = va.pop("_used")
        bench_cagr = None
        bench_curve = []
        if bench_frame is not None and not bench_frame.empty:
            # 같은 검증 달력 위에서 계산해야 한다 — 달력이 갈라지면 초과수익이
            # 기간 차이를 재게 된다(스펙)
            bench_curve = buy_and_hold(
                {"BENCH": bench_frame[bench_frame.index <= valid_end]},
                {"BENCH": {"market": "KR", "currency": "KRW", "is_etf": 0}},
                initial_capital_krw, fx, used["calendar"])
            bench_cagr = metrics([p["equity_krw"] for p in bench_curve], [])["cagr"]
        v = va["metrics"]
        excess = (round(v["cagr"] - bench_cagr, 2)
                  if v["cagr"] is not None and bench_cagr is not None else None)
        fold_rows.append({
            "fold": k + 1,
            "train_end": (valid_start - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            "valid_start": valid_start.strftime("%Y-%m-%d"),
            "valid_end": valid_end.strftime("%Y-%m-%d"),
            "params": best, "valid": v, "bench_cagr": bench_cagr,
            "excess_pct": excess,
        })
        # 체인링크 — 각 폴드는 초기자본에서 새로 시작하므로, 직전 폴드
        # 종료자본/초기자본 배율을 곱해 하나의 곡선으로 잇는다
        for pt in va["equity_curve"]:
            stitched.append({"date": pt["date"],
                             "equity_krw": round(pt["equity_krw"] * scale, 0)})
        if va["equity_curve"]:
            scale *= va["equity_curve"][-1]["equity_krw"] / initial_capital_krw
        for pt in bench_curve:
            stitched_bench.append({"date": pt["date"],
                                   "equity_krw": round(pt["equity_krw"] * bench_scale, 0)})
        if bench_curve:
            bench_scale *= bench_curve[-1]["equity_krw"] / initial_capital_krw

    excesses = sorted(f["excess_pct"] for f in fold_rows
                      if f["excess_pct"] is not None)
    median_excess = None
    if excesses:
        m = len(excesses) // 2
        median_excess = round(excesses[m] if len(excesses) % 2
                              else (excesses[m - 1] + excesses[m]) / 2, 2)
    distinct = {tuple(sorted(f["params"].items())) for f in fold_rows}
    summary = {
        "median_excess_pct": median_excess,
        "positive_folds": sum(1 for f in fold_rows
                              if (f["excess_pct"] or 0) > 0 and f["excess_pct"] is not None),
        "total_folds": len(fold_rows),
        "param_stability": {
            "distinct_combos": len(distinct),
            # 폴드마다 최적값이 튀면 그 파라미터에는 의미가 없다는 증거(스펙)
            "note": ("안정적" if len(distinct) == 1 else
                     "보통" if len(distinct) <= max(2, len(fold_rows) // 2) else
                     "불안정 — 폴드마다 최적 파라미터가 달라 채택 비추천"),
        },
    }
    return {"folds": fold_rows, "summary": summary,
            "stitched_curve": stitched,
            "stitched_metrics": metrics([c["equity_krw"] for c in stitched], []),
            "stitched_bench": stitched_bench}
