import sqlite3
from datetime import UTC, datetime

from helpers import job_with_gaps

from today.jobs import analysis_repo as ar
from today.projects import repo as pr
from today.projects.evaluate import IdeaEvaluation, build_prompt, evaluate_idea
from today.projects.gaps import GapStat

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def evaluation(score: int = 80) -> IdeaEvaluation:
    return IdeaEvaluation(
        verdict="Vale a pena.", score=score, covers=["spark"], already_shown=["PyTorch"],
        missing=["deploy"], scope_suggestions=["Adicionar Spark"], effort_note=None,
    )  # fmt: skip


class FakeAnalyst:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def complete(self, *, model, system, prompt, schema):
        self.calls.append({"model": model, "system": system, "prompt": prompt})
        return evaluation()


def test_prompt_has_profile_gaps_and_projects():
    others = [pr.Project(1, "today", "PWA pessoal", "done", None, None, None, "", "")]
    idea = "Risco de crédito no GCP com PySpark"
    project = pr.Project(2, "credit-risk", idea, "idea", None, None, None, "", "")
    gaps = [GapStat(skill="spark", jobs=14, required=9, weight=30.0)]

    prompt = build_prompt("# Perfil\nML Engineer", gaps, others, project)

    assert "# Perfil" in prompt and "ML Engineer" in prompt
    assert "spark: 14 vagas (9 como obrigatória)" in prompt
    assert "today (done): PWA pessoal" in prompt
    assert "credit-risk" in prompt and "Risco de crédito no GCP com PySpark" in prompt
    assert prompt.count("credit-risk") == 1  # the idea under evaluation is not listed as an existing project


def test_prompt_says_when_no_gaps_yet_or_empty_profile():
    project = pr.Project(1, "x", "ideia", "idea", None, None, None, "", "")

    prompt = build_prompt("", [], [project], project)

    assert "(nenhuma vaga analisada ainda" in prompt
    assert "(perfil vazio)" in prompt


def test_evaluate_stores_evaluation(conn: sqlite3.Connection):
    ar.set_profile(conn, "# Perfil", NOW)
    job_with_gaps(conn, "a", [("Spark", "required")], NOW)
    pid = pr.create_project(conn, "credit-risk", "Risco de crédito", NOW)
    analyst = FakeAnalyst()

    result = evaluate_idea(conn, analyst, "opus", pid, NOW)

    assert result == evaluation()
    assert analyst.calls[0]["model"] == "opus" and "spark: 1 vagas" in analyst.calls[0]["prompt"]
    stored = pr.get_project(conn, pid)
    assert IdeaEvaluation.model_validate(stored.evaluation) == evaluation()
    assert stored.evaluated_at is not None
