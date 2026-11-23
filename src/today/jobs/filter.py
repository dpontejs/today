"""Keep ML / AI / data science roles that are remote, or hybrid/onsite in São Paulo or Natal. No LLM here:
word-boundary regexes over the title and location, accents folded."""

import re
import unicodedata

from today.jobs.models import JobPosting

ROLE = re.compile(
    r"machine learning|\bml\b|\bmle\b|\bmlops\b|data scien\w*|cientista de dados|ciencia de dados"
    r"|deep learning|computer vision|visao computacional"
    r"|\b(ai|ia) engineer|\bengenheir[oa](\s?\(a\))? de (ia|ai)\b"
    r"|\bllms?\b|\bgenai\b|applied scientist|research engineer"
)
# Sales roles mention AI all the time; the role term must be the role, not the product.
SALES_LEAD = re.compile(r"^\W*(sales|account|commercial|comercial|vendas)\b")
LOCAL = re.compile(r"sao paulo|\bsp\b|\bnatal\b")
BRAZIL_OR_LATAM = re.compile(r"\bbrazil\b|\bbrasil\b|\blatam\b|latin america|america latina|\bsp\b|sao paulo")


def fold(text: str) -> str:
    """Lowercase without accents: 'Visão' -> 'visao'."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def passes_filter(job: JobPosting) -> bool:
    title = fold(job.title)
    if not ROLE.search(title) or SALES_LEAD.search(title):
        return False
    if job.workplace == "remote":
        return True
    location = fold(job.location or "")
    if job.workplace is None:
        return not location or bool(BRAZIL_OR_LATAM.search(location))
    return bool(LOCAL.search(location))
