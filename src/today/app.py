"""Application factory. Run with: uvicorn --factory today.app:from_env"""

from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from today import auth
from today.config import Settings, load_settings
from today.db import connect, migrate
from today.items import routes as item_routes

PACKAGE_DIR = Path(__file__).parent
STATIC_DIR = PACKAGE_DIR / "static"


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="today", docs_url=None, redoc_url=None, openapi_url=None)

    conn = connect(settings.db_path)
    migrate(conn)
    app.state.settings = settings
    app.state.conn = conn
    app.state.clock = lambda: datetime.now(UTC)
    templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
    templates.env.filters["local_time"] = lambda dt: dt.astimezone(settings.tz).strftime("%H:%M")
    templates.env.filters["local_day"] = lambda dt: dt.astimezone(settings.tz).strftime("%a %d").upper()
    app.state.templates = templates
    app.state.login_limiter = auth.LoginLimiter()

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
    app.include_router(item_routes.router)
    return app


def from_env() -> FastAPI:
    return create_app(load_settings())
