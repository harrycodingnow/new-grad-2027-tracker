"""Scoring and score-band tests."""

from __future__ import annotations

from datetime import UTC, datetime

from job_monitor.filters import TitleFilter, classify_graduation
from job_monitor.models import Job
from job_monitor.scoring import score_band, score_job
from job_monitor.sponsorship import classify_sponsorship

NOW = datetime(2026, 7, 12, tzinfo=UTC)


def build(job: Job, profile, filters) -> Job:
    tf = TitleFilter(filters)
    decision = tf.evaluate(job.title)
    job.graduation_match, _ = classify_graduation(job, filters)
    result = classify_sponsorship(f"{job.title} {job.description}", filters)
    job.sponsorship_classification = result.classification
    job.sponsorship_evidence = result.evidence
    job.international_student_risk_flags = result.risk_flags
    score_job(job, decision, profile, filters, now=NOW)
    return job


def test_strong_new_grad_job_scores_high(profile, filters):
    job = build(
        Job(
            title="Software Engineer, New Grad (2027)",
            description=(
                "Build backend APIs in Python and TypeScript on AWS. "
                "Visa sponsorship available; STEM OPT accepted."
            ),
            location="New York, NY",
            country="United States",
            date_posted="2026-07-10",
        ),
        profile,
        filters,
    )
    assert job.overall_score >= 80
    assert not job.disqualified
    assert "sponsorship" in job.score_explanation
    assert job.role_match_score > 60
    assert "python" in job.matched_keywords


def test_ineligible_job_is_hard_disqualified_but_scored(profile, filters):
    job = build(
        Job(
            title="Software Engineer I, Defense Systems",
            description="Active security clearance required. U.S. citizenship is required (ITAR).",
            location="Arlington, VA",
            country="United States",
            date_posted="2026-07-10",
        ),
        profile,
        filters,
    )
    assert job.disqualified
    assert "ineligible" in job.disqualify_reason
    assert job.overall_score > 0  # still scored and kept in the dataset


def test_no_sponsorship_language_scores_lower_than_positive(profile, filters):
    base = dict(location="Austin, TX", country="United States", date_posted="2026-07-10")
    positive = build(
        Job(title="Backend Engineer, New Grad", description="Visa sponsorship available.", **base),
        profile,
        filters,
    )
    unclear = build(
        Job(title="Backend Engineer, New Grad", description="Great snacks.", **base),
        profile,
        filters,
    )
    assert positive.overall_score > unclear.overall_score
    assert unclear.sponsorship_classification == "unclear"
    assert not unclear.disqualified


def test_stale_posting_loses_recency_points(profile, filters):
    fresh = build(
        Job(
            title="Data Engineer, New Grad",
            description="",
            date_posted="2026-07-11",
            location="Seattle, WA",
        ),
        profile,
        filters,
    )
    stale = build(
        Job(
            title="Data Engineer, New Grad",
            description="",
            date_posted="2026-03-01",
            location="Seattle, WA",
        ),
        profile,
        filters,
    )
    assert fresh.overall_score > stale.overall_score


def test_score_bands(filters):
    assert score_band(85, filters) == "excellent"
    assert score_band(70, filters) == "strong"
    assert score_band(55, filters) == "possible"
    assert score_band(30, filters) == "low"


def test_every_scored_job_has_explanation(profile, filters):
    job = build(
        Job(title="Machine Learning Engineer, Early Career", description="LLM evaluation and RAG."),
        profile,
        filters,
    )
    for part in ("role", "graduation", "sponsorship", "location", "recency"):
        assert part in job.score_explanation
