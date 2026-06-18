# Deploying the daily updater to Railway

This repo updates `README.md` once a day via a **Railway cron job** that runs
`update_tracker.py` and commits changes back to GitHub using the Contents API.
No long-running server, no git clone on the box — it runs and exits.

## What the job does

1. Loads hand-curated roles from `roles.json` (e.g., Ellipsis Labs).
2. Fetches public lists (`vanshb03/New-Grad-2027`, `SimplifyJobs/New-Grad-Positions`).
3. Keeps **only** roles that are **strictly 2027** *and* **SWE / AI-ML / Full-Stack**
   *and* international-student-friendly (drops 🛂 no-sponsorship, 🇺🇸 citizen-only, 🔒 closed).
4. Regenerates the table in `README.md` and commits it (only if it actually changed).

## 1. Create a GitHub token (so the job can commit)

Create a **fine-grained personal access token** scoped to this repo:

- GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate new token
- Repository access: **Only select repositories → `new-grad-2027-tracker`**
- Permissions: **Repository → Contents → Read and write**
- Copy the token (starts with `github_pat_…`).

## 2. Create the Railway service

Using the Railway dashboard:

1. **New Project → Deploy from GitHub repo** → pick `new-grad-2027-tracker`.
2. Railway reads `railway.json` automatically:
   - Builder: `RAILPACK` (auto-detects Python from `requirements.txt`)
   - Start command: `python update_tracker.py`
   - Cron schedule: `0 13 * * *` (13:00 UTC = 21:00 UTC+8)
   - Restart policy: `NEVER` (so a finished run doesn't loop)
3. **Variables** → add:
   | Variable | Value |
   | --- | --- |
   | `GH_TOKEN` | your `github_pat_…` token |
   | `GH_REPO` | `harrycodingnow/new-grad-2027-tracker` *(optional; this is the default)* |
   | `GH_BRANCH` | `main` *(optional; default)* |

> If you prefer the CLI: `railway init` → `railway up` → `railway variables --set GH_TOKEN=...`.
> The cron schedule can also be set/edited under **Service → Settings → Cron Schedule**.

## 3. Verify

- Trigger a manual run from Railway (**Deployments → Redeploy**) or wait for the schedule.
- Check the deploy logs: you should see `Resolved N strictly-2027 ... role(s).`
- A new commit `chore: daily 2027 tracker update [skip ci]` appears only when the
  table content changes.

## Run it locally first (no token needed)

```bash
pip install -r requirements.txt
DRY_RUN=1 python update_tracker.py   # writes README.md locally, no commit
```

## Notes / cost

- Railway cron has a **5-minute minimum** interval; daily is well within limits.
- Schedules run in **UTC**. Change `cronSchedule` in `railway.json` to retime.
- This task is deterministic — it does **not** call any AI model, so there are no
  Copilot/LLM costs. Railway only bills the few seconds of compute per day.
- To hand-add a verified role, edit `roles.json` and push; the next run merges it.
