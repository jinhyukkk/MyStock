import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import db, service
from app.api import router

# ponytail: 1시간 폴링 + 갱신 시 텔레그램 푸시 — 장중 분 단위 실시간성이 필요해지면 별도 알림 루프 분리
REFRESH_INTERVAL = 60 * 60  # 1시간

ROOT = Path(__file__).parent.parent.parent


def _load_env(path: Path) -> None:
    """루트 .env 로드 (이미 설정된 환경 변수가 우선). python-dotenv 불필요."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_load_env(ROOT / ".env")


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

    dist = ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            safe = _safe_static_path(dist, path)
            if safe:
                return FileResponse(safe)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
