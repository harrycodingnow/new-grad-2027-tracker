"""Sponsorship / work-authorization classification tests."""

from __future__ import annotations

from job_monitor.sponsorship import classify_sponsorship

POSITIVE = (
    "We build developer tools in Python. Visa sponsorship available for this "
    "position, and STEM OPT accepted for recent graduates."
)
NEGATIVE = (
    "Candidates must be authorized to work in the United States. This role is "
    "not eligible for visa sponsorship now or in the future. We will not sponsor "
    "applicants for work visas."
)
AMBIGUOUS = (
    "Join our platform team building distributed systems with Kubernetes. "
    "Competitive salary and benefits."
)
INELIGIBLE = (
    "Entry level engineers welcome. Active security clearance required; "
    "U.S. citizenship is required due to ITAR restrictions."
)
MIXED = (
    "We normally offer visa sponsorship. However, for this specific role there is "
    "no visa sponsorship now or in the future."
)


def test_positive_classification(filters):
    result = classify_sponsorship(POSITIVE, filters)
    assert result.classification == "likely_supported"
    assert "sponsorship available" in result.evidence.lower()
    assert result.risk_flags == []


def test_negative_classification(filters):
    result = classify_sponsorship(NEGATIVE, filters)
    assert result.classification == "likely_not_supported"
    assert (
        "not eligible for visa sponsorship" in result.evidence.lower()
        or "will not sponsor" in result.evidence.lower()
    )
    assert result.risk_flags


def test_ambiguous_is_unclear_not_supported(filters):
    result = classify_sponsorship(AMBIGUOUS, filters)
    assert result.classification == "unclear"
    assert result.evidence == ""


def test_ineligible_clearance_and_citizenship(filters):
    result = classify_sponsorship(INELIGIBLE, filters)
    assert result.classification == "ineligible"
    assert "clearance" in result.evidence.lower() or "citizenship" in result.evidence.lower()


def test_restrictive_language_wins_over_positive(filters):
    result = classify_sponsorship(MIXED, filters)
    assert result.classification == "likely_not_supported"


def test_evidence_is_actual_posting_text(filters):
    result = classify_sponsorship(POSITIVE, filters)
    assert result.evidence in POSITIVE or result.evidence.rstrip("…") in POSITIVE
