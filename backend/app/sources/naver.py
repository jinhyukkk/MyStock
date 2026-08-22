"""네이버 증권 모바일 JSON 어댑터 — **비공식 API**.

- 공식 문서·버전 보장이 없다. **예고 없이 스키마가 바뀌거나 차단될 수 있다.**
  그래서 파싱 실패는 예외로 올려 보내고, 상위(company.py)가 해당 블록만
  `unavailable`로 떨어뜨린 뒤 **이전 캐시는 그대로 둔다**.
- `User-Agent`가 없으면 응답이 달라진다(브라우저 UA 필수). Referer·로그인은 불필요.
- 병렬로 때리면 차단 사례가 보고돼 있어 상위에서 순차 + 종목 간 sleep으로 부른다.

실측 2026-08-21 (000660):
- `/integration` → totalInfos[per,eps,cnsPer,cnsEps,pbr,bps,dividend,dividendYieldRatio,
  foreignRate,marketValue], consensusInfo{recommMean,priceTargetMean,createDate}, researches[]
- `/finance/annual` 3년+컨센 1, `/finance/quarter` 5분기+컨센 1 (단위: 매출·이익 억원, EPS/BPS 원)
"""

from __future__ import annotations

import threading
import time

import requests

BASE = "https://m.stock.naver.com/api"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TIMEOUT = 8

# 시장 데이터 한 번 갱신에 지수·환율/채권·시그널·히트맵·수급까지 최대 18회를 순차로
# 부른다(market_kr.py 참고). 병렬 차단 사례가 보고돼 있어(모듈 헤더) 호출 사이 최소
# 간격을 강제한다. `_get`/`_get_front` **안**에 두는 이유: 단위 테스트는 이 두 함수를
# monkeypatch로 통째로 갈아끼우므로, 게이트를 이 안에 두면 스텁이 게이트까지 함께
# 대체돼 테스트는 느려지지 않는다. 반대로 `index_basic` 같은 상위 함수에서 별도 함수로
# 불렀다면 상위 함수는 테스트에서 그대로 실행되므로 매 호출 0.3초씩 잠들었을 것이다.
# 백그라운드 갱신 스레드와 요청 스레드가 겹칠 수 있어 락으로 보호한다.
MIN_INTERVAL_SEC = 0.3
_rate_lock = threading.Lock()
_last_call_at = [0.0]


def _throttle() -> None:
    with _rate_lock:
        wait = MIN_INTERVAL_SEC - (time.monotonic() - _last_call_at[0])
        if wait > 0:
            time.sleep(wait)
        _last_call_at[0] = time.monotonic()


