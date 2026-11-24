import pytest

from today.jobs.filter import passes_filter
from today.jobs.models import JobPosting


def job(title: str, location: str | None = "Brazil", workplace: str | None = "remote") -> JobPosting:
    return JobPosting(
        source="test",
        external_id="1",
        company="Acme",
        title=title,
        location=location,
        workplace=workplace,
        description=None,
        url="https://example.com/1",
        published_at=None,
    )


@pytest.mark.parametrize(
    ("title", "kept"),
    [
        ("ML Engineer", True),
        ("Cientista de Dados Pleno", True),
        ("Engenheiro de Visão Computacional", True),
        ("MLOps Engineer", True),
        ("AI/ ML Engineer", True),
        ("[30118] - AI Engineer", True),
        ("Engenheiro(a) de IA Pleno", True),
        ("Data Scientist II", True),
        ("LLM Applied Scientist", True),
        ("Account Executive", False),
        ("Sales Engineer – AI products", False),
        ("Comercial - Machine Learning Solutions", False),
        ("Product Designer", False),
        ("Deputy MLRO (AML Compliance)", False),
        ("Desenvolvedor HTML", False),
    ],
)
def test_filter_keeps_ml_roles_and_drops_sales(title: str, kept: bool):
    assert passes_filter(job(title)) is kept


@pytest.mark.parametrize(
    ("location", "workplace", "kept"),
    [
        ("Rio de Janeiro, RJ", "onsite", False),
        ("São Paulo, SP", "onsite", True),
        ("SAO PAULO, SP, Brasil", "onsite", True),
        ("Osasco, SP, Brasil", "hybrid", True),
        ("Natal", "onsite", True),
        ("Curitiba, Paraná", "hybrid", False),
        ("Berlin, Germany", "remote", True),
        (None, "remote", True),
        ("Brazil", None, True),
        ("Argentina, Brazil, Chile", None, True),
        ("LATAM", None, True),
        ("Bogota", None, False),
        ("Palo Alto", None, False),
        (None, None, True),
    ],
)
def test_filter_drops_onsite_outside_sp(location: str | None, workplace: str | None, kept: bool):
    assert passes_filter(job("Machine Learning Engineer", location, workplace)) is kept


@pytest.mark.parametrize(
    ("title", "kept"),
    [
        ("Estágio em Ciência de Dados", True),
        ("Machine Learning Intern", True),
        ("Estágio Comercial", False),
        ("Estagiário Jurídico", False),
        ("Software Engineering Intern", False),
    ],
)
def test_intern_kept_only_with_role_term(title: str, kept: bool):
    assert passes_filter(job(title)) is kept


@pytest.mark.parametrize("location", ["Remote", "Remoto", "Home Office", "Anywhere", "Remote - Brazil"])
def test_unknown_workplace_with_remote_location_kept(location: str):
    assert passes_filter(job("Machine Learning Engineer", location, None)) is True


@pytest.mark.parametrize(
    ("title", "kept"),
    [
        ("Engenheiro de Inteligência Artificial", True),
        ("Cientista de Inteligência Artificial Pleno", True),
        ("Software Engineer — Artificial Intelligence & Data Products", True),
        ("Advogado - Inteligência Artificial e Privacidade", False),
    ],
)
def test_spelled_out_ai_counts_with_an_engineering_role(title: str, kept: bool):
    assert passes_filter(job(title)) is kept


@pytest.mark.parametrize(
    ("title", "kept"),
    [
        ("Senior Machine Learning Engineer", False),
        ("Cientista de Dados Sênior", False),
        ("ML Engineer Sr.", False),
        ("Sr ML Engineer", False),
        ("Cientista de Dados Especialista", False),
        ("Staff Machine Learning Engineer", False),
        ("Principal Applied Scientist", False),
        ("Lead Data Scientist", False),
        ("Tech Lead - Machine Learning", False),
        ("Head of AI Engineering", False),
        ("Data Science Coordinator", False),
        ("Coordenador(a) de Ciência de Dados", False),
        ("Gerente de Machine Learning", False),
        ("Machine Learning Engineering Manager", False),
        ("Director, Applied Science", False),
        ("Diretor de Ciência de Dados", False),
        # kept: junior/mid/no level, and words that only look like levels
        ("Machine Learning Engineer", True),
        ("Cientista de Dados Pleno", True),
        ("Engenheiro de Machine Learning Júnior", True),
        ("Estágio em Ciência de Dados", True),
        ("Data Scientist II", True),
        ("ML Engineer - Lead Scoring models", True),  # "lead scoring" is a domain, not a level
        ("Machine Learning Engineer - Leadership Team support", True),
    ],
)
def test_filter_drops_senior_and_above(title: str, kept: bool):
    """~2 years of experience: senior/specialist and above use analysis quota and score ~30 (2026-11-24)."""
    assert passes_filter(job(title)) is kept
