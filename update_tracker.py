#!/usr/bin/env python3
"""Daily updater for the New Grad 2027 tracker.

Pulls public new-grad job lists, keeps ONLY strictly-2027 roles for
Software Engineer / AI-ML / Full-Stack that are international-student
friendly (offer sponsorship -> not flagged no-sponsorship, not
US-citizen-only, not closed), merges them with the hand-curated roles in
roles.json, regenerates README.md, and commits it to GitHub via the
Contents API.

Designed to run on a schedule (e.g., GitHub Actions): it runs once and exits.

Environment variables:
  GH_TOKEN   GitHub PAT with `contents:write` on the target repo (required
             to commit; also accepts GITHUB_TOKEN).
  GH_REPO    "owner/name" of the tracker repo. Default: harrycodingnow/new-grad-2027-tracker
  GH_BRANCH  Branch to commit to. Default: main
  DRY_RUN    If set ("1"/"true"), write README.md locally and skip the commit.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
from datetime import datetime, timezone

import requests

API = "https://api.github.com"
REPO = os.environ.get("GH_REPO", "harrycodingnow/new-grad-2027-tracker")
BRANCH = os.environ.get("GH_BRANCH", "main")
TOKEN = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")

# Public source lists that share the same markdown-table + emoji-marker format.
SOURCES = [
    "vanshb03/New-Grad-2027",
    "SimplifyJobs/New-Grad-Positions",
]

# Category detection (first match wins; order matters).
CATEGORIES = [
    ("AI / ML Engineer", re.compile(
        r"(ai engineer|machine learning|\bml\b|ml engineer|applied ai|"
        r"applied scientist|gen ?ai|deep learning|\bllm\b)", re.I)),
    ("Full-Stack", re.compile(r"full[\s-]?stack", re.I)),
    ("Software Engineer", re.compile(
        r"(software engineer|software developer|\bswe\b|backend|back-end|"
        r"front[\s-]?end|developer)", re.I)),
]

# Emoji constants (defined via codepoints so the file stays ASCII-safe).
NO_SPONSOR = "\U0001F6C2"            # 🛂 does NOT offer sponsorship
CITIZEN_ONLY = "\U0001F1FA\U0001F1F8"  # 🇺🇸 US citizenship required
CLOSED = "\U0001F512"               # 🔒 application closed
GREEN = "\U0001F7E2"                # 🟢 sponsorship-friendly
YELLOW = "\U0001F7E1"               # 🟡 sponsorship unconfirmed

# Markers that disqualify a role for an international student.
EXCLUDE_MARKERS = (NO_SPONSOR, CITIZEN_ONLY, CLOSED)

TABLE_HEADER = (
    "| Company | Role | Category | Location | Grad Year | Sponsorship | Apply | Date Added |\n"
    "| --- | --- | --- | --- | :---: | :---: | :---: | :---: |"
)


def gh_headers() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    return headers


def fetch_source_readme(repo: str) -> str:
    resp = requests.get(
        f"{API}/repos/{repo}/contents/README.md", headers=gh_headers(), timeout=30)
    resp.raise_for_status()
    return base64.b64decode(resp.json()["content"]).decode("utf-8", "replace")


def categorize(role: str) -> str | None:
    for name, pattern in CATEGORIES:
        if pattern.search(role):
            return name
    return None


def parse_table(text: str, source: str) -> list[dict]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows: list[dict] = []
    last_company = None
    for line in text.splitlines():
        if not line.startswith("| "):
            continue
        stripped = line.strip().strip("|")
        if stripped.lower().strip().startswith("company"):
            continue
        if set(stripped.replace("|", "").strip()) <= set("-: "):
            continue
        cells = [c.strip() for c in stripped.split(" | ")]
        if len(cells) < 5:
            continue
        company = cells[0].replace("*", "").strip()
        role, location, link_cell, date = cells[1], cells[2], cells[3], cells[-1]
        if company in ("", "\u21B3"):  # ↳ carry-over row -> reuse previous company
            company = last_company or ""
        else:
            last_company = company
        blob = " ".join(cells)
        if "2027" not in blob:                       # STRICTLY 2027
            continue
        if any(marker in blob for marker in EXCLUDE_MARKERS):
            continue
        category = categorize(role)
        if not category:
            continue
        match = re.search(r'href="([^"]+)"', link_cell)
        url = match.group(1) if match else (link_cell if link_cell.startswith("http") else "")
        url = re.sub(r"[?&]utm_source=[^\"&]+", "", url).strip()
        if not url:
            continue
        for marker in (CLOSED, NO_SPONSOR, CITIZEN_ONLY):
            role = role.replace(marker, "")
        role = role.strip()
        location = re.sub(r"</?br\s*/?>", " / ", location).strip(" /")
        rows.append({
            "company": company,
            "role": role,
            "category": category,
            "location": location,
            "grad_year": "2027",
            "sponsorship": GREEN,  # source did not flag it no-sponsorship
            "url": url,
            "source": source.split("/")[0],
            "date_added": today,
        })
    return rows


def load_seed() -> list[dict]:
    try:
        with open("roles.json", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as exc:
        print(f"WARN: roles.json is invalid JSON: {exc}", file=sys.stderr)
        return []


def render_readme(roles: list[dict]) -> tuple[str, int]:
    seen, unique = set(), []
    for role in roles:
        url = role.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(role)
    unique.sort(key=lambda r: (r.get("category", ""), r.get("company", "").lower()))

    if unique:
        body = "\n".join(
            f"| **{r['company']}** | {r['role']} | {r.get('category', '')} | "
            f"{r.get('location', '')} | {r.get('grad_year', '2027')} | "
            f"{r.get('sponsorship', YELLOW)} | [Apply]({r['url']}) | "
            f"{r.get('date_added', '')} |"
            for r in unique
        )
    else:
        body = ("| _No strictly-2027 roles live in the sources yet_ | — | — | — | "
                "— | — | — | — |")

    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (TEMPLATE.format(table=f"{TABLE_HEADER}\n{body}", updated=updated), len(unique))


TEMPLATE = """# New Grad 2027 — SWE / AI / Full-Stack Tracker 🎓

