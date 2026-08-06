import requests

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
ALT_URL = "https://api.alternative.me/fng/?limit=1"
_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def _fetch_yf_last(ticker: str) -> float:
    import yfinance as yf
    hist = yf.Ticker(ticker).history(period="5d")
    return float(hist["Close"].dropna().iloc[-1])


def _fetch_vkospi() -> float:
    import FinanceDataReader as fdr
    return float(fdr.DataReader("VKOSPI").iloc[-1]["Close"])


def fetch_sentiment() -> dict:
    out = {"vix": None, "vkospi": None, "cnn_fg": None, "crypto_fg": None,
           "usdkrw": None, "failed": []}
    try:
        out["vix"] = _fetch_yf_last("^VIX")
    except Exception:
        out["failed"].append("vix")
    try:
        out["usdkrw"] = _fetch_yf_last("KRW=X")
    except Exception:
        out["failed"].append("usdkrw")
    try:
        out["vkospi"] = _fetch_vkospi()
    except Exception:
        out["failed"].append("vkospi")
    try:
        r = requests.get(CNN_URL, headers=_HEADERS, timeout=10)
        r.raise_for_status()
        out["cnn_fg"] = int(round(r.json()["fear_and_greed"]["score"]))
    except Exception:
        out["failed"].append("cnn")
    try:
        r = requests.get(ALT_URL, timeout=10)
        r.raise_for_status()
        out["crypto_fg"] = int(r.json()["data"][0]["value"])
    except Exception:
        out["failed"].append("crypto_fg")
    return out


def fg_label(v) -> str:
    if v is None: return "정보 없음"
    if v < 25: return "극단적 공포"
    if v < 45: return "공포"
    if v <= 55: return "중립"
    if v <= 75: return "탐욕"
    return "극단적 탐욕"


def context_note(base: float, market: str, senti: dict) -> str | None:
    """시장 심리 참고 문구. 점수는 건드리지 않는다 — 검증 안 된 선형 보정으로
    지표 점수를 왜곡하는 것보다 맥락 표기가 정직하다."""
    fg = senti.get("crypto_fg") if market == "CRYPTO" else senti.get("cnn_fg")
    notes = []
    if fg is not None:
        if fg < 25 and base > 0:
            notes.append("시장 극단적 공포 — 역발상 매수 참고")
        elif fg < 25:
            notes.append("시장 극단적 공포 구간")
        elif fg > 75 and base > 0:
            notes.append("시장 과열 구간 — 추격 매수 신중")
        elif fg > 75:
            notes.append("시장 과열(탐욕) 구간")
    vix = senti.get("vix")
    if market in ("US", "KR") and vix is not None and vix >= 30:
        notes.append(f"변동성(VIX {vix:.0f}) 높음 — 신중")
    return " · ".join(notes) or None
