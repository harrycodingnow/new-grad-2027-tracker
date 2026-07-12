"""Run orchestration: fetch → gate → classify → score → merge → write → notify."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from . import notify, report, store
from .adapters import build_adapter
from .config import CompanyConfig, Config, load_config
from .dedupe import merge_state
from .errors import SourceError
from .filters import TitleFilter, classify_graduation, location_matches
from .http import HttpClient
from .llm import get_default_classifier
from .models import Job, SourceHealth
from .scoring import score_job
from .sponsorship import classify_sponsorship

log = logging.getLogger(__name__)


class Runner:
    def __init__(
        self,
        config: Config | None = None,
        data_dir: Path | None = None,
        client: HttpClient | None = None,
    ):
        self.config = config or load_config()
        self.data_dir = data_dir or store.DATA_DIR
        self.client = client or HttpClient()
        self.title_filter = TitleFilter(self.config.filters)
        self.llm = get_default_classifier()
        self.priorities = {c.name: c.priority for c in self.config.companies}

    # ------------------------------------------------------------------ fetch
    def fetch_company(self, company: CompanyConfig) -> list[Job]:
        adapter = build_adapter(company, self.client, title_prefilter=self.title_filter.prefilter)
        return adapter.fetch()

    def _fetch_all(
        self, companies: list[CompanyConfig], previous_health: dict[str, SourceHealth]
    ) -> tuple[dict[str, list[Job]], list[SourceHealth]]:
        fetched: dict[str, list[Job]] = {}
        health_rows: list[SourceHealth] = []
        now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        for company in companies:
            prev = previous_health.get(company.name)
            health = SourceHealth(
                company=company.name,
                source_type=company.source_type,
                last_attempt=now_iso,
                last_success=prev.last_success if prev else "",
                consecutive_failures=prev.consecutive_failures if prev else 0,
            )
            if not company.enabled or company.source_type == "unresolved":
                health.status = "skipped"
                health.error_category = "unsupported"
                health.error_message = company.notes or "disabled in companies.yaml"
                health_rows.append(health)
                continue
            try:
                jobs = self.fetch_company(company)
            except SourceError as exc:
                health.status = "failed"
                health.error_category = exc.category
                health.error_message = exc.message
                health.consecutive_failures += 1
                log.error("%s: %s (%s)", company.name, exc.message, exc.category)
            except Exception as exc:  # unexpected bug: record, keep going
                health.status = "failed"
                health.error_category = "parse_error"
                health.error_message = f"unexpected error: {exc!r}"
                health.consecutive_failures += 1
                log.exception("%s: unexpected error", company.name)
            else:
                fetched[company.name] = jobs
                health.status = "ok" if jobs else "ok_empty"
                health.error_category = "ok" if jobs else "ok_empty"
                health.jobs_fetched = len(jobs)
                health.last_success = now_iso
                health.consecutive_failures = 0
                log.info("%s: fetched %d posting(s)", company.name, len(jobs))
            health_rows.append(health)
        return fetched, health_rows

    # ---------------------------------------------------------------- process
    def process_jobs(self, company: CompanyConfig, raw_jobs: list[Job]) -> list[Job]:
        """Location gate → title gate → classify → score. Returns kept jobs."""
        kept: list[Job] = []
        for job in raw_jobs:
            job.title = job.title.strip()
            if not job.title:
                continue
            job.application_url = job.application_url.strip()
            if not location_matches(job, company.locations):
                continue
            if not job.country:
                job.country = "United States"
            decision = self.title_filter.evaluate(job.title)
            job.excluded_keywords = decision.excluded
            if not decision.passed:
                continue  # unrelated or explicitly excluded titles stay out of the dataset
            full_text = " ".join((job.title, job.description, job.requirements))
            job.graduation_match, grad_note = classify_graduation(job, self.config.filters)
            sponsorship = classify_sponsorship(full_text, self.config.filters)
            job.sponsorship_classification = sponsorship.classification
            job.sponsorship_evidence = sponsorship.evidence
            job.international_student_risk_flags = sponsorship.risk_flags
            score_job(job, decision, self.config.profile, self.config.filters)
            job.score_explanation = f"{job.score_explanation} · graduation note: {grad_note}"
            if self.llm is not None:
                job = self.llm.refine(job)
            job.ensure_job_id()
            kept.append(job)
        return kept

    # -------------------------------------------------------------------- run
    def run(self, only_companies: list[str] | None = None, dry_run: bool = False) -> dict:
        companies = self.config.companies
        if only_companies:
            wanted = {c.lower() for c in only_companies}
            companies = [c for c in companies if c.name.lower() in wanted]
            missing = wanted - {c.name.lower() for c in companies}
            if missing:
                raise SystemExit(f"unknown companies: {', '.join(sorted(missing))}")

        previous_active = store.load_jobs(self.data_dir / "active_jobs.json")
        previous_archived = store.load_jobs(self.data_dir / "archived_jobs.json")
        previous_health = store.load_health(self.data_dir / "source_health.json")

        fetched_raw, health_rows = self._fetch_all(companies, previous_health)

        processed: list[Job] = []
        by_name = {c.name: c for c in self.config.companies}
        for name, raw in fetched_raw.items():
            processed.extend(self.process_jobs(by_name[name], raw))

        # Preserve health rows for companies outside this run's scope.
        in_scope = {c.name for c in companies}
        for name, prev in previous_health.items():
            if name not in in_scope:
                health_rows.append(prev)

        result = merge_state(
            fetched=processed,
            previous_active=previous_active,
            previous_archived=previous_archived,
            fetched_ok_companies=set(fetched_raw),
            archive_after_missing_runs=self.config.archive_after_missing_runs,
        )

        new_visible = [j for j in result.new if not j.disqualified]
        digest_jobs = [
            j
            for j in sort_new(new_visible, self.priorities)
            if j.overall_score >= self.config.digest_min_score and not j.announced
        ]

        summary = {
            "companies_checked": len([h for h in health_rows if h.status in ("ok", "ok_empty")]),
            "companies_failed": len([h for h in health_rows if h.status == "failed"]),
            "companies_skipped": len([h for h in health_rows if h.status == "skipped"]),
            "active_jobs": len(result.active),
            "new_jobs": len(result.new),
            "closed_jobs": len(result.closed_this_run),
            "digest_jobs": len(digest_jobs),
            "dry_run": dry_run,
        }

        if dry_run:
            log.info("dry run: not writing data files or sending notifications")
            for job in sort_new(new_visible, self.priorities):
                log.info(
                    "would report new: %s — %s (score %d, %s)",
                    job.company,
                    job.title,
                    job.overall_score,
                    job.sponsorship_classification,
                )
            return summary

        issue_created = False
        if digest_jobs:
            issue_created = notify.create_digest_issue(digest_jobs, client=self.client)
            notify.send_telegram(digest_jobs, client=self.client)
            if issue_created:
                announced_ids = {j.job_id for j in digest_jobs}
                for job in result.active:
                    if job.job_id in announced_ids:
                        job.announced = True
        summary["issue_created"] = issue_created

        self._write_outputs(result, health_rows)
        return summary

    def _write_outputs(self, result, health_rows) -> None:
        d = self.data_dir
        store.save_jobs(d / "active_jobs.json", result.active)
        store.save_jobs_csv(d / "active_jobs.csv", result.active)
        store.save_jobs(d / "new_jobs.json", sort_new(result.new, self.priorities))
        store.save_jobs(d / "archived_jobs.json", result.archived)
        store.save_health(d / "source_health.json", health_rows)

        root = d.parent
        active_md = report.build_active_report(
            result.active, health_rows, self.config.filters, self.priorities
        )
        (root / "ACTIVE_JOBS.md").write_text(active_md, encoding="utf-8")
        new_md = report.build_new_report(result.new, self.config.filters, self.priorities)
        (root / "NEW_JOBS.md").write_text(new_md, encoding="utf-8")
        store.mirror_to_docs(d, root / "docs" / "data")

    # ------------------------------------------------------------ validation
    def validate_sources(self, only_companies: list[str] | None = None) -> list[dict]:
        """Try every configured source and report what happened. Read-only."""
        rows: list[dict] = []
        companies = self.config.companies
        if only_companies:
            wanted = {c.lower() for c in only_companies}
            companies = [c for c in companies if c.name.lower() in wanted]
        for company in companies:
            row = {"company": company.name, "source_type": company.source_type}
            if company.source_type == "unresolved":
                row.update(status="unresolved", detail=company.notes)
            elif not company.enabled:
                row.update(status="disabled", detail=company.notes)
            else:
                try:
                    jobs = self.fetch_company(company)
                except SourceError as exc:
                    row.update(status=f"FAILED ({exc.category})", detail=exc.message[:160])
                except Exception as exc:
                    row.update(status="FAILED (unexpected)", detail=repr(exc)[:160])
                else:
                    sample = jobs[0].title if jobs else ""
                    row.update(status=f"ok ({len(jobs)} jobs)", detail=sample[:80])
            rows.append(row)
            log.info("validate %-22s %-12s %s", row["company"], row["source_type"], row["status"])
        return rows


def sort_new(jobs: list[Job], priorities: dict[str, int]) -> list[Job]:
    return report.sort_recommended(jobs, priorities)
