import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import db, env, service
from app.api import router
from app.market_api import router as market_router

# ponytail: 1시간 폴링 + 갱신 시 텔레그램 푸시 — 장중 분 단위 실시간성이 필요해지면 별도 알림 루프 분리
REFRESH_INTERVAL = 60 * 60  # 1시간

ROOT = Path(__file__).parent.parent.parent


env.load(ROOT)


def _safe_static_path(dist: Path, path: str) -> Path | None:
    """dist 하위의 실제 파일만 반환하고, 그 외(경로 순회, 미존재 등)는 None."""
    if not path:
        return None
    dist_root = dist.resolve()
    requested = (dist / path).resolve()
    if requested.is_relative_to(dist_root) and requested.is_file():
        return requested
    return None


def create_app(db_path: str | None = None, refresh_on_start: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db = db.ThreadLocalDB(db_path)
        task = None
        if refresh_on_start:
            async def loop():
                while True:
                    try:
                        # to_thread는 워커 스레드에서 돌므로 그 스레드의 연결을 쓴다.
                        # 요청 스레드와 연결을 공유하면 동시 접근으로 프로세스가 죽는다.
                        await asyncio.to_thread(lambda: service.refresh_all(app.state.db.conn()))
                    except Exception:
                        pass
                    await asyncio.sleep(REFRESH_INTERVAL)
            task = asyncio.create_task(loop())
        yield
        if task:
            task.cancel()
        app.state.db.close_all()

    app = FastAPI(title="MyStock", lifespan=lifespan)
    app.include_router(router)
    app.include_router(market_router)

    dist = ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        # 진입점은 매번 재검증시킨다. index.html이 캐시되면 새 빌드를 올려도
        # 브라우저가 옛 진입점을 계속 써서 해시가 바뀐 청크를 아예 요청하지 않는다
        # — 사용자는 갱신했다고 믿는 채로 옛 화면을 본다.
        INDEX_HEADERS = {"Cache-Control": "no-cache, must-revalidate"}

        @app.get("/{path:path}")
        def spa(path: str):
            safe = _safe_static_path(dist, path)
            if safe:
                # 해시 없는 최상위 파일(index.html 등)은 캐시하면 같은 문제가 생긴다
                if safe.name == "index.html":
                    return FileResponse(safe, headers=INDEX_HEADERS)
                return FileResponse(safe)
            return FileResponse(dist / "index.html", headers=INDEX_HEADERS)

    return app


app = create_app()
