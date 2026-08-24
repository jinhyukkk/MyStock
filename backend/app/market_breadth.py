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
# 두 극점 사이에서 반대 극값(천장 판정이면 최저점, 바닥 판정이면 최고점)이 이 비율만큼
# 안쪽, 즉 중앙 절반(25%~75%) 에 있어야 M/W 로 인정한다. 높이만 보면 첫 극점 바로 옆에서
# 급락했다가 천천히 되오른(V자 반등 후 재하락) 모양도 M 이 된다 — 실제로 한국항공우주
# (047810, 반대극값 위치 0.135)가 이중천장으로 잡혔다.
# 실측(KR 200·US 500, 2026-08-24): 조건 없음 → W/M 합 KR 12.5%·US 22.8%,
# 0.20 → KR 10.5%·US 19.8%, 0.25 → KR 9.5%·US 17.4%, 0.30 → KR 6.0%·US 14.2%.
# 0.30 은 KR 이중바닥이 2.5%(200 종목 중 5)까지 떨어져 표가 자주 비고, 0.20 은 US 이중바닥이
# 10.6%로 채널·수렴보다 흔한 채로 남는다. 그 사이인 0.25 를 잡는다 (적중 KR 9.5%·US 17.4%).
DOUBLE_MID_BAND = 0.25
# 아래 네 문턱은 실제 유니버스(KR 200·US 500, 2026-08-22)에서 적중률을 재서 잡았다.
# 느슨하면(초기값 R²0.6·수렴비 0.6) 채널이 28%, 수렴이 70% 종목에 붙어 "패턴"이 아니라
# "거의 전부"가 된다 — 표에 뜬 4종목이 특별해 보이는데 실은 알파벳 앞 4개일 뿐이다.
CHANNEL_MIN_SLOPE_PCT = 8.0   # 창 전체에서 이 %는 기울어야 추세로 인정
CHANNEL_FIT_MIN = 0.8         # 회귀선 설명력(R²) 하한 — 이보다 낮으면 그냥 횡보다 (적중 KR 6%·US 14%)
SQUEEZE_RATIO = 0.35          # 최근 20일 변동폭 / 창 전체 변동폭
SQUEEZE_BAND_PCT = 8.0        # 그리고 최근 20일 고저폭이 가격의 이 % 미만 (적중 KR 2%·US 9%)

# 선명도 점수 하위 컷. 문턱을 넘긴 종목 중에서도 "겨우 넘긴" 것을 표에서 뺀다 —
# 점수는 정렬에만 쓰였으므로 후보가 적은 날에는 0점짜리도 4칸에 그대로 올라왔다.
# **점수 단위가 패턴군마다 달라 공통 상수 하나로는 못 자른다.** 그래서 두 개로 나눈다.
# (숫자가 우연히 같지만 하나는 %, 하나는 0~1 점수다 — 따로 조정한다.)
EDGE_MIN_PCT = 0.1      # golden/dead/high52/low52: 가격 대비 여유폭 %(상한 없음)
SHAPE_MIN_SCORE = 0.1   # double_bottom/double_top/squeeze: 0~1 정규화 점수
# 실측(KR 200·US 500, KR as_of 2026-08-24 / US 2026-08-21, 최근 20 거래일 되감기 평균):
# - EDGE 0.1 → golden US 12.0→10.8, dead US 3.9→3.1, high52 US 23.1→21.6, KR 은 거의 그대로.
#   오늘 스냅샷에서 잘린 대표: LMT(골든크로스, 두 선 간격이 가격의 0.0003% = 사실상 겹침),
#   NEM(신고가, 전고점 대비 0.15%). 0.2 로 올리면 dead US 가 4칸을 채우는 날이 14/20→7/20 로
#   반토막 나서 얻는 것(추가 제거 6%)보다 잃는 게 크다.
# - SHAPE 0.1 → squeeze US 31.7→19.8(37% 제거), double_bottom KR 15.7→12.8, double_top KR 7.1→5.5.
#   KR 이중바닥은 0.1 아래에 0.018~0.096 뭉치(POSCO홀딩스·녹십자 등 4종목)가 있고 그 위는
#   0.4 부터라 경계가 깨끗하다. 0.15 로 올리면 KR 수렴이 4칸을 채우는 날이 14/20→4/20,
#   빈 줄이 2/20 생긴다 — KR 수렴은 원래 적중 2%(200 중 4)라 컷을 더 못 견딘다.
# - 채널(channel_up/down)은 점수가 곧 R² 이고 CHANNEL_FIT_MIN(0.8)이 이미 하한이다.
#   여기에 컷을 더하는 건 CHANNEL_FIT_MIN 을 올리는 것과 같아(문턱값 변경) 중복이므로 두지 않는다.
_MIN_SCORE: dict[str, float] = {
    "golden": EDGE_MIN_PCT, "dead": EDGE_MIN_PCT,
    "high52": EDGE_MIN_PCT, "low52": EDGE_MIN_PCT,
    "double_bottom": SHAPE_MIN_SCORE, "double_top": SHAPE_MIN_SCORE,
    "squeeze": SHAPE_MIN_SCORE,
}


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


