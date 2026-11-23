"""Lever postings API (CI&T)."""

import httpx

from today.jobs.models import JobPosting, from_epoch, get_json, text_or_none, workplace

COMPANIES = {"ciandt": "CI&T"}


def fetch(client: httpx.Client, company: str) -> list[JobPosting]:
    data = get_json(client, f"https://api.lever.co/v0/postings/{company}", params={"mode": "json"})
    if not isinstance(data, list):
        raise ValueError(f"lever:{company} answered {type(data).__name__}, expected a list")
    return [
        JobPosting(
            source=f"lever:{company}",
            external_id=job["id"],
            company=COMPANIES.get(company, company),
            title=job["text"].strip(),
            location=(job.get("categories") or {}).get("location") or None,
            workplace=workplace(job.get("workplaceType")),
            description=text_or_none(job.get("description")),
            url=job["hostedUrl"],
            published_at=from_epoch(job.get("createdAt")),
        )
        for job in data
    ]
