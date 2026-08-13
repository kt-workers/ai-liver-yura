from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from .context_builder import ContextBuildError, build_context, validate_pr_scope
from .models import AgentIdentity, ReviewContext, ReviewDecision, ReviewTarget, ReviewVerdict
from .persistence import publish_decision
from .reviewer_backend import ReviewerBackend, ReviewerBackendError
from .validator import ReviewValidationError, validate_candidate


@dataclass(frozen=True)
class ReviewRunResult:
    decision: ReviewDecision
    published: bool


def _fallback_blocked_decision(
    *, target: ReviewTarget, reviewer_identity: AgentIdentity, summary: str
) -> ReviewDecision:
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
        trusted_workflow_ids: frozenset[int] = frozenset(),
    ) -> None:
        self.github = github
        self.backend = backend
        self.repository = repository
        self.reviewer_identity = reviewer_identity
        self.max_context_chars = max_context_chars
        self.max_backend_attempts = max_backend_attempts
        self.trusted_workflow_ids = trusted_workflow_ids

    def _build_context(
        self,
        *,
        pr_number: int,
        implementer_identity: AgentIdentity,
        expected_head_sha: str,
        trusted_base_sha: str,
    ) -> ReviewContext:
        return build_context(
            self.github,  # type: ignore[arg-type]
            repository=self.repository,
            pr_number=pr_number,
            implementer_identity=implementer_identity,
            expected_head_sha=expected_head_sha,
            trusted_base_sha=trusted_base_sha,
            max_context_chars=self.max_context_chars,
            trusted_workflow_ids=self.trusted_workflow_ids,
        )

    def _current_pr(self, *, pr_number: int, expected_head_sha: str) -> dict[str, object]:
        current = self.github.get_pull(pr_number)  # type: ignore[attr-defined]
        validate_pr_scope(
            current,
            repository=self.repository,
            expected_head_sha=expected_head_sha,
        )
        return cast(dict[str, object], current)

    def _assert_authority_generation(
        self,
        *,
        context: ReviewContext,
        pr_number: int,
        implementer_identity: AgentIdentity,
        expected_head_sha: str,
        trusted_base_sha: str,
    ) -> None:
        current = self._build_context(
            pr_number=pr_number,
            implementer_identity=implementer_identity,
            expected_head_sha=expected_head_sha,
            trusted_base_sha=trusted_base_sha,
        )
        if current.authority_generation != context.authority_generation:
            raise ContextBuildError("公開直前に正本世代が変化しました")

    def run(
        self,
        *,
        pr_number: int,
        implementer_identity: AgentIdentity,
        expected_head_sha: str,
        trusted_base_sha: str,
    ) -> ReviewRunResult:
        context = self._build_context(
            pr_number=pr_number,
            implementer_identity=implementer_identity,
            expected_head_sha=expected_head_sha,
            trusted_base_sha=trusted_base_sha,
        )

        decision: ReviewDecision | None = None
        final_problem = "レビュー担当から有効な結果を取得できませんでした"

        for _ in range(self.max_backend_attempts):
            # API呼出し直前にも対象範囲を再確認する。
            self._current_pr(pr_number=pr_number, expected_head_sha=expected_head_sha)
            try:
                candidate = self.backend.review(context)
            except ReviewerBackendError as exc:
                final_problem = f"レビュー担当接続に失敗しました: {type(exc).__name__}"
                continue

            current = self._current_pr(pr_number=pr_number, expected_head_sha=expected_head_sha)
            head = current.get("head")
            current_head = head.get("sha") if isinstance(head, dict) else None
            try:
                decision = validate_candidate(
                    candidate,
                    target=context.target,
                    current_head_sha=current_head if isinstance(current_head, str) else "",
                    implementer_identity=implementer_identity,
                    reviewer_identity=self.reviewer_identity,
                    context_complete=bool(context.canonical_documents),
                )
                break
            except ReviewValidationError as exc:
                final_problem = f"レビュー候補の意味検証に失敗しました: {exc}"
                if not exc.retryable:
                    break

        if decision is None:
            decision = _fallback_blocked_decision(
                target=context.target,
                reviewer_identity=self.reviewer_identity,
                summary=final_problem,
            )

        # 公開直前にも対象範囲全体を再確認する。
        self._current_pr(pr_number=pr_number, expected_head_sha=expected_head_sha)
        if decision.reviewed_head_sha != expected_head_sha:
            blocked = _fallback_blocked_decision(
                target=context.target,
                reviewer_identity=self.reviewer_identity,
                summary="レビュー対象SHAと実行開始時SHAが一致しないため結果を破棄しました",
            )
            return ReviewRunResult(decision=blocked, published=False)

        current_context = self._build_context(
            pr_number=pr_number,
            implementer_identity=implementer_identity,
            expected_head_sha=expected_head_sha,
            trusted_base_sha=trusted_base_sha,
        )
        if current_context.authority_generation != context.authority_generation:
            blocked = _fallback_blocked_decision(
                target=context.target,
                reviewer_identity=self.reviewer_identity,
                summary="正本世代がレビュー開始時から変化したため結果を破棄しました",
            )
            return ReviewRunResult(decision=blocked, published=False)

        published = publish_decision(
            self.github,  # type: ignore[arg-type]
            pr_number=pr_number,
            decision=decision,
            before_publish=lambda: self._assert_authority_generation(
                context=context,
                pr_number=pr_number,
                implementer_identity=implementer_identity,
                expected_head_sha=expected_head_sha,
                trusted_base_sha=trusted_base_sha,
            ),
        )
        return ReviewRunResult(decision=decision, published=published)
