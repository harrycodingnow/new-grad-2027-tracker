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
import html
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
# Public source lists. They share the Company | Role | Location | … | Date
# column order but differ in link style and sponsorship markers.
#   markers=True  -> repo flags non-friendly roles with 🛂/🇺🇸/🔒, so an
#                    unflagged role is treated as sponsorship-friendly (🟢).
#   markers=False -> repo carries no sponsorship signal; roles are 🟡 (unconfirmed).
SOURCES = [
    {"repo": "vanshb03/New-Grad-2027", "markers": True},
    {"repo": "SimplifyJobs/New-Grad-Positions", "markers": True, "format": "html"},
    {"repo": "zapplyjobs/New-Grad-Jobs-2026", "markers": True},
    {"repo": "ambicuity/New-Grad-Jobs", "markers": True},
    {"repo": "jobright-ai/2026-Software-Engineer-New-Grad", "markers": False},
]

# Graduation year to keep (set GRAD_FILTER="" to match all — used for testing).
GRAD_FILTER = os.environ.get("GRAD_FILTER", "2027")

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

# This is a *new-grad* tracker — drop internship rows from every source.
INTERN_RE = re.compile(r"\bintern(ship)?\b", re.I)

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

# Append-only run log: one row per execution.
HISTORY_PATH = "fetch_history.csv"
HISTORY_HEADER = (
    "fetched_at_utc,total_listings,seed_listings,"
    "matched_from_sources,rows_scanned,sources_ok,readme_updated"
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


_TAG_RE = re.compile(r"<[^>]+>")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL_MD_RE = re.compile(r"\]\((https?://[^)\s]+)\)")
_URL_HREF_RE = re.compile(r'href="(https?://[^"]+)"')
_DECOR = "\U0001F680\U0001F525\u21B3"  # 🚀 🔥 ↳ decorative prefixes


def _strip_markup(cell: str) -> str:
    text = _MD_LINK_RE.sub(r"\1", cell)   # [label](url) -> label
    text = _TAG_RE.sub("", text)          # drop HTML tags
    return text.replace("**", "").replace("*", "").strip()


def clean_company(cell: str) -> str:
    text = _strip_markup(cell)
    for char in _DECOR:
        text = text.replace(char, "")
    return text.strip()


def clean_url(url: str) -> str:
    url = url.strip().rstrip(").,")
    url = re.sub(r"(?i)([?&])utm_[a-z]+=[^&]*", r"\1", url)  # drop utm_* params
    url = re.sub(r"[?&]+$", "", url)
    return url.replace("?&", "?")


def extract_url(cells: list[str]) -> str:
    # Skip column 0 (company) so we don't grab the company-website link.
    for cell in cells[1:]:
        match = _URL_MD_RE.search(cell) or _URL_HREF_RE.search(cell)
        if match:
            return clean_url(match.group(1))
    return ""


def parse_table(text: str, source: dict) -> tuple[list[dict], int]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sponsorship = GREEN if source.get("markers") else YELLOW
    short = source["repo"].split("/")[0]
    rows: list[dict] = []
    scanned = 0
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
        scanned += 1
        company = clean_company(cells[0])
        if cells[0].strip().startswith("\u21B3") or company == "":  # ↳ carry-over
            company = last_company or ""
        else:
            last_company = company
        blob = " ".join(cells)
        if GRAD_FILTER and GRAD_FILTER not in blob:    # STRICTLY 2027 (default)
            continue
        if any(marker in blob for marker in EXCLUDE_MARKERS):  # 🛂 / 🇺🇸 / 🔒
            continue
        if INTERN_RE.search(cells[1]):                 # new-grad only
            continue
        role = _strip_markup(cells[1])
        for marker in (CLOSED, NO_SPONSOR, CITIZEN_ONLY):
            role = role.replace(marker, "")
        role = role.strip()
        category = categorize(role)
        if not category:
            continue
        url = extract_url(cells)
        if not url:
            continue
        location = _strip_markup(re.sub(r"</?br\s*/?>", " / ", cells[2]))
        location = re.sub(r"\s*/\s*", " / ", location).strip(" /")
        rows.append({
            "company": company,
            "role": role,
            "category": category,
            "location": location,
            "grad_year": "2027",
            "sponsorship": sponsorship,
            "url": url,
            "source": short,
            "date_added": today,
        })
    return rows, scanned


_TR_RE = re.compile(r"<tr>(.*?)</tr>", re.S | re.I)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)


def _html_text(cell: str) -> str:
    return html.unescape(_TAG_RE.sub("", cell)).replace("**", "").strip()


