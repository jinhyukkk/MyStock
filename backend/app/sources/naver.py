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

import requests

BASE = "https://m.stock.naver.com/api"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TIMEOUT = 8


def _get(path: str, params: dict | None = None):
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
    out = []
    for s in (d or {}).get("stocks", []):
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
