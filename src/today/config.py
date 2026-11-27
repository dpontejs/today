"""Runtime settings, read once from the environment."""

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

USER_TZ = "America/Fortaleza"
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
ANALYSTS = ("claude_cli", "anthropic_api")


@dataclass(frozen=True)
class Settings:
    db_path: Path
    passphrase_hash: str
    session_secret: str
    tz: ZoneInfo
    cookie_secure: bool = True
    api_token: str | None = None  # enables /mcp (ADR 0005)
    gemini_api_key: str | None = None  # enables natural-language capture (ADR 0003)
    gemini_model: str = DEFAULT_GEMINI_MODEL
    vapid_private_key: str | None = None  # enables web push (feature 05)
    vapid_public_key: str | None = None
    vapid_subject: str | None = None  # mailto: or https URL the push services can contact
    jobs_enabled: bool = False  # starts the job collection loop (feature 07)
    jobs_sources: frozenset[str] | None = None  # None: every source
    analyst: str | None = None  # claude_cli | anthropic_api; None: no job analysis (feature 08, ADR 0007)
    analyst_model: str = "sonnet"
    projects_model: str = "opus"  # idea evaluation (feature 10): few calls, the answer matters more
    jobs_push_score: int = 75
    analyze_limit: int = 40  # per collection; collections run every `jobs_every_days` days
    jobs_every_days: int = 2


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"environment variable {name} is required")
    return value


def load_settings() -> Settings:
    return Settings(
        db_path=Path(os.environ.get("DB_PATH", "data/today.db")),
        passphrase_hash=_required("PASSPHRASE_HASH"),
        session_secret=_required("SESSION_SECRET"),
        tz=ZoneInfo(USER_TZ),
        cookie_secure=os.environ.get("COOKIE_SECURE", "true").lower() != "false",
        api_token=_api_token(),
        gemini_api_key=os.environ.get("GEMINI_API_KEY") or None,
        gemini_model=os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL,
        jobs_enabled=os.environ.get("JOBS_ENABLED", "false").lower() == "true",
        jobs_sources=_jobs_sources(),
        analyst=_analyst(),
        analyst_model=os.environ.get("ANALYST_MODEL") or "sonnet",
        projects_model=os.environ.get("PROJECTS_MODEL") or "opus",
        jobs_push_score=int(os.environ.get("JOBS_PUSH_SCORE") or 75),
        analyze_limit=int(os.environ.get("ANALYZE_LIMIT") or 40),
        jobs_every_days=int(os.environ.get("JOBS_EVERY_DAYS") or 2),
        **_vapid(),
    )


def _jobs_sources() -> frozenset[str] | None:
    names = frozenset(s.strip() for s in os.environ.get("JOBS_SOURCES", "").split(",") if s.strip())
    return names or None


def _analyst() -> str | None:
    name = os.environ.get("ANALYST") or None
    if name is not None and name not in ANALYSTS:
        raise RuntimeError(f"environment variable ANALYST must be one of {', '.join(ANALYSTS)}")
    return name


def _api_token() -> str | None:
    token = os.environ.get("API_TOKEN") or None
    if token is not None and len(token) < 32:
        raise RuntimeError("environment variable API_TOKEN must have at least 32 characters")
    return token


def _vapid() -> dict:
    private = os.environ.get("VAPID_PRIVATE_KEY") or None
    if private is None:
        return {}
    return {
        "vapid_private_key": private,
        "vapid_public_key": _required("VAPID_PUBLIC_KEY"),
        "vapid_subject": _required("VAPID_SUBJECT"),
    }
