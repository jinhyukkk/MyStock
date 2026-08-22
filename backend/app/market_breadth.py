"""시장 내부(breadth)와 차트 패턴 — **순수 계산만 한다.**

입력은 종가 행렬(`pandas.DataFrame`, 행=거래일 오름차순, 열=심볼)이고 네트워크를 모른다.
호출자(`market_history.py`)가 유니버스를 정하고 행렬을 받아 온다. 이렇게 나눈 이유:
지표 계산은 합성 시계열로 단위 테스트할 수 있어야 하는데, 여기에 다운로드가 섞이면
테스트가 야후에 붙는다.

finviz 원본에는 전 종목 breadth 와 12종 차트 패턴이 있지만, 무료 소스로 전 종목 일봉을
매일 받을 수 없고 패턴도 파는 데가 없다. 그래서 **유니버스를 좁히고(시총 상위 N) 판정
근거가 분명한 패턴만** 계산한다 — 눈으로만 보이는 패턴(쐐기·헤드앤숄더)을 어림으로
찍어 내보내면 화면의 다른 실측값까지 못 믿게 된다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# 52주 = 거래일 기준. 넉넉히 잡으면 신고가가 과소 집계되고, 짧게 잡으면 흔해진다.
WEEKS52 = 252
SMA_SHORT = 50
SMA_LONG = 200
# 골든/데드크로스는 "최근에 일어난 사건"일 때만 의미가 있다 — 1년 전 교차까지 표시하면
# 오늘 화면이 아니게 된다.
CROSS_WINDOW = 5
# 한 패턴 줄에 넣는 종목 수. finviz 와 같은 4칸.
PER_PATTERN = 4
# 패턴 탐지에 쓰는 최근 구간(약 3개월) — 채널·이중바닥은 이 창 안에서만 본다.
PATTERN_WINDOW = 60
DOUBLE_TOL_PCT = 3.0      # 두 저점(고점)이 서로 이 % 안이면 같은 높이로 본다
DOUBLE_REBOUND_PCT = 5.0  # 그 사이가 이만큼은 되돌려야 W/M 모양이다
DOUBLE_CONFIRM_PCT = 2.0  # 두 번째 극점에서 이만큼 돌아서야 "완성된" 모양이다
DOUBLE_MIN_TAIL = 5       # 두 번째 극점이 마지막 며칠 안이면 아직 진행 중 — W/M 이 아니다
# 아래 네 문턱은 실제 유니버스(KR 200·US 500, 2026-08-22)에서 적중률을 재서 잡았다.
# 느슨하면(초기값 R²0.6·수렴비 0.6) 채널이 28%, 수렴이 70% 종목에 붙어 "패턴"이 아니라
# "거의 전부"가 된다 — 표에 뜬 4종목이 특별해 보이는데 실은 알파벳 앞 4개일 뿐이다.
CHANNEL_MIN_SLOPE_PCT = 8.0   # 창 전체에서 이 %는 기울어야 추세로 인정
CHANNEL_FIT_MIN = 0.8         # 회귀선 설명력(R²) 하한 — 이보다 낮으면 그냥 횡보다 (적중 KR 6%·US 14%)
SQUEEZE_RATIO = 0.35          # 최근 20일 변동폭 / 창 전체 변동폭
SQUEEZE_BAND_PCT = 8.0        # 그리고 최근 20일 고저폭이 가격의 이 % 미만 (적중 KR 2%·US 9%)


def _last_valid(df: pd.DataFrame) -> pd.Series:
    return df.ffill().iloc[-1]


def breadth(df: pd.DataFrame) -> list[dict]:
    """상승/하락·52주 신고가/신저가·SMA50/200 위아래 네 줄.

    각 줄은 좌우 개수와 비율만 준다. 분모는 그 지표를 계산할 수 있었던 종목 수 —
    상장 3개월짜리 종목까지 SMA200 분모에 넣으면 '아래' 쪽이 부풀려진다.
    """
    if df.empty or len(df) < 2:
        return []
    last = _last_valid(df)
    prev = df.ffill().iloc[-2]
    change = (last / prev - 1) * 100

    bars = [_bar("상승", "하락", None,
                 int((change > 0).sum()), int((change < 0).sum()))]

    win = df.tail(WEEKS52)
    high = win.max()
    low = win.min()
    # 신고가/신저가는 52주 자료가 있는 종목만 — 신규 상장은 자동으로 신고가가 된다
    enough = win.notna().sum() >= WEEKS52 * 0.8
    hi = int(((last >= high) & enough).sum())
    lo = int(((last <= low) & enough).sum())
    bars.append(_bar("신고가", "신저가", "52주", hi, lo))

    for window, label in ((SMA_SHORT, "SMA50"), (SMA_LONG, "SMA200")):
        if len(df) < window:
            continue
        sma = df.rolling(window).mean().iloc[-1]
        ok = sma.notna() & last.notna()
        above = int((ok & (last > sma)).sum())
        below = int((ok & (last <= sma)).sum())
        bars.append(_bar("위", "아래", label, above, below))
    return bars


def _bar(left: str, right: str, center: str | None, left_n: int, right_n: int) -> dict:
    total = left_n + right_n
    return {"left_label": left, "right_label": right, "center": center,
            "left_n": left_n, "right_n": right_n,
            "left_pct": round(left_n / total * 100, 1) if total else 0.0,
            "right_pct": round(right_n / total * 100, 1) if total else 0.0}


# ------------------------------------------------------------------ 차트 패턴

def _slope_fit(series: pd.Series) -> tuple[float, float]:
    """1차 회귀의 (창 전체 상승률 %, R²). 기울기를 %로 바꾸는 이유: 종목마다 가격
    단위가 달라 원 단위 기울기끼리는 비교가 안 된다. R² 를 같이 주는 이유: 기울기만
    보면 톱니처럼 튀는 종목도 '채널'이 되는데, 채널은 선을 따라간다는 뜻이다."""
    y = series.to_numpy(dtype=float)
    n = len(y)
    x = np.arange(n, dtype=float)
    b, a = np.polyfit(x, y, 1)
    start, end = a, a + b * (n - 1)
    if start <= 0:
        return 0.0, 0.0
    pred = a + b * x
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot else 0.0
    return (end / start - 1) * 100, r2


def _double(series: pd.Series, bottom: bool) -> bool:
    """이중바닥(W)/이중천장(M). 창을 반으로 갈라 양쪽 극점의 높이가 비슷한지, 그 사이가
    충분히 되돌렸는지, 두 극점이 서로 떨어져 있는지를 본다 — 눈으로 세는 규칙 그대로다.
    극점이 붙어 있으면(며칠 간격) 그냥 한 번의 바닥이라 W 가 아니다."""
    n = len(series)
    if n < 20:
        return False
    half = n // 2
    arr = series.to_numpy(dtype=float)
    if bottom:
        i1 = int(arr[:half].argmin())
        i2 = half + int(arr[half:].argmin())
        p1, p2 = arr[i1], arr[i2]
        if p1 <= 0 or p2 <= 0 or i2 - i1 < 10:
            return False
        mid = float(arr[i1:i2 + 1].max())
        rebound = (mid / max(p1, p2) - 1) * 100
        # 두 번째 저점에서 실제로 돌아섰는지. 이걸 안 보면 계속 흘러내리는 M 자 뒷다리도
        # "이중 바닥"이 된다(같은 자료가 두 패턴에 동시에 잡힌다).
        if i2 > n - DOUBLE_MIN_TAIL or arr[-1] < p2 * (1 + DOUBLE_CONFIRM_PCT / 100):
            return False
    else:
        i1 = int(arr[:half].argmax())
        i2 = half + int(arr[half:].argmax())
        p1, p2 = arr[i1], arr[i2]
        if p1 <= 0 or p2 <= 0 or i2 - i1 < 10:
            return False
        mid = float(arr[i1:i2 + 1].min())
        rebound = (1 - mid / min(p1, p2)) * 100
        if i2 > n - DOUBLE_MIN_TAIL or arr[-1] > p2 * (1 - DOUBLE_CONFIRM_PCT / 100):
            return False
    gap = abs(p1 / p2 - 1) * 100
    return gap <= DOUBLE_TOL_PCT and rebound >= DOUBLE_REBOUND_PCT


def _squeeze(series: pd.Series) -> bool:
    """변동성 수렴(삼각 수렴). 최근 20일 고저폭이 (1) 창 전체보다 뚜렷이 좁고
    (2) 가격 대비로도 좁아야 한다. 비율만 보면 원래 크게 출렁이던 종목이 '조금 덜'
    출렁이기만 해도 수렴으로 잡힌다 — 그래서 절대 폭 조건을 같이 건다."""
    if len(series) < 40:
        return False
    whole = float(series.max() - series.min())
    recent = series.tail(20)
    mean = float(recent.mean())
    if whole <= 0 or mean <= 0:
        return False
    band = float(recent.max() - recent.min())
    return band / whole < SQUEEZE_RATIO and band / mean * 100 < SQUEEZE_BAND_PCT


def patterns(df: pd.DataFrame, names: dict[str, str] | None = None) -> list[dict]:
    """종목별 판정 → 패턴별 종목 목록. 열 순서(유니버스 순 = 시총 순)를 유지해
    각 줄에는 큰 종목이 먼저 온다."""
    names = names or {}
    found: dict[str, list[dict]] = {k: [] for k in _PATTERN_ORDER}
    if df.empty:
        return []
    for symbol in df.columns:
        s = df[symbol].dropna()
        if len(s) < 30:
            continue
        for key in _classify(s):
            if len(found[key]) < PER_PATTERN:
                found[key].append({"symbol": symbol, "name": names.get(symbol)})
    return [{"signal": _PATTERN_ORDER[k][0], "icon": _PATTERN_ORDER[k][1], "tickers": v}
            for k, v in found.items() if v]


# 화면 순서 = 이 딕셔너리 순서. (라벨, 아이콘)
_PATTERN_ORDER: dict[str, tuple[str, str]] = {
    "golden": ("골든크로스", "✕"),
    "dead": ("데드크로스", "✕"),
    "high52": ("52주 신고가", "▲"),
    "low52": ("52주 신저가", "▼"),
    "channel_up": ("상승 채널", "⟋"),
    "channel_down": ("하락 채널", "⟍"),
    "double_bottom": ("이중 바닥", "W"),
    "double_top": ("이중 천장", "M"),
    "squeeze": ("변동성 수렴", "◣"),
}


def _classify(s: pd.Series) -> list[str]:
    out: list[str] = []
    if len(s) >= SMA_LONG:
        short = s.rolling(SMA_SHORT).mean()
        long = s.rolling(SMA_LONG).mean()
        diff = (short - long).dropna()
        if len(diff) > CROSS_WINDOW:
            now = diff.iloc[-1]
            before = diff.iloc[-1 - CROSS_WINDOW]
            if before <= 0 < now:
                out.append("golden")
            elif before >= 0 > now:
                out.append("dead")
    if len(s) >= WEEKS52 * 0.8:
        win = s.tail(WEEKS52)
        if s.iloc[-1] >= win.max():
            out.append("high52")
        elif s.iloc[-1] <= win.min():
            out.append("low52")

    w = s.tail(PATTERN_WINDOW)
    if len(w) >= 30:
        move, r2 = _slope_fit(w)
        if r2 >= CHANNEL_FIT_MIN and move >= CHANNEL_MIN_SLOPE_PCT:
            out.append("channel_up")
        elif r2 >= CHANNEL_FIT_MIN and move <= -CHANNEL_MIN_SLOPE_PCT:
            out.append("channel_down")
        if _double(w, bottom=True):
            out.append("double_bottom")
        elif _double(w, bottom=False):
            out.append("double_top")
        if _squeeze(w):
            out.append("squeeze")
    return out
