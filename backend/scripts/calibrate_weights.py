"""지표 가중치의 근거를 만든다 — 각 지표가 실제로 미래 수익률을 설명하는가.

기존 가중치(SWING_WEIGHTS 등)는 코드·문서 어디에도 산출 근거가 없었다. 과거 데이터에
맞춘 흔적이 없다는 점은 과최적화 위험을 낮추지만, 동시에 아무 근거가 없다는 뜻이다.

여기서 측정하는 것:

1. **지표별 IC(정보계수)** — 지표 점수와 forward 수익률의 순위상관. 부호가 뒤집혀 있으면
   그 지표는 거꾸로 쓰이고 있다는 뜻이다(52주 위치 감점이 대표적 의심 대상).
2. **지표 간 상관** — 평균회귀 3종(RSI·볼린저·스토캐스틱)이 정말 독립 정보인지.
   거의 같은 값을 낸다면 6지표가 아니라 실질 2팩터이고, 가중 0.50이 한 신호에 몰린 것이다.

forward 수익률은 backtest와 같은 규칙(익일 시가 진입, 2×ATR 손절, h일 종가 청산)으로
계산한다 — 검증에 쓰는 숫자와 가중치를 정하는 숫자가 달라선 안 된다.

    python -m scripts.calibrate_weights
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from app import backtest, db, indicators, scoring

HORIZON = 20
# 국면 반감 전의 원점수를 본다 — 반감은 조합 규칙이지 지표 자체의 정보량이 아니다
SCORERS = {
    "rsi": lambda df: scoring._score_rsi(df.iloc[-1])[0],
    "macd": lambda df: scoring._score_macd(df)[0],
    "sma_cross": lambda df: scoring._score_sma_cross(df)[0],
    "bollinger": lambda df: scoring._score_bollinger(df.iloc[-1])[0],
    "stoch": lambda df: scoring._score_stoch(df.iloc[-1])[0],
    "volume": lambda df: scoring._score_volume(df)[0],
    "alignment": lambda df: scoring._score_alignment(df.iloc[-1])[0],
    "pos_52w": lambda df: scoring._score_pos_52w(df.iloc[-1])[0],
    "trend_slope": lambda df: scoring._score_trend_slope(df)[0],
}


def collect(conn) -> pd.DataFrame:
    rows = []
    symbols = [r["symbol"] for r in conn.execute(
        "SELECT DISTINCT symbol FROM price_cache WHERE symbol NOT LIKE 'BENCH:%'")]
    for s in symbols:
        df = db.load_prices(conn, s, limit=1100)
        if len(df) < 150:
            continue
        e = indicators.compute_indicators(df)
        first = e["sma120"].first_valid_index()
        if first is None:
            continue
        o = e["open"].to_numpy(float)
        h_ = e["high"].to_numpy(float)
        lo = e["low"].to_numpy(float)
        c = e["close"].to_numpy(float)
        atrs = e["atr14"].to_numpy(float)
        n = len(e)
        for i in range(e.index.get_loc(first) + 10, n - 1 - HORIZON):
            window = e.iloc[:i + 1]
            entry = o[i + 1]
            if not entry:
                continue
            atr = atrs[i]
            stop = entry - backtest.STOP_ATR_MULT * atr if pd.notna(atr) and atr else None
            px, _ = backtest._exit_price(o, h_, lo, c, i + 1, i + HORIZON, stop)
            rec = {"fwd": (px / entry - 1) * 100}
            try:
                for name, fn in SCORERS.items():
                    rec[name] = fn(window)
            except (ValueError, IndexError, KeyError):
                continue
            rows.append(rec)
    return pd.DataFrame(rows)


def main() -> None:
    frame = collect(db.get_conn())
    if frame.empty:
        print("가격 데이터 없음 — 먼저 갱신하세요")
        return
    names = list(SCORERS)
    print(f"표본 {len(frame):,}개 · forward {HORIZON}일 (익일 시가 진입, 2×ATR 손절)\n")

    # 순위 변환 후 Pearson = Spearman (scipy 의존 없이)
    ranked = frame.rank()
    ic = ranked[names].corrwith(ranked["fwd"])
    print("지표별 IC (순위상관) — 부호가 음(-)이면 지표가 거꾸로 쓰이고 있다는 뜻")
    for name in sorted(names, key=lambda x: -abs(ic[x])):
        flag = "  ⚠ 부호 역전" if ic[name] < -0.01 else ""
        print(f"  {name:<12} {ic[name]:+.4f}{flag}")

    print("\n|IC| 비례 가중치 제안 (스윙 / 중장기 각각 합=1)")
    for label, keys in (("SWING", ["rsi", "macd", "sma_cross", "bollinger", "stoch", "volume"]),
                        ("LONG", ["alignment", "pos_52w", "trend_slope", "macd", "rsi"])):
        w = {k: abs(ic[k]) for k in keys}
        total = sum(w.values()) or 1.0
        print(f"  {label}: " + ", ".join(f"{k} {v / total:.2f}" for k, v in w.items()))

    print("\n지표군 내부 상관 — 높으면 독립 정보가 아니라 같은 신호를 여러 번 센 것")
    mr = ["rsi", "bollinger", "stoch"]
    corr = ranked[names].corr()
    for group in (mr, ["macd", "sma_cross"]):
        for a in group:
            print("  " + " ".join(f"{a}-{b} {corr.loc[a, b]:+.2f}" for b in group if b != a))
        print()
    print("  평균회귀군 vs 추세군: " + " ".join(
        f"{a}-{b} {corr.loc[a, b]:+.2f}" for a in mr for b in ("macd", "sma_cross")))

    combo = frame[mr].mean(axis=1)
    print(f"\n  평균회귀 3종 평균 합성 IC: {combo.rank().corr(ranked['fwd']):+.4f} "
          f"(개별 최고 |IC| {max(abs(ic[k]) for k in mr):.4f})")
    trend = frame[["macd", "sma_cross"]].mean(axis=1)
    print(f"  추세 2종 평균 합성 IC:   {trend.rank().corr(ranked['fwd']):+.4f} "
          f"(개별 최고 |IC| {max(abs(ic[k]) for k in ('macd', 'sma_cross')):.4f})")
    # n=13,588에서 5% 유의 임계 |IC| ≈ 1.96/sqrt(n). 다만 표본이 중첩돼 실제 임계는 더 크다.
    print(f"  참고: 순진한 5% 유의 임계 |IC| ≈ {1.96 / len(frame) ** 0.5:.4f} "
          f"(표본 중첩 보정 시 이보다 훨씬 큼)")

    print("\n52주 위치 구간별 forward 수익률 — 고점권 감점이 타당한지 직접 확인")
    pos = frame.assign(bucket=pd.cut(frame["pos_52w"], [-100, -20, 20, 100],
                                     labels=["고점권(-30)", "중간(0)", "저점권(+50)"]))
    for b, g in pos.groupby("bucket", observed=True):
        arr = np.asarray(g["fwd"])
        print(f"  {b:<12} n={len(g):>6}  평균 {arr.mean():+.2f}%  중앙값 {np.median(arr):+.2f}%")


if __name__ == "__main__":
    main()
