import pandas as pd

# 가중치 근거 — `scripts/calibrate_weights.py` 실측 (2026-08-16, 15종목 3년, n=13,588,
# forward 20일은 백테스트와 동일 규칙: 익일 시가 진입 · 2×ATR 손절).
#
# 1. RSI·볼린저·스토캐스틱의 상호 순위상관이 **+0.70 ~ +0.77**이었다. 세 지표는 독립
#    정보가 아니라 같은 국면을 세 번 세는 것이고, 예전 가중 합계 0.50이 사실상 한 신호에
#    몰려 있었다. → 하나의 합성 팩터(meanrev)로 묶는다.
# 2. 반면 MACD와 20/60 이평 교차의 상관은 **-0.10** — 추세군은 실제로 서로 다른 정보다.
#    "실질 2팩터"가 아니라 평균회귀 1 + 추세 2 + 거래량 1의 4팩터 구조로 본다.
# 3. 가중을 IC(정보계수)에 비례시키지 **않는다**. 측정된 |IC|가 전부 0.005~0.048로
#    순진한 5% 유의 임계(0.017)에 못 미치거나 걸치는 수준이고, 표본 중첩을 보정하면
#    유의한 지표가 남지 않는다. 게다가 |IC| 비례 배분은 부호를 무시하므로 실측에서
#    부호가 뒤집힌 지표(스토캐스틱 -0.047)에 가장 큰 가중을 주는 잘못된 처방이 된다.
#    한 국면(2022~2026)의 중첩 표본에 부호를 맞추는 것은 과최적화다.
#    → 측정으로 확인된 **실질 팩터 수**에만 근거해 균등에 가깝게 배분한다.
SWING_WEIGHTS = {"meanrev": 0.30, "macd": 0.25, "sma_cross": 0.25, "volume": 0.20}
LONG_WEIGHTS = {"alignment": 0.35, "pos_52w": 0.25, "trend_slope": 0.20,
                "macd": 0.10, "meanrev": 0.10}

# 위 실측에서 나온 지표별 IC. 이 점수의 예측력이 어느 정도인지 화면에 정직하게 알리기
# 위해 상수로 남긴다 — 숫자가 크게 보이는 것과 예측력이 있는 것은 다르다.
IC_MEASURED = {"n": 13588, "horizon": 20, "max_abs_ic": 0.048,
               "significance_threshold": 0.017, "measured_at": "2026-08-16"}


# 등급 임계값 — 실측 점수 분위수 기준 (2026-08-16, 보유·관심 15종목 × 3년, n=13,903).
#
# 기존 ±60/±20은 도달 불가능한 경계였다. 스윙 점수의 이론적 최대는 72.5지만 그 조합은
# 상호 배타적(과매도 + 상승 전환)이고 국면 반감까지 더해져, 실측 범위는 [-37, +35.5]에
# 그친다. 3년 동안 강력매수·강력매도가 단 한 번도 발생하지 않아 5등급 UI가 사실상
# 3등급으로 동작했다. 여기서는 상·하위 5% = 강력, 상·하위 20% = 매수/매도로 재보정한다.
#
# 중장기는 분포 자체가 다르다(평균 +10.9, 우편향) — 스윙 임계값을 그대로 쓰면 매도 등급이
# 과도하게 나온다. 그래서 축별로 분리한다. 요율이 아니라 분위수이므로, 국면이 크게
# 바뀌면 `scripts/calibrate_grades.py`로 다시 측정해 갱신해야 한다.
# 합성 팩터 도입(SWING_WEIGHTS 개편)으로 분포가 바뀌어 재측정한 값이다.
SWING_CUTS = (21.0, 11.0, -10.0, -20.5)      # p95 / p80 / p20 / p5
LONGTERM_CUTS = (40.5, 36.0, -11.5, -26.8)


def grade(score: float, kind: str = "swing") -> str:
    strong_buy, buy, sell, strong_sell = (
        LONGTERM_CUTS if kind == "longterm" else SWING_CUTS)
    if score >= strong_buy: return "강력매수"
    if score >= buy: return "매수"
    if score > sell: return "중립"
    if score > strong_sell: return "매도"
    return "강력매도"


def _score_rsi(row):
    r = row["rsi"]
    if r < 30: return 80, f"RSI {r:.0f} — 과매도 구간 (반등 가능성)"
    if r < 40: return 40, f"RSI {r:.0f} — 약한 과매도"
    if r > 70: return -80, f"RSI {r:.0f} — 과매수 구간 (조정 주의)"
    if r > 60: return -40, f"RSI {r:.0f} — 약한 과매수"
    return 0, f"RSI {r:.0f} — 중립 구간"


