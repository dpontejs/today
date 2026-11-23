"""Greenhouse job board API. No remote field: the location text and the filter decide."""

import html

import httpx

from today.jobs.models import JobPosting, from_iso, get_json, text_or_none

TOKENS = (
    "ifoodcarreiras",
    "inter",
    "c6bank",
    "xpinc",
    "btgpactual",
    "quintoandar",
    "stone",
    "vtex",
    "wildlifestudios",
    "hotmartcareersbr",
)


def fetch(client: httpx.Client, token: str) -> list[JobPosting]:
    data = get_json(
        client, f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", params={"content": "true"}
    )
    return [
        JobPosting(
            source=f"greenhouse:{token}",
            external_id=str(job["id"]),
            company=job.get("company_name") or token,
            title=job["title"].strip(),
            location=(job.get("location") or {}).get("name") or None,
            workplace=None,
            # `content` is HTML escaped once more: unescape, then strip.
            description=text_or_none(html.unescape(job.get("content") or "")),
            url=job["absolute_url"],
            published_at=from_iso(job.get("first_published") or job.get("updated_at")),
        )
        for job in data["jobs"]
    ]
