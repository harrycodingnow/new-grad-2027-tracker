"""Deduplication and run-over-run state merging.

Match order: source job ID → canonical application URL → deterministic
fingerprint. `first_seen` and announcement state survive across runs; cosmetic
description/location edits never resurrect a job as "new".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .models import Job
from .textutil import canonical_url


@dataclass
class MergeResult:
    active: list[Job] = field(default_factory=list)
    new: list[Job] = field(default_factory=list)
    archived: list[Job] = field(default_factory=list)  # full archive incl. this run's closures
    closed_this_run: list[Job] = field(default_factory=list)


class _Index:
    def __init__(self, jobs: list[Job]):
        self.by_id: dict[str, Job] = {}
        self.by_url: dict[tuple[str, str], Job] = {}
        self.by_fp: dict[str, Job] = {}
        for job in jobs:
            self.by_id.setdefault(job.job_id, job)
            url = canonical_url(job.application_url)
            if url:
                self.by_url.setdefault((job.company, url), job)
            self.by_fp.setdefault(job.fingerprint(), job)

    def find(self, job: Job) -> Job | None:
        found = self.by_id.get(job.job_id)
        if found is None:
            url = canonical_url(job.application_url)
            if url:
                found = self.by_url.get((job.company, url))
        if found is None:
            found = self.by_fp.get(job.fingerprint())
        return found


def merge_state(
    fetched: list[Job],
    previous_active: list[Job],
    previous_archived: list[Job],
    fetched_ok_companies: set[str],
    archive_after_missing_runs: int,
    now: datetime | None = None,
) -> MergeResult:
    """Merge freshly fetched jobs with the previous dataset.

    Companies that failed to fetch this run keep their previous jobs untouched
    (no missing-run increment), so flaky sources don't archive live jobs.
    """
    now_iso = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    prev_index = _Index(previous_active)
    archive_index = _Index(previous_archived)
    result = MergeResult(archived=list(previous_archived))

    matched_prev_ids: set[str] = set()
    seen_ids: set[str] = set()

    for job in fetched:
        job.ensure_job_id()
        prev = prev_index.find(job)
        if prev is not None:
            job.job_id = prev.job_id  # keep stable identity
        else:
            revived = archive_index.find(job)
            if revived is not None:
                job.job_id = revived.job_id
        if job.job_id in seen_ids:
            continue  # intra-run duplicate
        seen_ids.add(job.job_id)

        if prev is not None:
            # Same job as last run: keep history, refresh current fields.
            job.first_seen = prev.first_seen or now_iso
            job.announced = prev.announced
            matched_prev_ids.add(prev.job_id)
        else:
            revived = archive_index.find(job)
            if revived is not None:
                # Reopened posting: restore history, do not report as new.
                job.first_seen = revived.first_seen or now_iso
                job.announced = revived.announced
                result.archived = [a for a in result.archived if a.job_id != revived.job_id]
            else:
                job.first_seen = now_iso
                result.new.append(job)
        job.last_seen = now_iso
        job.status = "active"
        job.consecutive_missing = 0
        result.active.append(job)

    for prev in previous_active:
        if prev.job_id in matched_prev_ids or prev.job_id in seen_ids:
            continue
        if prev.company not in fetched_ok_companies:
            result.active.append(prev)  # source failed/skipped: carry over untouched
            continue
        prev.consecutive_missing += 1
        if prev.consecutive_missing >= archive_after_missing_runs:
            prev.status = "closed"
            result.closed_this_run.append(prev)
            result.archived.append(prev)
        else:
            result.active.append(prev)

    result.active.sort(key=lambda j: (j.company.lower(), j.job_id))
    result.archived.sort(key=lambda j: (j.company.lower(), j.job_id))
    return result
