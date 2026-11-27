"""MCP server: items (list, create, edit, complete, reopen, delete), collected jobs and the profile they are
analyzed against (ADR 0005, features 07 and 08).

The tool logic lives in plain functions over a connection (easy to test); `build_mcp` wraps them as MCP tools
and `mount_mcp` serves them at `/mcp` behind a bearer token. Stateless HTTP with JSON responses: every call
stands alone, which fits one process (ADR 0001) and short tools.
"""

import hmac
import sqlite3
from dataclasses import asdict
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from today.items.reminders import add_reminders, clean_reminders, list_reminders, replace_unsent_reminders
from today.items.repo import Item, ItemIn, insert_item, mark_done, reopen
from today.items.repo import delete_item as delete_row
from today.items.repo import update_item as update_row
from today.items.today import build_today
from today.jobs import analysis_repo
from today.jobs import repo as jobs_repo
from today.jobs.models import JobAnalysis
from today.projects import repo as projects_repo
from today.projects.gaps import GapStat, gap_stats

MAX_DESCRIPTION = 2000
MAX_JOBS = 100
MAX_PROFILE = 20_000

MAX_BATCH = 100
SOURCE = "mcp"


class DraftIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    due_at: datetime = Field(description="ISO 8601. Without an offset it is America/Fortaleza local time.")
    notes: str | None = Field(default=None, max_length=2000)
    source_key: str | None = Field(
        default=None,
        max_length=200,
        description="Stable id for imports, e.g. 'roadmap:M0:book-ch-1-2'. An existing key is skipped.",
    )
    reminders: list[datetime] | None = Field(
        default=None,
        description="When to notify (ISO 8601, local if no offset). Omitted: once at due_at. []: never.",
    )


class ItemOut(BaseModel):
    id: int
    title: str
    notes: str | None
    due_at: str = Field(description="ISO 8601 in America/Fortaleza")
    status: Literal["open", "done"]
    source: str
    source_key: str | None
    reminders: list[str] = Field(description="Notification times, ISO 8601 in America/Fortaleza")


class JobOut(BaseModel):
    id: int
    source: str
    company: str
    title: str
    location: str | None
    workplace: Literal["remote", "hybrid", "onsite"] | None
    url: str
    description: str | None = Field(description=f"Plain text, cut at {MAX_DESCRIPTION} characters")
    published_at: str | None = Field(description="ISO 8601 in America/Fortaleza")
    first_seen_at: str = Field(description="ISO 8601 in America/Fortaleza")
    status: Literal["new", "analyzed", "dismissed", "interested", "applied"]
    score: int | None = Field(default=None, description="0-100 fit against the profile; None if not analyzed")
    analysis: JobAnalysis | None = None


class Profile(BaseModel):
    body_md: str
    updated: bool = Field(description="False while the profile was never set")


class Deleted(BaseModel):
    deleted: int


class ItemsByBucket(BaseModel):
    late: list[ItemOut]
    today: list[ItemOut]
    next: list[ItemOut]
    done_today: list[ItemOut]


class CreateResult(BaseModel):
    created: list[ItemOut]
    skipped_source_keys: list[str]


def _local(value: datetime, tz: ZoneInfo) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=tz)


def _parse(value: str, tz: ZoneInfo, field: str) -> datetime:
    try:
        return _local(datetime.fromisoformat(value), tz)
    except ValueError:
        raise ValueError(f"{field} must be ISO 8601, e.g. 2026-11-20T09:00") from None


def _out(conn: sqlite3.Connection, item: Item, tz: ZoneInfo) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "notes": item.notes,
        "due_at": item.due_at.astimezone(tz).isoformat(),
        "status": item.status,
        "source": item.source,
        "source_key": item.source_key,
        "reminders": [r.astimezone(tz).isoformat() for r in list_reminders(conn, item.id)],
    }


# --- tool logic ------------------------------------------------------------------------------------


def list_items(conn: sqlite3.Connection, now: datetime, tz: ZoneInfo, days: int = 7) -> dict:
    if not 1 <= days <= 60:
        raise ValueError("days must be between 1 and 60")
    view = build_today(conn, now, tz, next_days=days)
    return {
        "late": [_out(conn, i, tz) for i in view.late],
        "today": [_out(conn, i, tz) for i in view.today],
        "next": [_out(conn, i, tz) for i in view.next],
        "done_today": [_out(conn, i, tz) for i in view.done_today],
    }


