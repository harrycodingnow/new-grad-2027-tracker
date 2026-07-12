"""Optional last-resort adapter for JavaScript-rendered pages via Playwright.

Only used when explicitly configured (source_type: playwright) and the
`playwright` extra is installed. It renders the page, then extracts jobs
either from JSON-LD blocks or with the same CSS-selector config as the HTML
adapter. It never bypasses CAPTCHAs, logins or robots restrictions — if the
rendered page presents a challenge, the source fails with `blocked`.
"""

from __future__ import annotations

import json
import logging

from bs4 import BeautifulSoup

from ..errors import BlockedError, InvalidConfigError, UnsupportedSourceError
from ..models import Job
from ..textutil import normalize_ws
from .base import Adapter
from .jsonld import _extract_postings

log = logging.getLogger(__name__)

_CHALLENGE_MARKERS = ("captcha", "cf-challenge", "are you a robot", "access denied")


class PlaywrightAdapter(Adapter):
    source_type = "playwright"

    def fetch(self) -> list[Job]:
        url = self.company.source_identifier.strip()
        if not url:
            raise InvalidConfigError(f"{self.company.name}: playwright adapter needs a URL")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise UnsupportedSourceError(
                f"{self.company.name}: playwright not installed "
                "(pip install -e '.[browser]' && playwright install chromium)"
            ) from exc

        from .. import USER_AGENT

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=USER_AGENT)
                page.goto(url, wait_until="networkidle", timeout=45000)
                wait_for = self.company.adapter_config.get("wait_for_selector")
                if wait_for:
                    page.wait_for_selector(wait_for, timeout=20000)
                html = page.content()
            finally:
                browser.close()

        lowered = html.lower()
        if any(marker in lowered for marker in _CHALLENGE_MARKERS):
            raise BlockedError(
                f"{self.company.name}: page presented an access challenge; not bypassing"
            )
        return self._parse(html, url)

    def _parse(self, html: str, url: str) -> list[Job]:
        soup = BeautifulSoup(html, "html.parser")
        jobs: list[Job] = []
        # Prefer structured data when present.
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                payload = json.loads(script.string or "")
            except (ValueError, TypeError):
                continue
            for posting in _extract_postings(payload):
                from ..textutil import strip_html

                jobs.append(
                    self.new_job(
                        title=posting.get("title", "") or "",
                        description=strip_html(posting.get("description", "") or ""),
                        application_url=posting.get("url") or url,
                        source_url=url,
                        date_posted=(posting.get("datePosted") or "")[:10],
                    )
                )
        if jobs:
            return jobs

        cfg = self.company.adapter_config
        row_sel, title_sel = cfg.get("row_selector"), cfg.get("title_selector")
        if not row_sel or not title_sel:
            raise InvalidConfigError(
                f"{self.company.name}: rendered page has no JSON-LD; "
                "row_selector/title_selector required"
            )
        from urllib.parse import urljoin

        for row in soup.select(row_sel):
            title_el = row.select_one(title_sel)
            if title_el is None:
                continue
            loc_el = (
                row.select_one(cfg["location_selector"]) if cfg.get("location_selector") else None
            )
            jobs.append(
                self.new_job(
                    title=normalize_ws(title_el.get_text(" ")),
                    location=normalize_ws(loc_el.get_text(" ")) if loc_el else "",
                    application_url=urljoin(url, title_el.get("href", "") or ""),
                    source_url=url,
                )
            )
        return jobs
