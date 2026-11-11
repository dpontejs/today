"""Application factory. Run with: uvicorn --factory today.app:from_env"""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from today import auth, capture, i18n
from today.config import Settings, load_settings
from today.db import connect, migrate
from today.items import routes as item_routes
from today.mcp_server import mount_mcp

PACKAGE_DIR = Path(__file__).parent
STATIC_DIR = PACKAGE_DIR / "static"


def create_app(settings: Settings) -> FastAPI:
    mcp = None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # A mounted sub-app's lifespan never runs, so the MCP session manager is started here.
        if mcp is None:
            yield
            return
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="today", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    conn = connect(settings.db_path)
    migrate(conn)
    app.state.settings = settings
    app.state.conn = conn
    app.state.clock = lambda: datetime.now(UTC)
    templates = Jinja2Templates(directory=PACKAGE_DIR / "templates", context_processors=[i18n.i18n_context])
    templates.env.filters["local_time"] = lambda dt: dt.astimezone(settings.tz).strftime("%H:%M")
    app.state.templates = templates
    app.state.login_limiter = auth.LoginLimiter()
    app.state.extractor = (
        capture.GeminiExtractor(settings.gemini_api_key, settings.gemini_model)
        if settings.gemini_api_key
        else None
    )

    @app.exception_handler(auth.LoginRequired)
    def _login_required(_request: Request, exc: auth.LoginRequired):
        return auth.login_required_response(exc)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest() -> FileResponse:
        return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/sw.js", include_in_schema=False)
    def service_worker() -> FileResponse:
        # Served from the root so its scope covers the whole app; no-cache so updates reach phones quickly.
        return FileResponse(
            STATIC_DIR / "sw.js",
            media_type="text/javascript",
            headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
        )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(auth.router)
    app.include_router(i18n.router)
    app.include_router(item_routes.router)
    app.include_router(capture.router)
    if settings.api_token:
        mcp = mount_mcp(app, settings.api_token)
    return app


def from_env() -> FastAPI:
    return create_app(load_settings())