def create_items(conn: sqlite3.Connection, drafts: list[DraftIn], now: datetime, tz: ZoneInfo) -> dict:
    if len(drafts) > MAX_BATCH:
        raise ValueError(f"send at most {MAX_BATCH} items per call")
    created, skipped = [], []
    for d in drafts:
        due = _local(d.due_at, tz)
        data = ItemIn(title=d.title.strip(), due_at=due, notes=d.notes)
        item = insert_item(conn, data, now, source=SOURCE, source_key=d.source_key)
        if item is None:
            skipped.append(d.source_key)
            continue
        wanted = [due] if d.reminders is None else [_local(r, tz) for r in d.reminders]
        times = clean_reminders(wanted, due_at=due, now=now)
        add_reminders(conn, item.id, times)
        created.append(_out(conn, item, tz))
    return {"created": created, "skipped_source_keys": skipped}


def complete_item(conn: sqlite3.Connection, item_id: int, now: datetime, tz: ZoneInfo) -> dict:
    item = mark_done(conn, item_id, now)
    if item is None:
        raise ValueError(f"item {item_id} not found")
    return _out(conn, item, tz)


def reopen_item(conn: sqlite3.Connection, item_id: int, tz: ZoneInfo) -> dict:
    item = reopen(conn, item_id)
    if item is None:
        raise ValueError(f"item {item_id} not found")
    return _out(conn, item, tz)


def update_item(
    conn: sqlite3.Connection,
    item_id: int,
    now: datetime,
    tz: ZoneInfo,
    title: str | None = None,
    due_at: str | None = None,
    notes: str | None = None,
    reminders: list[str] | None = None,
) -> dict:
    """Change only what is given. `notes=""` clears the notes; `reminders` replaces the unsent ones."""
    if title is None and due_at is None and notes is None and reminders is None:
        raise ValueError("nothing to update: pass title, due_at, notes or reminders")
    changes: dict = {}
    if title is not None:
        if not title.strip() or len(title.strip()) > 200:
            raise ValueError("title must have 1 to 200 characters")
        changes["title"] = title.strip()
    if due_at is not None:
        changes["due_at"] = _parse(due_at, tz, "due_at")
    if notes is not None:
        changes["notes"] = notes.strip()[:2000] or None
    times = [_parse(r, tz, "reminders") for r in reminders] if reminders is not None else None

    item = update_row(conn, item_id, changes)
    if item is None:
        raise ValueError(f"item {item_id} not found")
    if times is not None:
        replace_unsent_reminders(conn, item_id, clean_reminders(times, due_at=item.due_at, now=now))
    return _out(conn, item, tz)


def delete_item(conn: sqlite3.Connection, item_id: int) -> dict:
    if not delete_row(conn, item_id):
        raise ValueError(f"item {item_id} not found")
    return {"deleted": item_id}


def _job_out(job: jobs_repo.JobRow, tz: ZoneInfo, analysis: JobAnalysis | None = None) -> dict:
    description = job.description
    if description and len(description) > MAX_DESCRIPTION:
        description = description[:MAX_DESCRIPTION] + "…"
    return {
        "id": job.id,
        "source": job.source,
        "company": job.company,
        "title": job.title,
        "location": job.location,
        "workplace": job.workplace,
        "url": job.url,
        "description": description,
        "published_at": job.published_at.astimezone(tz).isoformat() if job.published_at else None,
        "first_seen_at": job.first_seen_at.astimezone(tz).isoformat(),
        "status": job.status,
        "score": analysis.score if analysis else None,
        "analysis": analysis.model_dump() if analysis else None,
    }


def list_jobs(
    conn: sqlite3.Connection,
    tz: ZoneInfo,
    status: str | None = None,
    limit: int = 30,
    min_score: int | None = None,
) -> list[dict]:
    """status None: `new`, or every status when min_score is given (scored jobs are already `analyzed`)."""
    if not 1 <= limit <= MAX_JOBS:
        raise ValueError(f"limit must be between 1 and {MAX_JOBS}")
    if status is None:
        status = "all" if min_score is not None else "new"
    rows = analysis_repo.jobs_with_analysis(conn, None if status == "all" else status, limit, min_score)
    return [_job_out(job, tz, analysis) for job, analysis in rows]


def get_profile(conn: sqlite3.Connection) -> dict:
    body = analysis_repo.get_profile(conn)
    return {"body_md": body, "updated": bool(body)}


def set_profile(conn: sqlite3.Connection, body_md: str, now: datetime) -> dict:
    if not body_md.strip():
        raise ValueError("body_md must not be empty")
    if len(body_md) > MAX_PROFILE:
        raise ValueError(f"body_md must have at most {MAX_PROFILE} characters")
    analysis_repo.set_profile(conn, body_md, now)
    return {"body_md": body_md, "updated": True}


def update_job_status(
    conn: sqlite3.Connection, job_id: int, status: str, now: datetime, tz: ZoneInfo
) -> dict:
    return _job_out(jobs_repo.set_status(conn, job_id, status, now), tz)


# --- MCP wiring ------------------------------------------------------------------------------------


