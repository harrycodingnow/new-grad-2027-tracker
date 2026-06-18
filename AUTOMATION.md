# Automation (GitHub Actions)

`README.md` is regenerated **daily** by a GitHub Actions workflow
(`.github/workflows/update-tracker.yml`) that runs `update_tracker.py` and
commits changes back to the repo. **No secrets or external services to set up** —
the workflow uses the built-in `GITHUB_TOKEN`.

## What the job does

1. Loads hand-curated roles from `roles.json` (e.g., Ellipsis Labs).
2. Fetches public lists (`vanshb03/New-Grad-2027`, `SimplifyJobs/New-Grad-Positions`).
3. Keeps **only** roles that are **strictly 2027** *and* **SWE / AI-ML / Full-Stack**
   *and* international-student-friendly (drops 🛂 no-sponsorship, 🇺🇸 citizen-only, 🔒 closed).
4. Regenerates the table in `README.md` and commits it **only when content changed**
   (the "Last updated" timestamp alone never triggers a commit).

## Schedule

- Runs at **13:00 UTC daily** (`0 13 * * *` → 21:00 UTC+8).
- Edit the `cron:` line in `.github/workflows/update-tracker.yml` to retime
  (schedules are always UTC). Use <https://crontab.guru> to build expressions.

## Run it now / manually

- **Actions tab → "Update 2027 tracker" → Run workflow** (enabled via `workflow_dispatch`).
- First scheduled/manual run usually makes **no commit** because the current README
  already matches — that's expected. Commits appear only when roles change.

> Note: commits made by `GITHUB_TOKEN` intentionally do **not** trigger other
> workflows, so there's no risk of an update loop.

## Run locally (no token needed)

```bash
pip install -r requirements.txt
DRY_RUN=1 python update_tracker.py   # writes README.md locally, no commit
```

## Add a role by hand

Edit `roles.json`, then commit/push. The next run merges it with the
auto-fetched roles (de-duplicated by URL).

## Cost

Deterministic — **no AI/LLM calls**, so no Copilot costs. GitHub Actions minutes
are **free for public repositories**.
