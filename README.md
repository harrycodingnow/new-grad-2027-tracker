# International New-Grad Job Monitor

Automated monitor of company career sites for **United States software jobs** relevant to an
international student **graduating May 2027** (potentially **December 2026**), who will work on
**F-1 OPT / STEM OPT** and may need **H-1B or other sponsorship** later.

It runs four times a day on GitHub Actions, fetches postings from each company's public
ATS/career API, filters for new-grad-friendly technical roles, classifies each posting's
work-authorization language, scores every job 0–100 with a written explanation, commits the
updated dataset back to this repo, and opens a **digest issue** when strong new matches appear.

> ⚠️ **Disclaimer:** the sponsorship classification is an automated screening aid based on
> posting text. It is **not legal advice** and **not a guarantee of eligibility**. Absence of
> sponsorship language is reported as *unclear*, never as *supported*. Always verify with the
> employer.

**Outputs**

| File | What it is |
| --- | --- |
| [ACTIVE_JOBS.md](ACTIVE_JOBS.md) | Human-readable report: excellent/strong/possible matches, evidence, source health |
| [NEW_JOBS.md](NEW_JOBS.md) | Jobs newly discovered in the latest run |
| [data/active_jobs.json](data/active_jobs.json) / [.csv](data/active_jobs.csv) | Full normalized dataset (source of truth) |
| [data/new_jobs.json](data/new_jobs.json) | Latest run's new jobs |
| [data/archived_jobs.json](data/archived_jobs.json) | Closed/expired postings with history |
| [data/source_health.json](data/source_health.json) | Per-company fetch status and error taxonomy |
| [docs/](docs/) | Static dashboard for GitHub Pages (search/filter/sort UI) |

## Architecture

```
config/                 profile.yaml    candidate profile (roles, skills, grad dates)
                        filters.yaml    include/exclude terms, sponsorship phrases, weights
                        companies.yaml  one entry per company (adapter + identifier)

job_monitor/
  adapters/             one adapter per source kind, all returning list[Job]:
    greenhouse.py         Greenhouse public Job Board API
    lever.py              Lever public Postings API
    ashby.py              Ashby public job-board API
    workday.py            Workday CXS career-site JSON API
    json_endpoint.py      configurable JSON endpoints + presets (Microsoft GCS,
                          amazon.jobs, Uber, SmartRecruiters, Oracle HCM, Jane Street, …)
    jsonld.py             pages embedding schema.org JobPosting JSON-LD
    html_page.py          generic HTML pages driven by CSS selectors
    playwright_page.py    optional last resort for JS-rendered pages
  http.py               timeouts, exponential retry, per-domain rate limit, honest UA
  filters.py            title gate + graduation-year classification
  sponsorship.py        work-authorization classification with quoted evidence
  scoring.py            explainable 0–100 score (deterministic, no LLM/API keys)
  dedupe.py             stable IDs, dedup, first_seen/last_seen, archiving
  store.py              JSON/CSV persistence + docs/ mirror for the dashboard
  report.py             ACTIVE_JOBS.md / NEW_JOBS.md generation
  notify.py             GitHub issue digest + optional Telegram
  runner.py             orchestration; llm.py is an optional classifier hook
```

Pipeline per run: **fetch → US-location gate → title gate → graduation + sponsorship
classification → scoring → merge with previous state → write outputs → notify.**

- A failing company never aborts the run; the failure is recorded in
  `data/source_health.json` with a category (`network_error`, `blocked`, `parse_error`,
  `invalid_config`, `structure_changed`, `unsupported`) — a source that truly returned zero
  jobs is `ok_empty`, never silently confused with a failure.
- Jobs keep their `first_seen` across runs; description/formatting edits do **not** make a job
  "new" again. After `lifecycle.archive_after_missing_runs` (default 3) consecutive runs
  missing from a *successfully fetched* source, a job is archived as closed.
- Hard-disqualified jobs (explicit no-sponsorship / clearance / citizenship requirements,
  incompatible graduation year) stay in the dataset with `disqualified: true` and the reason,
  but never appear in the recommended lists or digests.

### Scoring (configurable in `config/filters.yaml`)

| Component | Weight |
| --- | :---: |
| Role & skills match | 35 |
| New-grad / graduation-year compatibility | 20 |
| Sponsorship & work-authorization compatibility | 25 |
| Location compatibility | 10 |
| Posting recency | 10 |

