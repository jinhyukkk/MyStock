"""대시보드 시장 데이터 라우트. `api.py`와 분리한 이유: 그 파일은 종목 단위 작업이 자주
건드려서 같은 파일을 두 작업이 고치면 충돌한다. DB 를 쓰지 않으므로 `_conn(request)` 도 없다.

`market` 파라미터 기본값이 KR 인 이유: 이 앱의 보유·관심 종목이 국내 중심이라
대시보드를 열었을 때 먼저 봐야 하는 시장이 한국이다.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

from app import market

router = APIRouter(prefix="/api")
DEFAULT_MARKET = "KR"


def _check(name: str) -> str:
    if name not in market.MARKETS:
        raise HTTPException(status_code=400,
                            detail=f"unknown market: {name} "
                                   f"(가능: {', '.join(sorted(market.MARKETS))})")
    return name


@router.get("/market")
async def get_market(market_name: str = Query(DEFAULT_MARKET, alias="market")):
    # 첫 호출은 외부 소스를 동기로 기다린다(수 초). 이벤트 루프를 막지 않도록 스레드로.
    return await asyncio.to_thread(market.get_market, _check(market_name))


@router.post("/market/refresh")
async def refresh_market(market_name: str = Query(DEFAULT_MARKET, alias="market")):
    """TTL 무시하고 그 시장을 전부 다시 받는다 — 화면의 '새로고침' 버튼."""
    name = _check(market_name)
    await asyncio.to_thread(lambda: market.refresh(name, force=True))
    return await asyncio.to_thread(market.get_market, name)
