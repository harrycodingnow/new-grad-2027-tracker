"""Ashby public job-posting API adapter.

GET https://api.ashbyhq.com/posting-api/job-board/{org}
"""

from __future__ import annotations

from ..errors import InvalidConfigError, StructureChangedError
from ..models import Job
from ..textutil import strip_html
from .base import Adapter

API = "https://api.ashbyhq.com/posting-api/job-board/{org}"


class AshbyAdapter(Adapter):
    source_type = "ashby"

    def fetch(self) -> list[Job]:
        org = self.company.source_identifier.strip()
        if not org:
            raise InvalidConfigError(f"{self.company.name}: ashby organization name missing")
        data = self.client.get_json(API.format(org=org))
        if not isinstance(data, dict) or "jobs" not in data:
            raise StructureChangedError(f"{self.company.name}: ashby response missing 'jobs' key")
        jobs: list[Job] = []
        for item in data["jobs"]:
            if item.get("isListed") is False:
                continue
            locations = [item.get("location") or ""]
            locations += [
                loc.get("location", "")
                for loc in item.get("secondaryLocations") or []
                if loc.get("location")
            ]
            job = self.new_job(
                source_job_id=str(item.get("id", "")),
                title=item.get("title", "") or "",
                location="; ".join(loc for loc in locations if loc),
                workplace_type="remote" if item.get("isRemote") else "",
                department=item.get("department", "") or item.get("team", "") or "",
                employment_type=item.get("employmentType", "") or "",
                description=strip_html(item.get("descriptionHtml") or "")
                or (item.get("descriptionPlain") or ""),
                application_url=item.get("applyUrl") or item.get("jobUrl") or "",
                source_url=item.get("jobUrl", "") or "",
                date_posted=(item.get("publishedAt") or "")[:10],
            )
            jobs.append(job)
        return jobs
