from __future__ import annotations

from threading import Lock

from .contracts import (
    BodyExpressionContext,
    BodyExpressionFailureCode,
    BodyExpressionProjectionError,
)


def _same_provenance(left: BodyExpressionContext, right: BodyExpressionContext) -> bool:
    return (
        left.capture_source_context_revision == right.capture_source_context_revision
        and left.internal_state_revision == right.internal_state_revision
        and (
            left.internal_state_source_context_revision
            == right.internal_state_source_context_revision
        )
        and left.attention_revision == right.attention_revision
        and left.attention_source_context_revision == right.attention_source_context_revision
        and left.character_id == right.character_id
        and left.character_schema_version == right.character_schema_version
        and left.character_definition_revision == right.character_definition_revision
        and left.projection_policy_id == right.projection_policy_id
        and left.projection_policy_revision == right.projection_policy_revision
    )


def _same_projection(left: BodyExpressionContext, right: BodyExpressionContext) -> bool:
    return (
        left.axes == right.axes
        and left.focus_constraint == right.focus_constraint
        and left.applied_state_rule_ids == right.applied_state_rule_ids
        and left.applied_character_style_rule_ids == right.applied_character_style_rule_ids
        and left.source_facet_refs == right.source_facet_refs
    )


class BodyExpressionStore:
    def __init__(self) -> None:
        self._current: BodyExpressionContext | None = None
        self._lock = Lock()

    @property
    def current(self) -> BodyExpressionContext | None:
        with self._lock:
            return self._current

    @property
    def revision(self) -> int:
        with self._lock:
            return 0 if self._current is None else self._current.revision

    def commit(
        self,
        expected_revision: int,
        candidate: BodyExpressionContext,
    ) -> BodyExpressionContext:
        with self._lock:
            revision = 0 if self._current is None else self._current.revision
            if expected_revision != revision or candidate.revision != expected_revision + 1:
                raise BodyExpressionProjectionError(BodyExpressionFailureCode.STALE)
            current = self._current
            if current is not None:
                if _same_provenance(current, candidate):
                    if _same_projection(current, candidate):
                        return current
                    raise BodyExpressionProjectionError(BodyExpressionFailureCode.DETERMINISM)
                if (
                    candidate.capture_source_context_revision
                    < current.capture_source_context_revision
                ):
                    raise BodyExpressionProjectionError(BodyExpressionFailureCode.STALE)
                if candidate.internal_state_revision < current.internal_state_revision:
                    raise BodyExpressionProjectionError(BodyExpressionFailureCode.STALE)
                if candidate.attention_revision < current.attention_revision:
                    raise BodyExpressionProjectionError(BodyExpressionFailureCode.STALE)
                if (
                    candidate.character_id == current.character_id
                    and candidate.character_definition_revision
                    < current.character_definition_revision
                ):
                    raise BodyExpressionProjectionError(BodyExpressionFailureCode.STALE)
                if (
                    candidate.projection_policy_id == current.projection_policy_id
                    and candidate.projection_policy_revision < current.projection_policy_revision
                ):
                    raise BodyExpressionProjectionError(BodyExpressionFailureCode.STALE)
            self._current = candidate
            return candidate
