"""Runtime settings, read once from the environment."""

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

USER_TZ = "America/Fortaleza"


@dataclass(frozen=True)
class Settings:
    db_path: Path
    passphrase_hash: str
    session_secret: str
    tz: ZoneInfo
    cookie_secure: bool = True


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
    )
