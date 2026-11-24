"""Storage for projects and voice samples (feature 10). Plain SQL, like `jobs.repo`."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from today.jobs.repo import to_db

PROJECT_STATUSES = ("idea", "active", "done", "dropped")
VOICE_KINDS = ("linkedin_post",)


@dataclass(frozen=True)
class Project:
    id: int
    name: str
    idea_md: str
    status: str
    evaluation: dict[str, Any] | None  # IdeaEvaluation as stored; None until evaluated
    evaluated_at: str | None
    repo_url: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class VoiceSample:
    id: int
    kind: str
    body: str
    created_at: str


def _project(row: sqlite3.Row) -> Project:
    data = dict(row)
    raw = data.pop("evaluation_json")
    return Project(**data, evaluation=json.loads(raw) if raw else None)


def create_project(conn: sqlite3.Connection, name: str, idea_md: str, now: datetime) -> int:
    cursor = conn.execute(
        "INSERT INTO projects (name, idea_md, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (name, idea_md, to_db(now), to_db(now)),
    )
    return int(cursor.lastrowid)


def get_project(conn: sqlite3.Connection, project_id: int) -> Project | None:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _project(row) if row else None


def list_projects(conn: sqlite3.Connection, status: str | None = None) -> list[Project]:
    """Most recently updated first."""
    if status is not None and status not in PROJECT_STATUSES:
        raise ValueError(f"status must be one of {', '.join(PROJECT_STATUSES)}")
    where, args = ("WHERE status = ?", (status,)) if status else ("", ())
    rows = conn.execute(f"SELECT * FROM projects {where} ORDER BY updated_at DESC, id DESC", args).fetchall()
    return [_project(r) for r in rows]


def update_project(
    conn: sqlite3.Connection,
    project_id: int,
    now: datetime,
    *,
    idea_md: str | None = None,
    status: str | None = None,
    repo_url: str | None = None,
    evaluation: dict[str, Any] | None = None,
) -> Project:
    if status is not None and status not in PROJECT_STATUSES:
        raise ValueError(f"status must be one of {', '.join(PROJECT_STATUSES)}")
    fields: dict[str, Any] = {"updated_at": to_db(now)}
    if idea_md is not None:
        fields["idea_md"] = idea_md
    if status is not None:
        fields["status"] = status
    if repo_url is not None:
        fields["repo_url"] = repo_url
    if evaluation is not None:
        fields["evaluation_json"] = json.dumps(evaluation, ensure_ascii=False)
        fields["evaluated_at"] = to_db(now)
    sets = ", ".join(f"{name} = ?" for name in fields)  # names are the constants above
    conn.execute(f"UPDATE projects SET {sets} WHERE id = ?", (*fields.values(), project_id))
    project = get_project(conn, project_id)
    if project is None:
        raise ValueError(f"project {project_id} not found")
    return project


def add_voice_sample(conn: sqlite3.Connection, kind: str, body: str, now: datetime) -> VoiceSample:
    if kind not in VOICE_KINDS:
        raise ValueError(f"kind must be one of {', '.join(VOICE_KINDS)}")
    cursor = conn.execute(
        "INSERT INTO voice_samples (kind, body, created_at) VALUES (?, ?, ?)", (kind, body, to_db(now))
    )
    return VoiceSample(id=int(cursor.lastrowid), kind=kind, body=body, created_at=to_db(now))


def list_voice_samples(conn: sqlite3.Connection, kind: str, limit: int = 5) -> list[VoiceSample]:
    rows = conn.execute(
        "SELECT * FROM voice_samples WHERE kind = ? ORDER BY created_at DESC, id DESC LIMIT ?", (kind, limit)
    ).fetchall()
    return [VoiceSample(**dict(r)) for r in rows]