def _score_macd(df):
    last = df.iloc[-1]
    hist = df["macd_hist"].tail(4)
    crossed_up = hist.iloc[0] < 0 and hist.iloc[-1] > 0
    crossed_down = hist.iloc[0] > 0 and hist.iloc[-1] < 0
    if crossed_up: return 80, "MACD가 시그널선을 상향 돌파 (매수 전환)"
    if crossed_down: return -80, "MACD가 시그널선을 하향 돌파 (매도 전환)"
    if last["macd_hist"] > 0: return 40, "MACD 히스토그램 양(+) — 상승 모멘텀 유지"
    return -40, "MACD 히스토그램 음(-) — 하락 모멘텀 유지"


def _score_sma_cross(df):
    s20, s60 = df["sma20"], df["sma60"]
    now_above = s20.iloc[-1] > s60.iloc[-1]
    was_above = s20.iloc[-6] > s60.iloc[-6]
    if now_above and not was_above: return 80, "20일선이 60일선을 상향 돌파 (골든크로스)"
    if not now_above and was_above: return -80, "20일선이 60일선을 하향 돌파 (데드크로스)"
    if now_above: return 40, "20일선 > 60일선 — 단기 상승 흐름 유지"
    return -40, "20일선 < 60일선 — 단기 하락 흐름"


def _score_bollinger(row):
    band = row["bb_upper"] - row["bb_lower"]
    pct_b = (row["close"] - row["bb_lower"]) / (band if band else 1e-10)
    if pct_b < 0.05: return 60, "볼린저밴드 하단 이탈 — 단기 과매도"
    if pct_b < 0.2: return 30, "볼린저밴드 하단 근접"
    if pct_b > 0.95: return -60, "볼린저밴드 상단 이탈 — 단기 과열"
    if pct_b > 0.8: return -30, "볼린저밴드 상단 근접"
    return 0, "볼린저밴드 중앙 부근"


def _score_stoch(row):
    k, d = row["stoch_k"], row["stoch_d"]
    if k < 20 and k > d: return 70, f"스토캐스틱 {k:.0f} — 과매도권 상향 교차"
    if k < 20: return 40, f"스토캐스틱 {k:.0f} — 과매도권"
    if k > 80 and k < d: return -70, f"스토캐스틱 {k:.0f} — 과매수권 하향 교차"
    if k > 80: return -40, f"스토캐스틱 {k:.0f} — 과매수권"
    return 0, f"스토캐스틱 {k:.0f} — 중립"


def _pct_b(row) -> float:
    band = row["bb_upper"] - row["bb_lower"]
    return (row["close"] - row["bb_lower"]) / (band if band else 1e-10)


def _score_meanrev(row):
    """RSI·볼린저 %B·스토캐스틱을 0~100으로 정규화해 평균낸 합성 과매도/과매수 팩터.

    셋의 상호 상관이 0.70~0.77이라 따로 세면 같은 신호에 세 배 가중이 실린다.
    합성해서 하나로 세고, 세부 값은 근거 문구에 남겨 판단 재료는 잃지 않는다.
    """
    rsi_v = float(row["rsi"])
    pctb_v = max(0.0, min(1.0, float(_pct_b(row)))) * 100
    stoch_v = float(row["stoch_k"])
    pos = (rsi_v + pctb_v + stoch_v) / 3
    detail = f"(RSI {rsi_v:.0f} · %B {pctb_v:.0f} · 스토캐스틱 {stoch_v:.0f})"
    if pos < 20: return 70, f"과매도 종합 {pos:.0f}/100 — 되돌림 여지 {detail}"
    if pos < 35: return 35, f"약한 과매도 {pos:.0f}/100 {detail}"
    if pos > 80: return -70, f"과매수 종합 {pos:.0f}/100 — 조정 주의 {detail}"
    if pos > 65: return -35, f"약한 과매수 {pos:.0f}/100 {detail}"
    return 0, f"과매수·과매도 중립 {pos:.0f}/100 {detail}"


def _score_volume(df):
    row = df.iloc[-1]
    ratio = row["vol_ratio"]
    up_day = row["close"] >= df["close"].iloc[-2]
    if pd.isna(ratio): return 0, "거래량 데이터 부족"
    if ratio >= 1.8 and up_day:
        return 50, f"거래량 20일 평균 대비 {ratio*100:.0f}% 급증 + 상승 — 매수세 유입"
    if ratio >= 1.8:
        return -50, f"거래량 20일 평균 대비 {ratio*100:.0f}% 급증 + 하락 — 매도세 출회"
    return 0, f"거래량 평균 수준 ({ratio*100:.0f}%)"


def _score_alignment(row):
    c, s60, s120 = row["close"], row["sma60"], row["sma120"]
    if c > s60 > s120: return 70, "주가 > 60일선 > 120일선 — 중장기 정배열"
    if c < s60 < s120: return -70, "주가 < 60일선 < 120일선 — 중장기 역배열"
    return 0, "이동평균선 혼조 — 중장기 방향 불명확"


