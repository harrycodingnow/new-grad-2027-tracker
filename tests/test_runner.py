"""End-to-end runner test against fixture data — fully offline."""

from __future__ import annotations

import json

from job_monitor.config import Config, load_config
from job_monitor.runner import Runner

from .conftest import FakeClient, load_fixture, make_company


def offline_runner(tmp_path, client) -> Runner:
    real = load_config()
    config = Config(
        profile=real.profile,
        filters=real.filters,
        companies=[make_company()],
    )
    return Runner(config=config, data_dir=tmp_path / "data", client=client)


def test_full_run_writes_all_outputs(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    client = FakeClient(routes={"boards-api.greenhouse.io": load_fixture("greenhouse.json")})
    runner = offline_runner(tmp_path, client)
    # Redirect markdown/docs outputs into tmp so the test never touches the repo.
    data_dir = tmp_path / "data"
    summary = runner.run()

    assert summary["companies_checked"] == 1
    # 5 fixture jobs: senior excluded, London filtered out => 3 tracked.
    assert summary["active_jobs"] == 3
    assert summary["new_jobs"] == 3

    active = json.loads((data_dir / "active_jobs.json").read_text())
    titles = {j["title"] for j in active["jobs"]}
    assert "Senior Software Engineer, Platform" not in titles
    assert "Data Engineer, University Graduate" not in titles  # London
    assert "Software Engineer, New Grad (2027)" in titles

    by_title = {j["title"]: j for j in active["jobs"]}
    sponsored = by_title["Software Engineer, New Grad (2027)"]
    assert sponsored["sponsorship_classification"] == "likely_supported"
    assert "sponsorship available" in sponsored["sponsorship_evidence"].lower()
    assert not sponsored["disqualified"]

    clearance = by_title["Defense Systems Software Engineer I"]
    assert clearance["sponsorship_classification"] == "ineligible"
    assert clearance["disqualified"]
    assert clearance["international_student_risk_flags"]

    no_sponsor = by_title["Machine Learning Engineer, Early Career"]
    assert no_sponsor["sponsorship_classification"] == "likely_not_supported"
    assert no_sponsor["disqualified"]

    assert (data_dir / "active_jobs.csv").exists()
    assert (data_dir / "new_jobs.json").exists()
    assert (data_dir / "archived_jobs.json").exists()
    health = json.loads((data_dir / "source_health.json").read_text())
    assert health["sources"][0]["status"] == "ok"
    assert health["sources"][0]["jobs_fetched"] == 5

    md = (data_dir.parent / "ACTIVE_JOBS.md").read_text()
    assert "Software Engineer, New Grad (2027)" in md

    # Second run: nothing new, first_seen preserved.
    runner2 = offline_runner(tmp_path, client)
    summary2 = runner2.run()
    assert summary2["new_jobs"] == 0
    active2 = json.loads((data_dir / "active_jobs.json").read_text())
    first_seen = {j["job_id"]: j["first_seen"] for j in active["jobs"]}
    for j in active2["jobs"]:
        assert j["first_seen"] == first_seen[j["job_id"]]


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    client = FakeClient(routes={"boards-api.greenhouse.io": load_fixture("greenhouse.json")})
    runner = offline_runner(tmp_path, client)
    summary = runner.run(dry_run=True)
    assert summary["dry_run"] is True
    assert not (tmp_path / "data" / "active_jobs.json").exists()


def test_failed_source_recorded_not_fatal(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    class ExplodingClient(FakeClient):
        def get_json(self, url, **kwargs):
            from job_monitor.errors import NetworkError

            raise NetworkError("connection refused")

    runner = offline_runner(tmp_path, ExplodingClient())
    summary = runner.run()
    assert summary["companies_failed"] == 1
    health = json.loads((tmp_path / "data" / "source_health.json").read_text())
    row = health["sources"][0]
    assert row["status"] == "failed"
    assert row["error_category"] == "network_error"
    assert row["consecutive_failures"] == 1
