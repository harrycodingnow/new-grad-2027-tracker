"""Markdown report generation tests."""

from __future__ import annotations

from datetime import UTC, datetime

from job_monitor.models import Job, SourceHealth
from job_monitor.report import build_active_report, build_new_report, digest_table, sort_recommended

NOW = datetime(2026, 7, 12, 6, 30, tzinfo=UTC)


def job(**kw) -> Job:
    base = dict(
        job_id="examplecorp-1",
        company="ExampleCorp",
        title="Software Engineer, New Grad",
        location="New York, NY",
        application_url="https://example.test/jobs/1",
        overall_score=82,
        sponsorship_classification="likely_supported",
        sponsorship_evidence="Visa sponsorship available.",
        score_explanation="role 30/35 · graduation 20/20",
        date_posted="2026-07-10",
    )
    base.update(kw)
    return Job(**base)


def test_active_report_contents(filters):
    jobs = [
        job(),
        job(
            job_id="x-2",
            title="Data Engineer | Entry Level",
            overall_score=70,
            sponsorship_classification="unclear",
            sponsorship_evidence="",
        ),
        job(job_id="x-3", overall_score=55),
        job(
            job_id="x-4",
            overall_score=90,
            disqualified=True,
            disqualify_reason="sponsorship 'ineligible'",
        ),
    ]
    health = [
        SourceHealth(company="ExampleCorp", source_type="greenhouse", status="ok", jobs_fetched=4),
        SourceHealth(
            company="BrokenCo",
            source_type="html",
            status="failed",
            error_category="structure_changed",
            error_message="selector matched nothing",
        ),
        SourceHealth(
            company="Meta",
            source_type="unresolved",
            status="skipped",
            error_category="unsupported",
            error_message="no public API",
        ),
    ]
    md = build_active_report(jobs, health, filters, priorities={"ExampleCorp": 1}, now=NOW)
    assert "2026-07-12 06:30 UTC" in md
    assert "14:30" in md and "Asia/Taipei" in md  # UTC+8
    assert "**Active jobs tracked:** 4" in md
    assert "**Companies checked successfully:** 1" in md
    assert "BrokenCo" in md and "structure_changed" in md
    assert "Excellent matches" in md and "Strong matches" in md and "Possible matches" in md
    assert "not legal advice" in md.lower()
    # Markdown table cell escaping: the pipe in the title must be escaped.
    assert "Data Engineer \\| Entry Level" in md
    # Disqualified job stays out of the recommended tables.
    assert md.count("| ExampleCorp |") == 3


def test_sorting_order(filters):
    jobs = [
        job(job_id="a", overall_score=70, date_posted="2026-07-01", company="Zeta"),
        job(job_id="b", overall_score=70, date_posted="2026-07-10", company="Alpha"),
        job(job_id="c", overall_score=90, date_posted="2026-06-01", company="Beta"),
        job(
            job_id="d",
            overall_score=70,
            date_posted="2026-07-10",
            company="Alpha2",
        ),
    ]
    ranked = sort_recommended(jobs, priorities={"Alpha": 2, "Alpha2": 1, "Beta": 3, "Zeta": 1})
    assert [j.job_id for j in ranked] == ["c", "d", "b", "a"]


def test_new_report_empty(filters):
    md = build_new_report([], filters, priorities={}, now=NOW)
    assert "No new matching jobs" in md


def test_digest_table_truncates_and_links():
    long_evidence = "sponsorship " * 40
    md = digest_table([job(sponsorship_evidence=long_evidence)])
    assert "[Apply](https://example.test/jobs/1)" in md
    assert md.startswith("| Apply | Company |")
    assert "…" in md  # evidence truncated


def test_jobs_table_puts_apply_first(filters):
    md = build_new_report([job()], filters, priorities={}, now=NOW)
    assert "| Apply | Company | Title |" in md
    assert "| [Apply](https://example.test/jobs/1) | ExampleCorp |" in md
