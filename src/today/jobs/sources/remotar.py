"""Remotar (Brazilian remote jobs board). 50 per page."""

import httpx

from today.jobs.models import SEARCH_TERMS, JobPosting, dedupe, from_iso, get_json, text_or_none, workplace

URL = "https://api.remotar.com.br/jobs"
MAX_PAGES = 3


def _posting(job: dict) -> JobPosting:
    company = (job.get("company") or {}).get("name") or job.get("companyDisplayName") or ""
    place = ", ".join(p for p in (job.get("city"), job.get("state")) if p)
    return JobPosting(
        source="remotar",
        external_id=str(job["id"]),
        company=company,
        title=job["title"].strip(),
        location=place or None,
        workplace=workplace(job.get("type")),
        description=text_or_none(job.get("description")),
        url=job.get("externalLink") or f"https://remotar.com.br/job/{job['id']}",
        published_at=from_iso(job.get("createdAt")),
    )


def fetch(client: httpx.Client, terms: tuple[str, ...] = SEARCH_TERMS) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    for term in terms:
        for page in range(1, MAX_PAGES + 1):
            data = get_json(client, URL, params={"search": term, "page": page})
            jobs += [_posting(j) for j in data["data"]]
            if page >= int(data["meta"].get("last_page") or 1):
                break
    return dedupe(jobs)
