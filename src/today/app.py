"""Application factory. Run with: uvicorn --factory today.app:from_env"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from today import auth
from today.config import Settings, load_settings
from today.db import connect, migrate

PACKAGE_DIR = Path(__file__).parent


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="today", docs_url=None, redoc_url=None, openapi_url=None)

    conn = connect(settings.db_path)
    migrate(conn)
    app.state.settings = settings
    app.state.conn = conn
    app.state.templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
    app.state.login_limiter = auth.LoginLimiter()

    @app.exception_handler(auth.LoginRequired)
    def _login_required(_request: Request, exc: auth.LoginRequired):
        return auth.login_required_response(exc)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    app.include_router(auth.router)
    return app


def from_env() -> FastAPI:
    return create_app(load_settings())
