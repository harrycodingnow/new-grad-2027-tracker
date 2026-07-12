"""Configurable JSON endpoint adapter.

Two modes:

1. Presets — `source_identifier` selects a built-in fetcher for well-known
   public career APIs:
       amazon                             amazon.jobs search.json
       google                             careers.google.com API
       uber                               uber.com careers API
       janestreet                         janestreet.com jobs feed
       oracle                             Oracle HCM recruiting API
       salesforce                         careers.salesforce.com API
       smartrecruiters:{company}          SmartRecruiters public postings API

Eightfold-hosted sites use the dedicated `eightfold` adapter (PCSX API); the
legacy /api/apply/v2/jobs preset was removed when tenants migrated to PCSX.

2. Generic — `adapter_config` describes the request, pagination, and dot-path
   field mappings (see README "Adding a company"). Placeholders {offset},
   {page}, {limit} and {query} are substituted in URLs and body values.
"""

from __future__ import annotations

import logging
from typing import Any

from ..errors import InvalidConfigError, StructureChangedError
from ..models import Job
from ..textutil import strip_html
from .base import Adapter

log = logging.getLogger(__name__)

DEFAULT_QUERIES = ["new grad software engineer", "university graduate engineer"]


def dig(data: Any, path: str, default: Any = None) -> Any:
    """Resolve a dot path ("result.jobs.0.title"). Lists map over remaining path."""
    if not path:
        return data
    current = data
    parts = path.split(".")
    for i, part in enumerate(parts):
        if isinstance(current, list):
            if part.isdigit():
                idx = int(part)
                current = current[idx] if idx < len(current) else None
            else:
                rest = ".".join(parts[i:])
                return [dig(item, rest, default) for item in current]
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return default
        if current is None:
            return default
    return current


def as_text(value: Any, sep: str = "; ") -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return sep.join(as_text(v, sep) for v in value if v is not None)
    return str(value)


