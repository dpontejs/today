"""Himalayas remote jobs search, restricted to roles open to Brazil. 20 per page, `page` from 1."""

import httpx

from today.jobs.models import SEARCH_TERMS, JobPosting, dedupe, from_epoch, get_json, text_or_none

URL = "https://himalayas.app/jobs/api/search"
PAGE = 20
MAX_PAGES = 3
TERMS = tuple(t for t in SEARCH_TERMS if t.isascii())  # an English board


def _posting(job: dict) -> JobPosting:
    return JobPosting(
        source="himalayas",
        external_id=job["guid"],
        company=job.get("companyName") or "",
        title=job["title"].strip(),
        location=", ".join(job.get("locationRestrictions") or []) or None,
        workplace=None,
        description=text_or_none(job.get("description")),
        url=job["guid"],
        published_at=from_epoch(job.get("pubDate")),
    )


def fetch(client: httpx.Client, terms: tuple[str, ...] = TERMS) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    for term in terms:
        for page in range(1, MAX_PAGES + 1):
            data = get_json(client, URL, params={"q": term, "country": "Brazil", "page": page})
            jobs += [_posting(j) for j in data["jobs"]]
            if len(data["jobs"]) < PAGE or page * PAGE >= int(data.get("totalCount") or 0):
                break
    return dedupe(jobs)
