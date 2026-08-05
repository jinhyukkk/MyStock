import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db, service
from app.api import router

REFRESH_INTERVAL = 6 * 60 * 60  # 6시간


def create_app(db_path: str | None = None, refresh_on_start: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.conn = db.get_conn(db_path)
        task = None
        if refresh_on_start:
            async def loop():
                while True:
                    try:
                        await asyncio.to_thread(service.refresh_all, app.state.conn)
                    except Exception:
                        pass
                    await asyncio.sleep(REFRESH_INTERVAL)
            task = asyncio.create_task(loop())
        yield
        if task:
            task.cancel()
        app.state.conn.close()

    app = FastAPI(title="MyStock", lifespan=lifespan)
    app.include_router(router)

    from pathlib import Path
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            file = dist / path
            if path and file.is_file():
                return FileResponse(file)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
