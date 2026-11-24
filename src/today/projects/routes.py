"""Projects tab (feature 10): register an idea, get it evaluated, move it through idea → active → done.

The project row is written before the analyst is called, so a failed or slow evaluation never loses the idea;
the detail page then offers to evaluate again. Closing a project (portfolio entry, LinkedIn post) happens in
the `/fechar-projeto` Claude Code skill through MCP, not here."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from today.auth import require_session
from today.llm.analyst import AnalystError
from today.projects import repo
from today.projects.evaluate import evaluate_idea

log = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_session)])

USER_STATUSES = ("active", "done", "dropped")
MAX_NAME = 120
MAX_IDEA = 5000


def _render(request: Request, status_code: int = 200, selected=None, **context) -> HTMLResponse:
    conn = request.app.state.conn
    return request.app.state.templates.TemplateResponse(
        request,
        "projects.html",
        {
            "projects": repo.list_projects(conn),
            "selected": selected,
            "list_url": "/projects",
            "analyst_on": request.app.state.analyst is not None,
            "error": None,
            "draft": {},
            **context,
        },
        status_code=status_code,
    )


def _found(request: Request, project_id: int) -> repo.Project:
    project = repo.get_project(request.app.state.conn, project_id)
    if project is None:
        raise HTTPException(status_code=404)
    return project


def _evaluate(request: Request, project_id: int) -> None:
    """Best effort: on any analyst failure the project stays, with the previous evaluation (or none)."""
    state = request.app.state
    if state.analyst is None:
        return
    try:
        evaluate_idea(state.conn, state.analyst, state.settings.projects_model, project_id, state.clock())
    except AnalystError as exc:
        log.warning("project %s evaluation failed: %s", project_id, exc)


@router.get("/projects", response_class=HTMLResponse)
def projects_page(request: Request) -> HTMLResponse:
    return _render(request)


@router.post("/projects")
def create_project(
    request: Request, name: Annotated[str, Form()] = "", idea_md: Annotated[str, Form()] = ""
) -> Response:
    name, idea_md = name.strip(), idea_md.strip()
    if not name or not idea_md or len(name) > MAX_NAME or len(idea_md) > MAX_IDEA:
        return _render(request, 422, error="project_invalid", draft={"name": name, "idea_md": idea_md})
    project_id = repo.create_project(request.app.state.conn, name, idea_md, request.app.state.clock())
    _evaluate(request, project_id)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.get("/projects/{project_id}", response_class=HTMLResponse)
def project_detail(request: Request, project_id: int) -> HTMLResponse:
    return _render(request, selected=_found(request, project_id))


@router.post("/projects/{project_id}/evaluate")
def reevaluate(request: Request, project_id: int, idea_md: Annotated[str, Form()] = "") -> Response:
    _found(request, project_id)
    idea_md = idea_md.strip()
    if idea_md and len(idea_md) <= MAX_IDEA:
        repo.update_project(request.app.state.conn, project_id, request.app.state.clock(), idea_md=idea_md)
    _evaluate(request, project_id)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@router.post("/projects/{project_id}/status")
def set_status(request: Request, project_id: int, status: Annotated[str, Form()]) -> Response:
    _found(request, project_id)
    if status not in USER_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {', '.join(USER_STATUSES)}")
    repo.update_project(request.app.state.conn, project_id, request.app.state.clock(), status=status)
    return RedirectResponse(f"/projects/{project_id}", status_code=303)
