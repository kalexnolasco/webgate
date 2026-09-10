from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.ext.asyncio import AsyncSession

from webgate import __version__
from webgate.agent.routes import router as agent_router
from webgate.agent.store import load_config
from webgate.auth.routes import limiter
from webgate.auth.routes import router as auth_router
from webgate.auth.service import seed_admin
from webgate.backup.routes import router as backup_router
from webgate.branding.routes import router as branding_router
from webgate.config import settings
from webgate.db.engine import async_session_factory, close_db, get_session, init_db
from webgate.demo import seed_demo
from webgate.files.pool import sftp_pool
from webgate.files.routes import router as files_router
from webgate.recordings.routes import router as recordings_router
from webgate.servers.monitor import server_monitor
from webgate.servers.routes import router as servers_router
from webgate.snippets.routes import router as snippets_router
from webgate.terminal.routes import router as terminal_router
from webgate.webhooks.routes import router as webhooks_router


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
        version=__version__,
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
    async def health() -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        return {
            "status": "ok",
            "instance_id": server_monitor.instance_id,
            "monitor_role": "leader" if server_monitor.is_leader else "follower",
        }

    @app.get("/api/config")
    async def public_config(  # pyright: ignore[reportUnusedFunction]
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> dict[str, object]:
        # Public flags consumed by the frontend before login. The agent flag comes
        # from the database because an admin owns that setting, not the deployment;
        # environment variables only seed a fresh install.
        agent_available = False
        if not settings.demo_mode:
            agent_available = (await load_config(session)).enabled
        return {"demo_mode": settings.demo_mode, "agent_available": agent_available}

    if settings.demo_mode:
        # In demo mode block any state-changing request on /api/* except an
        # explicit allowlist of (method, path_pattern). Share-token endpoints
        # need to be reachable so the public demo can exercise the shared
        # terminal feature -- but only the exact two routes, not any URL
        # that starts with /api/terminal/share/.
        import re as _re
        WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
        # (method, compiled regex of full path)
        DEMO_WRITE_ALLOWLIST: list[tuple[str, _re.Pattern[str]]] = [
            ("POST",   _re.compile(r"^/api/auth/login$")),
            ("POST",   _re.compile(r"^/api/auth/totp/verify$")),
            ("POST",   _re.compile(r"^/api/terminal/share/[\w-]+$")),
            ("DELETE", _re.compile(r"^/api/terminal/share/[\w-]+$")),
        ]

        @app.middleware("http")
        async def _demo_readonly(request: Request, call_next):  # pyright: ignore[reportUnusedFunction]
            path = request.url.path
            if request.method in WRITE_METHODS and path.startswith("/api/"):
                allowed = any(
                    m == request.method and rx.match(path)
                    for m, rx in DEMO_WRITE_ALLOWLIST
                )
                if not allowed:
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
    app.include_router(backup_router)
    app.include_router(agent_router)
    app.include_router(branding_router)
    app.include_router(servers_router)
    app.include_router(terminal_router)
    app.include_router(files_router)
    app.include_router(snippets_router)
    app.include_router(webhooks_router)
    app.include_router(recordings_router)

    app.mount("/", StaticFiles(directory=str(settings.static_dir), html=True), name="static")

    return app
