"""다음 금융 quotes 어댑터 — **비공식 API**.

- `Referer: https://finance.daum.net/quotes/A{code}` 가 **없으면 거부**된다(실측 2026-08-21).
  User-Agent도 브라우저 값이 필요하다.
- 공식 문서가 없어 **예고 없이 스키마가 바뀌거나 막힐 수 있다.** 파싱 실패는 위로 올리고
  상위가 블록만 떨어뜨린다.
- 이 종목 엔드포인트만 신뢰한다. 뉴스·재무·프로필 하위 API는 전부 500을 준다.
- 쓰는 값: `companySummary`(한국어 기업개요), `wicsSectorName`(한글 섹터),
  `marketCap`(원), `listingDate`, `listedShareCount`, `foreignRatio`(**0~1 비율**),
  `per`/`pbr`/`eps`/`bps`/`dps`.
"""

from __future__ import annotations

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TIMEOUT = 8


def quote(code: str) -> dict:
    url = f"https://finance.daum.net/api/quotes/A{code}"
    r = requests.get(url, params={"summary": "false", "changeStatistics": "true"},
                     headers={"User-Agent": UA,
                              "Referer": f"https://finance.daum.net/quotes/A{code}",
                              "Accept": "application/json"},
                     timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()
