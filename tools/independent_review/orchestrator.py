from __future__ import annotations

from dataclasses import dataclass

from .context_builder import build_context
from .models import (
    AgentIdentity,
    ProviderReviewCandidate,
    ReviewDecision,
    ReviewTarget,
    ReviewVerdict,
)
from .persistence import publish_decision
from .reviewer_backend import ReviewerBackend, ReviewerBackendError
from .validator import ReviewValidationError, validate_candidate


@dataclass(frozen=True)
class ReviewRunResult:
    decision: ReviewDecision
    published: bool


def _blocked_candidate(summary: str) -> ProviderReviewCandidate:
    return ProviderReviewCandidate(
        verdict_candidate=ReviewVerdict.BLOCKED,
        findings=[],
        summary=summary,
    )


def _fallback_blocked_decision(
    *, target: ReviewTarget, reviewer_identity: AgentIdentity, summary: str
) -> ReviewDecision:
    # Trusted infrastructure decision. No provider finding is promoted when validation failed.
    from datetime import datetime, timezone

    return ReviewDecision(
        verdict=ReviewVerdict.BLOCKED,
        reviewed_head_sha=target.head_sha,
        reviewer_identity=reviewer_identity,
        findings=[],
        blocking_finding_ids=[],
        summary=summary,
        created_at=datetime.now(timezone.utc),
    )


class ReviewOrchestrator:
    def __init__(
        self,
        *,
        github: object,
        backend: ReviewerBackend,
        repository: str,
        reviewer_identity: AgentIdentity,
        max_context_chars: int = 600_000,
        max_backend_attempts: int = 2,
    ) -> None:
        self.github = github
        self.backend = backend
        self.repository = repository
        self.reviewer_identity = reviewer_identity
        self.max_context_chars = max_context_chars
        self.max_backend_attempts = max_backend_attempts

    def run(self, *, pr_number: int, implementer_identity: AgentIdentity) -> ReviewRunResult:
        context = build_context(
            self.github,  # type: ignore[arg-type]
            repository=self.repository,
            pr_number=pr_number,
            implementer_identity=implementer_identity,
            max_context_chars=self.max_context_chars,
        )
        candidate: ProviderReviewCandidate | None = None
        backend_error: ReviewerBackendError | None = None
        for _ in range(self.max_backend_attempts):
            try:
                candidate = self.backend.review(context)
                backend_error = None
                break
            except ReviewerBackendError as exc:
                backend_error = exc
        if candidate is None:
            candidate = _blocked_candidate(
                f"Reviewer backend unavailable after bounded retry: {type(backend_error).__name__}"
            )

        current = self.github.get_pull(pr_number)  # type: ignore[attr-defined]
        current_head_obj = current.get("head")
        current_head = (
            current_head_obj.get("sha") if isinstance(current_head_obj, dict) else None
        )
        if not isinstance(current_head, str):
            current_head = ""
        try:
            decision = validate_candidate(
                candidate,
                target=context.target,
                current_head_sha=current_head,
                implementer_identity=implementer_identity,
                reviewer_identity=self.reviewer_identity,
                context_complete=bool(context.canonical_documents),
            )
        except ReviewValidationError as exc:
            decision = _fallback_blocked_decision(
                target=context.target,
                reviewer_identity=self.reviewer_identity,
                summary=f"Deterministic review validation blocked this result: {exc}",
            )

        # Never publish an old SHA as a current result after a final stale check.
        latest = self.github.get_pull(pr_number)  # type: ignore[attr-defined]
        latest_head_obj = latest.get("head")
        latest_head = latest_head_obj.get("sha") if isinstance(latest_head_obj, dict) else None
        if latest_head != context.target.head_sha:
            decision = _fallback_blocked_decision(
                target=context.target,
                reviewer_identity=self.reviewer_identity,
                summary="Review became stale before persistence; PR head changed.",
            )
            return ReviewRunResult(decision=decision, published=False)

        published = publish_decision(
            self.github,  # type: ignore[arg-type]
            pr_number=pr_number,
            decision=decision,
        )
        return ReviewRunResult(decision=decision, published=published)
