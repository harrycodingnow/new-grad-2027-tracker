"""Persistence round-trip and end-to-end runner state tests (offline)."""

from __future__ import annotations

import csv
import json

from job_monitor import store
from job_monitor.models import Job, SourceHealth


def test_jobs_json_roundtrip(tmp_path):
    jobs = [
        Job(
            job_id="a-1",
            company="A",
            title="Software Engineer, New Grad",
            matched_keywords=["python"],
            first_seen="2026-07-12T00:00:00Z",
        ),
    ]
    path = tmp_path / "active_jobs.json"
    store.save_jobs(path, jobs)
    loaded = store.load_jobs(path)
    assert loaded[0].to_dict() == jobs[0].to_dict()
    payload = json.loads(path.read_text())
    assert payload["count"] == 1
    assert "generated_at" in payload


def test_csv_output(tmp_path):
    jobs = [Job(job_id="a-1", company="A", title="T", matched_keywords=["x", "y"])]
    path = tmp_path / "active_jobs.csv"
    store.save_jobs_csv(path, jobs)
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["job_id"] == "a-1"
    assert rows[0]["matched_keywords"] == "x; y"


def test_health_roundtrip(tmp_path):
    health = [SourceHealth(company="A", source_type="greenhouse", status="ok", jobs_fetched=3)]
    path = tmp_path / "source_health.json"
    store.save_health(path, health)
    loaded = store.load_health(path)
    assert loaded["A"].jobs_fetched == 3


def test_mirror_to_docs(tmp_path):
    data_dir = tmp_path / "data"
    docs_dir = tmp_path / "docs" / "data"
    store.save_jobs(data_dir / "active_jobs.json", [])
    store.save_jobs(data_dir / "new_jobs.json", [])
    store.save_health(data_dir / "source_health.json", [])
    store.mirror_to_docs(data_dir, docs_dir)
    assert (docs_dir / "active_jobs.json").exists()
    assert (docs_dir / "source_health.json").exists()
