"""Which gaps repeat in the jobs the owner cares about (feature 10): the market signal for project ideas."""

import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

from pydantic import BaseModel

from today.jobs.models import JobAnalysis
from today.jobs.repo import to_db

INTERESTED_WEIGHT = 3.0  # interested or applied
STRONG_WEIGHT = 2.0  # score >= STRONG_SCORE
STRONG_SCORE = 70


class GapStat(BaseModel):
    skill: str  # normalized: lowercase, trimmed
    jobs: int  # distinct jobs listing it
    required: int  # of those, as required
    weight: float  # sum over jobs of the job's weight


def _weight(status: str, score: int) -> float:
    if status in ("interested", "applied"):
        return INTERESTED_WEIGHT
    return STRONG_WEIGHT if score >= STRONG_SCORE else 1.0


def gap_stats(conn: sqlite3.Connection, now: datetime, days: int = 60, limit: int = 20) -> list[GapStat]:
    """Gaps of jobs analyzed in the last `days` (dismissed ones excluded), heaviest first."""
    rows = conn.execute(
        """SELECT j.status, a.score, a.analysis_json FROM job_analyses a JOIN jobs j ON j.id = a.job_id
           WHERE a.analyzed_at >= ? AND j.status != 'dismissed'""",
        (to_db(now - timedelta(days=days)),),
    ).fetchall()
    jobs: dict[str, int] = defaultdict(int)
    required: dict[str, int] = defaultdict(int)
    weight: dict[str, float] = defaultdict(float)
    for row in rows:
        kinds: dict[str, set[str]] = defaultdict(set)  # one count per job, even if listed twice
        for gap in JobAnalysis.model_validate_json(row["analysis_json"]).gaps:
            skill = gap.skill.strip().lower()
            if skill:
                kinds[skill].add(gap.kind)
        for skill, seen in kinds.items():
            jobs[skill] += 1
            required[skill] += "required" in seen
            weight[skill] += _weight(row["status"], row["score"])
    stats = [GapStat(skill=s, jobs=jobs[s], required=required[s], weight=weight[s]) for s in jobs]
    stats.sort(key=lambda s: (-s.weight, -s.jobs, s.skill))
    return stats[:limit]
