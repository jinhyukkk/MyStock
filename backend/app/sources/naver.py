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
