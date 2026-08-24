"""저장된 일봉으로 현재 스코어링 로직을 과거에 적용해 등급별 성과를 검증한다.

각 과거 시점 d에 대해 "d까지의 데이터만"으로 점수를 계산하고(룩어헤드 없음),
d 이후의 수익률을 등급별로 집계한다. 심리 보정은 과거 값을 알 수 없으므로
적용하지 않는다(현재 표시 점수와 동일 기준).

검증 규칙을 앱이 권장하는 실행 규칙에 맞춘다:

- **진입가는 익일 시가.** 신호를 만든 종가에 그 종가로 체결한다고 가정하면
  실제로 낼 수 없는 주문으로 성과를 계산하게 된다.
- **청산은 2×ATR 손절 또는 h거래일 종가.** 앱은 손절을 권장하는데 백테스트가
  무조건 보유였다면, 지시대로 손절을 건 사용자는 표시된 수익률을 구조적으로
  받을 수 없다. 손절을 이식해야 검증한 전략과 실행하는 전략이 같아진다.
- **표본은 비중첩 에피소드 수로 센다.** 20일 forward 수익률은 인접일끼리 최대
  19일이 겹치므로, 신호일 수를 독립 표본으로 쓰면 표준오차가 과소 계상된다.
"""
import math

import pandas as pd

from app import indicators, scoring

HORIZONS = (5, 20)          # 스윙 등급 검증 구간
LONG_HORIZONS = (60, 120)   # 중장기 등급 검증 구간
GRADE_ORDER = ["강력매수", "매수", "중립", "매도", "강력매도"]
COST_PCT = 0.3  # 시장·유동성을 모를 때의 폴백 (%p). 실제로는 costs.backtest_cost_pct 사용
STOP_ATR_MULT = 2.0  # service._risk_block의 손절 폭과 동일하게 유지할 것
MIN_EPISODES = 20  # 비중첩 에피소드가 이보다 적으면 수치를 신뢰 구간째로 숨긴다
VERSION = 8  # 결과 스키마 버전 — 올리면 저장된 백테스트 캐시가 무효화된다


def _exit_price(o, h_, l_, c_, entry_i: int, exit_i: int, stop: float | None):
    """진입(entry_i 시가) 이후 exit_i까지 보유. 저가가 손절선을 건드리면 그 자리에서 청산.

    갭 하락으로 시가가 이미 손절선 아래면 시가 체결 — 손절선 체결을 가정하면
    갭 리스크만큼 성과가 낙관적으로 부풀려진다.
    """
    if stop is not None:
        for d in range(entry_i, exit_i + 1):
            if l_[d] <= stop:
                return (min(o[d], stop), True)
    return (c_[exit_i], False)


def _episodes(indices: list[int], horizon: int) -> int:
    """서로 겹치지 않는 신호 묶음 수 — horizon일 안에 이어지는 신호는 하나로 센다."""
    count, last = 0, None
    for i in indices:
        if last is None or i - last >= horizon:
            count += 1
            last = i
    return count


def _stdev(vals: list[float]) -> float | None:
    if len(vals) < 2:
        return None
    mean = sum(vals) / len(vals)
    return math.sqrt(sum((v - mean) ** 2 for v in vals) / (len(vals) - 1))


