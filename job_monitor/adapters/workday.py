"""Workday CXS (career site) JSON API adapter.

Identifier format: "{host}/{tenant}/{site}", e.g.
"nvidia.wd5.myworkdayjobs.com/nvidia/NVIDIAExternalCareerSite".

Listing:  POST https://{host}/wday/cxs/{tenant}/{site}/jobs
Details:  GET  https://{host}/wday/cxs/{tenant}/{site}{externalPath}

The listing does not include descriptions, so details are fetched only for
titles that pass the prefilter, capped at `detail_fetch_cap` per run.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta

from ..errors import InvalidConfigError, NetworkError, StructureChangedError
from ..filters import location_matches
from ..models import Job
from ..textutil import strip_html
from .base import Adapter

log = logging.getLogger(__name__)

# Workday's stable facet ID for "United States of America".
US_COUNTRY_FACET = "bc33aa3152ec42d4995f4791a106ed09"
PAGE_SIZE = 20  # CXS maximum

DEFAULT_SEARCH_TEXTS = ["new grad", "university graduate", "early career engineer"]


class WorkdayAdapter(Adapter):
    source_type = "workday"

    def fetch(self) -> list[Job]:
        ident = self.company.source_identifier.strip().rstrip("/")
        parts = ident.split("/")
        if len(parts) != 3:
            raise InvalidConfigError(
                f"{self.company.name}: workday identifier must be host/tenant/site, got {ident!r}"
            )
        host, tenant, site = parts
        base = f"https://{host}/wday/cxs/{tenant}/{site}"
        cfg = self.company.adapter_config
        search_texts = cfg.get("search_texts") or DEFAULT_SEARCH_TEXTS
        max_pages = int(cfg.get("max_pages", 3))
        # Workday's US facet GUID is common but not universal; some tenants
        # reject it with HTTP 400. Fall back to unfaceted search (the runner's
        # location gate filters non-US postings downstream).
        facets = {"locationCountry": [cfg.get("country_facet", US_COUNTRY_FACET)]}

        seen: dict[str, dict] = {}
        for text in search_texts:
            for page in range(max_pages):
                body = {
                    "appliedFacets": facets,
                    "limit": PAGE_SIZE,
                    "offset": page * PAGE_SIZE,
                    "searchText": text,
                }
                try:
                    data = self.client.post_json(f"{base}/jobs", json_body=body)
                except NetworkError as exc:
                    if facets and "400" in exc.message:
                        log.info(
                            "%s: tenant rejected the country facet; retrying unfaceted",
                            self.company.name,
                        )
                        facets = {}
                        body["appliedFacets"] = {}
                        data = self.client.post_json(f"{base}/jobs", json_body=body)
                    else:
                        raise
                postings = data.get("jobPostings")
                if postings is None:
                    raise StructureChangedError(
                        f"{self.company.name}: workday response missing 'jobPostings'"
                    )
                for item in postings:
                    path = item.get("externalPath")
                    if path:
                        seen.setdefault(path, item)
                if len(postings) < PAGE_SIZE:
                    break

        jobs: list[Job] = []
        details_fetched = 0
        for path, item in seen.items():
            title = item.get("title", "") or ""
            bullet = item.get("bulletFields") or []
            source_job_id = str(bullet[0]) if bullet else path.rsplit("/", 1)[-1]
            job = self.new_job(
                source_job_id=source_job_id,
                title=title,
                location=item.get("locationsText", "") or "",
                date_posted=_parse_posted_on(item.get("postedOn", "")),
                application_url=f"https://{host}/en-US/{site}{path}",
                source_url=f"https://{host}/en-US/{site}{path}",
            )
            location_ok = location_matches(job, self.company.locations)
            if (
                location_ok
                and self.title_prefilter(title)
                and details_fetched < self.detail_fetch_cap
            ):
                details_fetched += 1
                try:
                    self._fill_details(job, base, path)
                except Exception as exc:  # detail failure should not sink the listing
                    log.warning("%s: detail fetch failed for %s: %s", self.company.name, path, exc)
            jobs.append(job)
        return jobs

    def _fill_details(self, job: Job, base: str, path: str) -> None:
        data = self.client.get_json(f"{base}{path}")
        info = data.get("jobPostingInfo") or {}
        job.description = strip_html(info.get("jobDescription", ""))
        job.employment_type = info.get("timeType", "") or ""
        job.location = info.get("location", "") or job.location
        if info.get("country"):
            job.country = (
                (info["country"].get("descriptor") or job.country)
                if isinstance(info["country"], dict)
                else job.country
            )
        posted = _parse_posted_on(info.get("postedOn", ""))
        if posted:
            job.date_posted = posted
        if info.get("externalUrl"):
            job.application_url = info["externalUrl"]


def _parse_posted_on(text: str) -> str:
    """Convert Workday's 'Posted 3 Days Ago' style strings to an ISO date."""
    if not text:
        return ""
    text = text.lower()
    today = datetime.now(UTC).date()
    if "today" in text:
        return today.isoformat()
    if "yesterday" in text:
        return (today - timedelta(days=1)).isoformat()
    match = re.search(r"(\d+)\+?\s*day", text)
    if match:
        return (today - timedelta(days=int(match.group(1)))).isoformat()
    if "30+" in text:
        return (today - timedelta(days=31)).isoformat()
    return ""
