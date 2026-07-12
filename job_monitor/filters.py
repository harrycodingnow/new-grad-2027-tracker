"""Title/location gates and graduation-year classification.

All terms come from config/filters.yaml; nothing is hardcoded here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .models import Job
from .textutil import word_boundary_pattern

_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_GRAD_CONTEXT_RE = re.compile(
    r"(graduat\w+|class of|degree|expected|completion)\D{0,40}\b(20\d{2})\b|"
    r"\b(20\d{2})\b\D{0,40}(graduat\w+|grads?\b)",
    re.IGNORECASE,
)


@dataclass
class TitleDecision:
    passed: bool
    matched: list[str]
    excluded: list[str]


class TitleFilter:
    """Applies the configurable include/exclude title rules."""

    def __init__(self, filters: dict[str, Any]):
        tf = filters.get("title_filters", {})
        self.include_level = [(t, word_boundary_pattern(t)) for t in tf.get("include_level", [])]
        self.include_role = [(t, word_boundary_pattern(t)) for t in tf.get("include_role", [])]
        self.exclude = [(t, word_boundary_pattern(t)) for t in tf.get("exclude", [])]

    def evaluate(self, title: str) -> TitleDecision:
        excluded = [term for term, pat in self.exclude if pat.search(title)]
        level_hits = [term for term, pat in self.include_level if pat.search(title)]
        role_hits = [term for term, pat in self.include_role if pat.search(title)]
        passed = bool(level_hits or role_hits) and not excluded
        return TitleDecision(passed=passed, matched=level_hits + role_hits, excluded=excluded)

    def prefilter(self, title: str) -> bool:
        """Cheap gate used by adapters to decide whether to fetch details."""
        return self.evaluate(title).passed


def location_matches(job: Job, allowed: list[str]) -> bool:
    """True when the job location plausibly matches the configured (US) locations."""
    if job.country and "united states" in job.country.lower():
        return True
    if not allowed:
        return True
    text = f"{job.location} {job.country}".lower()
    if not text.strip():
        return False
    if any(word_boundary_pattern(term).search(text) for term in allowed):
        return True
    # "Remote" with no explicit non-US country: treat as possible US remote.
    return "remote" in text and not job.country


def classify_graduation(job: Job, filters: dict[str, Any]) -> tuple[str, str]:
    """Classify graduation-date compatibility.

    Returns (graduation_match, explanation). A "2026" title is never
    auto-rejected; it is classified as compatible because the candidate may
    graduate in December 2026.
    """
    grad_cfg = filters.get("graduation", {})
    compatible = {int(y) for y in grad_cfg.get("compatible_years", [2026, 2027])}
    incompatible = {int(y) for y in grad_cfg.get("incompatible_years", [])}

    title_years = {int(y) for y in _YEAR_RE.findall(job.title)}
    text_years: set[int] = set()
    for match in _GRAD_CONTEXT_RE.finditer(job.description):
        year = match.group(2) or match.group(3)
        if year:
            text_years.add(int(year))

    mentioned = title_years or text_years
    good = sorted(mentioned & compatible)
    bad = sorted(mentioned & incompatible)

    if good:
        year = good[-1]
        note = (
            "matches May 2027 graduation"
            if year == 2027
            else "matches potential Dec 2026 early graduation"
        )
        return f"compatible_{year}", f"posting targets {year} grads — {note}"
    if bad:
        return (
            f"incompatible_{bad[-1]}",
            f"posting targets {bad[-1]} grads, before the candidate's earliest availability (Dec 2026)",
        )
    if mentioned:
        future = sorted(mentioned)[-1]
        if future > max(compatible):
            return (
                f"future_{future}",
                f"posting targets {future} grads (later than needed but possibly open)",
            )
    return "unspecified", "no graduation year stated; assumed open to upcoming grads"
