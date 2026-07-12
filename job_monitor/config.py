"""Load and validate the YAML configuration files in config/."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

VALID_SOURCE_TYPES = {
    "greenhouse",
    "lever",
    "ashby",
    "workday",
    "json",
    "jsonld",
    "html",
    "playwright",
    "unresolved",
}


@dataclass
class CompanyConfig:
    name: str
    enabled: bool = True
    priority: int = 3
    careers_url: str = ""
    source_type: str = "unresolved"
    source_identifier: str = ""
    locations: list[str] = field(default_factory=list)
    notes: str = ""
    adapter_config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CompanyConfig:
        cfg = cls(
            name=str(data.get("name", "")).strip(),
            enabled=bool(data.get("enabled", True)),
            priority=int(data.get("priority", 3)),
            careers_url=str(data.get("careers_url", "") or ""),
            source_type=str(data.get("source_type", "unresolved") or "unresolved"),
            source_identifier=str(data.get("source_identifier", "") or ""),
            locations=list(data.get("locations") or []),
            notes=str(data.get("notes", "") or ""),
            adapter_config=dict(data.get("adapter_config") or {}),
        )
        if not cfg.name:
            raise ValueError("company entry missing 'name'")
        if cfg.source_type not in VALID_SOURCE_TYPES:
            raise ValueError(f"{cfg.name}: unknown source_type {cfg.source_type!r}")
        return cfg


@dataclass
class Config:
    profile: dict[str, Any]
    filters: dict[str, Any]
    companies: list[CompanyConfig]

    @property
    def weights(self) -> dict[str, int]:
        return dict(self.filters.get("scoring", {}).get("weights", {}))

    @property
    def thresholds(self) -> dict[str, int]:
        return dict(self.filters.get("scoring", {}).get("thresholds", {}))

    @property
    def digest_min_score(self) -> int:
        return int(self.filters.get("scoring", {}).get("digest_min_score", 65))

    @property
    def archive_after_missing_runs(self) -> int:
        return int(self.filters.get("lifecycle", {}).get("archive_after_missing_runs", 3))


def _load_yaml(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_config(config_dir: Path | None = None) -> Config:
    base = config_dir or CONFIG_DIR
    profile = _load_yaml(base / "profile.yaml") or {}
    filters = _load_yaml(base / "filters.yaml") or {}
    raw = _load_yaml(base / "companies.yaml") or {}
    companies = [CompanyConfig.from_dict(c) for c in raw.get("companies", [])]
    names = [c.name for c in companies]
    if len(names) != len(set(names)):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise ValueError(f"duplicate company names in companies.yaml: {dupes}")
    return Config(profile=profile, filters=filters, companies=companies)
