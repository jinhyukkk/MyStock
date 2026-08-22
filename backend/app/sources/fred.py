"""FRED(세인트루이스 연준) 어댑터 — 미국 경제지표 **발표 일정**. 무료 키(`FRED_API_KEY`).

dart.py 와 같은 규약: 키가 없으면 `available()` 이 False 이고, 상위는 그 블록을
`unavailable` + 한국어 안내로 내보낸다. 키를 요구하는 경로가 다른 블록(지수·시그널)을
막으면 안 된다.

발표 '예정일'만 있고 예상치·실제치는 없다. 유료 컨센서스 자료라 무료 소스에 없다 —
화면에서 예상/실제 칸을 지어내지 않고 일정만 보여주는 이유다.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import requests

BASE = "https://api.stlouisfed.org/fred"
TIMEOUT = 10


def api_key() -> str | None:
    key = (os.environ.get("FRED_API_KEY") or "").strip()
    return key or None


def available() -> bool:
    return api_key() is not None


def release_dates(days: int = 14, today: date | None = None) -> list[dict]:
    """오늘부터 `days` 일 안의 지표 발표 일정. 반환: [{date, name}] (날짜 오름차순).

    `include_release_dates_with_no_data=true` 를 켜야 아직 값이 안 나온 **미래** 일정이
    오고, 그래야 이름(release_name)도 같이 온다.
    """
    key = api_key()
    if not key:
        raise RuntimeError("FRED_API_KEY 없음")
    start = today or date.today()
    r = requests.get(f"{BASE}/releases/dates", timeout=TIMEOUT, params={
        "api_key": key, "file_type": "json",
        "realtime_start": start.isoformat(),
        "realtime_end": (start + timedelta(days=days)).isoformat(),
        "include_release_dates_with_no_data": "true",
        "sort_order": "asc", "limit": 1000,
    })
    r.raise_for_status()
    data = r.json()
    if "release_dates" not in data:
        raise ValueError(f"FRED releases/dates 응답 형식 변경: {str(data)[:200]}")
    out = []
    for row in data["release_dates"]:
        name, when = row.get("release_name"), row.get("date")
        if name and when:
            out.append({"date": when[:10], "name": name})
    return out
