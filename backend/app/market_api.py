"""대시보드 시장 데이터 라우트. `api.py`와 분리한 이유: 그 파일은 종목상세 작업이 진행 중이라
같은 파일을 두 작업이 고치면 충돌한다. DB 를 쓰지 않으므로 `_conn(request)` 도 필요 없다."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter

from app import market

router = APIRouter(prefix="/api")


@router.get("/market")
async def get_market():
    # 첫 호출은 야후를 동기로 기다린다(수 초). 이벤트 루프를 막지 않도록 스레드로.
    return await asyncio.to_thread(market.get_market)


@router.post("/market/refresh")
async def refresh_market():
    """TTL 무시하고 전부 다시 받는다 — 화면의 '새로고침' 버튼."""
    await asyncio.to_thread(lambda: market.refresh(force=True))
    return await asyncio.to_thread(market.get_market)
