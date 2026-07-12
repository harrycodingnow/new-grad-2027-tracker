"""Sanity checks on repo configuration and GitHub Actions workflows."""

from __future__ import annotations

from pathlib import Path

import yaml

from job_monitor.config import VALID_SOURCE_TYPES, load_config

ROOT = Path(__file__).resolve().parent.parent


def _load_workflow(name: str) -> dict:
    with open(ROOT / ".github" / "workflows" / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_companies_config_valid():
    config = load_config()
    assert len(config.companies) >= 40
    for company in config.companies:
        assert company.source_type in VALID_SOURCE_TYPES
        if company.enabled and company.source_type != "unresolved":
            assert company.source_identifier or company.adapter_config, company.name
        if company.source_type == "unresolved":
            assert not company.enabled, f"{company.name}: unresolved sources must be disabled"
            assert "UNRESOLVED" in company.notes.upper(), company.name


def test_filters_config_shape():
    config = load_config()
    tf = config.filters["title_filters"]
    assert "new grad" in tf["include_level"]
    assert "senior" in tf["exclude"]
    weights = config.weights
    assert sum(weights.values()) == 100
    assert config.digest_min_score == config.thresholds["strong"]


def test_monitor_workflow():
    wf = _load_workflow("monitor.yml")
    on = wf.get("on") or wf.get(True)  # YAML parses bare `on` as boolean True
    schedules = [entry["cron"] for entry in on["schedule"]]
    assert len(schedules) == 4  # four times a day
    for cron in schedules:
        minute = cron.split()[0]
        assert minute not in ("0", "00"), "avoid scheduling exactly on the hour"
    assert "workflow_dispatch" in on
    assert wf["permissions"] == {"contents": "write", "issues": "write"}
    assert "concurrency" in wf
    steps = wf["jobs"]["monitor"]["steps"]
    text = str(steps)
    assert "3.12" in text
    assert "requirements.lock" in text
    assert "pytest" in text
    assert "[skip ci]" in text
    assert any(s.get("if") == "failure()" for s in steps)


def test_tests_workflow():
    wf = _load_workflow("tests.yml")
    on = wf.get("on") or wf.get(True)
    assert "push" in on and "pull_request" in on
    assert wf["permissions"] == {"contents": "read"}
