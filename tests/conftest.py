from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from argon2 import PasswordHasher
from today.config import Settings
from today.db import connect, migrate

PASSPHRASE = "correct horse battery staple"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "today.db",
        passphrase_hash=PasswordHasher().hash(PASSPHRASE),
        session_secret="test-secret",
        tz=ZoneInfo("America/Fortaleza"),
        cookie_secure=True,
    )


@pytest.fixture
def conn(settings: Settings):
    connection = connect(settings.db_path)
    migrate(connection)
    yield connection
    connection.close()
