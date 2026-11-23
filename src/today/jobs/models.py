"""The posting every adapter returns, and the helpers adapters share."""

import html
import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

import httpx
from pydantic import BaseModel

Workplace = Literal["remote", "hybrid", "onsite"]
USER_AGENT = "today-personal/1.0"
TIMEOUT = 30.0


class JobPosting(BaseModel):
    source: str  # "greenhouse:ifoodcarreiras", "gupy", "ashby:nubank", "linkedin", ...
    external_id: str
    company: str
    title: str
    location: str | None
    workplace: Workplace | None  # None when the source has no field
    description: str | None  # plain text
    url: str
    published_at: datetime | None


Fetch = Callable[[httpx.Client], list[JobPosting]]


class PartialFetch(Exception):
    """A source stopped early (e.g. rate limited): keep `jobs`, and show the message in the report."""

    def __init__(self, jobs: list[JobPosting], message: str) -> None:
        super().__init__(message)
        self.jobs = jobs


_DROP = re.compile(r"<(script|style|head)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_BREAK = re.compile(r"<\s*(br|/?p|/?div|/?li|/?ul|/?ol|/?h[1-6]|/?tr)\b[^>]*>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]*>")


def html_to_text(markup: str) -> str:
    """Plain text from an HTML fragment: scripts dropped, block tags become line breaks, entities decoded."""
    text = _BREAK.sub("\n", _DROP.sub("", markup))
    text = html.unescape(_TAG.sub("", text)).replace("\xa0", " ")
    # A stray "<" left by truncated markup would read as a tag downstream.
    text = text.replace("<", "‹")
    lines = (re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def text_or_none(markup: str | None) -> str | None:
    return (html_to_text(markup) or None) if markup else None


def get_json(client: httpx.Client, url: str, **kwargs) -> dict | list:
    """GET and decode JSON. A non-2xx status or a body that is not JSON (an HTML error page) raises."""
    response = client.get(url, **kwargs)
    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        raise ValueError(f"{url} did not answer JSON (got {response.headers.get('content-type')})") from None


def from_epoch(seconds: float | int | str | None) -> datetime | None:
    if seconds in (None, ""):
        return None
    value = float(seconds)
    if value > 1e11:  # milliseconds
        value /= 1000
    return datetime.fromtimestamp(value, UTC)


def from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)


def workplace(value: str | None) -> Workplace | None:
    """Normalize the many spellings ('Hybrid', 'on-site', 'OnSite', 'remote') to the three values."""
    key = re.sub(r"[^a-z]", "", (value or "").lower())
    return {"remote": "remote", "hybrid": "hybrid", "onsite": "onsite", "presencial": "onsite"}.get(key)


def dedupe(jobs: list[JobPosting]) -> list[JobPosting]:
    seen: dict[str, JobPosting] = {}
    for job in jobs:
        seen.setdefault(job.external_id, job)
    return list(seen.values())


SEARCH_TERMS = (
    "machine learning",
    "cientista de dados",
    "visão computacional",
    "MLOps",
    "inteligência artificial",
    "deep learning",
)
