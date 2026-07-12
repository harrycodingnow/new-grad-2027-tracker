"""Explainable 0-100 scoring. No LLM required; see llm.py for the optional hook."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .filters import TitleDecision
from .models import Job
from .textutil import word_boundary_pattern

# Fraction of each weight granted per sponsorship classification.
_SPONSORSHIP_FACTOR = {
    "likely_supported": 1.0,
    "possibly_supported": 0.7,
    "unclear": 0.45,
    "likely_not_supported": 0.0,
    "ineligible": 0.0,
}

# Classifications that disqualify a job from the recommended lists.
HARD_DISQUALIFIERS = {"ineligible", "likely_not_supported"}


def score_job(
    job: Job,
    decision: TitleDecision,
    profile: dict[str, Any],
    filters: dict[str, Any],
    now: datetime | None = None,
) -> None:
    """Fill role_match_score, overall_score, score_explanation, disqualified."""
    now = now or datetime.now(UTC)
    weights = filters.get("scoring", {}).get("weights", {})
    w_role = int(weights.get("role_skills", 35))
    w_grad = int(weights.get("graduation", 20))
    w_sponsor = int(weights.get("sponsorship", 25))
    w_loc = int(weights.get("location", 10))
    w_recency = int(weights.get("recency", 10))
    parts: list[str] = []

    # --- role & skills (role_match_score is the 0-100 subscore) -------------
    title_lower = job.title.lower()
    primary = [r for r in profile.get("roles", {}).get("primary", []) if r.lower() in title_lower]
    secondary = [
        r for r in profile.get("roles", {}).get("secondary", []) if r.lower() in title_lower
    ]
    role_base = 60 if primary or decision.matched else 0
    if not primary and secondary:
        role_base = 45
    text = f"{job.title} {job.description} {job.requirements}"
    skills = [s for s in profile.get("skills", []) if word_boundary_pattern(str(s)).search(text)]
    role_score = min(100, role_base + min(40, 5 * len(skills)))
    job.role_match_score = role_score
    job.matched_keywords = sorted({*decision.matched, *(s.lower() for s in skills)})
    pts_role = round(role_score / 100 * w_role)
    role_note = (
        f"primary role match ({primary[0]})"
        if primary
        else f"secondary role match ({secondary[0]})"
        if secondary
        else "title matched filter terms"
        if decision.matched
        else "no role-family match"
    )
    skill_note = f"; skills: {', '.join(s.lower() for s in skills[:6])}" if skills else ""
    parts.append(f"role {pts_role}/{w_role} ({role_note}{skill_note})")

    # --- graduation compatibility -------------------------------------------
    grad_factor = {
        "compatible_2027": 1.0,
        "compatible_2026": 0.9,
    }.get(job.graduation_match)
    if grad_factor is None:
        if job.graduation_match.startswith("incompatible"):
            grad_factor = 0.0
        elif job.graduation_match.startswith("future"):
            grad_factor = 0.5
        else:  # unspecified
            grad_factor = 0.6 if _has_new_grad_marker(decision) else 0.4
    pts_grad = round(grad_factor * w_grad)
    parts.append(f"graduation {pts_grad}/{w_grad} ({job.graduation_match})")

    # --- sponsorship ----------------------------------------------------------
    factor = _SPONSORSHIP_FACTOR.get(job.sponsorship_classification, 0.45)
    pts_sponsor = round(factor * w_sponsor)
    parts.append(f"sponsorship {pts_sponsor}/{w_sponsor} ({job.sponsorship_classification})")

    # --- location -------------------------------------------------------------
    if job.country.lower().startswith("united states") or job.location:
        pts_loc = w_loc
        loc_note = job.location or job.country
    else:
        pts_loc = round(0.5 * w_loc)
        loc_note = "location unknown"
    parts.append(f"location {pts_loc}/{w_loc} ({loc_note[:40]})")

    # --- recency ----------------------------------------------------------------
    scoring_cfg = filters.get("scoring", {})
    full_days = int(scoring_cfg.get("recency_full_days", 7))
    zero_days = int(scoring_cfg.get("recency_zero_days", 60))
    age = _age_days(job.date_posted, now)
    if age is None:
        recency_factor, recency_note = 0.5, "posting date unknown"
    elif age <= full_days:
        recency_factor, recency_note = 1.0, f"posted {age}d ago"
    elif age >= zero_days:
        recency_factor, recency_note = 0.0, f"posted {age}d ago"
    else:
        recency_factor = 1 - (age - full_days) / (zero_days - full_days)
        recency_note = f"posted {age}d ago"
    pts_recency = round(recency_factor * w_recency)
    parts.append(f"recency {pts_recency}/{w_recency} ({recency_note})")

    job.overall_score = pts_role + pts_grad + pts_sponsor + pts_loc + pts_recency
    job.score_explanation = " · ".join(parts)

    # --- hard disqualifiers ------------------------------------------------------
    job.disqualified = False
    job.disqualify_reason = ""
    if job.sponsorship_classification in HARD_DISQUALIFIERS:
        job.disqualified = True
        job.disqualify_reason = f"sponsorship classification '{job.sponsorship_classification}'" + (
            f": {job.sponsorship_evidence[:160]}" if job.sponsorship_evidence else ""
        )
    elif job.graduation_match.startswith("incompatible"):
        job.disqualified = True
        job.disqualify_reason = f"graduation mismatch ({job.graduation_match})"


def score_band(score: int, filters: dict[str, Any]) -> str:
    thresholds = filters.get("scoring", {}).get("thresholds", {})
    if score >= int(thresholds.get("excellent", 80)):
        return "excellent"
    if score >= int(thresholds.get("strong", 65)):
        return "strong"
    if score >= int(thresholds.get("possible", 50)):
        return "possible"
    return "low"


def _has_new_grad_marker(decision: TitleDecision) -> bool:
    markers = ("grad", "entry", "early", "campus", "junior", "associate", "engineer i", "swe i")
    return any(any(m in term for m in markers) for term in decision.matched)


def _age_days(date_posted: str, now: datetime) -> int | None:
    if not date_posted:
        return None
    try:
        posted = datetime.fromisoformat(date_posted[:10]).replace(tzinfo=UTC)
    except ValueError:
        return None
    return max(0, (now - posted).days)
