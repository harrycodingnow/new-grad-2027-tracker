"""Source adapters. Each adapter fetches one company and returns list[Job]."""

from __future__ import annotations

from ..config import CompanyConfig
from ..errors import UnsupportedSourceError
from ..http import HttpClient
from .ashby import AshbyAdapter
from .base import Adapter, TitlePrefilter
from .greenhouse import GreenhouseAdapter
from .html_page import HtmlAdapter
from .json_endpoint import JsonAdapter
from .jsonld import JsonLdAdapter
from .lever import LeverAdapter
from .playwright_page import PlaywrightAdapter
from .workday import WorkdayAdapter

_ADAPTERS: dict[str, type[Adapter]] = {
    "greenhouse": GreenhouseAdapter,
    "lever": LeverAdapter,
    "ashby": AshbyAdapter,
    "workday": WorkdayAdapter,
    "json": JsonAdapter,
    "jsonld": JsonLdAdapter,
    "html": HtmlAdapter,
    "playwright": PlaywrightAdapter,
}


def build_adapter(
    company: CompanyConfig, client: HttpClient, title_prefilter: TitlePrefilter | None = None
) -> Adapter:
    if company.source_type == "unresolved":
        raise UnsupportedSourceError(
            f"{company.name}: source unresolved — {company.notes or 'no public source discovered'}"
        )
    cls = _ADAPTERS.get(company.source_type)
    if cls is None:
        raise UnsupportedSourceError(f"{company.name}: unknown source_type {company.source_type!r}")
    return cls(company, client, title_prefilter=title_prefilter)


__all__ = ["Adapter", "build_adapter"]