def _score_pos_52w(row):
    """52주 범위 내 위치.

    고점권 감점(-30)은 뺐다. 실측(`calibrate_weights.py`, n=13,588, forward 20일)에서
    고점권 이후 수익률은 평균 +2.98% / 중앙값 -1.63%로 중간권(+2.05% / -1.68%)과
    사실상 같았다 — 감점할 근거가 없다. 저점권만 평균 +3.58% / 중앙값 +0.53%로
    뚜렷이 나아 가점을 남긴다.

    부수 효과로 ML-12의 구조적 모순도 사라진다: 정배열(+70)이면 pos_52w가 높을 수밖에
    없어 두 항이 서로 상쇄되던 문제가 감점 제거로 없어진다.
    """
    p = row["pos_52w"]
    if p < 0.2: return 50, f"52주 저점권 ({p*100:.0f}% 위치) — 저평가 구간 가능성"
    if p > 0.9: return 0, f"52주 고점권 ({p*100:.0f}% 위치) — 실측상 중간권과 성과 차이 없음"
    return 0, f"52주 범위 중간 ({p*100:.0f}% 위치)"


def _score_trend_slope(df):
    s120 = df["sma120"].dropna()
    if len(s120) < 21: return 0, "장기 추세 판단 데이터 부족"
    change = (s120.iloc[-1] - s120.iloc[-21]) / s120.iloc[-21]
    if change > 0.02: return 60, f"120일선이 최근 1개월 +{change*100:.1f}% — 장기 상승 추세"
    if change < -0.02: return -60, f"120일선이 최근 1개월 {change*100:.1f}% — 장기 하락 추세"
    return 0, "120일선 횡보 — 장기 추세 중립"


REGIME_LABELS = {"up": "상승 추세", "down": "하락 추세", "neutral": "추세 중립"}
_MEANREV = ("meanrev",)  # 평균회귀 성격 팩터 (RSI·볼린저·스토캐스틱 합성)


def _regime(row) -> str:
    c, s60, s120 = row["close"], row["sma60"], row["sma120"]
    if c > s60 > s120: return "up"
    if c < s60 < s120: return "down"
    return "neutral"


def _apply_regime(parts: dict, regime: str) -> dict:
    """추세 국면과 역행하는 평균회귀 신호는 반감 — 하락장 과매도 매수(떨어지는 칼),
    상승장 과매수 매도(추세 이탈)를 그대로 믿지 않는다."""
    if regime == "neutral":
        return parts
    out = dict(parts)
    for k in _MEANREV:
        score, reason = out[k]
        if regime == "down" and score > 0:
            out[k] = (score / 2, reason + " ⚠ 하락 추세 중 반등 신호 — 신뢰도 반감")
        elif regime == "up" and score < 0:
            out[k] = (score / 2, reason + " ⚠ 상승 추세 중 조정 신호 — 신뢰도 반감")
    return out


def score_ticker(df: pd.DataFrame) -> dict:
    if len(df.dropna(subset=["sma120"])) < 10:
        raise ValueError("insufficient data")
    last = df.iloc[-1]
    regime = _regime(last)
    swing_parts = {
        "meanrev": _score_meanrev(last), "macd": _score_macd(df),
        "sma_cross": _score_sma_cross(df), "volume": _score_volume(df),
    }
    swing_parts = _apply_regime(swing_parts, regime)
    long_parts = {
        "alignment": _score_alignment(last), "pos_52w": _score_pos_52w(last),
        "trend_slope": _score_trend_slope(df),
        "macd": swing_parts["macd"], "meanrev": swing_parts["meanrev"],
    }
    swing = sum(SWING_WEIGHTS[k] * v[0] for k, v in swing_parts.items())
    longterm = sum(LONG_WEIGHTS[k] * v[0] for k, v in long_parts.items())

    names = {"meanrev": "과매수·과매도", "macd": "MACD", "sma_cross": "이동평균 교차",
             "volume": "거래량", "alignment": "이평선 배열",
             "pos_52w": "52주 위치", "trend_slope": "장기 추세"}
    indicator_scores = (
        [{"name": names[k], "score": v[0], "reason": v[1], "scope": "swing"}
         for k, v in swing_parts.items()] +
        [{"name": names[k], "score": v[0], "reason": v[1], "scope": "longterm"}
         for k, v in long_parts.items() if k in ("alignment", "pos_52w", "trend_slope")])
    top = sorted(indicator_scores, key=lambda x: abs(x["score"]), reverse=True)[:3]
    summary = ", ".join(t["reason"] for t in top if t["score"] != 0) or "뚜렷한 시그널 없음"
    return {
        "swing_score": round(swing, 1), "longterm_score": round(longterm, 1),
        "swing_grade": grade(swing), "longterm_grade": grade(longterm, "longterm"),
        "regime": regime, "regime_label": REGIME_LABELS[regime],
        "indicator_scores": indicator_scores, "summary": summary,
    }