def _aggregate(records: list[dict], grade_key: str, horizons, cost_pct: float) -> tuple[list, list]:
    grades, missing = [], []
    for g in GRADE_ORDER:
        rows = [r for r in records if r[grade_key] == g]
        if not rows:
            # 관측 0회를 조용히 빼면 "데이터가 아직 안 쌓였다"로 읽힌다 — 명시적으로 알린다
            missing.append(g)
            continue
        entry = {"grade": g, "n": len(rows)}
        for h in horizons:
            vals = [r[f"fwd{h}"] for r in rows if r.get(f"fwd{h}") is not None]
            idxs = [r["i"] for r in rows if r.get(f"fwd{h}") is not None]
            entry[f"episodes{h}"] = _episodes(idxs, h)
            if not vals:
                for k in ("avg_fwd", "avg_net", "avg_stress", "avg_hold", "win",
                          "win_gross", "se", "stop_rate", "avg_excess"):
                    entry[f"{k}{h}"] = None
                entry[f"insufficient{h}"] = True
                continue
            avg = sum(vals) / len(vals)
            entry[f"avg_fwd{h}"] = round(avg, 2)
            entry[f"avg_net{h}"] = round(avg - cost_pct, 2)
            # 비용 가정이 2배였다면 이 등급이 여전히 플러스인가. 5일 +0.3%대 엣지는
            # 스프레드 가정 하나로 사라진다 — 그 취약함을 표에서 바로 보이게 한다.
            entry[f"avg_stress{h}"] = round(avg - cost_pct * 2, 2)
            # 손절 없이 h일 보유했을 때 — 손절이 얼마를 깎았는지 비교용
            holds = [r[f"hold{h}"] for r in rows if r.get(f"hold{h}") is not None]
            entry[f"avg_hold{h}"] = round(sum(holds) / len(holds), 2) if holds else None
            # 승률도 비용 차감 후 기준 — 0~COST_PCT 구간의 "승"은 실제로는 패다
            entry[f"win{h}"] = round(sum(v > cost_pct for v in vals) / len(vals) * 100, 1)
            entry[f"win{h}_gross"] = round(sum(v > 0 for v in vals) / len(vals) * 100, 1)
            stops = [r[f"stopped{h}"] for r in rows if r.get(f"fwd{h}") is not None]
            entry[f"stop_rate{h}"] = round(sum(stops) / len(stops) * 100, 1) if stops else None
            # 표준오차는 신호일 수가 아니라 비중첩 에피소드 수로 나눈다
            sd = _stdev(vals)
            eps = entry[f"episodes{h}"]
            entry[f"se{h}"] = round(sd / math.sqrt(eps), 2) if sd is not None and eps else None
            entry[f"insufficient{h}"] = eps < MIN_EPISODES
            exs = [r[f"ex{h}"] for r in rows if r.get(f"ex{h}") is not None]
            entry[f"avg_excess{h}"] = round(sum(exs) / len(exs), 2) if exs else None
        grades.append(entry)
    return grades, missing


BUY_GRADES = ("강력매수", "매수")
SELL_GRADES = ("매도", "강력매도")


def discrimination(grades: list[dict], horizon: int) -> dict | None:
    """등급 판별력 — 매수 등급 성적에서 매도 등급 성적을 뺀 값(%p, 비용 차감 후).

    상승장 구간에서는 모든 등급의 h일 평균이 플러스로 나온다. 요약 카드가
    "이 등급 승률 62%"만 보여주면 그 62%가 중립 등급 50%와 다를 게 없다는 사실,
    나아가 매도 등급이 매수보다 나았다는 사실이 아래 표 속에 묻힌다.
    표본이 모자라 수치를 감춘 칸은 계산에서도 뺀다 — 감춘 값을 근거로 쓸 수는 없다.
    """
    def side(names):
        vals = [g[f"avg_net{horizon}"] for g in grades
                if g["grade"] in names
                and g.get(f"insufficient{horizon}") is not True
                and g.get(f"avg_net{horizon}") is not None]
        # 집계값은 numpy float으로 들어온다 — 그대로 두면 비교 결과가 numpy.bool_ 이
        # 되어 결과를 캐시에 저장할 때 JSON 직렬화가 깨지고 API 전체가 500이 된다
        return round(float(sum(vals) / len(vals)), 2) if vals else None

    buy, sell = side(BUY_GRADES), side(SELL_GRADES)
    if buy is None or sell is None:
        return None
    spread = round(buy - sell, 2)
    return {"horizon": horizon, "buy_net": buy, "sell_net": sell,
            "spread": spread, "discriminates": bool(spread > 0)}


