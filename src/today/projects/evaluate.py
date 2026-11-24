"""Is this project idea worth it for me? (feature 10). One structured call to the `Analyst` (ADR 0007).

The prompt carries the profile, the gaps that repeat in the jobs the owner cares about (`gap_stats`) and the
projects already registered, so the answer is about marginal value: what the idea would prove that nothing
else in the portfolio proves yet."""

import sqlite3
from datetime import datetime

from pydantic import BaseModel, Field

from today.jobs import analysis_repo
from today.llm.analyst import Analyst
from today.projects import repo
from today.projects.gaps import GapStat, gap_stats

PROMPT_VERSION = "1"

SYSTEM = """\
Você avalia ideias de projeto de portfólio para quem procura emprego em ML/IA. Recebe o perfil da pessoa, \
as lacunas que mais se repetem nas vagas que interessam a ela (com contagem) e os projetos que ela já tem. \
Responda só com o JSON pedido, em pt-BR.

- verdict: 1 ou 2 frases dizendo se vale fazer e por quê, pensando no valor marginal para as vagas-alvo.
- score de 0 a 100: 80+ quando cobre lacunas frequentes e obrigatórias que o perfil ainda não prova; \
abaixo de 50 quando repete o que o perfil e os projetos já mostram.
- covers: lacunas da lista que o projeto, como descrito, demonstraria (nomes da lista; junte sinônimos).
- already_shown: o que a ideia repete do que o perfil ou os projetos já provam.
- missing: o que falta na ideia para ela convencer quem contrata para essas vagas.
- scope_suggestions: mudanças concretas de escopo, cada uma ligada a uma lacuna da lista e com o porquê.
- effort_note: se o prazo dito parece curto ou longo para o escopo; null se não houver prazo ou se estiver ok.
Não invente lacunas: se a lista estiver vazia, diga que ainda não há sinal das vagas e avalie pelo perfil.
"""


class IdeaEvaluation(BaseModel):
    verdict: str
    score: int = Field(ge=0, le=100)
    covers: list[str]
    already_shown: list[str]
    missing: list[str]
    scope_suggestions: list[str]
    effort_note: str | None


def build_prompt(
    profile: str, gaps: list[GapStat], projects: list[repo.Project], project: repo.Project
) -> str:
    gap_lines = (
        "\n".join(f"- {g.skill}: {g.jobs} vagas ({g.required} como obrigatória)" for g in gaps)
        if gaps
        else "(nenhuma vaga analisada ainda: sem sinal do mercado)"
    )
    others = [p for p in projects if p.id != project.id]
    project_lines = "\n".join(f"- {p.name} ({p.status}): {p.idea_md.strip()}" for p in others) or "(nenhum)"
    return (
        f"<perfil>\n{profile.strip() or '(perfil vazio)'}\n</perfil>\n\n"
        f"<lacunas_das_vagas>\n{gap_lines}\n</lacunas_das_vagas>\n\n"
        f"<projetos_registrados>\n{project_lines}\n</projetos_registrados>\n\n"
        f"<ideia>\nNome: {project.name}\n{project.idea_md.strip()}\n</ideia>"
    )


def evaluate_idea(
    conn: sqlite3.Connection, analyst: Analyst, model: str, project_id: int, now: datetime
) -> IdeaEvaluation:
    """Evaluate the idea and store the result. Analyst errors propagate and leave the project untouched."""
    project = repo.get_project(conn, project_id)
    if project is None:
        raise ValueError(f"project {project_id} not found")
    prompt = build_prompt(
        analysis_repo.get_profile(conn), gap_stats(conn, now), repo.list_projects(conn), project
    )
    result = analyst.complete(model=model, system=SYSTEM, prompt=prompt, schema=IdeaEvaluation)
    repo.update_project(conn, project_id, now, evaluation=result.model_dump())
    return result
