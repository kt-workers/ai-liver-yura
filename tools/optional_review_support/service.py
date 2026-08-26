"""任意レビュー支援の読取専用実行境界。"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from .contracts import (
    AdvisoryCandidate,
    AdvisoryFinding,
    ReviewAdvisory,
    ReviewAdvisoryAvailability,
    ReviewContext,
    ReviewContextInput,
    ReviewTarget,
    _sanitize_presentation,
)


class OptionalReviewBackend(Protocol):
    """任意providerのread-only advisory候補生成Port。"""

    def review(self, context: ReviewContext) -> AdvisoryCandidate:
        """未信頼candidateだけを返す。"""


CurrentHeadReader = Callable[[ReviewTarget], str]
ReadOnlyContextInputReader = Callable[[ReviewTarget], ReviewContextInput]


@dataclass(frozen=True)
class ReadOnlyReviewContextCollector:
    """read-only adapterを注入し、trusted targetを固定したcontextを構築する。"""

    reader: ReadOnlyContextInputReader

    def collect(self, target: ReviewTarget) -> ReviewContext:
        """sourceがtargetを差し替えられない形でimmutable contextを返す。"""

        inputs = self.reader(target)
        if not isinstance(inputs, ReviewContextInput):
            raise ValueError("read-only sourceのcontext inputが不正です。")
        return ReviewContext(
            target=target,
            implementer=inputs.implementer,
            reviewer=inputs.reviewer,
            issue_references=inputs.issue_references,
            canonical_references=inputs.canonical_references,
            gate_evidence=inputs.gate_evidence,
            untrusted_pr_data=inputs.untrusted_pr_data,
            collected_at=datetime.now(timezone.utc),
        )


class OptionalReviewService:
    """retry/poll/writeを持たないboundedな任意レビュー実行器。"""

    def __init__(self, *, cache_limit: int = 128) -> None:
        if isinstance(cache_limit, bool) or cache_limit <= 0:
            raise ValueError("cache_limit は正の整数である必要があります。")
        self._cache_limit = cache_limit
        self._cache: OrderedDict[tuple[str, str], ReviewAdvisory] = OrderedDict()

    def run(
        self,
        context: ReviewContext,
        *,
        backend: OptionalReviewBackend | None,
        current_head: CurrentHeadReader,
    ) -> ReviewAdvisory:
        """最大一回のbackend呼出で、typed advisoryだけを返す。"""

        cache_key = (context.target.identity_key, context.context_generation)
        cached = self._cache.get(cache_key)
        if cached is not None:
            try:
                live_head = current_head(context.target)
            except Exception:
                return self._unavailable(
                    context,
                    "TARGET_READ_UNAVAILABLE",
                    "対象headを再確認できません。",
                )
            if live_head != context.target.head_sha:
                return ReviewAdvisory(
                    target=context.target,
                    context_generation=context.context_generation,
                    availability=ReviewAdvisoryAvailability.STALE_TARGET,
                    summary=(
                        "対象headが収集時点から変化したため、助言をcurrent targetとして扱いません。"
                    ),
                    diagnostic_code="STALE_TARGET",
                )
            self._cache.move_to_end(cache_key)
            return cached

        if backend is None:
            return self._remember(
                cache_key,
                self._unavailable(
                    context, "BACKEND_NOT_CONFIGURED", "任意review backendは設定されていません。"
                ),
            )

        try:
            candidate = backend.review(context)
        except Exception:
            return self._remember(
                cache_key,
                self._unavailable(
                    context, "BACKEND_UNAVAILABLE", "任意review backendを利用できません。"
                ),
            )

        try:
            live_head = current_head(context.target)
        except Exception:
            return self._remember(
                cache_key,
                self._unavailable(
                    context, "TARGET_READ_UNAVAILABLE", "対象headを再確認できません。"
                ),
            )
        if live_head != context.target.head_sha:
            return self._remember(
                cache_key,
                ReviewAdvisory(
                    target=context.target,
                    context_generation=context.context_generation,
                    availability=ReviewAdvisoryAvailability.STALE_TARGET,
                    summary=(
                        "対象headが収集時点から変化したため、助言をcurrent targetとして扱いません。"
                    ),
                    diagnostic_code="STALE_TARGET",
                ),
            )
        if (
            not isinstance(candidate, AdvisoryCandidate)
            or candidate.echoed_head_sha != context.target.head_sha
        ):
            return self._remember(
                cache_key,
                ReviewAdvisory(
                    target=context.target,
                    context_generation=context.context_generation,
                    availability=ReviewAdvisoryAvailability.INVALID_OUTPUT,
                    summary="任意review backendの出力をtrusted advisoryへ変換できません。",
                    diagnostic_code="INVALID_OUTPUT",
                ),
            )
        try:
            findings = tuple(
                AdvisoryFinding(
                    title=_sanitize_presentation(finding.title),
                    explanation=_sanitize_presentation(finding.explanation),
                    path=finding.path,
                    line=finding.line,
                )
                for finding in candidate.findings
            )
            advisory = ReviewAdvisory(
                target=context.target,
                context_generation=context.context_generation,
                availability=ReviewAdvisoryAvailability.AVAILABLE,
                summary=_sanitize_presentation(candidate.summary),
                findings=findings,
            )
        except ValueError:
            advisory = ReviewAdvisory(
                target=context.target,
                context_generation=context.context_generation,
                availability=ReviewAdvisoryAvailability.INVALID_OUTPUT,
                summary="任意review backendの出力をtrusted advisoryへ変換できません。",
                diagnostic_code="INVALID_OUTPUT",
            )
        return self._remember(cache_key, advisory)

    def _remember(self, cache_key: tuple[str, str], advisory: ReviewAdvisory) -> ReviewAdvisory:
        self._cache[cache_key] = advisory
        self._cache.move_to_end(cache_key)
        while len(self._cache) > self._cache_limit:
            self._cache.popitem(last=False)
        return advisory

    @staticmethod
    def _unavailable(context: ReviewContext, diagnostic_code: str, summary: str) -> ReviewAdvisory:
        return ReviewAdvisory(
            target=context.target,
            context_generation=context.context_generation,
            availability=ReviewAdvisoryAvailability.UNAVAILABLE,
            summary=summary,
            diagnostic_code=diagnostic_code,
        )
