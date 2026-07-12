"""Deduplication, state preservation, and archiving tests."""

from __future__ import annotations

from datetime import UTC, datetime

from job_monitor.dedupe import merge_state
from job_monitor.models import Job

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


def make(
    job_id="",
    source_job_id="1",
    title="Software Engineer, New Grad",
    company="ExampleCorp",
    url="https://example.test/jobs/1",
    **kw,
) -> Job:
    job = Job(
        job_id=job_id,
        source_job_id=source_job_id,
        company=company,
        title=title,
        location=kw.pop("location", "New York, NY"),
        application_url=url,
        **kw,
    )
    return job


def merged(fetched, prev_active=(), prev_archived=(), ok=("ExampleCorp",), threshold=3):
    return merge_state(
        fetched=list(fetched),
        previous_active=list(prev_active),
        previous_archived=list(prev_archived),
        fetched_ok_companies=set(ok),
        archive_after_missing_runs=threshold,
        now=NOW,
    )


def test_new_job_detected():
    result = merged([make()])
    assert len(result.new) == 1
    assert result.new[0].first_seen == "2026-07-12T12:00:00Z"
    assert result.new[0].job_id  # deterministic id assigned


def test_first_seen_preserved_across_runs():
    first = merged([make()])
    prev = first.active[0]
    assert prev.first_seen == "2026-07-12T12:00:00Z"
    prev.announced = True
    again = merged([make()], prev_active=[prev])
    assert again.new == []
    job = again.active[0]
    assert job.first_seen == prev.first_seen  # history preserved
    assert job.announced is True  # announcement state preserved
    assert job.last_seen == "2026-07-12T12:00:00Z"


def test_description_update_is_not_a_new_job():
    prev = merged([make(description="old text", location="New York, NY")]).active[0]
    updated = make(description="totally rewritten description", location="New York,  NY ")
    result = merged([updated], prev_active=[prev])
    assert result.new == []
    assert result.active[0].description == "totally rewritten description"
    assert result.active[0].job_id == prev.job_id


def test_duplicate_within_one_run_collapses():
    a = make(source_job_id="1")
    b = make(source_job_id="1")
    result = merged([a, b])
    assert len(result.active) == 1
    assert len(result.new) == 1


def test_match_by_canonical_url_when_source_id_changes():
    prev = merged(
        [make(source_job_id="old-1", url="https://example.test/jobs/1?utm_source=x")]
    ).active[0]
    refetched = make(source_job_id="new-9", url="https://example.test/jobs/1")
    result = merged([refetched], prev_active=[prev])
    assert result.new == []
    assert result.active[0].job_id == prev.job_id


def test_missing_job_archived_after_threshold():
    prev = merged([make()]).active[0]
    # Run 1 & 2 missing: kept active with counter.
    r1 = merged([], prev_active=[prev])
    assert r1.active[0].consecutive_missing == 1
    r2 = merged([], prev_active=r1.active)
    assert r2.active[0].consecutive_missing == 2
    # Run 3: archived as closed.
    r3 = merged([], prev_active=r2.active)
    assert r3.active == []
    assert len(r3.archived) == 1
    assert r3.archived[0].status == "closed"
    assert r3.closed_this_run


def test_failed_source_does_not_increment_missing():
    prev = merged([make()]).active[0]
    result = merged([], prev_active=[prev], ok=())  # company fetch failed this run
    assert result.active[0].consecutive_missing == 0
    assert result.archived == []


def test_reopened_job_not_reported_as_new():
    prev = merged([make()]).active[0]
    prev.status = "closed"
    result = merged([make()], prev_archived=[prev])
    assert result.new == []  # revived from archive
    assert result.active[0].job_id == prev.job_id
    assert result.archived == []