class ProjectOut(BaseModel):
    id: int
    name: str
    idea_md: str
    status: str
    evaluation: dict | None
    evaluated_at: str | None
    repo_url: str | None
    updated_at: str


class VoiceSampleOut(BaseModel):
    id: int
    kind: str
    body: str
    created_at: str


MAX_VOICE_SAMPLE = 10_000


def _project_out(project: projects_repo.Project) -> dict:
    return ProjectOut(
        id=project.id, name=project.name, idea_md=project.idea_md, status=project.status,
        evaluation=project.evaluation, evaluated_at=project.evaluated_at, repo_url=project.repo_url,
        updated_at=project.updated_at,
    ).model_dump()  # fmt: skip


def get_gap_stats(conn: sqlite3.Connection, now: datetime, days: int = 60) -> list[dict]:
    if not 1 <= days <= 365:
        raise ValueError("days must be between 1 and 365")
    return [g.model_dump() for g in gap_stats(conn, now, days=days)]


def get_project(conn: sqlite3.Connection, project_id: int) -> dict:
    project = projects_repo.get_project(conn, project_id)
    if project is None:
        raise ValueError(f"project {project_id} not found")
    return _project_out(project)


def update_project(
    conn: sqlite3.Connection, project_id: int, now: datetime, status: str | None, repo_url: str | None
) -> dict:
    get_project(conn, project_id)
    return _project_out(projects_repo.update_project(conn, project_id, now, status=status, repo_url=repo_url))


def add_voice_sample(conn: sqlite3.Connection, kind: str, body: str, now: datetime) -> dict:
    body = body.strip()
    if not body or len(body) > MAX_VOICE_SAMPLE:
        raise ValueError(f"body must have 1 to {MAX_VOICE_SAMPLE} characters")
    return asdict(projects_repo.add_voice_sample(conn, kind, body, now))


def list_voice_samples(conn: sqlite3.Connection, kind: str, limit: int) -> list[dict]:
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    if kind not in projects_repo.VOICE_KINDS:
        raise ValueError(f"kind must be one of {', '.join(projects_repo.VOICE_KINDS)}")
    return [asdict(v) for v in projects_repo.list_voice_samples(conn, kind, limit)]


