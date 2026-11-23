"""Ashby posting API (Nubank)."""

import httpx

from today.jobs.models import JobPosting, from_iso, get_json, workplace

COMPANIES = {"nubank": "Nubank"}


def fetch(client: httpx.Client, org: str) -> list[JobPosting]:
    data = get_json(client, f"https://api.ashbyhq.com/posting-api/job-board/{org}")
    return [
        JobPosting(
            source=f"ashby:{org}",
            external_id=job["id"],
            company=COMPANIES.get(org, org),
            title=job["title"].strip(),
            location=job.get("location") or None,
            workplace=workplace(job.get("workplaceType")) or ("remote" if job.get("isRemote") else None),
            description=(job.get("descriptionPlain") or "").replace("<", "‹").strip() or None,
            url=job["jobUrl"],
            published_at=from_iso(job.get("publishedAt")),
        )
        for job in data["jobs"]
        if job.get("isListed", True)
    ]
