"""OpenDART 어댑터 — 2차 소스(무료 키 필요, `.env`의 `DART_API_KEY`).

키가 없으면 `available()`이 False이고, 상위는 해당 블록을 `unavailable` + 한국어 안내로
내보낸다. **키를 요구하는 경로가 1차 데이터(네이버·다음)를 막으면 안 된다** — 여기서
예외가 나도 다른 블록은 그대로 채워져야 한다.

`corp_code`(8자리)↔종목코드 매핑은 `corpCode.xml`(zip) 1회 다운로드로 만든다.
"""

from __future__ import annotations

import io
import os
import zipfile
from functools import lru_cache

import requests

BASE = "https://opendart.fss.or.kr/api"
TIMEOUT = 15


def api_key() -> str | None:
    key = (os.environ.get("DART_API_KEY") or "").strip()
    return key or None


def available() -> bool:
    return api_key() is not None


@lru_cache(maxsize=1)
def _corp_map() -> dict[str, str]:
    key = api_key()
    if not key:
        return {}
    r = requests.get(f"{BASE}/corpCode.xml", params={"crtfc_key": key}, timeout=30)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        raw = zf.read(zf.namelist()[0]).decode("utf-8")
    import xml.etree.ElementTree as ET
    out = {}
    for el in ET.fromstring(raw).iter("list"):
        stock = (el.findtext("stock_code") or "").strip()
        corp = (el.findtext("corp_code") or "").strip()
        if stock and corp:
            out[stock] = corp
    return out


def corp_code(code: str) -> str | None:
    return _corp_map().get(code)


def _call(path: str, params: dict) -> dict:
    key = api_key()
    if not key:
        raise RuntimeError("DART_API_KEY 없음")
    r = requests.get(f"{BASE}/{path}", params={**params, "crtfc_key": key}, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    # status 013 = 조회 데이터 없음. 예외로 올리면 "키가 있는데 데이터가 없는 종목"이
    # 매번 실패로 기록돼 30분 backoff에 걸린다 — 빈 목록으로 정상 처리한다.
    if data.get("status") == "013":
        return {"list": []}
    if data.get("status") not in (None, "000"):
        raise RuntimeError(f"DART {data.get('status')}: {data.get('message')}")
    return data


def elestock(code: str) -> list[dict]:
    """임원·주요주주 소유보고 = 국내 내부자 거래."""
    cc = corp_code(code)
    if not cc:
        return []
    return _call("elestock.json", {"corp_code": cc}).get("list") or []


def stock_total(code: str, year: int) -> list[dict]:
    """주식의 총수 현황 — 발행주식수 이력."""
    cc = corp_code(code)
    if not cc:
        return []
    return _call("stockTotqySttus.json",
                 {"corp_code": cc, "bsns_year": str(year),
                  "reprt_code": "11011"}).get("list") or []
