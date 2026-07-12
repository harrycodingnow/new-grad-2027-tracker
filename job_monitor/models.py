"""Normalized data model shared by every source adapter."""

from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass, field
from typing import Any

SPONSORSHIP_CLASSES = (
    "likely_supported",
    "possibly_supported",
    "unclear",
    "likely_not_supported",
    "ineligible",
)

# Source-health error taxonomy. `ok` / `ok_empty` are successes.
ERROR_CATEGORIES = (
    "ok",
    "ok_empty",
    "network_error",
    "parse_error",
    "blocked",
    "invalid_config",
    "structure_changed",
    "unsupported",
)


@dataclass
class Job:
    """One normalized job posting."""

    job_id: str = ""
    source_job_id: str = ""
    company: str = ""
    title: str = ""
    location: str = ""
    country: str = ""
    workplace_type: str = ""  # onsite | hybrid | remote | ""
    department: str = ""
    employment_type: str = ""
    description: str = ""
    requirements: str = ""
    application_url: str = ""
    source_url: str = ""
    source_type: str = ""
    date_posted: str = ""  # ISO date if known
    first_seen: str = ""  # ISO datetime UTC
    last_seen: str = ""  # ISO datetime UTC
    status: str = "active"  # active | closed
    graduation_match: str = ""  # e.g. compatible_2027 | unspecified | incompatible_2025
    role_match_score: int = 0  # 0-100 role/skills subscore
    sponsorship_classification: str = "unclear"
    sponsorship_evidence: str = ""
    international_student_risk_flags: list[str] = field(default_factory=list)
    overall_score: int = 0
    matched_keywords: list[str] = field(default_factory=list)
    excluded_keywords: list[str] = field(default_factory=list)
    # Bookkeeping (kept in the dataset, explained in the README schema section)
    score_explanation: str = ""
    disqualified: bool = False
    disqualify_reason: str = ""
    consecutive_missing: int = 0
    announced: bool = False

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def ensure_job_id(self) -> None:
        """Set a stable ID: prefer the source's own ID, else a deterministic hash."""
        if self.job_id:
            return
        if self.source_job_id:
            self.job_id = f"{_slug(self.company)}-{self.source_job_id}"
        else:
            self.job_id = f"{_slug(self.company)}-{self.fingerprint()[:16]}"

    def fingerprint(self) -> str:
        """Deterministic fallback fingerprint from stable descriptive fields."""
        basis = "|".join(
            s.strip().lower()
            for s in (self.company, self.title, self.location, self.application_url)
        )
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()


@dataclass
class SourceHealth:
    """Outcome of the most recent fetch attempt for one company."""

    company: str
    source_type: str
    last_attempt: str = ""
    last_success: str = ""
    status: str = "unknown"  # ok | ok_empty | failed | skipped
    jobs_fetched: int = 0
    error_category: str = ""
    error_message: str = ""
    consecutive_failures: int = 0

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceHealth:
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")
