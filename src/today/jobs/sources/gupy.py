"""Gupy job portal search (every company on Gupy, including Itaú and Creditas). One search per term."""

import httpx

from today.jobs.models import SEARCH_TERMS, JobPosting, dedupe, from_iso, get_json, text_or_none, workplace

URL = "https://portal.gupy.io/api/job-search/jobs"
PAGE = 10
MAX_PER_TERM = 100  # the portal seems to cap a search here


def _posting(job: dict) -> JobPosting:
    place = ", ".join(p for p in (job.get("city"), job.get("state")) if p)
    return JobPosting(
        source="gupy",
        external_id=str(job["id"]),
        company=job.get("careerPageName") or "",
        title=job["name"].strip(),
        location=place or None,
        workplace=workplace(job.get("workplaceType")),
        description=text_or_none(job.get("description")),
        url=job["jobUrl"],
        published_at=from_iso(job.get("publishedDate")),
    )


def fetch(client: httpx.Client, terms: tuple[str, ...] = SEARCH_TERMS) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    for term in terms:
        offset = 0
        while offset < MAX_PER_TERM:
            data = get_json(client, URL, params={"jobName": term, "limit": PAGE, "offset": offset})
            jobs += [_posting(j) for j in data["data"]]
            offset += PAGE
            if not data["data"] or offset >= data["pagination"]["total"]:
                break
    return dedupe(jobs)
