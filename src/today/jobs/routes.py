"""Jobs tab: a list + detail screen to triage the analyzed roles (feature 09).

Views split the jobs by what the owner still has to do: `review` (analyzed, fits now), `later` (fits only
after the planned move), and the three statuses the owner sets. Marking a job opens the next one of the same
view, so a whole slot can be triaged in a row; the forms work without JavaScript and htmx boosts them.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from today.auth import require_session
from today.jobs import analysis_repo, repo

router = APIRouter(dependencies=[Depends(require_session)])

USER_STATUSES = ("interested", "dismissed", "applied")
DEFAULT_VIEW = "review"


def _view(view: str) -> str:
    if view not in analysis_repo.VIEWS:
        raise HTTPException(status_code=404)
    return view


def _render(request: Request, view: str, selected=None) -> HTMLResponse:
    conn = request.app.state.conn
    return request.app.state.templates.TemplateResponse(
        request,
        "jobs.html",
        {
            "view": view,
            "views": list(analysis_repo.VIEWS),
            "counts": analysis_repo.view_counts(conn),
            "jobs": analysis_repo.jobs_in_view(conn, view),
            "selected": selected,
            "list_url": f"/jobs?view={view}",
        },
    )


@router.get("/jobs", response_class=HTMLResponse)
def jobs_page(request: Request, view: str = DEFAULT_VIEW) -> HTMLResponse:
    return _render(request, _view(view))


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(request: Request, job_id: int, view: str = DEFAULT_VIEW) -> HTMLResponse:
    found = analysis_repo.job_with_analysis(request.app.state.conn, job_id)
    if found is None:
        raise HTTPException(status_code=404)
    return _render(request, _view(view), selected=found)


@router.post("/jobs/{job_id}/status")
def mark_job(
    request: Request,
    job_id: int,
    status: Annotated[str, Form()],
    view: Annotated[str, Form()] = DEFAULT_VIEW,
) -> Response:
    conn = request.app.state.conn
    view = _view(view)
    if status not in USER_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {', '.join(USER_STATUSES)}")
    if analysis_repo.job_with_analysis(conn, job_id) is None:
        raise HTTPException(status_code=404)
    # The next job is the one right after this one in the view as it was before marking.
    ids = [job.id for job, _ in analysis_repo.jobs_in_view(conn, view)]
    following = ids[ids.index(job_id) + 1 :] if job_id in ids else ids
    repo.set_status(conn, job_id, status, request.app.state.clock())
    target = f"/jobs/{following[0]}?view={view}" if following else f"/jobs?view={view}"
    return RedirectResponse(target, status_code=303)
