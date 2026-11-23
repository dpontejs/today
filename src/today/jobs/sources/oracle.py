"""Oracle Recruiting Cloud (PicPay). Few open roles: list them all and let the filter decide."""

from datetime import UTC, datetime

import httpx

from today.jobs.models import JobPosting, get_json, text_or_none, workplace

HOST = "https://epdm.fa.la1.oraclecloud.com"
SITE = "CX_1"
PAGE = 25
MAX = 500


def _date(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value).replace(tzinfo=UTC) if value else None


def fetch(client: httpx.Client) -> list[JobPosting]:
    rows: list[dict] = []
    offset = 0
    while offset < MAX:
        params = {
            "onlyData": "true",
            "expand": "requisitionList",
            "finder": f"findReqs;siteNumber={SITE},limit={PAGE},offset={offset}",
        }
        data = get_json(
            client, f"{HOST}/hcmRestApi/resources/latest/recruitingCEJobRequisitions", params=params
        )
        search = data["items"][0]
        rows += search["requisitionList"]
        offset += PAGE
        if not search["requisitionList"] or offset >= search["TotalJobsCount"]:
            break
    return [
        JobPosting(
            source="oracle:picpay",
            external_id=str(row["Id"]),
            company="PicPay",
            title=row["Title"].strip(),
            location=row.get("PrimaryLocation") or None,
            workplace=workplace(row.get("WorkplaceType") or row.get("WorkplaceTypeCode")),
            description=text_or_none(row.get("ShortDescriptionStr")),
            url=f"{HOST}/hcmUI/CandidateExperience/pt-BR/sites/{SITE}/job/{row['Id']}",
            published_at=_date(row.get("PostedDate")),
        )
        for row in rows
    ]
