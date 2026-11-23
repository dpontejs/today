"""Source adapters: plain functions `Fetch(client) -> list[JobPosting]`, keyed by `source`."""

from functools import partial

import httpx

from today.jobs.models import TIMEOUT, USER_AGENT, Fetch
from today.jobs.sources import ashby, eightfold, greenhouse, gupy, himalayas, lever, linkedin, oracle, remotar

SOURCES: dict[str, Fetch] = {
    **{f"greenhouse:{t}": partial(greenhouse.fetch, token=t) for t in greenhouse.TOKENS},
    "gupy": gupy.fetch,
    "ashby:nubank": partial(ashby.fetch, org="nubank"),
    "lever:ciandt": partial(lever.fetch, company="ciandt"),
    "eightfold:mercadolibre": eightfold.fetch,
    "oracle:picpay": oracle.fetch,
    "himalayas": himalayas.fetch,
    "remotar": remotar.fetch,
    "linkedin": linkedin.fetch,
}


def make_client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, follow_redirects=True)
