"""Notifications: GitHub issue digest (primary) and optional Telegram.

Issue creation failures never fail the monitoring run. Announcement state is
the `announced` flag on each job record, persisted in data/active_jobs.json,
so already-announced jobs are never re-announced.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

from .http import HttpClient
from .models import Job
from .report import DISCLAIMER, digest_table

log = logging.getLogger(__name__)

ISSUE_LABELS = ["job-alert", "new-jobs"]


def create_digest_issue(jobs: list[Job], client: HttpClient | None = None) -> bool:
    """Open one digest issue for this run. Returns True on success."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        log.info("GITHUB_TOKEN/GITHUB_REPOSITORY not set; skipping issue digest")
        return False
    client = client or HttpClient()
    today = datetime.now(UTC).date().isoformat()
    count = len(jobs)
    title = f"[New Jobs] {count} strong match{'es' if count != 1 else ''} found — {today}"
    body = "\n".join(
        [
            f"The monitor found **{count}** newly posted job(s) scoring ≥ the digest threshold.",
            "",
            digest_table(jobs),
            "",
            DISCLAIMER,
            "",
            "_Full details in `ACTIVE_JOBS.md` and `data/new_jobs.json`._",
        ]
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        _ensure_labels(client, repo, headers)
        client.post(
            f"https://api.github.com/repos/{repo}/issues",
            headers=headers,
            json_body={"title": title, "body": body, "labels": ISSUE_LABELS},
        )
        log.info("created digest issue: %s", title)
        return True
    except Exception as exc:
        log.warning("failed to create digest issue (run continues): %s", exc)
        return False


def _ensure_labels(client: HttpClient, repo: str, headers: dict[str, str]) -> None:
    for name, color in (("job-alert", "1d76db"), ("new-jobs", "0e8a16")):
        try:
            client.post(
                f"https://api.github.com/repos/{repo}/labels",
                headers=headers,
                json_body={"name": name, "color": color},
            )
        except Exception:
            pass  # label already exists (422) or creation not permitted


def send_telegram(jobs: list[Job], client: HttpClient | None = None) -> bool:
    """Optional Telegram digest. Runs only when both secrets are configured."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    client = client or HttpClient()
    lines = [f"🔔 {len(jobs)} new strong job match(es):", ""]
    for job in jobs[:15]:
        lines.append(
            f"• {job.company} — {job.title} ({job.location or 'location n/a'}) "
            f"score {job.overall_score} [{job.sponsorship_classification}]\n  {job.application_url}"
        )
    if len(jobs) > 15:
        lines.append(f"…and {len(jobs) - 15} more (see ACTIVE_JOBS.md)")
    try:
        client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json_body={
                "chat_id": chat_id,
                "text": "\n".join(lines),
                "disable_web_page_preview": True,
            },
        )
        return True
    except Exception as exc:
        log.warning("telegram notification failed (run continues): %s", exc)
        return False
