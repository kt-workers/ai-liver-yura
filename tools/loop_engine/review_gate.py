"""Trusted-review result gate without provider or credential ownership."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReviewGateStatus(str, Enum):
    PASS = "PASS"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    ESCALATE = "ESCALATE"
    NOT_RUN = "NOT_RUN"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class ReviewEvidence:
    reviewed_head_sha: str
    verdict: str
    blocking_count: int


def evaluate_exact_head(
    expected_head_sha: str, evidence: ReviewEvidence | None
) -> ReviewGateStatus:
    if evidence is None:
        return ReviewGateStatus.NOT_RUN
    if evidence.reviewed_head_sha != expected_head_sha:
        return ReviewGateStatus.STALE
    if evidence.verdict == "PASS" and evidence.blocking_count == 0:
        return ReviewGateStatus.PASS
    if evidence.verdict == "REQUEST_CHANGES":
        return ReviewGateStatus.REQUEST_CHANGES
    if evidence.verdict == "ESCALATE":
        return ReviewGateStatus.ESCALATE
    return ReviewGateStatus.NOT_RUN