class JsonAdapter(Adapter):
    source_type = "json"

    def fetch(self) -> list[Job]:
        ident = self.company.source_identifier.strip()
        kind = ident.split(":", 1)[0] if ident else ""
        preset = getattr(self, f"_fetch_{kind}", None)
        if ident and preset is not None:
            return preset()
        if self.company.adapter_config.get("request"):
            return self._fetch_generic()
        raise InvalidConfigError(
            f"{self.company.name}: json adapter needs a known preset identifier "
            f"or adapter_config.request (got {ident!r})"
        )

    # ------------------------------------------------------------- presets
    def _queries(self) -> list[str]:
        return list(self.company.adapter_config.get("queries") or DEFAULT_QUERIES)

    def _fetch_amazon(self) -> list[Job]:
        found: dict[str, dict] = {}
        for query in self._queries():
            offset = 0
            for _ in range(int(self.company.adapter_config.get("max_pages", 2))):
                params = {
                    "base_query": query,
                    "country": "USA",
                    "result_limit": 100,
                    "offset": offset,
                    "sort": "recent",
                }
                data = self.client.get_json("https://www.amazon.jobs/en/search.json", params=params)
                jobs = data.get("jobs")
                if jobs is None:
                    raise StructureChangedError(
                        f"{self.company.name}: unexpected search.json response"
                    )
                for item in jobs:
                    key = str(item.get("id_icims") or item.get("id") or item.get("job_path", ""))
                    if key:
                        found.setdefault(key, item)
                if len(jobs) < 100:
                    break
                offset += 100

        out: list[Job] = []
        for key, item in found.items():
            description = " ".join(
                strip_html(item.get(k) or "")
                for k in ("description", "basic_qualifications", "preferred_qualifications")
            ).strip()
            path = item.get("job_path", "") or ""
            url = f"https://www.amazon.jobs{path}" if path.startswith("/") else path
            out.append(
                self.new_job(
                    source_job_id=key,
                    title=item.get("title", "") or "",
                    location=as_text(item.get("normalized_location") or item.get("location")),
                    country="United States",
                    department=item.get("job_category", "") or "",
                    employment_type=item.get("job_schedule_type", "") or "",
                    description=description,
                    requirements=strip_html(item.get("basic_qualifications") or ""),
                    application_url=url,
                    source_url=url,
                    date_posted=_us_date(item.get("posted_date", "")),
                )
            )
        return out

    def _fetch_google(self) -> list[Job]:
        found: dict[str, dict] = {}
        for query in self._queries():
            for page in range(1, int(self.company.adapter_config.get("max_pages", 3)) + 1):
                params = {"q": query, "location": "United States", "page": page}
                data = self.client.get_json(
                    "https://careers.google.com/api/v3/search/", params=params
                )
                jobs = data.get("jobs")
                if jobs is None:
                    raise StructureChangedError(
                        f"{self.company.name}: unexpected careers API response"
                    )
                for item in jobs:
                    key = str(item.get("id", ""))
                    if key:
                        found.setdefault(key, item)
                if not jobs:
                    break

        out: list[Job] = []
        for key, item in found.items():
            job_id = key.rsplit("/", 1)[-1]
            description = " ".join(
                strip_html(item.get(k) or "")
                for k in ("description", "summary", "qualifications", "responsibilities")
            ).strip()
            out.append(
                self.new_job(
                    source_job_id=job_id,
                    title=item.get("title", "") or "",
                    location=as_text([loc.get("display") for loc in item.get("locations") or []]),
                    country="United States",
                    description=description,
                    requirements=strip_html(item.get("qualifications") or ""),
                    application_url=item.get("apply_url")
                    or f"https://careers.google.com/jobs/results/{job_id}/",
                    source_url=f"https://careers.google.com/jobs/results/{job_id}/",
                    date_posted=(item.get("publish_date") or item.get("created") or "")[:10],
                )
            )
        return out

    def _fetch_uber(self) -> list[Job]:
        url = "https://www.uber.com/api/loadSearchJobsResults?localeCode=en"
        headers = {"x-csrf-token": "x", "content-type": "application/json"}
        found: dict[str, dict] = {}
        for query in self._queries():
            for page in range(int(self.company.adapter_config.get("max_pages", 2))):
                body = {
                    "params": {
                        "location": [{"country": "USA", "region": "", "city": ""}],
                        "query": query,
                    },
                    "limit": 50,
                    "page": page,
                }
                data = self.client.post_json(url, headers=headers, json_body=body)
                results = dig(data, "data.results")
                if results is None:
                    raise StructureChangedError(
                        f"{self.company.name}: unexpected careers API response"
                    )
                for item in results:
                    key = str(item.get("id", ""))
                    if key:
                        found.setdefault(key, item)
                if len(results) < 50:
                    break

        out: list[Job] = []
        for key, item in found.items():
            all_locations = item.get("allLocations") or []
            if not all_locations and item.get("location"):
                all_locations = [item["location"]]
            locations = [
                ", ".join(str(part) for part in (loc.get("city"), loc.get("region")) if part)
                for loc in all_locations
                if (loc.get("countryName") or loc.get("country")) in ("United States", "USA")
            ]
            out.append(
                self.new_job(
                    source_job_id=key,
                    title=item.get("title", "") or "",
                    location=as_text(locations),
                    country="United States",
                    department=item.get("department", "") or "",
                    description=strip_html(item.get("description", "") or ""),
                    application_url=f"https://www.uber.com/global/en/careers/list/{key}/",
                    source_url=f"https://www.uber.com/global/en/careers/list/{key}/",
                    date_posted=(item.get("creationDate") or "")[:10],
                )
            )
        return out

    def _fetch_janestreet(self) -> list[Job]:
        data = self.client.get_json("https://www.janestreet.com/jobs/main.json")
        if not isinstance(data, list):
            raise StructureChangedError(f"{self.company.name}: unexpected jobs feed shape")
        out: list[Job] = []
        for item in data:
            city = item.get("city", "") or ""
            if not any(tok in city for tok in ("New York", "NYC", "Austin", "Chicago", "US")):
                continue
            job_id = str(item.get("id", ""))
            url = f"https://www.janestreet.com/join-jane-street/position/{job_id}/"
            out.append(
                self.new_job(
                    source_job_id=job_id,
                    title=item.get("position", "") or item.get("title", "") or "",
                    location=city,
                    country="United States",
                    department=item.get("team", "") or "",
                    employment_type=item.get("duration") or item.get("type") or "",
                    description=strip_html(
                        as_text(item.get("overview") or item.get("description"), " ")
                    ),
                    application_url=url,
                    source_url=url,
                )
            )
        return out

    def _fetch_smartrecruiters(self) -> list[Job]:
        _, _, company = self.company.source_identifier.partition(":")
        if not company:
            raise InvalidConfigError(f"{self.company.name}: use smartrecruiters:{{company}}")
        base = f"https://api.smartrecruiters.com/v1/companies/{company}/postings"
        found: dict[str, dict] = {}
        offset = 0
        for _ in range(int(self.company.adapter_config.get("max_pages", 5))):
            data = self.client.get_json(base, params={"limit": 100, "offset": offset})
            content = data.get("content")
            if content is None:
                raise StructureChangedError(f"{self.company.name}: unexpected postings response")
            for item in content:
                loc_country = (dig(item, "location.country") or "").lower()
                if loc_country and loc_country not in ("us", "usa", "united states"):
                    continue
                key = str(item.get("id", ""))
                if key:
                    found.setdefault(key, item)
            offset += 100
            if offset >= int(data.get("totalFound", 0)) or not content:
                break

        out: list[Job] = []
        details_fetched = 0
        for key, item in found.items():
            city = dig(item, "location.city") or ""
            region = dig(item, "location.region") or ""
            url = f"https://jobs.smartrecruiters.com/{company}/{key}"
            job = self.new_job(
                source_job_id=key,
                title=item.get("name", "") or "",
                location=", ".join(p for p in (city, region) if p),
                country="United States",
                department=dig(item, "function.label") or "",
                employment_type=dig(item, "typeOfEmployment.label") or "",
                application_url=url,
                source_url=url,
                date_posted=(item.get("releasedDate") or "")[:10],
            )
            ref = item.get("ref")
            if ref and self.title_prefilter(job.title) and details_fetched < self.detail_fetch_cap:
                details_fetched += 1
                try:
                    detail = self.client.get_json(ref)
                    sections = dig(detail, "jobAd.sections") or {}
                    job.description = " ".join(
                        strip_html(dig(sections, f"{sec}.text") or "")
                        for sec in (
                            "companyDescription",
                            "jobDescription",
                            "qualifications",
                            "additionalInformation",
                        )
                    ).strip()
                    job.requirements = strip_html(dig(sections, "qualifications.text") or "")
                except Exception as exc:
                    log.warning("%s: detail fetch failed for %s: %s", self.company.name, key, exc)
            out.append(job)
        return out

    def _fetch_oracle(self) -> list[Job]:
        base = (
            "https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/"
            "recruitingCEJobRequisitions"
        )
        site = self.company.adapter_config.get("site_number", "CX_45001")
        found: dict[str, dict] = {}
        for query in self._queries():
            finder = (
                f"findReqs;siteNumber={site},keyword={query},limit=50,offset=0,"
                "sortBy=POSTING_DATES_DESC"
            )
            params = {
                "onlyData": "true",
                # requisitionList is only returned when explicitly expanded.
                "expand": "requisitionList.secondaryLocations",
                "finder": finder,
            }
            data = self.client.get_json(base, params=params)
            items = dig(data, "items.0.requisitionList")
            if items is None:
                raise StructureChangedError(f"{self.company.name}: unexpected HCM response")
            for item in items:
                key = str(item.get("Id", ""))
                if key:
                    found.setdefault(key, item)

        out: list[Job] = []
        for key, item in found.items():
            url = f"https://careers.oracle.com/jobs/#en/sites/jobsearch/job/{key}"
            out.append(
                self.new_job(
                    source_job_id=key,
                    title=item.get("Title", "") or "",
                    location=item.get("PrimaryLocation", "") or "",
                    description=strip_html(item.get("ShortDescriptionStr", "") or ""),
                    application_url=url,
                    source_url=url,
                    date_posted=(item.get("PostedDate") or "")[:10],
                )
            )
        return out

    def _fetch_salesforce(self) -> list[Job]:
        base = "https://careers.salesforce.com/api/jobs"
        found: dict[str, dict] = {}
        for query in self._queries():
            for page in range(1, int(self.company.adapter_config.get("max_pages", 3)) + 1):
                params = {
                    "page": page,
                    "pageSize": 50,
                    "search": query,
                    "country": "United States of America",
                }
                data = self.client.get_json(base, params=params)
                jobs = data.get("jobs") if isinstance(data, dict) else None
                if jobs is None:
                    raise StructureChangedError(
                        f"{self.company.name}: unexpected careers API response"
                    )
                for item in jobs:
                    key = str(item.get("id") or dig(item, "jobId") or "")
                    if key:
                        found.setdefault(key, item)
                if len(jobs) < 50:
                    break

        out: list[Job] = []
        for key, item in found.items():
            url = item.get("url") or item.get("applyUrl") or self.company.careers_url
            out.append(
                self.new_job(
                    source_job_id=key,
                    title=item.get("title") or item.get("name") or "",
                    location=as_text(item.get("locations") or item.get("location")),
                    department=item.get("department", "") or "",
                    description=strip_html(as_text(item.get("description"), " ")),
                    application_url=url,
                    source_url=url,
                    date_posted=(item.get("postedDate") or item.get("datePosted") or "")[:10],
                )
            )
        return out

    # ------------------------------------------------------------- generic
    def _fetch_generic(self) -> list[Job]:
        cfg = self.company.adapter_config
        request = cfg["request"]
        fields = cfg.get("fields") or {}
        jobs_path = cfg.get("jobs_path", "")
        if not request.get("url") or not fields.get("title"):
            raise InvalidConfigError(
                f"{self.company.name}: generic json config needs request.url and fields.title"
            )
        pagination = cfg.get("pagination") or {}
        mode = pagination.get("mode", "none")
        limit = int(pagination.get("limit", 50))
        max_pages = int(pagination.get("max_pages", 3)) if mode != "none" else 1
        start_page = int(pagination.get("start_page", 1))

        out: list[Job] = []
        seen: set[str] = set()
        for page_num in range(max_pages):
            subs = {
                "offset": page_num * limit,
                "page": start_page + page_num,
                "limit": limit,
            }
            url = request["url"].format(**subs)
            body = _substitute(request.get("body"), subs)
            method = (request.get("method") or "GET").upper()
            if method == "POST":
                data = self.client.post_json(url, headers=request.get("headers"), json_body=body)
            else:
                data = self.client.get_json(url, headers=request.get("headers"))
            items = dig(data, jobs_path) if jobs_path else data
            if items is None or not isinstance(items, list):
                raise StructureChangedError(
                    f"{self.company.name}: jobs_path {jobs_path!r} did not yield a list"
                )
            for item in items:
                job = self.new_job(
                    source_job_id=as_text(dig(item, fields.get("source_job_id", ""))),
                    title=as_text(dig(item, fields["title"])),
                    location=as_text(dig(item, fields.get("location", ""))),
                    country=as_text(dig(item, fields.get("country", ""))),
                    department=as_text(dig(item, fields.get("department", ""))),
                    employment_type=as_text(dig(item, fields.get("employment_type", ""))),
                    description=strip_html(as_text(dig(item, fields.get("description", "")), " ")),
                    date_posted=as_text(dig(item, fields.get("date_posted", "")))[:10],
                )
                url_field = fields.get("url", "")
                if url_field.startswith("http"):
                    job.application_url = url_field.format(source_job_id=job.source_job_id)
                else:
                    job.application_url = as_text(dig(item, url_field)) if url_field else ""
                job.source_url = job.application_url or url
                key = job.source_job_id or job.fingerprint()
                if key not in seen:
                    seen.add(key)
                    out.append(job)
            if len(items) < limit:
                break
        return out


def _substitute(body: Any, subs: dict[str, Any]) -> Any:
    if isinstance(body, dict):
        return {k: _substitute(v, subs) for k, v in body.items()}
    if isinstance(body, list):
        return [_substitute(v, subs) for v in body]
    if isinstance(body, str) and "{" in body:
        formatted = body.format(**subs)
        return int(formatted) if formatted.isdigit() and body.strip("{}") in subs else formatted
    return body


def _us_date(value: str) -> str:
    """Convert 'July 10, 2026' to ISO."""
    from datetime import datetime

    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except (ValueError, AttributeError):
            continue
    return ""
