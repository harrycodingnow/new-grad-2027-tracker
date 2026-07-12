"""Human-reviewable persistence: JSON as source of truth, CSV alongside."""

from __future__ import annotations

import csv
import dataclasses
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from .models import Job, SourceHealth

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DOCS_DATA_DIR = ROOT / "docs" / "data"

_CSV_COLUMNS = [f.name for f in dataclasses.fields(Job)]


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_jobs(path: Path) -> list[Job]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    return [Job.from_dict(item) for item in payload.get("jobs", [])]


def load_health(path: Path) -> dict[str, SourceHealth]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        payload = json.load(fh)
    return {h["company"]: SourceHealth.from_dict(h) for h in payload.get("sources", [])}


def save_jobs(path: Path, jobs: list[Job]) -> None:
    payload = {
        "generated_at": _now_iso(),
        "count": len(jobs),
        "jobs": [job.to_dict() for job in jobs],
    }
    _write_json(path, payload)


def save_jobs_csv(path: Path, jobs: list[Job]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_COLUMNS)
        writer.writeheader()
        for job in jobs:
            row = job.to_dict()
            for key, value in row.items():
                if isinstance(value, list):
                    row[key] = "; ".join(str(v) for v in value)
            writer.writerow(row)


def save_health(path: Path, health: list[SourceHealth]) -> None:
    payload = {
        "generated_at": _now_iso(),
        "sources": [h.to_dict() for h in sorted(health, key=lambda h: h.company.lower())],
    }
    _write_json(path, payload)


def mirror_to_docs(data_dir: Path = DATA_DIR, docs_dir: Path = DOCS_DATA_DIR) -> None:
    """Copy the JSON the dashboard needs into docs/ for GitHub Pages."""
    docs_dir.mkdir(parents=True, exist_ok=True)
    for name in ("active_jobs.json", "new_jobs.json", "source_health.json"):
        src = data_dir / name
        if src.exists():
            shutil.copyfile(src, docs_dir / name)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, sort_keys=False)
        fh.write("\n")
