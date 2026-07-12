"""Shared fixtures. All tests run offline: the fake client never hits the network."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from job_monitor.config import CompanyConfig, load_config

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    path = FIXTURES / name
    if name.endswith(".json"):
        return json.loads(path.read_text(encoding="utf-8"))
    return path.read_text(encoding="utf-8")


@dataclass
class FakeResponse:
    text: str = ""
    payload: Any = None
    url: str = "https://example.test/"

    def json(self) -> Any:
        if self.payload is not None:
            return self.payload
        return json.loads(self.text)


@dataclass
class FakeClient:
    """Duck-typed stand-in for job_monitor.http.HttpClient."""

    routes: dict[str, Any] = field(default_factory=dict)
    default: Any = None
    calls: list[str] = field(default_factory=list)

    def _lookup(self, url: str) -> Any:
        self.calls.append(url)
        for key, value in self.routes.items():
            if key in url:
                return value
        if self.default is not None:
            return self.default
        raise AssertionError(f"unexpected URL in offline test: {url}")

    def request(self, method: str, url: str, **kwargs: Any) -> FakeResponse:
        value = self._lookup(url)
        if isinstance(value, FakeResponse):
            return value
        if isinstance(value, str):
            return FakeResponse(text=value, url=url)
        return FakeResponse(payload=value, url=url)

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        return self.request("POST", url, **kwargs)

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self.get(url, **kwargs).json()

    def post_json(self, url: str, **kwargs: Any) -> Any:
        return self.post(url, **kwargs).json()


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def filters(config):
    return config.filters


@pytest.fixture
def profile(config):
    return config.profile


def make_company(**overrides: Any) -> CompanyConfig:
    base: dict[str, Any] = {
        "name": "ExampleCorp",
        "enabled": True,
        "priority": 2,
        "careers_url": "https://example.test/careers",
        "source_type": "greenhouse",
        "source_identifier": "examplecorp",
        "locations": [
            "United States",
            "New York",
            "Austin",
            "Seattle",
            "Chicago",
            "Raleigh",
            "Remote - US",
            "Boston",
            "Arlington",
            "San Francisco",
        ],
        "notes": "",
    }
    base.update(overrides)
    return CompanyConfig.from_dict(base)
