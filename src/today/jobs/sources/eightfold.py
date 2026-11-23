"""Eightfold careers search (Mercado Livre). The search has no description: one detail call per posting."""

import httpx

from today.jobs.models import SEARCH_TERMS, JobPosting, dedupe, from_epoch, get_json, text_or_none, workplace

BASE = "https://mercadolibre.eightfold.ai"
DOMAIN = "mercadolibre.com"
PAGE = 10
MAX_PER_TERM = 50


def _search(client: httpx.Client, term: str) -> list[dict]:
    positions: list[dict] = []
    start = 0
    while start < MAX_PER_TERM:
        params = {"domain": DOMAIN, "query": term, "location": "Brazil", "start": start}
        data = get_json(client, f"{BASE}/api/pcsx/search", params=params)["data"]
        positions += data["positions"]
        start += PAGE
        if not data["positions"] or start >= data["count"]:
            break
    return positions


def fetch(client: httpx.Client, terms: tuple[str, ...] = SEARCH_TERMS) -> list[JobPosting]:
    found: dict[int, dict] = {}
    for term in terms:
        for position in _search(client, term):
            found.setdefault(position["id"], position)
    jobs = []
    for pid, position in found.items():
        params = {"position_id": pid, "domain": DOMAIN}
        detail = get_json(client, f"{BASE}/api/pcsx/position_details", params=params)["data"]
        jobs.append(
            JobPosting(
                source="eightfold:mercadolibre",
                external_id=str(pid),
                company="Mercado Livre",
                title=position["name"].strip(),
                location="; ".join(position.get("locations") or []) or None,
                workplace=workplace(position.get("workLocationOption")),
                description=text_or_none(detail.get("jobDescription")),
                url=detail.get("publicUrl") or f"{BASE}{position['positionUrl']}",
                published_at=from_epoch(position.get("postedTs")),
            )
        )
    return dedupe(jobs)
