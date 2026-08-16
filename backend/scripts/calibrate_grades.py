"""등급 임계값 재보정 — scoring.SWING_CUTS / LONGTERM_CUTS의 근거를 다시 만든다.

저장된 일봉 전체에 현재 스코어링을 룩어헤드 없이 적용해 점수 분포를 뽑고,
상·하위 5%/20% 분위수를 출력한다. 그 값을 scoring.py의 상수에 반영하면 된다.

    python -m scripts.calibrate_grades

임계값을 점수의 절대 크기가 아니라 분위수로 잡는 이유: 가중치·지표 조합에서 나오는
실제 점수 범위는 이론적 최대치보다 훨씬 좁고(스윙 실측 [-37, +35.5] vs 이론 72.5),
그걸 모르고 ±60을 쓰면 최상위 등급이 영원히 발생하지 않는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from app import db, indicators, scoring

QUANTILES = (5, 20, 80, 95)


def collect(conn) -> tuple[list, list]:
    swing, longterm = [], []
    symbols = [r["symbol"] for r in conn.execute(
        "SELECT DISTINCT symbol FROM price_cache WHERE symbol NOT LIKE 'BENCH:%'")]
    for s in symbols:
        df = db.load_prices(conn, s, limit=1100)
        if len(df) < 150:
            continue
        enriched = indicators.compute_indicators(df)
        first = enriched["sma120"].first_valid_index()
        if first is None:
            continue
        for i in range(enriched.index.get_loc(first) + 10, len(enriched)):
            try:
                r = scoring.score_ticker(enriched.iloc[:i + 1])
            except ValueError:
                continue
            swing.append(r["swing_score"])
            longterm.append(r["longterm_score"])
    return swing, longterm


def main() -> None:
    conn = db.get_conn()
    swing, longterm = collect(conn)
    if not swing:
        print("가격 데이터 없음 — 먼저 갱신하세요")
        return
    for name, values, current in (("SWING_CUTS", swing, scoring.SWING_CUTS),
                                  ("LONGTERM_CUTS", longterm, scoring.LONGTERM_CUTS)):
        a = np.array(values)
        p5, p20, p80, p95 = (np.percentile(a, q) for q in QUANTILES)
        print(f"\n{name}  n={len(a)}  범위=[{a.min():.1f}, {a.max():.1f}]  평균={a.mean():.2f}")
        print(f"  제안값: ({p95:.1f}, {p80:.1f}, {p20:.1f}, {p5:.1f})")
        print(f"  현재값: {current}")
        counts = {g: 0 for g in ("강력매수", "매수", "중립", "매도", "강력매도")}
        kind = "longterm" if name.startswith("LONG") else "swing"
        for v in values:
            counts[scoring.grade(v, kind)] += 1
        for g, c in counts.items():
            print(f"    {g:<6} {c:>6}  {c / len(values) * 100:5.1f}%")


if __name__ == "__main__":
    main()
