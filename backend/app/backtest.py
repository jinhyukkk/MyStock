"""저장된 일봉으로 현재 스코어링 로직을 과거에 적용해 등급별 성과를 검증한다.

각 과거 시점 d에 대해 "d까지의 데이터만"으로 스윙 점수를 계산하고
(룩어헤드 없음), d 이후 5일/20일 수익률을 등급별로 집계한다.
심리 보정은 과거 값을 알 수 없으므로 적용하지 않는다(현재 표시 점수와 동일 기준).
"""
import pandas as pd

from app import indicators, scoring

HORIZONS = (5, 20)
GRADE_ORDER = ["강력매수", "매수", "중립", "매도", "강력매도"]


def backtest_ticker(df: pd.DataFrame) -> dict | None:
    if len(df) < 150:
        return None
    enriched = indicators.compute_indicators(df)
    closes = enriched["close"]
    n = len(enriched)
    first_valid = enriched["sma120"].first_valid_index()
    if first_valid is None:
        return None
    start = enriched.index.get_loc(first_valid) + 10
    records = []
    for i in range(start, n - min(HORIZONS)):
        try:
            res = scoring.score_ticker(enriched.iloc[:i + 1])
        except ValueError:
            continue
        rec = {"grade": res["swing_grade"]}
        for h in HORIZONS:
            rec[f"fwd{h}"] = (round((closes.iloc[i + h] / closes.iloc[i] - 1) * 100, 2)
                              if i + h < n else None)
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
            entry[f"win{h}"] = round(sum(v > 0 for v in vals) / len(vals) * 100, 1) if vals else None
        grades.append(entry)
    return {
        "samples": len(records),
        "start": enriched.index[start].strftime("%Y-%m-%d"),
        "end": enriched.index[-1].strftime("%Y-%m-%d"),
        "grades": grades,
    }
