"""Parsing/normalization tests for every adapter, using recorded fixtures."""

from __future__ import annotations

import pytest

from job_monitor.adapters.ashby import AshbyAdapter
from job_monitor.adapters.eightfold import EightfoldAdapter
from job_monitor.adapters.greenhouse import GreenhouseAdapter
from job_monitor.adapters.html_page import HtmlAdapter
from job_monitor.adapters.json_endpoint import JsonAdapter, dig
from job_monitor.adapters.jsonld import JsonLdAdapter
from job_monitor.adapters.lever import LeverAdapter
from job_monitor.errors import InvalidConfigError, StructureChangedError

from .conftest import FakeClient, load_fixture, make_company


def test_greenhouse_parsing():
    client = FakeClient(routes={"boards-api.greenhouse.io": load_fixture("greenhouse.json")})
    jobs = GreenhouseAdapter(make_company(), client).fetch()
    assert len(jobs) == 5
    job = jobs[0]
    assert job.source_job_id == "4011001"
    assert job.title == "Software Engineer, New Grad (2027)"
    assert job.company == "ExampleCorp"
    assert job.source_type == "greenhouse"
    assert job.location == "New York, NY"
    assert job.date_posted == "2026-06-28"
    assert "Visa sponsorship available" in job.description
    assert "<" not in job.description  # HTML stripped


def test_greenhouse_structure_change():
    client = FakeClient(routes={"boards-api.greenhouse.io": {"unexpected": []}})
    with pytest.raises(StructureChangedError):
        GreenhouseAdapter(make_company(), client).fetch()


def test_lever_parsing():
    client = FakeClient(routes={"api.lever.co": load_fixture("lever.json")})
    company = make_company(source_type="lever", source_identifier="examplecorp")
    jobs = LeverAdapter(company, client).fetch()
    assert len(jobs) == 2
    job = jobs[0]
    assert job.title == "Backend Engineer - New Grad"
    assert job.location == "Austin, TX"
    assert job.employment_type == "Full-time"
    assert job.workplace_type == "hybrid"
    assert job.date_posted == "2026-06-21"
    assert "H-1B sponsorship" in job.description
    assert "2027" in job.requirements


def test_ashby_parsing():
    client = FakeClient(routes={"api.ashbyhq.com": load_fixture("ashby.json")})
    company = make_company(source_type="ashby", source_identifier="examplecorp")
    jobs = AshbyAdapter(company, client).fetch()
    assert len(jobs) == 2  # unlisted job dropped
    job = jobs[0]
    assert job.title == "Full-Stack Engineer (Entry Level)"
    assert "Chicago, IL" in job.location and "New York, NY" in job.location
    assert job.date_posted == "2026-07-05"
    assert "Immigration sponsorship available" in job.description


def test_eightfold_parsing():
    fixture = load_fixture("eightfold.json")
    client = FakeClient(
        routes={
            "api/pcsx/search": fixture["search"],
            "api/pcsx/position_details": fixture["details"],
        }
    )
    company = make_company(
        source_type="eightfold",
        source_identifier="apply.careers.example.com/example.com",
    )

    def new_grad_only(title: str) -> bool:
        return "New Grad" in title

    jobs = EightfoldAdapter(company, client, title_prefilter=new_grad_only).fetch()
    assert len(jobs) == 2
    by_id = {j.source_job_id: j for j in jobs}

    job = by_id["200014796"]
    assert job.title == "Software Engineer, New Grad (2027)"
    assert job.source_type == "eightfold"
    assert job.date_posted == "2026-06-22"
    assert job.workplace_type == "onsite"
    assert job.employment_type == "Full-Time"
    assert job.application_url == "https://apply.careers.example.com/careers/job/1970393556640555"
    assert "Visa sponsorship available" in job.description
    assert "<" not in job.description  # HTML stripped

    # Prefiltered-out title: listed without a detail fetch.
    manager = by_id["200014999"]
    assert manager.date_posted == "2026-06-15"
    assert manager.description == ""
    detail_calls = [u for u in client.calls if "position_details" in u]
    assert len(detail_calls) == 1


