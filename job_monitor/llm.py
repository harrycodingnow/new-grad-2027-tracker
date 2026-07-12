"""Optional LLM-classifier interface (disabled by default).

The default pipeline is fully deterministic and needs no API keys. If you
want an LLM second opinion on sponsorship language or role fit, implement
`LLMClassifier` and register it in `runner.Runner` via `llm_classifier=`.

Contract: the classifier may only REFINE `unclear` / `possibly_supported`
classifications; deterministic negative/ineligible evidence always wins.
"""

from __future__ import annotations

from typing import Protocol

from .models import Job


class LLMClassifier(Protocol):
    """Interface for an optional LLM-based refinement pass."""

    def refine(self, job: Job) -> Job:
        """Return the job, possibly with refined classification fields."""
        ...


def get_default_classifier() -> LLMClassifier | None:
    """No LLM by default. Return an implementation here to enable one."""
    return None
