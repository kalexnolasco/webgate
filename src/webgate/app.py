from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from webgate.auth.routes import limiter
from webgate.auth.routes import router as auth_router
from webgate.auth.service import seed_admin
from webgate.config import settings
from webgate.db.engine import async_session_factory, close_db, init_db
from webgate.files.pool import sftp_pool
from webgate.files.routes import router as files_router
from webgate.servers.monitor import server_monitor
from webgate.servers.routes import router as servers_router
from webgate.terminal.routes import router as terminal_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    await init_db()
    async with async_session_factory() as session:
        await seed_admin(session)
    await sftp_pool.start()
    await server_monitor.start()
    yield
    await server_monitor.stop()
    await sftp_pool.stop()
    await close_db()


def create_app() -> FastAPI:
    app = FastAPI(title="webgate", version="0.1.0", lifespan=lifespan)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    origins = [o.strip() for o in settings.allowed_origins.split(",")]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    app.include_router(auth_router)
    app.include_router(servers_router)
    app.include_router(terminal_router)
    app.include_router(files_router)

    app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="static")

    return app
