"""Markdown report generation (ACTIVE_JOBS.md, NEW_JOBS.md)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .models import Job, SourceHealth
from .scoring import score_band
from .textutil import md_escape, truncate

DISCLAIMER = (
    "> ⚠️ **Disclaimer:** sponsorship classification is an automated screening aid based on "
    "posting text. It is **not legal advice** and **not a guarantee of eligibility**. Always "
    "verify work-authorization requirements with the employer before applying."
)

_SPONSOR_BADGE = {
    "likely_supported": "🟢 likely supported",
    "possibly_supported": "🟡 possibly supported",
    "unclear": "⚪ unclear",
    "likely_not_supported": "🔴 likely not supported",
    "ineligible": "⛔ ineligible",
}


def sort_recommended(jobs: list[Job], priorities: dict[str, int]) -> list[Job]:
    """Score desc, posting date desc, company priority asc, company name asc."""
    return sorted(
        jobs,
        key=lambda j: (
            -j.overall_score,
            -(_date_ord(j.date_posted)),
            priorities.get(j.company, 9),
            j.company.lower(),
        ),
    )


def build_active_report(
    jobs: list[Job],
    health: list[SourceHealth],
    filters: dict[str, Any],
    priorities: dict[str, int],
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(UTC)
    taipei = now.astimezone(ZoneInfo("Asia/Taipei"))
    ok = [h for h in health if h.status in ("ok", "ok_empty")]
    failed = [h for h in health if h.status == "failed"]
    skipped = [h for h in health if h.status == "skipped"]

    recommended = [j for j in jobs if not j.disqualified]
    ranked = sort_recommended(recommended, priorities)
    bands: dict[str, list[Job]] = {"excellent": [], "strong": [], "possible": [], "low": []}
    for job in ranked:
        bands[score_band(job.overall_score, filters)].append(job)

    lines = [
        "# Active Job Matches",
        "",
        f"_Last updated: **{now.strftime('%Y-%m-%d %H:%M UTC')}** "
        f"({taipei.strftime('%Y-%m-%d %H:%M')} Asia/Taipei) — auto-generated, do not edit._",
        "",
        DISCLAIMER,
        "",
    ]

    for band, heading in (
        ("excellent", "## 🌟 Excellent matches (80–100)"),
        ("strong", "## ✅ Strong matches (65–79)"),
        ("possible", "## 🤔 Possible matches (50–64)"),
    ):
        lines += [heading, ""]
        lines += _jobs_table(bands[band])
        lines.append("")

    lines += [
        "## Summary",
        "",
        f"- **Active jobs tracked:** {len(jobs)}",
        f"- **Recommended (not disqualified):** {len(recommended)}",
        f"- **Companies checked successfully:** {len(ok)}",
        f"- **Failed sources:** {len(failed)}",
        f"- **Unresolved/disabled sources:** {len(skipped)}",
        f"- Matches — excellent: {len(bands['excellent'])}, strong: {len(bands['strong'])}, "
        f"possible: {len(bands['possible'])}, low priority: {len(bands['low'])}",
        "",
    ]

    if failed or skipped:
        lines += ["## Source problems", ""]
        lines += ["| Company | Status | Category | Detail |", "| --- | --- | --- | --- |"]
        for h in failed + skipped:
            lines.append(
                f"| {md_escape(h.company)} | {h.status} | {h.error_category} "
                f"| {md_escape(truncate(h.error_message, 140))} |"
            )
        lines.append("")

    lines += [
        f"_{len(bands['low'])} lower-priority matches and any disqualified postings are in "
        "[data/active_jobs.json](data/active_jobs.json) / "
        "[data/active_jobs.csv](data/active_jobs.csv)._",
        "",
    ]
    return "\n".join(lines)


def build_new_report(
    new_jobs: list[Job],
    filters: dict[str, Any],
    priorities: dict[str, int],
    now: datetime | None = None,
) -> str:
    now = now or datetime.now(UTC)
    lines = [
        "# Newly Discovered Jobs",
        "",
        f"_Found in the run at **{now.strftime('%Y-%m-%d %H:%M UTC')}** — auto-generated._",
        "",
        DISCLAIMER,
        "",
    ]
    visible = [j for j in new_jobs if not j.disqualified]
    if not visible:
        lines.append("No new matching jobs were discovered in this run.")
        lines.append("")
        return "\n".join(lines)
    lines += _jobs_table(sort_recommended(visible, priorities))
    lines.append("")
    return "\n".join(lines)


def digest_table(jobs: list[Job]) -> str:
    """Markdown table for the GitHub issue digest."""
    lines = [
        "| Apply | Company | Title | Location | Score | Sponsorship | Key reason |",
        "| --- | --- | --- | --- | :---: | --- | --- |",
    ]
    for job in jobs:
        reason = job.sponsorship_evidence or job.score_explanation
        lines.append(
            f"| [Apply]({job.application_url}) "
            f"| {md_escape(job.company)} "
            f"| {md_escape(job.title)} "
            f"| {md_escape(truncate(job.location, 60))} "
            f"| {job.overall_score} "
            f"| {_SPONSOR_BADGE.get(job.sponsorship_classification, job.sponsorship_classification)} "
            f"| {md_escape(truncate(reason, 160))} |"
        )
    return "\n".join(lines)


def _jobs_table(jobs: list[Job]) -> list[str]:
    if not jobs:
        return ["_None right now._"]
    lines = [
        "| Apply | Company | Title | Location | Sponsorship | Posted |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for job in jobs:
        lines.append(
            f"| [Apply]({job.application_url}) "
            f"| {md_escape(job.company)} "
            f"| {md_escape(job.title)} "
            f"| {md_escape(truncate(job.location, 60))} "
            f"| {_SPONSOR_BADGE.get(job.sponsorship_classification, job.sponsorship_classification)} "
            f"| {job.date_posted or '—'} |"
        )
    return lines


def _date_ord(date_posted: str) -> int:
    try:
        return int(datetime.fromisoformat(date_posted[:10]).timestamp())
    except (ValueError, TypeError):
        return 0
