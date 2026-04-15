from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from webgate.auth.routes import limiter
from webgate.auth.routes import router as auth_router
from webgate.auth.service import seed_admin
from webgate.config import settings
from webgate.db.engine import async_session_factory, close_db, init_db
from webgate.demo import seed_demo
from webgate.files.pool import sftp_pool
from webgate.files.routes import router as files_router
from webgate.servers.monitor import server_monitor
from webgate.servers.routes import router as servers_router
from webgate.snippets.routes import router as snippets_router
from webgate.terminal.routes import router as terminal_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    await init_db()
    async with async_session_factory() as session:
        await seed_admin(session)
        if settings.demo_mode:
            await seed_demo(session)
    await sftp_pool.start()
    await server_monitor.start()
    yield
    await server_monitor.stop()
    await sftp_pool.stop()
    await close_db()


def create_app() -> FastAPI:
    app = FastAPI(
        title="webgate",
        version="0.1.0",
        lifespan=lifespan,
        root_path=settings.root_path,
    )
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

    @app.get("/api/config")
    async def public_config() -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        # Public flags consumed by the frontend before login.
        return {"demo_mode": settings.demo_mode}

    if settings.demo_mode:
        # In demo mode block any state-changing request on /api/* except login
        # and the WS quick-connect endpoint (no arbitrary SSH targets allowed).
        WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
        WRITE_ALLOWLIST = {"/api/auth/login", "/api/auth/totp/verify"}

        @app.middleware("http")
        async def _demo_readonly(request: Request, call_next):  # pyright: ignore[reportUnusedFunction]
            path = request.url.path
            if request.method in WRITE_METHODS and path.startswith("/api/") and path not in WRITE_ALLOWLIST:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Demo mode: write operations are disabled"},
                )
            if path.endswith("/api/ws/terminal/quick"):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Demo mode: quick-connect is disabled"},
                )
            return await call_next(request)

    app.include_router(auth_router)
    app.include_router(servers_router)
    app.include_router(terminal_router)
    app.include_router(files_router)
    app.include_router(snippets_router)

    app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="static")

    return app