def test_eightfold_tenant_error_is_structure_change():
    payload = {"status": "failure", "errorCode": None, "errorMsg": "Tenant not identified"}
    client = FakeClient(routes={"api/pcsx/search": payload})
    company = make_company(
        source_type="eightfold", source_identifier="careers.example.com/example.com"
    )
    with pytest.raises(StructureChangedError):
        EightfoldAdapter(company, client).fetch()


def test_jsonld_parsing():
    client = FakeClient(default=load_fixture("jsonld.html"))
    company = make_company(source_type="jsonld", source_identifier="https://example.test/careers")
    jobs = JsonLdAdapter(company, client).fetch()
    assert len(jobs) == 1  # WebPage node ignored
    job = jobs[0]
    assert job.title == "AI Engineer, University Graduate 2026"
    assert job.source_job_id == "REQ-9001"
    assert job.location == "Boston, MA"
    assert job.country == "US"
    assert job.application_url == "https://example.com/jobs/req-9001"
    assert "Sponsorship considered" in job.description


def test_html_parsing():
    client = FakeClient(default=load_fixture("generic.html"))
    company = make_company(
        source_type="html",
        source_identifier="https://example.test/jobs?offset={offset}",
        adapter_config={
            "row_selector": "tr.job-row",
            "title_selector": "td.title a",
            "location_selector": "td.location",
            "fetch_details": False,
        },
    )
    jobs = HtmlAdapter(company, client).fetch()
    assert len(jobs) == 2
    assert jobs[0].title == "Software Engineer I - Cloud Platform"
    assert jobs[0].application_url == "https://example.test/careers/12345"
    assert jobs[0].location == "Raleigh, NC, United States"


def test_html_selector_mismatch_is_structure_change():
    client = FakeClient(default="<html><body><p>redesigned page</p></body></html>")
    company = make_company(
        source_type="html",
        source_identifier="https://example.test/jobs",
        adapter_config={"row_selector": "tr.job-row", "title_selector": "a"},
    )
    with pytest.raises(StructureChangedError):
        HtmlAdapter(company, client).fetch()


def test_json_adapter_generic_mapping():
    payload = {
        "result": {
            "openings": [
                {
                    "req": "R-1",
                    "name": "Software Engineer (New Grad)",
                    "site": {"city": "Denver"},
                    "posted": "2026-07-01T00:00:00Z",
                    "desc": "<p>Python and SQL. OPT accepted.</p>",
                }
            ]
        }
    }
    client = FakeClient(default=payload)
    company = make_company(
        source_type="json",
        source_identifier="",
        adapter_config={
            "request": {"url": "https://example.test/api/jobs?page={page}"},
            "jobs_path": "result.openings",
            "fields": {
                "source_job_id": "req",
                "title": "name",
                "location": "site.city",
                "description": "desc",
                "date_posted": "posted",
                "url": "https://example.test/apply/{source_job_id}",
            },
        },
    )
    jobs = JsonAdapter(company, client).fetch()
    assert len(jobs) == 1
    job = jobs[0]
    assert job.source_job_id == "R-1"
    assert job.location == "Denver"
    assert job.date_posted == "2026-07-01"
    assert job.application_url == "https://example.test/apply/R-1"
    assert "OPT accepted" in job.description


def test_json_adapter_rejects_missing_config():
    company = make_company(source_type="json", source_identifier="")
    with pytest.raises(InvalidConfigError):
        JsonAdapter(company, FakeClient()).fetch()


def test_dig_paths():
    data = {"a": {"b": [{"c": 1}, {"c": 2}]}, "items": [{"list": [5]}]}
    assert dig(data, "a.b.c") == [1, 2]
    assert dig(data, "items.0.list") == [5]
    assert dig(data, "missing.path") is None