def _double(series: pd.Series, bottom: bool) -> float | None:
    """이중바닥(W)/이중천장(M). 창을 반으로 갈라 양쪽 극점의 높이가 비슷한지, 그 사이가
    충분히 되돌렸는지, 두 극점이 서로 떨어져 있는지, 그 되돌림이 두 극점 **가운데**에서
    일어났는지를 본다 — 눈으로 세는 규칙 그대로다.
    극점이 붙어 있으면(며칠 간격) 그냥 한 번의 바닥이라 W 가 아니다.

    반환: 판정 실패면 None, 성공이면 선명도 점수(0~1, 클수록 교과서적).
    점수를 세 조건의 **최솟값**으로 잡는 이유 — 하나라도 문턱에 턱걸이한 모양(예: 두
    극점 높이차 2.9% / 문턱 3%)은 사람 눈에도 애매하다. 평균을 쓰면 나머지 둘이 좋을 때
    그 턱걸이가 묻힌다."""
    n = len(series)
    if n < 20:
        return None
    half = n // 2
    arr = series.to_numpy(dtype=float)
    if bottom:
        i1 = int(arr[:half].argmin())
        i2 = half + int(arr[half:].argmin())
        p1, p2 = arr[i1], arr[i2]
        if p1 <= 0 or p2 <= 0 or i2 - i1 < 10:
            return None
        mid_idx = i1 + int(arr[i1:i2 + 1].argmax())   # 두 저점 사이의 반대 극값 = 최고점
        rebound = (arr[mid_idx] / max(p1, p2) - 1) * 100
        # 두 번째 저점에서 실제로 돌아섰는지. 이걸 안 보면 계속 흘러내리는 M 자 뒷다리도
        # "이중 바닥"이 된다(같은 자료가 두 패턴에 동시에 잡힌다).
        if i2 > n - DOUBLE_MIN_TAIL or arr[-1] < p2 * (1 + DOUBLE_CONFIRM_PCT / 100):
            return None
    else:
        i1 = int(arr[:half].argmax())
        i2 = half + int(arr[half:].argmax())
        p1, p2 = arr[i1], arr[i2]
        if p1 <= 0 or p2 <= 0 or i2 - i1 < 10:
            return None
        mid_idx = i1 + int(arr[i1:i2 + 1].argmin())   # 두 고점 사이의 반대 극값 = 최저점
        rebound = (1 - arr[mid_idx] / min(p1, p2)) * 100
        if i2 > n - DOUBLE_MIN_TAIL or arr[-1] > p2 * (1 - DOUBLE_CONFIRM_PCT / 100):
            return None
    # 되돌림이 두 극점 한쪽에 치우쳐 있으면 M/W 가 아니라 V자 반등 뒤 재하락(또는 그 반대)이다
    span = i2 - i1
    if not (i1 + span * DOUBLE_MID_BAND <= mid_idx <= i1 + span * (1 - DOUBLE_MID_BAND)):
        return None
    gap = abs(p1 / p2 - 1) * 100
    if gap > DOUBLE_TOL_PCT or rebound < DOUBLE_REBOUND_PCT:
        return None
    mid_rel = (mid_idx - i1) / span
    return min(
        1 - gap / DOUBLE_TOL_PCT,                          # 두 극점 높이가 같을수록 1
        min(rebound / (DOUBLE_REBOUND_PCT * 3), 1.0),      # 충분히 되돌렸으면 1로 포화
        1 - abs(mid_rel - 0.5) * 2,                        # 반대 극값이 정중앙이면 1
    )


def _squeeze(series: pd.Series) -> float | None:
    """변동성 수렴(삼각 수렴). 최근 20일 고저폭이 (1) 창 전체보다 뚜렷이 좁고
    (2) 가격 대비로도 좁아야 한다. 비율만 보면 원래 크게 출렁이던 종목이 '조금 덜'
    출렁이기만 해도 수렴으로 잡힌다 — 그래서 절대 폭 조건을 같이 건다.

    반환: 판정 실패면 None, 성공이면 두 문턱 대비 여유폭 중 최솟값(0~1)."""
    if len(series) < 40:
        return None
    whole = float(series.max() - series.min())
    recent = series.tail(20)
    mean = float(recent.mean())
    if whole <= 0 or mean <= 0:
        return None
    band = float(recent.max() - recent.min())
    ratio = band / whole
    pct = band / mean * 100
    if ratio >= SQUEEZE_RATIO or pct >= SQUEEZE_BAND_PCT:
        return None
    return min(1 - ratio / SQUEEZE_RATIO, 1 - pct / SQUEEZE_BAND_PCT)


