import pandas as pd

SWING_WEIGHTS = {"rsi": 0.20, "macd": 0.20, "sma_cross": 0.20,
                 "bollinger": 0.15, "stoch": 0.15, "volume": 0.10}
LONG_WEIGHTS = {"alignment": 0.35, "pos_52w": 0.25, "trend_slope": 0.20,
                "macd": 0.10, "rsi": 0.10}


def grade(score: float) -> str:
    if score >= 60: return "강력매수"
    if score >= 20: return "매수"
    if score > -20: return "중립"
    if score > -60: return "매도"
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
    p = row["pos_52w"]
    if p < 0.2: return 50, f"52주 저점권 ({p*100:.0f}% 위치) — 저평가 구간 가능성"
    if p > 0.9: return -30, f"52주 고점권 ({p*100:.0f}% 위치) — 고점 부담"
    return 0, f"52주 범위 중간 ({p*100:.0f}% 위치)"


def _score_trend_slope(df):
    s120 = df["sma120"].dropna()
    if len(s120) < 21: return 0, "장기 추세 판단 데이터 부족"
    change = (s120.iloc[-1] - s120.iloc[-21]) / s120.iloc[-21]
    if change > 0.02: return 60, f"120일선이 최근 1개월 +{change*100:.1f}% — 장기 상승 추세"
    if change < -0.02: return -60, f"120일선이 최근 1개월 {change*100:.1f}% — 장기 하락 추세"
    return 0, "120일선 횡보 — 장기 추세 중립"


REGIME_LABELS = {"up": "상승 추세", "down": "하락 추세", "neutral": "추세 중립"}
_MEANREV = ("rsi", "bollinger", "stoch")  # 평균회귀 성격 지표


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
        "rsi": _score_rsi(last), "macd": _score_macd(df),
        "sma_cross": _score_sma_cross(df), "bollinger": _score_bollinger(last),
        "stoch": _score_stoch(last), "volume": _score_volume(df),
    }
    swing_parts = _apply_regime(swing_parts, regime)
    long_parts = {
        "alignment": _score_alignment(last), "pos_52w": _score_pos_52w(last),
        "trend_slope": _score_trend_slope(df),
        "macd": swing_parts["macd"], "rsi": swing_parts["rsi"],
    }
    swing = sum(SWING_WEIGHTS[k] * v[0] for k, v in swing_parts.items())
    longterm = sum(LONG_WEIGHTS[k] * v[0] for k, v in long_parts.items())

    names = {"rsi": "RSI", "macd": "MACD", "sma_cross": "이동평균 교차",
             "bollinger": "볼린저밴드", "stoch": "스토캐스틱", "volume": "거래량",
             "alignment": "이평선 배열", "pos_52w": "52주 위치", "trend_slope": "장기 추세"}
    indicator_scores = (
        [{"name": names[k], "score": v[0], "reason": v[1], "scope": "swing"}
         for k, v in swing_parts.items()] +
        [{"name": names[k], "score": v[0], "reason": v[1], "scope": "longterm"}
         for k, v in long_parts.items() if k in ("alignment", "pos_52w", "trend_slope")])
    top = sorted(indicator_scores, key=lambda x: abs(x["score"]), reverse=True)[:3]
    summary = ", ".join(t["reason"] for t in top if t["score"] != 0) or "뚜렷한 시그널 없음"
    return {
        "swing_score": round(swing, 1), "longterm_score": round(longterm, 1),
        "swing_grade": grade(swing), "longterm_grade": grade(longterm),
        "regime": regime, "regime_label": REGIME_LABELS[regime],
        "indicator_scores": indicator_scores, "summary": summary,
    }