def backtest_ticker(df: pd.DataFrame, bench: pd.DataFrame | pd.Series | None = None,
                    bench_label: str | None = None,
                    cost_pct: float | None = None) -> dict | None:
    if len(df) < 150:
        return None
    cost_pct = COST_PCT if cost_pct is None else cost_pct
    enriched = indicators.compute_indicators(df)
    n = len(enriched)
    first_valid = enriched["sma120"].first_valid_index()
    if first_valid is None:
        return None
    opens = enriched["open"].to_numpy(dtype=float)
    highs = enriched["high"].to_numpy(dtype=float)
    lows = enriched["low"].to_numpy(dtype=float)
    closes = enriched["close"].to_numpy(dtype=float)
    atrs = enriched["atr14"].to_numpy(dtype=float)
    # 벤치마크를 종목 거래일에 맞춰 정렬 (휴장일 차이는 직전 값으로 보간)
    b_open = b_close = None
    if bench is not None and len(bench):
        bf = bench.to_frame("close") if isinstance(bench, pd.Series) else bench
        bf = bf.reindex(enriched.index, method="ffill")
        b_close = bf["close"].to_numpy(dtype=float)
        b_open = (bf["open"].to_numpy(dtype=float) if "open" in bf else b_close)

    all_horizons = tuple(sorted(set(HORIZONS + LONG_HORIZONS)))
    start = enriched.index.get_loc(first_valid) + 10
    records = []
    # i는 신호일, i+1 시가에 진입 — 마지막 봉에서는 낼 수 있는 주문이 없다
    for i in range(start, n - 1 - min(all_horizons)):
        try:
            res = scoring.score_ticker(enriched.iloc[:i + 1])
        except ValueError:
            continue
        entry_i = i + 1
        entry = opens[entry_i]
        if not entry:
            continue
        atr = atrs[i]
        stop = entry - STOP_ATR_MULT * atr if pd.notna(atr) and atr else None
        rec = {"i": i, "swing": res["swing_grade"], "longterm": res["longterm_grade"]}
        for h in all_horizons:
            exit_i = i + h
            if exit_i >= n:
                rec[f"fwd{h}"] = None
                continue
            px, stopped = _exit_price(opens, highs, lows, closes, entry_i, exit_i, stop)
            rec[f"fwd{h}"] = round((px / entry - 1) * 100, 2)
            rec[f"hold{h}"] = round((closes[exit_i] / entry - 1) * 100, 2)
            rec[f"stopped{h}"] = stopped
            if b_close is not None and pd.notna(b_open[entry_i]) and pd.notna(b_close[exit_i]) \
                    and b_open[entry_i]:
                bench_ret = (b_close[exit_i] / b_open[entry_i] - 1) * 100
                # 벤치마크는 지수 보유라 매매비용이 없다 — 종목 쪽 왕복 비용을 빼지
                # 않고 뺄셈하면 초과수익이 cost_pct만큼 낙관적으로 부풀려진다.
                rec[f"ex{h}"] = round(rec[f"fwd{h}"] - cost_pct - bench_ret, 2)
        records.append(rec)
    if not records:
        return None

    grades, missing = _aggregate(records, "swing", HORIZONS, cost_pct)
    long_grades, long_missing = _aggregate(records, "longterm", LONG_HORIZONS, cost_pct)
    # 이 관측 기간이 물리적으로 만들 수 있는 최대 비중첩 표본 수.
    # 이게 MIN_EPISODES보다 작으면 "데이터가 더 쌓이면 채워진다"가 아니라
    # 지금 보유한 기간으로는 통계적 검증 자체가 불가능하다는 뜻이다.
    max_episodes = {str(h): len(records) // h + 1 for h in all_horizons}
    return {
        "version": VERSION,
        "samples": len(records),
        "start": enriched.index[start].strftime("%Y-%m-%d"),
        "end": enriched.index[-1].strftime("%Y-%m-%d"),
        "bench_label": bench_label if b_close is not None else None,
        "cost_pct": cost_pct,
        # 왕복 비용을 한 숫자로만 고지하면 슬리피지가 들어갔는지 알 수 없다.
        # 들어갔다는 사실과, 그 가정이 틀렸을 때의 결과를 함께 밝힌다.
        "cost_breakdown": {
            "total_pct": cost_pct,
            "stress_pct": round(cost_pct * 2, 4),
            "note": ("수수료·세금에 유동성 기반 호가 슬리피지를 더한 값입니다. "
                     "실제 체결은 이보다 밀릴 수 있어 비용 2배 가정도 함께 봅니다."),
        },
        "stop_atr_mult": STOP_ATR_MULT,
        "min_episodes": MIN_EPISODES,
        "max_episodes": max_episodes,
        "horizons": list(HORIZONS),
        "long_horizons": list(LONG_HORIZONS),
        "entry_rule": "신호 다음 거래일 시가 체결",
        "excess_net": True,  # 초과수익도 왕복 비용 차감 후 (벤치마크는 비용 0)
        "exit_rule": f"{STOP_ATR_MULT:g}×ATR 손절 터치 시 청산, 아니면 보유 기간 종가",
        "grades": grades,
        # 등급이 방향을 가르는지 한 숫자로 — 상승장에서는 전 등급이 플러스로 나온다
        "discrimination": {str(h): discrimination(grades, h) for h in HORIZONS},
        "missing_grades": missing,
        "longterm_grades": long_grades,
        "missing_longterm_grades": long_missing,
    }
