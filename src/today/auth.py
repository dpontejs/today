"""Single-user passphrase login with a signed session cookie (ADR 0004)."""

import threading
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
    """In-memory login attempt counter (ADR 0001: one process).

    An attempt is counted *before* the passphrase is checked, under a lock, so parallel requests cannot all
    slip past the limit while Argon2 runs. Besides the per-IP limit there is a global one: with a single user,
    many failures from many IPs is an attack (or a spoofed X-Forwarded-For), never normal traffic.
    """

    def __init__(
        self,
        max_failures: int = 5,
        window: timedelta = timedelta(minutes=10),
        global_max_failures: int = 20,
    ) -> None:
        self.max_failures = max_failures
        self.window = window
        self.global_max_failures = global_max_failures
        self._attempts: list[tuple[datetime, str]] = []
        self._lock = threading.Lock()

    def attempt(self, ip: str, now: datetime) -> bool:
        """Record an attempt from `ip`; False if it is over a limit (and then nothing is recorded)."""
        with self._lock:
            self._attempts = [(t, a) for t, a in self._attempts if now - t < self.window]
            per_ip = sum(1 for _, a in self._attempts if a == ip)
            if per_ip >= self.max_failures or len(self._attempts) >= self.global_max_failures:
                return False
            self._attempts.append((now, ip))
            return True

    def succeed(self, ip: str) -> None:
        """A correct passphrase: forget this IP's attempts."""
        with self._lock:
            self._attempts = [(t, a) for t, a in self._attempts if a != ip]


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

    if not limiter.attempt(ip, now):
        return _login_page(request, 429, "Too many attempts. Try again in a few minutes.")
    if not verify_passphrase(settings, passphrase):
        return _login_page(request, 401, "Wrong passphrase.")

    limiter.succeed(ip)
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
