"""저장된 일봉으로 현재 스코어링 로직을 과거에 적용해 등급별 성과를 검증한다.

각 과거 시점 d에 대해 "d까지의 데이터만"으로 스윙 점수를 계산하고
(룩어헤드 없음), d 이후 5일/20일 수익률을 등급별로 집계한다.
심리 보정은 과거 값을 알 수 없으므로 적용하지 않는다(현재 표시 점수와 동일 기준).
"""
import pandas as pd

from app import indicators, scoring

HORIZONS = (5, 20)
GRADE_ORDER = ["강력매수", "매수", "중립", "매도", "강력매도"]
COST_PCT = 0.3  # 왕복 수수료+슬리피지 근사 (%p) — 순수익률 = 평균 - COST_PCT


def backtest_ticker(df: pd.DataFrame, bench: pd.Series | None = None,
                    bench_label: str | None = None) -> dict | None:
    if len(df) < 150:
        return None
    enriched = indicators.compute_indicators(df)
    closes = enriched["close"]
    n = len(enriched)
    first_valid = enriched["sma120"].first_valid_index()
    if first_valid is None:
        return None
    # 벤치마크 종가를 종목 거래일에 맞춰 정렬 (휴장일 차이는 직전 값으로 보간)
    b = None
    if bench is not None and not bench.empty:
        b = bench.reindex(enriched.index, method="ffill")
    start = enriched.index.get_loc(first_valid) + 10
    records = []
    for i in range(start, n - min(HORIZONS)):
        try:
            res = scoring.score_ticker(enriched.iloc[:i + 1])
        except ValueError:
            continue
        rec = {"grade": res["swing_grade"]}
        for h in HORIZONS:
            if i + h >= n:
                rec[f"fwd{h}"] = None
                continue
            fwd = (closes.iloc[i + h] / closes.iloc[i] - 1) * 100
            rec[f"fwd{h}"] = round(fwd, 2)
            if b is not None and pd.notna(b.iloc[i]) and pd.notna(b.iloc[i + h]) and b.iloc[i]:
                rec[f"ex{h}"] = round(fwd - (b.iloc[i + h] / b.iloc[i] - 1) * 100, 2)
        records.append(rec)
    if not records:
        return None

    grades = []
    for g in GRADE_ORDER:
        rows = [r for r in records if r["grade"] == g]
        if not rows:
            continue
        entry = {"grade": g, "n": len(rows)}
        for h in HORIZONS:
            vals = [r[f"fwd{h}"] for r in rows if r[f"fwd{h}"] is not None]
            entry[f"avg_fwd{h}"] = round(sum(vals) / len(vals), 2) if vals else None
            entry[f"avg_net{h}"] = round(entry[f"avg_fwd{h}"] - COST_PCT, 2) if vals else None
            entry[f"win{h}"] = round(sum(v > 0 for v in vals) / len(vals) * 100, 1) if vals else None
            exs = [r[f"ex{h}"] for r in rows if r.get(f"ex{h}") is not None]
            entry[f"avg_excess{h}"] = round(sum(exs) / len(exs), 2) if exs else None
        grades.append(entry)
    return {
        "samples": len(records),
        "start": enriched.index[start].strftime("%Y-%m-%d"),
        "end": enriched.index[-1].strftime("%Y-%m-%d"),
        "bench_label": bench_label if b is not None else None,
        "cost_pct": COST_PCT,
        "grades": grades,
    }
