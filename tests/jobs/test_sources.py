"""Each adapter against a response recorded on 2026-11-23 (LinkedIn's was written by hand: the guest endpoint
answered 429 while recording). No test touches the network."""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from today.jobs.models import html_to_text
from today.jobs.sources import (
    SOURCES,
    ashby,
    eightfold,
    greenhouse,
    gupy,
    himalayas,
    lever,
    linkedin,
    oracle,
    remotar,
)

FIXTURES = Path(__file__).parent.parent / "fixtures" / "jobs"
ORACLE_PATH = "epdm.fa.la1.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"


def serve(routes: dict[str, str], seen: list[httpx.Request] | None = None) -> httpx.Client:
    """A client whose transport answers `host+path` with a fixture file; anything else is a 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        key = request.url.host + request.url.path
        if key == "mercadolibre.eightfold.ai/api/pcsx/position_details":
            name = f"eightfold_details_{request.url.params['position_id']}.json"
        elif key in routes:
            name = routes[key]
        else:
            return httpx.Response(404, text="not found")
        content = (FIXTURES / name).read_bytes()
        kind = "text/html" if name.endswith(".html") else "application/json"
        return httpx.Response(200, content=content, headers={"content-type": kind})

    return httpx.Client(transport=httpx.MockTransport(handler))


def no_sleep(_seconds: float) -> None:
    return None


def test_greenhouse_parses_recorded_response():
    client = serve(
        {"boards-api.greenhouse.io/v1/boards/ifoodcarreiras/jobs": "greenhouse_ifoodcarreiras.json"}
    )

    jobs = greenhouse.fetch(client, "ifoodcarreiras")

    assert len(jobs) == 2
    first = jobs[0]
    assert first.source == "greenhouse:ifoodcarreiras"
    assert first.external_id == "8058884002"
    assert first.company == "iFood"
    assert first.title == "Senior Staff AI/ ML Engineer"
    assert first.url == "https://job-boards.greenhouse.io/ifoodcarreiras/jobs/8058884002"
    assert first.location == "Brasil"
    assert first.workplace is None
    assert first.published_at == datetime(2025, 7, 17, 14, 20, 45, tzinfo=UTC)
    assert first.description and "<" not in first.description and "&lt;" not in first.description


def test_gupy_parses_recorded_response():
    client = serve({"portal.gupy.io/api/job-search/jobs": "gupy_portal.json"})

    jobs = gupy.fetch(client)

    assert len(jobs) == 3  # the same fixture answers every term: postings are deduplicated by id
    first = jobs[0]
    assert first.source == "gupy"
    assert first.external_id == "12921860"
    assert first.company == "Memed ativo"
    assert first.title == "Machine Learning Enginner"
    assert first.url.startswith("https://memed.gupy.io/job/")
    assert first.workplace == "remote"
    assert first.location is None
    assert jobs[1].workplace == "onsite"
    assert jobs[1].location == "Curitiba, Paraná"
    assert first.description and "<" not in first.description


def test_ashby_parses_recorded_response():
    client = serve({"api.ashbyhq.com/posting-api/job-board/nubank": "ashby_nubank.json"})

    jobs = ashby.fetch(client, "nubank")

    assert len(jobs) == 2
    first = jobs[0]
    assert first.source == "ashby:nubank"
    assert first.external_id == "ecd4ec39-1f0a-4f65-b27a-f537c895a233"
    assert first.company == "Nubank"
    assert first.title == "Lead Machine Learning Engineer"
    assert first.url == "https://jobs.ashbyhq.com/nubank/ecd4ec39-1f0a-4f65-b27a-f537c895a233"
    assert first.workplace == "hybrid"
    assert first.location == "São Paulo"
    assert first.description and "<" not in first.description


def test_lever_parses_recorded_response():
    client = serve({"api.lever.co/v0/postings/ciandt": "lever_ciandt.json"})

    jobs = lever.fetch(client, "ciandt")

    assert len(jobs) == 2
    first = jobs[0]
    assert first.source == "lever:ciandt"
    assert first.external_id == "b5a7671b-6612-4ed7-ae0a-132c920bc66d"
    assert first.company == "CI&T"
    assert first.title == "[30118] - Senior AI Engineer"
    assert first.url == "https://jobs.lever.co/ciandt/b5a7671b-6612-4ed7-ae0a-132c920bc66d"
    assert first.workplace == "remote"
    assert first.location == "Brazil"
    assert first.description and "<" not in first.description


def test_eightfold_parses_recorded_response():
    client = serve({"mercadolibre.eightfold.ai/api/pcsx/search": "eightfold_search.json"})

    jobs = eightfold.fetch(client)

    assert len(jobs) == 3
    first = jobs[0]
    assert first.source == "eightfold:mercadolibre"
    assert first.external_id == "45279412"
    assert first.company == "Mercado Livre"
    assert first.title == "Senior Software Engineer — Artificial Intelligence & Data Products"
    assert first.url == "https://mercadolibre.eightfold.ai/careers/job/45279412"
    assert first.workplace == "hybrid"
    assert first.location == "Sudeste,Brazil; Osasco, SP, Brasil"
    assert jobs[1].workplace == "onsite"
    assert first.description and "<" not in first.description


def test_oracle_parses_recorded_response():
    client = serve({ORACLE_PATH: "oracle_picpay.json"})

    jobs = oracle.fetch(client)

    assert len(jobs) == 3
    first = jobs[0]
    assert first.source == "oracle:picpay"
    assert first.external_id == "11815"
    assert first.company == "PicPay"
    assert first.title == "ANALISTA ESTRATEGIA PREVENCAO PL"
    assert (
        first.url
        == "https://epdm.fa.la1.oraclecloud.com/hcmUI/CandidateExperience/pt-BR/sites/CX_1/job/11815"
    )
    assert first.workplace is None
    assert first.location == "SAO PAULO, SP, Brasil"
    assert first.published_at == datetime(2026, 11, 16, tzinfo=UTC)
    assert first.description is None


def test_himalayas_parses_recorded_response():
    client = serve({"himalayas.app/jobs/api/search": "himalayas.json"})

    jobs = himalayas.fetch(client)

    assert len(jobs) == 2
    first = jobs[0]
    assert first.source == "himalayas"
    assert (
        first.external_id
        == "https://himalayas.app/companies/zarego/jobs/machine-learning-engineer-python-remote-latam"
    )
    assert first.company == "Zarego"
    assert first.title == "Machine Learning Engineer - Python / Remote LATAM"
    assert first.url == first.external_id
    assert first.workplace is None
    assert "Brazil" in first.location
    assert first.description and "<" not in first.description


def test_remotar_parses_recorded_response():
    client = serve({"api.remotar.com.br/jobs": "remotar.json"})

    jobs = remotar.fetch(client)

    assert len(jobs) == 3
    first = jobs[0]
    assert first.source == "remotar"
    assert first.external_id == "173089"
    assert first.company == "System Soft Technologies"
    assert first.title == "Machine Learning Engineer"
    assert first.url == "https://www.linkedin.com/jobs/view/4492585641/?"
    assert first.workplace == "remote"
    assert first.description and "<" not in first.description


def test_linkedin_parses_recorded_response():
    seen: list[httpx.Request] = []
    client = serve(
        {"www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search": "linkedin_search.html"}, seen
    )

    jobs = linkedin.fetch(client, sleep=no_sleep)

    assert len(jobs) == 2
    first = jobs[0]
    assert first.source == "linkedin"
    assert first.external_id == "4492585641"
    assert first.company == "Acme AI & Dados"
    assert first.title == "Machine Learning Engineer"
    assert first.url == "https://www.linkedin.com/jobs/view/4492585641"
    assert first.workplace is None
    assert first.location == "São Paulo, São Paulo, Brazil"
    assert first.published_at == datetime(2026, 11, 23, tzinfo=UTC)
    assert first.description is None  # fetched by `collect`, only for postings that pass the filter
    assert all(r.url.params["f_TPR"] == "r86400" for r in seen)
    assert all("Mozilla" in r.headers["user-agent"] for r in seen)
    assert all("cookie" not in r.headers for r in seen)


def test_linkedin_stops_on_429_and_reports_what_it_had():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(200, content=(FIXTURES / "linkedin_search.html").read_bytes())
        return httpx.Response(429)

    slept: list[float] = []
    with pytest.raises(linkedin.PartialFetch) as blocked:
        linkedin.fetch(httpx.Client(transport=httpx.MockTransport(handler)), sleep=slept.append)

    assert len(blocked.value.jobs) == 2  # kept, and the block still shows in the report
    assert "429" in str(blocked.value)
    assert len(calls) == 2  # one page, then the 429 stops every remaining term
    assert slept and all(3 <= s <= 7 for s in slept)


def test_linkedin_description_is_plain_text():
    client = serve({"www.linkedin.com/jobs/view/4492585641": "linkedin_detail.html"})

    text = linkedin.fetch_linkedin_description(client, "4492585641")

    assert text is not None
    assert "computer vision models & ship them" in text
    assert "MLOps" in text
    assert "<" not in text and "Show more" not in text


def test_adapter_raises_on_html_error_page():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>", headers={"content-type": "text/html"})

    with pytest.raises(ValueError):
        lever.fetch(httpx.Client(transport=httpx.MockTransport(handler)), "ciandt")


def test_html_to_text_drops_tags_scripts_and_entities():
    text = html_to_text("<p>A &amp; B</p><script>alert(1)</script><ul><li>one</li><li>two</li></ul>")

    assert text == "A & B\none\ntwo"


def test_sources_registry_has_every_spec_source():
    tokens = ["ifoodcarreiras", "inter", "c6bank", "xpinc", "btgpactual", "quintoandar", "stone", "vtex"]
    tokens += ["wildlifestudios", "hotmartcareersbr"]
    expected = {f"greenhouse:{t}" for t in tokens} | {
        "gupy",
        "ashby:nubank",
        "lever:ciandt",
        "eightfold:mercadolibre",
        "oracle:picpay",
        "himalayas",
        "remotar",
        "linkedin",
    }
    assert set(SOURCES) == expected


def test_linkedin_never_sends_cookies_even_when_set():
    sent: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request.headers.get("cookie"))
        name = "linkedin_detail.html" if "/jobs/view/" in request.url.path else "linkedin_search.html"
        body = (FIXTURES / name).read_bytes()
        return httpx.Response(200, content=body, headers={"set-cookie": "bcookie=abc; Path=/"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    linkedin.fetch(client, terms=("a", "b"), sleep=no_sleep)
    linkedin.fetch_linkedin_description(client, "4492585641")

    assert len(sent) == 3
    assert sent == [None, None, None]


def test_linkedin_challenge_page_raises():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><script>var _0x26bb=1;</script></html>")

    with pytest.raises(ValueError, match="no job cards"):
        linkedin.fetch(httpx.Client(transport=httpx.MockTransport(handler)), sleep=no_sleep)


def test_linkedin_cards_that_do_not_parse_raise():
    page = '<li><div data-entity-urn="urn:li:jobPosting:1"><h3 class="renamed">ML</h3></div></li>'

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=page)

    with pytest.raises(ValueError, match="markup changed"):
        linkedin.fetch(httpx.Client(transport=httpx.MockTransport(handler)), sleep=no_sleep)


def test_linkedin_empty_result_is_not_an_error():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="")

    assert linkedin.fetch(httpx.Client(transport=httpx.MockTransport(handler)), sleep=no_sleep) == []


def test_linkedin_descriptions_pause_and_stop_on_block():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if len(calls) == 2:
            return httpx.Response(429)
        return httpx.Response(200, content=(FIXTURES / "linkedin_detail.html").read_bytes())

    slept: list[float] = []
    describe = linkedin.Describer(sleep=slept.append)
    client = httpx.Client(transport=httpx.MockTransport(handler))

    results = [describe(client, i) for i in ("1", "2", "3", "4")]

    assert results[0] and results[1:] == [None, None, None]
    assert len(calls) == 2  # blocked at the second: no more requests this run
    assert len(slept) == 1 and 3 <= slept[0] <= 7
