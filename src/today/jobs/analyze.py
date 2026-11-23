"""Pre-analysis of collected jobs against the owner's profile (feature 08).

`analyze_pending` takes the oldest `new` jobs, asks the analyst for a `JobAnalysis` each, and stores it.
An analyst error leaves the job `new` for the next slot; three errors take it out of the queue."""

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from today.jobs import analysis_repo
from today.jobs.models import PROMPT_VERSION, Gap, JobAnalysis
from today.jobs.repo import JobRow
from today.llm.analyst import Analyst, AnalystError

log = logging.getLogger(__name__)

__all__ = [
    "PROMPT_VERSION",
    "SYSTEM",
    "AnalyzeReport",
    "Gap",
    "JobAnalysis",
    "analyze_pending",
    "build_prompt",
]

MAX_DESCRIPTION = 12_000

SYSTEM = """\
Você avalia vagas para uma pessoa que procura emprego em ML/IA. Recebe o perfil dela (em markdown) \
e uma vaga, e responde só com o JSON pedido, em pt-BR.

- meets: requisitos da vaga que o perfil atende, curtos ("PyTorch", "deploy de modelos").
- gaps: o que falta. kind "required" para o que a vaga exige, "nice_to_have" para diferencial; note opcional.
- workplace, location, seniority: o que a vaga diz; "unknown" quando ela não diz.
- company_summary: área, porte e maturidade da empresa em uma ou duas frases.
- target_company: true só se a empresa está na lista de empresas-alvo do perfil.
- verdict: uma frase dizendo se vale aplicar e por quê.

score de 0 a 100, nesta ordem de peso:
1. Lacunas "required" pesam mais: cada uma derruba bastante a nota.
2. Lacunas "nice_to_have" pesam pouco.
3. Senioridade um nível acima do perfil não penaliza; dois ou mais níveis acima, sim. \
Estágio e júnior são bem-vindos se o perfil diz que aceita.
4. Empresa-alvo: +5.
5. Presencial ou híbrido fora de São Paulo e de Natal: −20.
Use a faixa inteira: 85+ é para aplicar hoje, abaixo de 50 é descartar.
"""


@dataclass(frozen=True)
class AnalyzeReport:
    analyzed: list[int] = field(default_factory=list)  # job ids stored this run, in order
    failed: int = 0
    skipped_reason: str | None = None


def build_prompt(job: JobRow, profile: str) -> str:
    description = job.description or "(sem descrição)"
    if len(description) > MAX_DESCRIPTION:
        description = description[:MAX_DESCRIPTION] + "\n(truncated)"
    return (
        f"<perfil>\n{profile.strip()}\n</perfil>\n\n"
        "<vaga>\n"
        f"Título: {job.title}\n"
        f"Empresa: {job.company}\n"
        f"Local: {job.location or 'não informado'}\n"
        f"Modelo de trabalho: {job.workplace or 'não informado'}\n"
        f"Fonte: {job.source}\n"
        f"Descrição:\n{description}\n"
        "</vaga>"
    )


def analyze_pending(
    conn: sqlite3.Connection, analyst: Analyst, model: str, now: datetime, limit: int = 20
) -> AnalyzeReport:
    profile = analysis_repo.get_profile(conn)
    if not profile.strip():
        log.warning("job analysis skipped: empty profile (set it with the set_profile MCP tool)")
        return AnalyzeReport(skipped_reason="empty profile")

    analyzed: list[int] = []
    failed = 0
    for job in analysis_repo.pending_jobs(conn, limit):
        try:
            result = analyst.complete(
                model=model, system=SYSTEM, prompt=build_prompt(job, profile), schema=JobAnalysis
            )
        except AnalystError as exc:
            failed += 1
            attempts = analysis_repo.record_failure(conn, job.id)
            gave_up = ", giving up" if attempts >= analysis_repo.MAX_ATTEMPTS else ""
            log.warning("job %s analysis failed (attempt %s%s): %s", job.id, attempts, gave_up, exc)
            continue
        analysis_repo.store_analysis(conn, job.id, result, model, now)
        analyzed.append(job.id)
    return AnalyzeReport(analyzed=analyzed, failed=failed)