Bands: **80–100 excellent · 65–79 strong · 50–64 possible · <50 low priority.** Every
recommended job carries a `score_explanation` showing exactly where its points came from.
Scoring is deterministic text matching — no paid LLM API is required. An optional LLM
refinement hook exists in `job_monitor/llm.py` (disabled by default, may only refine
*unclear*/*possibly* classifications).

### Sponsorship classification

Every posting's full text is scanned for positive phrases ("visa sponsorship available",
"OPT accepted", …) and restrictive ones ("will not sponsor", "U.S. citizenship required",
"security clearance", ITAR, …) — the exact matched sentence is stored in
`sponsorship_evidence`. Classes: `likely_supported`, `possibly_supported`, `unclear`,
`likely_not_supported`, `ineligible`. The most restrictive signal wins, and a company's
general sponsorship track record is deliberately ignored — only this posting's text counts.

**Limitations:** phrase matching cannot read intent; postings often omit visa language
entirely (→ `unclear`); boilerplate like "authorized to work in the US" is genuinely
ambiguous; and employers change policies mid-cycle. Treat the classification as triage, not
truth.

## Local installation

Requires Python **3.12+**.

```bash
git clone <this repo> && cd <repo>
make install          # venv + locked deps + editable install
make test             # offline test suite
make lint             # ruff
```

## Running the monitor

```bash
make monitor                                   # full run, writes data/ + reports
make dry-run                                   # fetch + log changes, write nothing
.venv/bin/python -m job_monitor --company Microsoft --company NVIDIA
.venv/bin/python -m job_monitor validate-sources   # try every configured source
make dashboard                                 # serve docs/ at localhost:8000
```

`validate-sources` prints a table of every company with its adapter, HTTP outcome and a
sample job title — use it after editing `companies.yaml`.

## Adding or disabling a company

Edit `config/companies.yaml`:

```yaml
- name: ExampleCorp
  enabled: true
  priority: 2
  careers_url: https://example.com/careers
  source_type: greenhouse          # greenhouse | lever | ashby | workday | json | jsonld | html | playwright
  source_identifier: examplecorp   # board token / host/tenant/site / preset name / URL
  locations: ["United States", "New York"]
  notes: ""
```

- **Greenhouse**: identifier is the board token in `boards.greenhouse.io/<token>`.
- **Lever**: token in `jobs.lever.co/<token>`. **Ashby**: org in `jobs.ashbyhq.com/<org>`.
- **Workday**: `host/tenant/site`, e.g. `nvidia.wd5.myworkdayjobs.com/nvidia/NVIDIAExternalCareerSite`
  (find it in the career site's XHR calls to `/wday/cxs/...`).
- **json**: either a preset (`microsoft`, `amazon`, `uber`, `oracle`, `janestreet`,
  `smartrecruiters:<company>`, `eightfold:<host>:<domain>`) or a fully generic mapping via
  `adapter_config` (`request.url`, `jobs_path`, `fields`, optional `pagination`) — see
  `tests/test_adapters.py::test_json_adapter_generic_mapping` for a working example.
- **html**: `source_identifier` is a URL template (may contain `{offset}`/`{page}`);
  `adapter_config` supplies `row_selector`, `title_selector`, etc.
- **playwright**: optional; install with `pip install -e '.[browser]' && playwright install chromium`.

Then run `python -m job_monitor validate-sources --company ExampleCorp` and only commit once
it reports ok. **Never guess ATS identifiers** — unresolved companies should stay
`source_type: unresolved` + `enabled: false` with an explanatory note.

Adjust candidate filters in `config/profile.yaml` (who you are) and `config/filters.yaml`
(include/exclude terms, sponsorship phrases, weights, thresholds, archive policy).

## GitHub Actions setup

Two workflows ship with the repo:

- `.github/workflows/monitor.yml` — scheduled 4×/day (02:23, 08:23, 14:23, 20:23 UTC —
  deliberately off the top of the hour) plus `workflow_dispatch`. It installs locked deps with
  pip caching, runs lint + tests first, executes the monitor, commits only when generated
  files changed (as `job-monitor-bot`, message `chore(jobs): update monitored openings
  [skip ci]`), and uploads `monitor.log` + `source_health.json` as artifacts on failure.
  Concurrency group `job-monitor` prevents overlapping runs. Permissions are the minimum:
  `contents: write`, `issues: write`.
- `.github/workflows/tests.yml` — lint + tests on every push/PR (read-only permissions).

**Required repository settings**

1. *Settings → Actions → General → Workflow permissions*: select **Read and write
   permissions** (needed for the data commit and the digest issue). The workflow-level
   `permissions:` block already requests only `contents: write` + `issues: write`.
2. *(Optional)* Enable **Issues** in *Settings → General → Features* if disabled — digests are
   skipped (not fatal) without it.

### Enabling GitHub Pages (dashboard)

*Settings → Pages → Build and deployment*: Source **Deploy from a branch**, branch **main**,
folder **/docs**. The monitor mirrors the JSON the dashboard needs into `docs/data/` on every
run, so the page is fully static — no server, no Node.js.

### Optional Telegram notifications (disabled by default)

Create a bot with [@BotFather](https://t.me/BotFather), then add repository secrets
`TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (*Settings → Secrets and variables → Actions*).
When both are present the digest is also sent to Telegram; when absent, nothing happens.

## GitHub issue digests

When a run discovers **new** jobs scoring **≥ 65** (configurable via
`scoring.digest_min_score`), it opens **one** issue per run titled like
`[New Jobs] 6 strong matches found — 2026-07-12`, labeled `job-alert` + `new-jobs`, containing
a table of company / title / location / score / sponsorship / key reason / apply link.
Announcement state is stored on each job record (`announced`) inside `data/active_jobs.json`,
so a job is never announced twice. Issue-creation failures are logged and never fail the run.

## Troubleshooting broken sources

1. Check `data/source_health.json` (also surfaced in ACTIVE_JOBS.md and the dashboard):
   `error_category` tells you whether it's network, blocked, parsing, config, or a changed
   page structure; `consecutive_failures` shows how long it's been broken.
2. Reproduce locally: `python -m job_monitor validate-sources --company <Name>` or
   `python -m job_monitor --company <Name> --dry-run -v`.
3. `structure_changed` usually means the ATS moved (e.g. company left Greenhouse) — re-discover
   the source and update `companies.yaml`.
4. `blocked` means the site refuses automated clients. Do **not** work around CAPTCHAs, logins
   or robots restrictions — mark the company `unresolved` instead.
5. Jobs from a failing source are intentionally kept (not archived) until the source recovers.

## Data schema (`data/active_jobs.json`)

Each job record:

| Field | Meaning |
| --- | --- |
| `job_id` | stable ID: `<company-slug>-<source_job_id>`, else deterministic hash of company/title/location/URL |
| `source_job_id` | ATS's own requisition/posting ID |
| `company`, `title`, `location`, `country`, `workplace_type`, `department`, `employment_type` | normalized posting facts |
| `description`, `requirements` | plain-text posting body (HTML stripped) |
| `application_url`, `source_url`, `source_type` | where to apply / where it was found / adapter kind |
| `date_posted` | ISO date if the source provides one |
| `first_seen`, `last_seen`, `status`, `consecutive_missing` | lifecycle across runs (`active`/`closed`) |
| `graduation_match` | `compatible_2027` / `compatible_2026` / `unspecified` / `incompatible_<year>` / `future_<year>` |
| `role_match_score` | 0–100 role+skills subscore |
| `sponsorship_classification` | `likely_supported` / `possibly_supported` / `unclear` / `likely_not_supported` / `ineligible` |
| `sponsorship_evidence` | exact sentence/passage from the posting that drove the classification |
| `international_student_risk_flags` | matched restrictive phrases (clearance, ITAR, citizenship, …) |
| `overall_score`, `score_explanation` | 0–100 score and the per-component breakdown |
| `matched_keywords`, `excluded_keywords` | filter terms that hit |
| `disqualified`, `disqualify_reason` | hard-disqualifier flag (kept in dataset, hidden from recommendations) |
| `announced` | already included in a digest issue |

`data/source_health.json` rows: `company`, `source_type`, `last_attempt`, `last_success`,
`status`, `jobs_fetched`, `error_category`, `error_message`, `consecutive_failures`.

## Testing & development

```bash
make test        # pytest, fully offline (fixtures under tests/fixtures/)
make lint        # ruff check + format check
make format      # auto-format
pre-commit install   # optional git hooks (ruff + hygiene)
```

The suite covers adapter parsing/normalization for every adapter, dedup and state
preservation (including "description edited ≠ new job" and archiving after N missing runs),
title filtering (senior exclusion, new-grad inclusion, "2026" not auto-rejected), sponsorship
classification (positive/negative/ambiguous/ineligible + evidence), scoring and bands,
Markdown generation/escaping, JSON/CSV round-trips, and the GitHub workflow configuration.

## Company support

Status from live validation on **2026-07-12** (run from a non-US network; re-check any time
with `python -m job_monitor validate-sources`).

| Company | Adapter | Status | Last validation | Notes |
| --- | --- | --- | --- | --- |
| Microsoft | json (GCS API) | ⚠️ pending | unreachable from non-US validation network | expected to work from US GitHub runners — confirm via first Actions run |
| Amazon (incl. AWS) | json (amazon.jobs) | ✅ working | 2026-07-12 | strict `base_query`; broad queries + title gate |
| NVIDIA | workday | ✅ working | 2026-07-12 | ~2000 US postings |
| Qualcomm | unresolved | ❌ | 2026-07-12 | Eightfold API 403 |
| Google | unresolved | ❌ | 2026-07-12 | public careers API removed (404) |
| Meta | unresolved | ❌ | — | authenticated GraphQL only |
| Apple | unresolved | ❌ | — | CSRF-gated search API |
| Cisco | unresolved | ❌ | 2026-07-12 | moved to JS-rendered Phenom portal |
| Uber | json | ✅ working | 2026-07-12 | |
| Databricks | greenhouse | ✅ working | 2026-07-12 | 786 postings |
| Snowflake | unresolved | ❌ | 2026-07-12 | Eightfold "tenant not identified" |
| Bloomberg | unresolved | ❌ | 2026-07-12 | no public API |
| Stripe | greenhouse | ✅ working | 2026-07-12 | 511 postings |
| MongoDB | greenhouse | ✅ working | 2026-07-12 | 387 postings |
| Confluent | unresolved | ❌ | 2026-07-12 | old Greenhouse board 404s |
| Cloudflare | greenhouse | ✅ working | 2026-07-12 | 249 postings |
| Oracle | json (HCM API) | ✅ working | 2026-07-12 | |
| Salesforce | unresolved | ❌ | 2026-07-12 | api/jobs 404 |
| Adobe | workday | ✅ working | 2026-07-12 | 605 postings |
| ServiceNow | json (SmartRecruiters) | ✅ working | 2026-07-12 | 418 postings |
| SAP | unresolved | ❌ | — | SuccessFactors, no public API |
| Workday | workday | ✅ working | 2026-07-12 | 174 postings |
| LinkedIn | unresolved | ❌ | — | automated access disallowed |
| Intuit | unresolved | ❌ | — | Phenom-hosted |
| AMD | unresolved | ❌ | 2026-07-12 | Phenom-hosted |
| Intel | workday | ✅ working | 2026-07-12 | 612 postings |
| Broadcom | workday | ✅ working | 2026-07-12 | 273 postings |
| Marvell | workday | ✅ working | 2026-07-12 | 582 postings |
| Micron | workday | ✅ working | 2026-07-12 | ~2700 postings |
| Applied Materials | workday | ✅ working | 2026-07-12 | ~1800 postings |
| Lam Research | unresolved | ❌ | 2026-07-12 | Eightfold API 403 |
| KLA | workday | ✅ working | 2026-07-12 | 891 postings |
| ASML | unresolved | ❌ | 2026-07-12 | custom portal |
| Synopsys | unresolved | ❌ | 2026-07-12 | Eightfold API restricted |
| Cadence | workday | ✅ working | 2026-07-12 | 562 postings |
| TSMC | unresolved | ❌ | — | custom portal |
| Optiver | greenhouse | ✅ working | 2026-07-12 | US board `optiverus` |
| IMC | greenhouse | ✅ working | 2026-07-12 | 157 postings |
| DRW | greenhouse | ✅ working | 2026-07-12 | board `drweng` |
| Hudson River Trading | greenhouse | ✅ working | 2026-07-12 | board `wehrtyou` |
| Two Sigma | unresolved | ❌ | 2026-07-12 | Avature, JS-rendered |
| Citadel | unresolved | ❌ | 2026-07-12 | blocks automated clients (403) |
| Jane Street | json | ✅ working | 2026-07-12 | public jobs feed |
| Goldman Sachs | unresolved | ❌ | 2026-07-12 | private API |
| BlackRock | unresolved | ❌ | — | Phenom-hosted |
| Morgan Stanley | unresolved | ❌ | 2026-07-12 | Eightfold API 403 |
| Visa | unresolved | ❌ | 2026-07-12 | SmartRecruiters board is not the main feed |
| Mastercard | workday | ✅ working | 2026-07-12 | 532 postings |
| PayPal | unresolved | ❌ | 2026-07-12 | Eightfold API 403 |

Unresolved ≠ impossible: several (Cisco, Two Sigma, Intuit, BlackRock) could be revisited
with the optional Playwright adapter; others need a source that doesn't exist publicly today.
The monitor never bypasses CAPTCHAs, logins, robots restrictions or rate limits.
