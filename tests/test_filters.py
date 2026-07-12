"""Title gate, location gate, and graduation classification tests."""

from __future__ import annotations

import pytest

from job_monitor.filters import TitleFilter, classify_graduation, location_matches
from job_monitor.models import Job


@pytest.fixture
def tf(filters):
    return TitleFilter(filters)


@pytest.mark.parametrize(
    "title",
    [
        "Software Engineer, New Grad (2027)",
        "University Graduate - Backend Engineer",
        "Machine Learning Engineer, Early Career",
        "Associate Software Engineer",
        "Software Engineer I",
        "Data Engineer, Entry Level",
        "Full-Stack Engineer (2026 Grads)",
    ],
)
def test_new_grad_titles_pass(tf, title):
    assert tf.evaluate(title).passed


@pytest.mark.parametrize(
    "title",
    [
        "Senior Software Engineer",
        "Staff Infrastructure Engineer",
        "Principal Architect",
        "Engineering Manager, Payments",
        "Software Engineer II",
        "Software Engineering Intern (Summer 2027)",
        "Director of Engineering",
        "Sr. Data Scientist",
        "Vice President, Technology",
    ],
)
def test_excluded_titles_fail(tf, title):
    decision = tf.evaluate(title)
    assert not decision.passed
    assert decision.excluded


def test_unrelated_title_fails(tf):
    assert not tf.evaluate("Account Executive, Mid-Market Sales").passed


def test_2026_title_not_auto_rejected(tf, filters):
    """A '2026' title passes the gate and is classified, not discarded."""
    title = "Software Engineer, New Grad (Class of 2026)"
    assert tf.evaluate(title).passed
    job = Job(title=title, description="")
    match, note = classify_graduation(job, filters)
    assert match == "compatible_2026"
    assert "Dec 2026" in note


def test_graduation_classification_2027(filters):
    job = Job(title="Software Engineer, New Grad", description="Expected graduation in 2027.")
    match, _ = classify_graduation(job, filters)
    assert match == "compatible_2027"


def test_graduation_incompatible_year(filters):
    job = Job(title="2025 New Grad Software Engineer", description="")
    match, note = classify_graduation(job, filters)
    assert match == "incompatible_2025"
    assert "Dec 2026" in note


def test_graduation_unspecified(filters):
    job = Job(title="Software Engineer, Early Career", description="Great team.")
    match, _ = classify_graduation(job, filters)
    assert match == "unspecified"


def test_location_matching():
    allowed = ["United States", "New York", "Remote - US"]
    assert location_matches(Job(location="New York, NY"), allowed)
    assert location_matches(Job(location="Anywhere", country="United States"), allowed)
    assert location_matches(Job(location="Remote"), allowed)  # possible US remote
    assert not location_matches(Job(location="London, United Kingdom"), allowed)
    assert not location_matches(Job(location="Bengaluru, India"), allowed)
