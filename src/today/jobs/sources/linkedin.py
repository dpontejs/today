"""LinkedIn guest search, no login and no cookies, ever. Low volume: last 24 h, at most 3 pages per term,
3–7 s between requests, and the whole source stops at the first 429/999 (what JobSpy does)."""

import random
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from today.jobs.models import SEARCH_TERMS, JobPosting, dedupe, html_to_text

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
VIEW = "https://www.linkedin.com/jobs/view/{}"
PAGE = 10
MAX_PAGES = 3
BLOCKED = {429, 999}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_CARD = re.compile(r'data-entity-urn="urn:li:jobPosting:(\d+)"(.*?)(?=data-entity-urn=|\Z)', re.DOTALL)
_TITLE = re.compile(r'class="base-search-card__title"[^>]*>(.*?)</h3>', re.DOTALL)
_COMPANY = re.compile(r'class="base-search-card__subtitle"[^>]*>(.*?)</h4>', re.DOTALL)
_LOCATION = re.compile(r'class="job-search-card__location"[^>]*>(.*?)</span>', re.DOTALL)
_DATE = re.compile(r'<time[^>]*datetime="(\d{4}-\d{2}-\d{2})"')
# Up to the "show more" button, not the first </div>: descriptions may hold their own divs.
_MARKUP = re.compile(r'class="show-more-less-html__markup[^"]*"[^>]*>(.*?)(?:<button|</section>)', re.DOTALL)


def _text(pattern: re.Pattern, block: str) -> str | None:
    match = pattern.search(block)
    return (html_to_text(match.group(1)) or None) if match else None


def _parse(page: str) -> list[JobPosting]:
    jobs = []
    for job_id, block in _CARD.findall(page):
        title = _text(_TITLE, block)
        if not title:
            continue
        date = _DATE.search(block)
        jobs.append(
            JobPosting(
                source="linkedin",
                external_id=job_id,
                company=_text(_COMPANY, block) or "",
                title=title,
                location=_text(_LOCATION, block),
                workplace=None,  # f_WT is ignored without login
                description=None,
                url=VIEW.format(job_id),
                published_at=datetime.fromisoformat(date.group(1)).replace(tzinfo=UTC) if date else None,
            )
        )
    return jobs


def fetch(
    client: httpx.Client,
    terms: tuple[str, ...] = SEARCH_TERMS,
    sleep: Callable[[float], None] = time.sleep,
) -> list[JobPosting]:
    jobs: list[JobPosting] = []
    first = True
    for term in terms:
        for page in range(MAX_PAGES):
            if not first:
                sleep(random.uniform(3, 7))
            first = False
            params = {"keywords": term, "location": "Brazil", "f_TPR": "r86400", "start": page * PAGE}
            response = client.get(SEARCH, params=params, headers=HEADERS)
            if response.status_code in BLOCKED:
                return dedupe(jobs)
            response.raise_for_status()
            found = _parse(response.text)
            jobs += found
            if len(found) < PAGE:
                break
    return dedupe(jobs)


def fetch_linkedin_description(client: httpx.Client, external_id: str) -> str | None:
    """The public job page's description, or None when it is unavailable or blocked."""
    try:
        response = client.get(VIEW.format(external_id), headers=HEADERS)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    match = _MARKUP.search(response.text)
    return (html_to_text(match.group(1)) or None) if match else None
