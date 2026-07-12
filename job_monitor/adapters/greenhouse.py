"""Greenhouse public Job Board API adapter.

https://developers.greenhouse.io/job-board.html
GET https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true
"""

from __future__ import annotations

import html as html_mod

from ..errors import InvalidConfigError, StructureChangedError
from ..models import Job
from ..textutil import strip_html
from .base import Adapter

API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


class GreenhouseAdapter(Adapter):
    source_type = "greenhouse"

    def fetch(self) -> list[Job]:
        board = self.company.source_identifier.strip()
        if not board:
            raise InvalidConfigError(f"{self.company.name}: greenhouse board token missing")
        data = self.client.get_json(API.format(board=board), params={"content": "true"})
        if not isinstance(data, dict) or "jobs" not in data:
            raise StructureChangedError(
                f"{self.company.name}: greenhouse response missing 'jobs' key"
            )
        jobs: list[Job] = []
        for item in data["jobs"]:
            content = strip_html(html_mod.unescape(item.get("content") or ""))
            departments = ", ".join(
                d.get("name", "") for d in item.get("departments") or [] if d.get("name")
            )
            job = self.new_job(
                source_job_id=str(item.get("id", "")),
                title=item.get("title", "") or "",
                location=(item.get("location") or {}).get("name", "") or "",
                department=departments,
                description=content,
                application_url=item.get("absolute_url", "") or "",
                source_url=item.get("absolute_url", "") or "",
                date_posted=_date(item.get("first_published") or item.get("updated_at") or ""),
            )
            jobs.append(job)
        return jobs


def _date(value: str) -> str:
    return value[:10] if value else ""