def parse_html_table(text: str, source: dict) -> tuple[list[dict], int]:
    """Parse SimplifyJobs-style HTML tables (<tr>/<td>)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sponsorship = GREEN if source.get("markers") else YELLOW
    short = source["repo"].split("/")[0]
    rows: list[dict] = []
    scanned = 0
    last_company = None
    for tr in _TR_RE.findall(text):
        cells = _TD_RE.findall(tr)
        if len(cells) < 5:
            continue
        scanned += 1
        company = _html_text(cells[0])
        if company in ("", "\u21B3"):  # ↳ carry-over row
            company = last_company or ""
        else:
            last_company = company
        if GRAD_FILTER and GRAD_FILTER not in tr:      # STRICTLY 2027 (default)
            continue
        if any(marker in tr for marker in EXCLUDE_MARKERS):  # 🛂 / 🇺🇸 / 🔒
            continue
        role = _html_text(cells[1])
        if INTERN_RE.search(role):                     # new-grad only
            continue
        for marker in (CLOSED, NO_SPONSOR, CITIZEN_ONLY):
            role = role.replace(marker, "")
        role = role.strip()
        category = categorize(role)
        if not category:
            continue
        url = ""
        for match in re.finditer(r'href="(https?://[^"]+)"', cells[3]):
            candidate = match.group(1)
            if "simplify.jobs" in candidate:           # skip the Simplify tracking link
                continue
            url = clean_url(candidate)
            break
        if not url:
            continue
        rows.append({
            "company": company,
            "role": role,
            "category": category,
            "location": _html_text(cells[2]),
            "grad_year": "2027",
            "sponsorship": sponsorship,
            "url": url,
            "source": short,
            "date_added": today,
        })
    return rows, scanned


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

📊 **Run log:** fetch times and listing counts for every run are recorded in [`fetch_history.csv`](fetch_history.csv).

## Legend

- 🟢 — Offers visa sponsorship / international-student friendly
- 🟡 — Sponsorship unconfirmed — verify with recruiter
- 🔴 — No sponsorship / US-persons only (e.g., ITAR)

## The List 🚀

{table}

## Sources

**Auto-scraped daily** — filtered to strictly-2027 · SWE / AI-ML / Full-Stack · international-student-friendly:

- [vanshb03/New-Grad-2027](https://github.com/vanshb03/New-Grad-2027)
- [SimplifyJobs/New-Grad-Positions](https://github.com/SimplifyJobs/New-Grad-Positions)
- [zapplyjobs/New-Grad-Jobs-2026](https://github.com/zapplyjobs/New-Grad-Jobs-2026)
- [ambicuity/New-Grad-Jobs](https://github.com/ambicuity/New-Grad-Jobs)
- [jobright-ai/2026-Software-Engineer-New-Grad](https://github.com/jobright-ai/2026-Software-Engineer-New-Grad)

**Also worth checking by hand:**

- [Jobright — Software Engineer · 2027 New Grads](https://jobright.ai/jobs/software-engineer---2027-new-grads-jobs-in-united-states)
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


def append_history(row: str, summary: str) -> None:
    """Append one CSV row to the run-history file (local in DRY_RUN, else via API)."""
    if DRY_RUN:
        exists = os.path.exists(HISTORY_PATH)
        with open(HISTORY_PATH, "a", encoding="utf-8") as handle:
            if not exists or os.path.getsize(HISTORY_PATH) == 0:
                handle.write(HISTORY_HEADER + "\n")
            handle.write(row + "\n")
        print("DRY_RUN: appended fetch_history.csv locally.")
        return

    sha, current = get_current(HISTORY_PATH)
    if current is None:
        content = HISTORY_HEADER + "\n" + row + "\n"
    else:
        content = current if current.endswith("\n") else current + "\n"
        content += row + "\n"
    payload = {
        "message": f"log: {summary} [skip ci]",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha
    resp = requests.put(
        f"{API}/repos/{REPO}/contents/{HISTORY_PATH}",
        headers=gh_headers(), json=payload, timeout=30)
    resp.raise_for_status()
    print(f"Appended {HISTORY_PATH} -> {resp.json()['commit']['html_url']}")


def main() -> int:
    seed = load_seed()
    roles = list(seed)
    matched_from_sources = 0
    rows_scanned = 0
    sources_ok: list[str] = []
    for source in SOURCES:
        parser = parse_html_table if source.get("format") == "html" else parse_table
        try:
            rows, scanned = parser(fetch_source_readme(source["repo"]), source)
        except Exception as exc:  # noqa: BLE001 - keep going if one source fails
            print(f"WARN: source {source['repo']} failed: {exc}", file=sys.stderr)
            continue
        roles += rows
        matched_from_sources += len(rows)
        rows_scanned += scanned
        sources_ok.append(source["repo"].split("/")[0])

    content, count = render_readme(roles)
    print(f"Resolved {count} strictly-2027 sponsorship-friendly role(s) "
          f"({len(seed)} seed + {matched_from_sources} from {len(sources_ok)} source(s); "
          f"{rows_scanned} rows scanned).")

    fetched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if DRY_RUN:
        prev = None
        if os.path.exists("README.md"):
            with open("README.md", encoding="utf-8") as handle:
                prev = handle.read()
        readme_updated = _ignore_timestamp(prev) != _ignore_timestamp(content)
        with open("README.md", "w", encoding="utf-8") as handle:
            handle.write(content)
        print("DRY_RUN: wrote README.md locally; no commit made.")
    else:
        if not TOKEN:
            print("ERROR: set GH_TOKEN (PAT or GITHUB_TOKEN with contents:write) "
                  "to commit.", file=sys.stderr)
            return 1
        readme_updated = commit_readme(content)

    row = (f"{fetched_at},{count},{len(seed)},{matched_from_sources},"
           f"{rows_scanned},{';'.join(sources_ok) or 'none'},"
           f"{str(readme_updated).lower()}")
    summary = f"fetched {count} listing(s) at {fetched_at}"
    append_history(row, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
