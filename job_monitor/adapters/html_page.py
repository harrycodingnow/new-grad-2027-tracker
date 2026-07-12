"""Generic HTML career-page adapter driven by CSS selectors.

source_identifier: URL template, may contain {offset} or {page}.
adapter_config:
  row_selector:       CSS selector for one job row/card       (required)
  title_selector:     selector inside the row for the title link (required)
  location_selector:  selector inside the row for the location  (optional)
  date_selector:      selector inside the row for a posted date  (optional)
  url_prefix:         prepended to relative hrefs                (optional)
  page_size:          rows per page, used with {offset}          (default 25)
  max_pages:          pagination cap                             (default 3)
  fetch_details:      fetch each job page for the description    (default true)
  detail_selector:    selector on the job page for the text      (default body)
"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..errors import InvalidConfigError, StructureChangedError
from ..models import Job
from ..textutil import normalize_ws
from .base import Adapter

log = logging.getLogger(__name__)


class HtmlAdapter(Adapter):
    source_type = "html"

    def fetch(self) -> list[Job]:
        cfg = self.company.adapter_config
        url_template = self.company.source_identifier.strip()
        row_sel = cfg.get("row_selector")
        title_sel = cfg.get("title_selector")
        if not url_template or not row_sel or not title_sel:
            raise InvalidConfigError(
                f"{self.company.name}: html adapter needs source_identifier, "
                "row_selector and title_selector"
            )
        page_size = int(cfg.get("page_size", 25))
        max_pages = int(cfg.get("max_pages", 3))
        paginated = "{offset}" in url_template or "{page}" in url_template

        jobs: list[Job] = []
        seen_urls: set[str] = set()
        for page in range(max_pages if paginated else 1):
            url = url_template.format(offset=page * page_size, page=page + 1)
            resp = self.client.get(url)
            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.select(row_sel)
            if page == 0 and not rows:
                raise StructureChangedError(
                    f"{self.company.name}: selector {row_sel!r} matched nothing — "
                    "page structure may have changed"
                )
            new_on_page = 0
            for row in rows:
                title_el = row.select_one(title_sel)
                if title_el is None:
                    continue
                href = title_el.get("href", "")
                link = urljoin(cfg.get("url_prefix") or url, href) if href else url
                if link in seen_urls:
                    continue
                seen_urls.add(link)
                new_on_page += 1
                loc_el = (
                    row.select_one(cfg["location_selector"])
                    if cfg.get("location_selector")
                    else None
                )
                date_el = row.select_one(cfg["date_selector"]) if cfg.get("date_selector") else None
                jobs.append(
                    self.new_job(
                        title=normalize_ws(title_el.get_text(" ")),
                        location=normalize_ws(loc_el.get_text(" ")) if loc_el else "",
                        application_url=link,
                        source_url=url,
                        date_posted=normalize_ws(date_el.get_text(" "))[:10] if date_el else "",
                    )
                )
            if not paginated or new_on_page == 0 or len(rows) < page_size:
                break

        if cfg.get("fetch_details", True):
            self._fill_details(jobs, cfg.get("detail_selector") or "body")
        return jobs

    def _fill_details(self, jobs: list[Job], detail_selector: str) -> None:
        fetched = 0
        for job in jobs:
            if not self.title_prefilter(job.title) or fetched >= self.detail_fetch_cap:
                continue
            fetched += 1
            try:
                resp = self.client.get(job.application_url)
                soup = BeautifulSoup(resp.text, "html.parser")
                el = soup.select_one(detail_selector)
                if el is not None:
                    job.description = normalize_ws(el.get_text(" "))[:20000]
            except Exception as exc:
                log.warning(
                    "%s: detail fetch failed for %s: %s",
                    self.company.name,
                    job.application_url,
                    exc,
                )