def _get(path: str, params: dict | None = None):
    _throttle()
    r = requests.get(f"{BASE}{path}", params=params,
                     headers={"User-Agent": UA, "Accept": "application/json"},
                     timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def integration(code: str) -> dict:
    """스냅샷 지표 + 컨센서스 + 최근 리포트 5건."""
    return _get(f"/stock/{code}/integration")


def finance(code: str, period: str = "annual") -> dict:
    """period: 'annual' | 'quarter'."""
    return _get(f"/stock/{code}/finance/{period}")


def news(code: str, size: int = 20) -> list:
    return _get(f"/news/stock/{code}", {"pageSize": size, "page": 1})


def research(code: str, size: int = 20) -> list:
    return _get(f"/research/stock/{code}", {"pageSize": size, "page": 1})


def research_url(research_id) -> str | None:
    """리포트 본문 페이지. 200 응답 실측 2026-08-21."""
    if research_id in (None, ""):
        return None
    return f"https://m.stock.naver.com/investment/research/company/{research_id}"


# ── 시장 단위(대시보드) ────────────────────────────────────────────────────────
# 종목 단위 함수들과 달리 여기서는 **숫자로 바꿔서** 돌려준다. 네이버는 "281,500" 처럼
# 콤마가 든 문자열을 주는데, 이걸 그대로 올리면 빌더마다 같은 파싱을 반복하게 된다.

FRONT_BASE = "https://m.stock.naver.com/front-api"
RANKING_KINDS = ("up", "down", "searchTop", "marketValue")


def _num(v) -> float | None:
    """'281,500' → 281500.0, '+2,481' → 2481.0, 'N/A'·'' → None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("+", "").strip()
    if not s or s.upper() == "N/A":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _get_front(path: str, params: dict | None = None):
    _throttle()
    r = requests.get(f"{FRONT_BASE}{path}", params=params,
                     headers={"User-Agent": UA, "Accept": "application/json"},
                     timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def index_basic(code: str) -> dict:
    """지수 현재가. code: KOSPI | KOSDAQ | KPI200.

    전일 종가는 응답에 없어 `last - change` 로 만든다. 등락 부호는
    `compareToPreviousClosePrice` 에 이미 들어 있으므로 `fluctuationsType` 을 보지 않는다.
    """
    d = _get(f"/index/{code}/basic")
    last = _num(d.get("closePrice"))
    change = _num(d.get("compareToPreviousClosePrice"))
    return {"last": last, "change": change,
            "change_pct": _num(d.get("fluctuationsRatio")),
            "prev_close": None if last is None or change is None else last - change,
            "traded_at": d.get("localTradedAt")}


def ranking(kind: str, market: str, n: int) -> list[dict]:
    """순위 목록. kind: up|down|searchTop|marketValue, market: KOSPI|KOSDAQ.

    `is_etf` 를 같이 준다 — 시총 상위에는 KODEX·TIGER 가 섞여 있고 히트맵은 회사만 그린다.
    ETF 를 여기서 지우지 않는 이유는 시그널 표에서는 보여줘도 되기 때문이다. 거르는 판단은
    부르는 쪽이 한다.
    """
    if kind not in RANKING_KINDS:
        raise ValueError(f"unknown ranking kind: {kind}")
    d = _get(f"/stocks/{kind}/{market}", {"page": 1, "pageSize": n})
    # "stocks" 키 자체가 없으면(스키마 변경·에러 응답) 예외를 올린다. 빈 리스트는
    # 정상("오늘 상승 종목 없음")일 수 있으므로 키 부재와 빈 리스트를 구분해야 한다 —
    # 구분하지 않으면 []가 성공으로 캐시돼 화면이 "빈 화면"을 정상 데이터로 보여준다.
    if not isinstance(d, dict) or "stocks" not in d:
        raise ValueError(f"naver ranking missing 'stocks': {kind}/{market} → {d!r}")
    out = []
    for s in d["stocks"]:
        code = s.get("itemCode")
        if not code:
            continue
        out.append({"symbol": code, "name": s.get("stockName"),
                    "last": _num(s.get("closePrice")),
                    "change_pct": _num(s.get("fluctuationsRatio")),
                    "volume": _num(s.get("accumulatedTradingVolume")),
                    "market_value": _num(s.get("marketValue")),
                    "is_etf": s.get("stockEndType") == "etf"})
    return out


def investor_trend(market: str) -> dict:
    """투자자별 순매수(억원). market: KOSPI | KOSDAQ.

    장 마감 후 집계라 `bizdate` 가 전일일 수 있다 — 날짜를 같이 올려 화면이
    "오늘 수급"으로 읽히지 않게 한다.
    """
    d = _get(f"/index/{market}/trend")
    # "bizdate" 키 자체가 없으면 예외를 올린다(I1과 같은 이유 — ranking() 주석 참고).
    if not isinstance(d, dict) or "bizdate" not in d:
        raise ValueError(f"naver investor_trend missing 'bizdate': {market} → {d!r}")
    biz = str(d.get("bizdate") or "")
    date = f"{biz[:4]}-{biz[4:6]}-{biz[6:8]}" if len(biz) == 8 else None
    return {"date": date, "personal": _num(d.get("personalValue")),
            "foreign": _num(d.get("foreignValue")),
            "institution": _num(d.get("institutionalValue"))}


def market_index(category: str, code: str) -> dict:
    """환율·국채. category: exchange | bond. code: FX_USDKRW, KR3YT=RR …"""
    d = _get_front("/marketIndex/productDetail",
                   {"category": category, "reutersCode": code})
    if not d.get("isSuccess") or not d.get("result"):
        raise ValueError(f"naver marketIndex failed: {code} {d.get('message')}")
    r = d["result"]
    last = _num(r.get("closePrice"))
    change = _num(r.get("fluctuations"))
    return {"last": last, "change": change,
            "change_pct": _num(r.get("fluctuationsRatio")),
            "prev_close": None if last is None or change is None else last - change,
            "traded_at": r.get("localTradedAt")}