A curated list of **strictly 2027** new-grad, full-time roles in the **United States**, focused on:

- 💻 **Software Engineer**
- 🤖 **AI / ML Engineer**
- 🧩 **Full-Stack Engineer**

**International-student-friendly (visa sponsorship) preferred.** Roles are included only when explicitly labeled for **2027 graduates**.

> ⚠️ As of mid-2026, dedicated **2027** full-time new-grad postings are just beginning to appear — most open **Aug–Oct 2026**. This list auto-updates daily and will grow as the cycle ramps up.

_Last updated: {updated} · auto-generated by `update_tracker.py` (GitHub Actions)._

## Legend

- 🟢 — Offers visa sponsorship / international-student friendly
- 🟡 — Sponsorship unconfirmed — verify with recruiter
- 🔴 — No sponsorship / US-persons only (e.g., ITAR)

## The List 🚀

{table}

## Sources

- [Jobright — Software Engineer · 2027 New Grads](https://jobright.ai/jobs/software-engineer---2027-new-grads-jobs-in-united-states)
- [vanshb03/New-Grad-2027](https://github.com/vanshb03/New-Grad-2027)
- [SimplifyJobs/New-Grad-Positions](https://github.com/SimplifyJobs/New-Grad-Positions)
- [Simplify — New Grad Roles with Visa Sponsorship](https://simplify.jobs/l/New-Grad-Roles-with-Visa-Sponsorship)

---

_Maintained by [@harrycodingnow](https://github.com/harrycodingnow). Hand-add verified roles to `roles.json`; the rest are pulled automatically. Contributions welcome via issue or PR._
"""


def get_current(path: str) -> tuple[str | None, str | None]:
    resp = requests.get(
        f"{API}/repos/{REPO}/contents/{path}",
        headers=gh_headers(), params={"ref": BRANCH}, timeout=30)
    if resp.status_code == 200:
        data = resp.json()
        return data["sha"], base64.b64decode(data["content"]).decode("utf-8", "replace")
    return None, None


def _ignore_timestamp(text: str | None) -> str:
    if text is None:
        return ""
    return re.sub(r"_Last updated:.*?\._", "", text)


def commit_readme(content: str) -> bool:
    sha, current = get_current("README.md")
    if _ignore_timestamp(current) == _ignore_timestamp(content):
        print("No substantive change to README.md; skipping commit.")
        return False
    payload = {
        "message": "chore: daily 2027 tracker update [skip ci]",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha
    resp = requests.put(
        f"{API}/repos/{REPO}/contents/README.md",
        headers=gh_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    print(f"Committed README.md -> {resp.json()['commit']['html_url']}")
    return True


def main() -> int:
    roles = list(load_seed())
    for source in SOURCES:
        try:
            roles += parse_table(fetch_source_readme(source), source)
        except Exception as exc:  # noqa: BLE001 - keep going if one source fails
            print(f"WARN: source {source} failed: {exc}", file=sys.stderr)

    content, count = render_readme(roles)
    print(f"Resolved {count} strictly-2027 sponsorship-friendly role(s).")

    if DRY_RUN:
        with open("README.md", "w", encoding="utf-8") as handle:
            handle.write(content)
        print("DRY_RUN: wrote README.md locally; no commit made.")
        return 0

    if not TOKEN:
        print("ERROR: set GH_TOKEN (GitHub PAT with contents:write) to commit.",
              file=sys.stderr)
        return 1

    commit_readme(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
