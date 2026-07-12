"""Eightfold PCSX (position search experience) API adapter.

Identifier format: "{host}/{domain}", e.g.
"apply.careers.microsoft.com/microsoft.com".

Listing:  GET https://{host}/api/pcsx/search
              ?domain={domain}&query={q}&location={loc}&start={n}&num=10
Details:  GET https://{host}/api/pcsx/position_details?position_id={id}&domain={domain}

Older Eightfold tenants exposed /api/apply/v2/jobs; tenants migrated to PCSX
reject it with 403 "Not authorized for PCSX" and serve this API instead.
The listing omits descriptions, so details are fetched only for titles that
pass the prefilter, capped at `detail_fetch_cap` per run.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ..errors import InvalidConfigError, StructureChangedError
from ..filters import location_matches
from ..models import Job
from ..textutil import strip_html
from .base import Adapter

log = logging.getLogger(__name__)

PAGE_SIZE = 10  # server-side cap; larger `num` values still return 10
DEFAULT_QUERIES = ["software engineer", "new grad", "machine learning engineer"]
DEFAULT_SEARCH_LOCATION = "United States"


class EightfoldAdapter(Adapter):
    source_type = "eightfold"

    def fetch(self) -> list[Job]:
        ident = self.company.source_identifier.strip().rstrip("/")
        host, _, domain = ident.partition("/")
        if not host or not domain:
            raise InvalidConfigError(
                f"{self.company.name}: eightfold identifier must be host/domain, got {ident!r}"
            )
        cfg = self.company.adapter_config
        queries = cfg.get("queries") or DEFAULT_QUERIES
        search_location = cfg.get("search_location", DEFAULT_SEARCH_LOCATION)
        max_pages = int(cfg.get("max_pages", 20))
        base = f"https://{host}/api/pcsx"

        seen: dict[str, dict] = {}
        for query in queries:
            for page in range(max_pages):
                params = {
                    "domain": domain,
                    "query": query,
                    "start": page * PAGE_SIZE,
                    "num": PAGE_SIZE,
                    "sort_by": "timestamp",  # newest first so paging caps hurt least
                }
                if search_location:
                    params["location"] = search_location
                data = self.client.get_json(f"{base}/search", params=params)
                positions = _positions(self.company.name, data)
                for item in positions:
                    pos_id = str(item.get("id", ""))
                    if pos_id:
                        seen.setdefault(pos_id, item)
                if len(positions) < PAGE_SIZE:
                    break

        jobs: list[Job] = []
        details_fetched = 0
        for pos_id, item in seen.items():
            title = item.get("name", "") or ""
            locations = item.get("locations") or item.get("standardizedLocations") or []
            path = item.get("positionUrl") or f"/careers/job/{pos_id}"
            url = f"https://{host}{path}?domain={domain}"
            job = self.new_job(
                source_job_id=str(item.get("displayJobId") or pos_id),
                title=title,
                location="; ".join(locations),
                department=item.get("department", "") or "",
                workplace_type=item.get("workLocationOption", "") or "",
                date_posted=_epoch_date(item.get("postedTs") or item.get("creationTs")),
                application_url=url,
                source_url=url,
            )
            location_ok = location_matches(job, self.company.locations)
            if (
                location_ok
                and self.title_prefilter(title)
                and details_fetched < self.detail_fetch_cap
            ):
                details_fetched += 1
                try:
                    self._fill_details(job, base, domain, pos_id)
                except Exception as exc:  # detail failure should not sink the listing
                    log.warning(
                        "%s: detail fetch failed for %s: %s", self.company.name, pos_id, exc
                    )
            jobs.append(job)
        return jobs

    def _fill_details(self, job: Job, base: str, domain: str, pos_id: str) -> None:
        data = self.client.get_json(
            f"{base}/position_details", params={"position_id": pos_id, "domain": domain}
        )
        info = data.get("data") or {}
        job.description = strip_html(info.get("jobDescription", "") or "")
        employment = info.get("efcustomTextEmploymentType") or []
        if employment:
            job.employment_type = str(employment[0])
        if info.get("location"):
            job.location = info["location"]
        if info.get("publicUrl"):
            job.application_url = info["publicUrl"]
            job.source_url = info["publicUrl"]


def _positions(company: str, data: object) -> list[dict]:
    if isinstance(data, dict):
        if data.get("status") == "failure" or data.get("errorMsg"):
            raise StructureChangedError(
                f"{company}: eightfold PCSX error: {data.get('errorMsg') or data}"
            )
        payload = data.get("data")
        if isinstance(payload, dict) and isinstance(payload.get("positions"), list):
            return payload["positions"]
    raise StructureChangedError(f"{company}: eightfold response missing 'data.positions'")


def _epoch_date(value: object) -> str:
    try:
        ts = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    return datetime.fromtimestamp(ts, UTC).date().isoformat()
