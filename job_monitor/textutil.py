"""Text helpers: HTML stripping, evidence extraction, Markdown escaping, URLs."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gh_src",
    "lever-source",
    "source",
    "src",
    "ref",
    "referrer",
}


def strip_html(html: str) -> str:
    """Convert an HTML fragment to plain text with normalized whitespace."""
    if not html:
        return ""
    if "<" not in html:
        return normalize_ws(html)
    soup = BeautifulSoup(html, "html.parser")
    return normalize_ws(soup.get_text(" "))


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def canonical_url(url: str) -> str:
    """Normalize an application URL for deduplication."""
    if not url:
        return ""
    parts = urlparse(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in _TRACKING_PARAMS]
    path = parts.path.rstrip("/")
    return urlunparse(
        (parts.scheme.lower() or "https", parts.netloc.lower(), path, "", urlencode(query), "")
    )


def find_evidence(text: str, phrase: str, context: int = 160) -> str:
    """Return the sentence (or a short passage) around the first hit of `phrase`."""
    lowered = text.lower()
    idx = lowered.find(phrase.lower())
    if idx < 0:
        return ""
    # Expand to sentence boundaries where possible.
    start = max(text.rfind(".", 0, idx), text.rfind("\n", 0, idx), text.rfind("•", 0, idx)) + 1
    end_candidates = [
        p
        for p in (text.find(".", idx + len(phrase)), text.find("\n", idx + len(phrase)))
        if p != -1
    ]
    end = min(end_candidates) + 1 if end_candidates else len(text)
    if end - start > 2 * context + len(phrase):
        start = max(idx - context, start)
        end = min(idx + len(phrase) + context, end)
    return normalize_ws(text[start:end])


def md_escape(text: str) -> str:
    """Escape characters that would break a Markdown table cell."""
    return (text or "").replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ").strip()


def truncate(text: str, limit: int = 240) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def word_boundary_pattern(term: str) -> re.Pattern[str]:
    """Compile a case-insensitive word-boundary regex for a configured term."""
    escaped = re.escape(term.strip())
    # \b does not work adjacent to non-word chars (e.g. "c#"), fall back to lookarounds.
    return re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)
