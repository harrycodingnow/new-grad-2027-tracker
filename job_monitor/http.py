"""HTTP client with timeouts, retries, per-domain rate limiting and a clear UA."""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlparse

import requests

from . import USER_AGENT
from .errors import BlockedError, NetworkError

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 25  # seconds
MAX_RETRIES = 3
BACKOFF_BASE = 1.5  # seconds; grows exponentially
MIN_DOMAIN_INTERVAL = 1.0  # seconds between requests to the same domain

_BLOCKED_STATUS = {401, 403, 407, 451}
_RETRY_STATUS = {429, 500, 502, 503, 504}


class HttpClient:
    """Small wrapper around requests.Session used by all adapters."""

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        min_domain_interval: float = MIN_DOMAIN_INTERVAL,
    ):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.session.headers["Accept-Language"] = "en-US,en;q=0.9"
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_domain_interval = min_domain_interval
        self._last_request_at: dict[str, float] = {}

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        data: Any = None,
    ) -> requests.Response:
        """Perform a request with rate limiting and exponential retry.

        Raises NetworkError / BlockedError on failure.
        """
        domain = urlparse(url).netloc
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle(domain)
            try:
                resp = self.session.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    data=data,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                log.warning(
                    "request error (%s/%s) %s %s: %s", attempt, self.max_retries, method, url, exc
                )
                self._sleep(attempt)
                continue

            if resp.status_code in _BLOCKED_STATUS:
                raise BlockedError(
                    f"HTTP {resp.status_code} for {url} (access restricted; not bypassing)"
                )
            if resp.status_code in _RETRY_STATUS:
                last_error = NetworkError(f"HTTP {resp.status_code} for {url}")
                retry_after = resp.headers.get("Retry-After")
                log.warning(
                    "retryable status %s (%s/%s) for %s",
                    resp.status_code,
                    attempt,
                    self.max_retries,
                    url,
                )
                self._sleep(attempt, retry_after)
                continue
            if resp.status_code >= 400:
                raise NetworkError(f"HTTP {resp.status_code} for {url}")
            return resp

        raise NetworkError(
            f"request failed after {self.max_retries} attempts: {url} ({last_error})"
        )

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", url, **kwargs)

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return _decode_json(self.get(url, **kwargs))

    def post_json(self, url: str, **kwargs: Any) -> Any:
        return _decode_json(self.post(url, **kwargs))

    def _throttle(self, domain: str) -> None:
        last = self._last_request_at.get(domain)
        if last is not None:
            wait = self.min_domain_interval - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_request_at[domain] = time.monotonic()

    def _sleep(self, attempt: int, retry_after: str | None = None) -> None:
        delay = BACKOFF_BASE * (2 ** (attempt - 1))
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass
        time.sleep(min(delay, 30))


def _decode_json(resp: requests.Response) -> Any:
    from .errors import ParseError

    try:
        return resp.json()
    except ValueError as exc:
        snippet = resp.text[:200].replace("\n", " ")
        raise ParseError(f"expected JSON from {resp.url}, got: {snippet!r}") from exc
