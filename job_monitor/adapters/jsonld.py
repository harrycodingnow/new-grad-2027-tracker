"""Adapter for pages embedding schema.org JobPosting JSON-LD.

source_identifier: one URL, or adapter_config.urls for several pages.
Each page may contain one or many JobPosting objects (directly, in a list,
or inside @graph / itemListElement).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bs4 import BeautifulSoup

from ..errors import InvalidConfigError, ParseError
from ..models import Job
from ..textutil import strip_html
from .base import Adapter

log = logging.getLogger(__name__)


class JsonLdAdapter(Adapter):
    source_type = "jsonld"

    def fetch(self) -> list[Job]:
        urls = list(self.company.adapter_config.get("urls") or [])
        if self.company.source_identifier.strip():
            urls.insert(0, self.company.source_identifier.strip())
        if not urls:
            raise InvalidConfigError(f"{self.company.name}: jsonld adapter needs at least one URL")

        jobs: list[Job] = []
        found_any_ld = False
        for url in urls:
            resp = self.client.get(url)
            soup = BeautifulSoup(resp.text, "html.parser")
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    payload = json.loads(script.string or "")
                except (ValueError, TypeError):
                    continue
                found_any_ld = True
                for posting in _extract_postings(payload):
                    jobs.append(self._to_job(posting, url))
        if not jobs and not found_any_ld:
            raise ParseError(
                f"{self.company.name}: no JSON-LD blocks found — page structure may have changed"
            )
        return jobs

    def _to_job(self, posting: dict[str, Any], page_url: str) -> Job:
        org = posting.get("hiringOrganization")
        if isinstance(org, dict):
            org = org.get("name", "")
        job = self.new_job(
            source_job_id=str(posting.get("identifier", {}).get("value", ""))
            if isinstance(posting.get("identifier"), dict)
            else str(posting.get("identifier") or ""),
            title=posting.get("title", "") or "",
            location=_location(posting),
            country=_country(posting),
            employment_type=_first(posting.get("employmentType")) or "",
            description=strip_html(posting.get("description", "") or ""),
            application_url=posting.get("url") or posting.get("directApply") or page_url,
            source_url=page_url,
            date_posted=(posting.get("datePosted") or "")[:10],
        )
        if posting.get("jobLocationType") == "TELECOMMUTE":
            job.workplace_type = "remote"
        return job


def _extract_postings(payload: Any) -> list[dict[str, Any]]:
    """Find JobPosting dicts anywhere in a JSON-LD payload."""
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("@type") == "JobPosting" or (
                isinstance(node.get("@type"), list) and "JobPosting" in node["@type"]
            ):
                found.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return found


def _location(posting: dict[str, Any]) -> str:
    locs = posting.get("jobLocation")
    if isinstance(locs, dict):
        locs = [locs]
    parts: list[str] = []
    for loc in locs or []:
        address = loc.get("address") if isinstance(loc, dict) else None
        if isinstance(address, dict):
            piece = ", ".join(
                str(address.get(k, ""))
                for k in ("addressLocality", "addressRegion")
                if address.get(k)
            )
            if piece:
                parts.append(piece)
        elif isinstance(address, str):
            parts.append(address)
    return "; ".join(dict.fromkeys(parts))


def _country(posting: dict[str, Any]) -> str:
    locs = posting.get("jobLocation")
    if isinstance(locs, dict):
        locs = [locs]
    for loc in locs or []:
        address = loc.get("address") if isinstance(loc, dict) else None
        if isinstance(address, dict):
            country = address.get("addressCountry")
            if isinstance(country, dict):
                country = country.get("name")
            if country:
                return str(country)
    return ""


def _first(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")
