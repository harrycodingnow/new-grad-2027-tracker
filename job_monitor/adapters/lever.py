"""Lever public Postings API adapter.

GET https://api.lever.co/v0/postings/{site}?mode=json
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..errors import InvalidConfigError, StructureChangedError
from ..models import Job
from .base import Adapter

API = "https://api.lever.co/v0/postings/{site}"


class LeverAdapter(Adapter):
    source_type = "lever"

    def fetch(self) -> list[Job]:
        site = self.company.source_identifier.strip()
        if not site:
            raise InvalidConfigError(f"{self.company.name}: lever site token missing")
        data = self.client.get_json(API.format(site=site), params={"mode": "json"})
        if not isinstance(data, list):
            raise StructureChangedError(f"{self.company.name}: lever response is not a list")
        jobs: list[Job] = []
        for item in data:
            categories = item.get("categories") or {}
            requirements = ""
            for lst in item.get("lists") or []:
                if (
                    "requirement" in (lst.get("text") or "").lower()
                    or "qualification" in (lst.get("text") or "").lower()
                ):
                    requirements += " " + (lst.get("content") or "")
            created = item.get("createdAt")
            date_posted = (
                datetime.fromtimestamp(created / 1000, tz=UTC).date().isoformat() if created else ""
            )
            job = self.new_job(
                source_job_id=str(item.get("id", "")),
                title=item.get("text", "") or "",
                location=categories.get("location", "") or "",
                country=item.get("country", "") or "",
                workplace_type=(item.get("workplaceType") or "").lower(),
                department=categories.get("team", "") or "",
                employment_type=categories.get("commitment", "") or "",
                description=item.get("descriptionPlain", "") or _strip(item.get("description", "")),
                requirements=_strip(requirements),
                application_url=item.get("applyUrl") or item.get("hostedUrl") or "",
                source_url=item.get("hostedUrl", "") or "",
                date_posted=date_posted,
            )
            jobs.append(job)
        return jobs


def _strip(html: str) -> str:
    from ..textutil import strip_html

    return strip_html(html)
