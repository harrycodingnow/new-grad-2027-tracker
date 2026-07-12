"""International-student / work-authorization classification.

Deterministic phrase matching over the full posting text. The classification
is an automated screening aid — NOT legal advice and NOT a guarantee of
eligibility. Absence of sponsorship language yields "unclear", never
"likely_supported". A company's general sponsorship track record is
deliberately ignored: only this posting's text counts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .textutil import find_evidence, truncate


@dataclass
class SponsorshipResult:
    classification: str = "unclear"
    evidence: str = ""
    risk_flags: list[str] = field(default_factory=list)


def classify_sponsorship(text: str, filters: dict[str, Any]) -> SponsorshipResult:
    cfg = filters.get("sponsorship", {})
    lowered = text.lower()

    def hits(key: str) -> list[str]:
        return [p for p in cfg.get(key, []) if p.lower() in lowered]

    ineligible = hits("ineligible")
    negative = hits("negative")
    positive = hits("positive")
    weak_positive = hits("weak_positive")

    result = SponsorshipResult()
    result.risk_flags = ineligible + negative

    # Most restrictive signal wins; positive language elsewhere in the posting
    # does not override an explicit restriction.
    if ineligible:
        result.classification = "ineligible"
        result.evidence = _evidence(text, ineligible)
    elif negative:
        result.classification = "likely_not_supported"
        result.evidence = _evidence(text, negative)
    elif positive:
        result.classification = "likely_supported"
        result.evidence = _evidence(text, positive)
    elif weak_positive:
        result.classification = "possibly_supported"
        result.evidence = _evidence(text, weak_positive)
    else:
        result.classification = "unclear"
        result.evidence = ""
    return result


def _evidence(text: str, phrases: list[str]) -> str:
    for phrase in phrases:
        passage = find_evidence(text, phrase)
        if passage:
            return truncate(passage, 400)
    return truncate(phrases[0], 400)