def build_mcp(app: FastAPI) -> MCPServer:
    """Tools read the connection, clock and zone from `app.state` at call time (tests swap the clock)."""
    server = MCPServer(
        "today",
        instructions=(
            "Personal reminders and to-dos of one user in America/Fortaleza. "
            "Times without an offset are local. Use source_key when importing from a document, "
            "so running the import again does not duplicate items. "
            "Job openings (ML/AI roles) are collected every 2 days at 07:00: read them with list_jobs "
            "and triage with update_job_status; applying is always done by the user. "
            "After each collection every new role is scored 0-100 against the user's profile "
            "(get_profile/set_profile): list_jobs(min_score=70) returns the strong ones, best first. "
            "Portfolio projects: list_projects/get_project/update_project; get_gap_stats tells which "
            "gaps repeat in the jobs the user cares about; list_voice_samples/add_voice_sample hold "
            "texts the user approved, to write in their voice."
        ),
    )
    state = app.state

    def tz() -> ZoneInfo:
        return state.settings.tz

    def guarded(fn, *args):
        try:
            return fn(*args)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(
        name="list_items",
        description="Open items split into late, today and the next `days` days, plus items done today.",
    )
    def list_items_tool(days: int = 7) -> ItemsByBucket:
        return ItemsByBucket(**guarded(list_items, state.conn, state.clock(), tz(), days))

    @server.tool(
        name="create_items",
        description=f"Create up to {MAX_BATCH} items. Items whose source_key already exists are skipped.",
    )
    def create_items_tool(items: list[DraftIn]) -> CreateResult:
        return CreateResult(**guarded(create_items, state.conn, items, state.clock(), tz()))

    @server.tool(
        name="complete_item",
        description="Mark an item as done. Doing it twice keeps the first completion time.",
    )
    def complete_item_tool(id: int) -> ItemOut:
        return ItemOut(**guarded(complete_item, state.conn, id, state.clock(), tz()))

    @server.tool(name="reopen_item", description="Reopen an item that was marked as done.")
    def reopen_item_tool(id: int) -> ItemOut:
        return ItemOut(**guarded(reopen_item, state.conn, id, tz()))

    @server.tool(
        name="update_item",
        description=(
            "Edit an item: pass only what changes. Times are ISO 8601 (local if no offset). notes='' clears "
            "the notes. reminders replaces the reminders not sent yet."
        ),
    )
    def update_item_tool(
        id: int,
        title: str | None = None,
        due_at: str | None = None,
        notes: str | None = None,
        reminders: list[str] | None = None,
    ) -> ItemOut:
        return ItemOut(
            **guarded(update_item, state.conn, id, state.clock(), tz(), title, due_at, notes, reminders)
        )

    @server.tool(name="delete_item", description="Delete an item and its reminders. Cannot be undone.")
    def delete_item_tool(id: int) -> Deleted:
        return Deleted(**guarded(delete_item, state.conn, id))

    @server.tool(
        name="list_jobs",
        description=(
            "Collected job openings with their analysis (score 0-100, gaps, verdict), newest first. "
            "status: new, analyzed, dismissed, interested, applied or all; default new, or all when "
            f"min_score is given. min_score: only analyzed jobs at or above it, best first. limit: 1 to "
            f"{MAX_JOBS}."
        ),
    )
    def list_jobs_tool(
        status: str | None = None, limit: int = 30, min_score: int | None = None
    ) -> list[JobOut]:
        return [JobOut(**j) for j in guarded(list_jobs, state.conn, tz(), status, limit, min_score)]

    @server.tool(
        name="update_job_status",
        description="Set a job's status: new, analyzed, dismissed, interested or applied.",
    )
    def update_job_status_tool(id: int, status: str) -> JobOut:
        return JobOut(**guarded(update_job_status, state.conn, id, status, state.clock(), tz()))

    @server.tool(
        name="get_profile",
        description="The user's profile (markdown) that new jobs are scored against. Empty: analysis is off.",
    )
    def get_profile_tool() -> Profile:
        return Profile(**get_profile(state.conn))

    @server.tool(
        name="set_profile",
        description=(
            "Replace the whole profile (markdown): experience, skills, projects, preferences (seniority, "
            "target companies, remote/onsite cities). Read it with get_profile first and send it back edited."
        ),
    )
    def set_profile_tool(body_md: str) -> Profile:
        return Profile(**guarded(set_profile, state.conn, body_md, state.clock()))

    @server.tool(
        name="get_gap_stats",
        description=(
            "Gaps that repeat in the jobs analyzed in the last `days` (dismissed excluded), heaviest first. "
            "weight: 3 per job marked interested/applied, 2 if score >= 70, else 1. The market signal for "
            "choosing or scoping portfolio projects."
        ),
    )
    def get_gap_stats_tool(days: int = 60) -> list[GapStat]:
        return [GapStat(**g) for g in guarded(get_gap_stats, state.conn, state.clock(), days)]

    @server.tool(
        name="list_projects",
        description="Portfolio projects (idea, active, done, dropped), most recently updated first.",
    )
    def list_projects_tool(status: str | None = None) -> list[ProjectOut]:
        projects = guarded(projects_repo.list_projects, state.conn, status)
        return [ProjectOut(**_project_out(p)) for p in projects]

    @server.tool(name="get_project", description="One project with its idea and stored idea evaluation.")
    def get_project_tool(id: int) -> ProjectOut:
        return ProjectOut(**guarded(get_project, state.conn, id))

    @server.tool(
        name="update_project",
        description="Set a project's status (idea, active, done, dropped) and/or its repository URL.",
    )
    def update_project_tool(id: int, status: str | None = None, repo_url: str | None = None) -> ProjectOut:
        return ProjectOut(**guarded(update_project, state.conn, id, state.clock(), status, repo_url))

    @server.tool(
        name="list_voice_samples",
        description=(
            "Texts the user approved, newest first, to imitate their voice when writing for them "
            "(kind: linkedin_post). Empty: there is no reference yet; write the first one together."
        ),
    )
    def list_voice_samples_tool(kind: str = "linkedin_post", limit: int = 5) -> list[VoiceSampleOut]:
        return [VoiceSampleOut(**v) for v in guarded(list_voice_samples, state.conn, kind, limit)]

    @server.tool(
        name="add_voice_sample",
        description="Store an approved text (e.g. the final LinkedIn post) as a voice reference.",
    )
    def add_voice_sample_tool(kind: str, body: str) -> VoiceSampleOut:
        return VoiceSampleOut(**guarded(add_voice_sample, state.conn, kind, body, state.clock()))

    return server


class BearerGuard:
    """ASGI wrapper: 401 unless `Authorization: Bearer <token>` matches (constant-time comparison)."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        headers = dict(scope.get("headers", []))
        if not hmac.compare_digest(headers.get(b"authorization", b""), self.expected):
            response = JSONResponse(
                {"error": "unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"}
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def mount_mcp(app: FastAPI, token: str) -> MCPServer:
    server = build_mcp(app)
    # host="0.0.0.0" turns off the SDK's localhost-only Host check: the app is served as today.diegoponte.dev
    # and the bearer token is the protection.
    mcp_app = server.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True, host="0.0.0.0"
    )
    (route,) = [r for r in mcp_app.routes if getattr(r, "path", None) == "/mcp"]
    app.router.add_route("/mcp", BearerGuard(route.endpoint, token), methods=["GET", "POST", "DELETE"])
    return server