def patterns(df: pd.DataFrame, names: dict[str, str] | None = None) -> list[dict]:
    """종목별 판정 → 패턴별 종목 목록. 각 줄은 **선명도 점수 내림차순 상위 4개**다.

    유니버스 순(시총 순)으로 앞에서 4개를 자르면 문턱을 아슬아슬하게 넘긴 종목이
    시총이 크다는 이유만으로 표를 차지한다 — 화면에 뜨는 4개가 "가장 선명한 4개"가
    아니라 "시총 상위 4개"가 된다. 점수는 같은 패턴 안에서만 비교하므로 패턴 간
    정규화는 필요 없고(그래서 하위 컷 `_MIN_SCORE` 도 패턴군별로 따로 잡는다),
    정렬·컷에만 쓰고 응답에는 넣지 않는다(프론트 계약 유지).
    동점이면 파이썬 정렬이 안정적이라 기존처럼 시총 순이 남는다."""
    names = names or {}
    found: dict[str, list[tuple[float, dict]]] = {k: [] for k in _PATTERN_ORDER}
    if df.empty:
        return []
    for symbol in df.columns:
        s = df[symbol].dropna()
        if len(s) < 30:
            continue
        for key, score in _classify(s):
            # 문턱은 넘겼지만 선명도가 하위인 종목은 아예 뺀다 — 후보가 4개뿐인 날에는
            # 정렬만으로 걸러지지 않아 "겨우 넘긴" 모양이 표에 그대로 올라온다.
            if score < _MIN_SCORE.get(key, 0.0):
                continue
            found[key].append((score, {"symbol": symbol, "name": names.get(symbol)}))
    rows = []
    for k, hits in found.items():
        if not hits:
            continue
        top = sorted(hits, key=lambda h: h[0], reverse=True)[:PER_PATTERN]
        rows.append({"signal": _PATTERN_ORDER[k][0], "icon": _PATTERN_ORDER[k][1],
                     "tickers": [t for _, t in top]})
    return rows


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


def _classify(s: pd.Series) -> list[tuple[str, float]]:
    """(패턴키, 선명도 점수). 점수는 같은 패턴끼리 줄 세우는 용도라 패턴 간 단위가
    달라도 된다 — 정규화하려 들면 오히려 각 패턴의 '선명함'이 뭉개진다.
    판정 조건(문턱값)은 점수와 무관하게 그대로다."""
    out: list[tuple[str, float]] = []
    last = float(s.iloc[-1])
    if len(s) >= SMA_LONG:
        short = s.rolling(SMA_SHORT).mean()
        long = s.rolling(SMA_LONG).mean()
        diff = (short - long).dropna()
        if len(diff) > CROSS_WINDOW:
            now = diff.iloc[-1]
            before = diff.iloc[-1 - CROSS_WINDOW]
            # 갓 교차해 두 선이 붙어 있으면 다음 날 되돌려질 수 있다 — 벌어진 폭(가격 대비 %)이
            # 클수록 확정된 교차로 본다.
            spread = abs(float(now)) / last * 100 if last > 0 else 0.0
            if before <= 0 < now:
                out.append(("golden", spread))
            elif before >= 0 > now:
                out.append(("dead", spread))
    if len(s) >= WEEKS52 * 0.8:
        win = s.tail(WEEKS52)
        # 돌파 여유폭: 마지막 봉을 뺀 창 최고/최저 대비 몇 % 넘어섰나. 전고점과 동률(0%)이면
        # "겨우 닿은" 신고가라 뒤로 밀린다.
        if last >= win.max():
            prior = float(win.iloc[:-1].max())
            out.append(("high52", (last / prior - 1) * 100 if prior > 0 else 0.0))
        elif last <= win.min():
            prior = float(win.iloc[:-1].min())
            out.append(("low52", (1 - last / prior) * 100 if prior > 0 else 0.0))

    w = s.tail(PATTERN_WINDOW)
    if len(w) >= 30:
        move, r2 = _slope_fit(w)
        # 채널의 선명함 = 가격이 회귀선을 얼마나 잘 따라가는가 = R².
        if r2 >= CHANNEL_FIT_MIN and move >= CHANNEL_MIN_SLOPE_PCT:
            out.append(("channel_up", r2))
        elif r2 >= CHANNEL_FIT_MIN and move <= -CHANNEL_MIN_SLOPE_PCT:
            out.append(("channel_down", r2))
        bottom = _double(w, bottom=True)
        if bottom is not None:
            out.append(("double_bottom", bottom))
        else:
            top = _double(w, bottom=False)
            if top is not None:
                out.append(("double_top", top))
        sq = _squeeze(w)
        if sq is not None:
            out.append(("squeeze", sq))
    return out
