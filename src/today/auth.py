"""Single-user passphrase login with a signed session cookie (ADR 0004)."""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from itsdangerous import BadSignature, TimestampSigner

from today.config import Settings

COOKIE_NAME = "today_session"
SESSION_MAX_AGE = 90 * 24 * 3600
SESSION_VALUE = "owner"

router = APIRouter()


class LoginRequired(Exception):
    def __init__(self, htmx: bool) -> None:
        self.htmx = htmx


class LoginLimiter:
    """In-memory failed-login counter per client IP. Enough for one process (ADR 0001)."""

    def __init__(self, max_failures: int = 5, window: timedelta = timedelta(minutes=10)) -> None:
        self.max_failures = max_failures
        self.window = window
        self._failures: dict[str, list[datetime]] = defaultdict(list)

    def _recent(self, ip: str, now: datetime) -> list[datetime]:
        recent = [t for t in self._failures[ip] if now - t < self.window]
        self._failures[ip] = recent
        return recent

    def is_blocked(self, ip: str, now: datetime) -> bool:
        return len(self._recent(ip, now)) >= self.max_failures

    def record_failure(self, ip: str, now: datetime) -> None:
        self._recent(ip, now).append(now)

    def reset(self, ip: str) -> None:
        self._failures.pop(ip, None)


def _signer(settings: Settings) -> TimestampSigner:
    return TimestampSigner(settings.session_secret, salt="today-session")


def verify_passphrase(settings: Settings, passphrase: str) -> bool:
    try:
        return PasswordHasher().verify(settings.passphrase_hash, passphrase)
    except (VerificationError, InvalidHashError):
        return False


def has_session(request: Request) -> bool:
    settings: Settings = request.app.state.settings
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return False
    try:
        return _signer(settings).unsign(token, max_age=SESSION_MAX_AGE).decode() == SESSION_VALUE
    except BadSignature:
        return False


def require_session(request: Request) -> None:
    """FastAPI dependency: raises LoginRequired, turned into a redirect by the app's exception handler."""
    if not has_session(request):
        raise LoginRequired(htmx=request.headers.get("HX-Request") == "true")


def login_required_response(exc: LoginRequired) -> Response:
    if exc.htmx:
        # A 303 would be followed by HTMX and the login page swapped into a row; HX-Redirect reloads the page.
        return Response(status_code=200, headers={"HX-Redirect": "/login"})
    return RedirectResponse("/login", status_code=303)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _login_page(request: Request, status_code: int, error: str | None = None) -> HTMLResponse:
    return request.app.state.templates.TemplateResponse(
        request, "login.html", {"error": error}, status_code=status_code
    )


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> HTMLResponse:
    return _login_page(request, 200)


@router.post("/login", response_class=HTMLResponse)
def login(request: Request, passphrase: Annotated[str, Form()]) -> Response:
    settings: Settings = request.app.state.settings
    limiter: LoginLimiter = request.app.state.login_limiter
    ip, now = _client_ip(request), datetime.now(UTC)

    if limiter.is_blocked(ip, now):
        return _login_page(request, 429, "Too many attempts. Try again in a few minutes.")
    if not verify_passphrase(settings, passphrase):
        limiter.record_failure(ip, now)
        return _login_page(request, 401, "Wrong passphrase.")

    limiter.reset(ip)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        _signer(settings).sign(SESSION_VALUE).decode(),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )
    return response


@router.post("/logout")
def logout() -> Response:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response
