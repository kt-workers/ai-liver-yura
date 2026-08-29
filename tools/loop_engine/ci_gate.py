"""厳密HEADのCI証拠を判定する。試験可能性のため通信処理は外部から注入する。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CIGateStatus(str, Enum):
    PASS = "PASS"
    YIELD_EXTERNAL = "YIELD_EXTERNAL"
    FAILED = "FAILED"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class CIObservation:
    head_sha: str
    conclusion: str | None


def evaluate_exact_head(expected_head_sha: str, evidence: CIObservation | None) -> CIGateStatus:
    if evidence is None:
        return CIGateStatus.YIELD_EXTERNAL
    if evidence.head_sha != expected_head_sha:
        return CIGateStatus.STALE
    if evidence.conclusion in {None, "queued", "in_progress"}:
        return CIGateStatus.YIELD_EXTERNAL
    return CIGateStatus.PASS if evidence.conclusion == "success" else CIGateStatus.FAILED
