"""Common adapter interface."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable

from ..config import CompanyConfig
from ..http import HttpClient
from ..models import Job

# Predicate deciding whether a title is promising enough to fetch details for.
TitlePrefilter = Callable[[str], bool]

log = logging.getLogger(__name__)

# Safety cap on per-company detail-page fetches for sources whose listing
# endpoint does not include descriptions.
DEFAULT_DETAIL_FETCH_CAP = 40


class Adapter(ABC):
    """Fetches raw postings for one company and maps them to the Job model."""

    source_type: str = ""

    def __init__(
        self,
        company: CompanyConfig,
        client: HttpClient,
        title_prefilter: TitlePrefilter | None = None,
    ):
        self.company = company
        self.client = client
        self.title_prefilter = title_prefilter or (lambda _title: True)
        self.detail_fetch_cap = int(
            company.adapter_config.get("detail_fetch_cap", DEFAULT_DETAIL_FETCH_CAP)
        )

    @abstractmethod
    def fetch(self) -> list[Job]:
        """Return normalized jobs. Raise a SourceError subclass on failure."""

    def new_job(self, **kwargs: object) -> Job:
        job = Job(**kwargs)  # type: ignore[arg-type]
        job.company = self.company.name
        job.source_type = self.source_type
        return job
