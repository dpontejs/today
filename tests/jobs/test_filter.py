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
        ("Senior ML Engineer", True),
        ("Cientista de Dados Pleno", True),
        ("Engenheiro de Visão Computacional", True),
        ("MLOps Engineer", True),
        ("Senior Staff AI/ ML Engineer", True),
        ("[30118] - Senior AI Engineer", True),
        ("Engenheiro(a) de IA Sênior", True),
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
