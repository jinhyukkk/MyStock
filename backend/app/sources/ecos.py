"""한국은행 ECOS 어댑터 — 국내 **100대 주요 경제지표**. 무료 키(`ECOS_API_KEY`).

미국(FRED)은 발표 일정을 주지만 국내에는 대응하는 무료 일정 API 가 없다. 대신 ECOS
`KeyStatisticList` 가 기준금리·물가·실업률 같은 지표의 **최신값과 기준시점**을 준다 —
'언제 나오나' 대신 '지금 얼마인가'를 보여주는 쪽으로 국내 패널을 채운다.

dart.py 와 같은 규약: 키가 없으면 `available()` 이 False, 상위가 `unavailable` 처리.
"""
from __future__ import annotations

import os

import requests

BASE = "https://ecos.bok.or.kr/api"
TIMEOUT = 10
COUNT = 100


def api_key() -> str | None:
    key = (os.environ.get("ECOS_API_KEY") or "").strip()
    return key or None


def available() -> bool:
    return api_key() is not None


def key_statistics() -> list[dict]:
    """100대 지표. 반환: [{category, name, value, unit, period}].

    `period`(CYCLE)는 20260814 / 202608 / 2026 처럼 주기마다 자릿수가 다르다 —
    포맷은 부르는 쪽에서 한다. 여기서는 원문을 그대로 올린다.
    """
    key = api_key()
    if not key:
        raise RuntimeError("ECOS_API_KEY 없음")
    r = requests.get(f"{BASE}/KeyStatisticList/{key}/json/kr/1/{COUNT}", timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    # 인증 실패·한도 초과는 200 + {"RESULT":{"CODE":"INFO-100",...}} 로 온다 —
    # raise_for_status 만 믿으면 빈 목록이 정상값으로 캐시된다.
    if "RESULT" in data:
        res = data["RESULT"]
        raise RuntimeError(f"ECOS {res.get('CODE')}: {res.get('MESSAGE')}")
    rows = ((data.get("KeyStatisticList") or {}).get("row")) or []
    return [{"category": r.get("CLASS_NAME"), "name": r.get("KEYSTAT_NAME"),
             "value": r.get("DATA_VALUE"), "unit": r.get("UNIT_NAME"),
             "period": str(r.get("CYCLE") or "")} for r in rows if r.get("KEYSTAT_NAME")]
