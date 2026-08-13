from __future__ import annotations

from datetime import datetime, timezone

from .models import (
    AgentIdentity,
    CredentialScope,
    FindingSeverity,
    ProviderReviewCandidate,
    ReviewDecision,
    ReviewTarget,
    ReviewVerdict,
)


class ReviewValidationError(RuntimeError):
    pass


def validate_candidate(
    candidate: ProviderReviewCandidate,
    *,
    target: ReviewTarget,
    current_head_sha: str,
    implementer_identity: AgentIdentity,
    reviewer_identity: AgentIdentity,
    context_complete: bool,
) -> ReviewDecision:
    if current_head_sha != target.head_sha:
        raise ReviewValidationError("review target is stale: current PR head changed")
    if candidate.echoed_head_sha and candidate.echoed_head_sha != target.head_sha:
        raise ReviewValidationError("provider echoed a different head SHA")
    if reviewer_identity.agent_id == implementer_identity.agent_id:
        raise ReviewValidationError("reviewer agent identity collides with implementer")
    if reviewer_identity.session_id == implementer_identity.session_id:
        raise ReviewValidationError("reviewer session collides with implementer")
    if reviewer_identity.credential_scope not in {
        CredentialScope.READ_ONLY,
        CredentialScope.REVIEW_WRITE,
    }:
        raise ReviewValidationError("reviewer has forbidden credential scope")
    if not context_complete:
        raise ReviewValidationError("required review context is incomplete")
    if len(candidate.findings) > 50:
        raise ReviewValidationError("provider returned too many findings")
    if len(candidate.summary) > 8_000:
        raise ReviewValidationError("provider summary exceeds safety limit")
    for item in candidate.findings:
        if len(item.title) > 500 or len(item.explanation) > 8_000:
            raise ReviewValidationError("provider finding text exceeds safety limit")
        if len(item.evidence) > 20 or any(len(value) > 2_000 for value in item.evidence):
            raise ReviewValidationError("provider finding evidence exceeds safety limit")

    finding_ids = [item.finding_id for item in candidate.findings]
    fingerprints = [item.fingerprint for item in candidate.findings]
    if len(finding_ids) != len(set(finding_ids)):
        raise ReviewValidationError("duplicate finding_id")
    if len(fingerprints) != len(set(fingerprints)):
        raise ReviewValidationError("duplicate finding fingerprint")

    blocking = [
        item.finding_id for item in candidate.findings if item.severity == FindingSeverity.BLOCKING
    ]
    if candidate.verdict_candidate == ReviewVerdict.PASS and blocking:
        raise ReviewValidationError("PASS cannot contain BLOCKING findings")
    if candidate.verdict_candidate == ReviewVerdict.CHANGES_REQUESTED and not blocking:
        raise ReviewValidationError("CHANGES_REQUESTED requires a BLOCKING finding")
    if candidate.verdict_candidate == ReviewVerdict.BLOCKED and blocking:
        raise ReviewValidationError("BLOCKED is not a substitute for code findings")

    return ReviewDecision(
        verdict=candidate.verdict_candidate,
        reviewed_head_sha=target.head_sha,
        reviewer_identity=reviewer_identity,
        findings=candidate.findings,
        blocking_finding_ids=blocking,
        summary=candidate.summary,
        confidence=candidate.confidence,
        created_at=datetime.now(timezone.utc),
    )
