from __future__ import annotations

from app.domain.activity_execution import (
    ActivityExecutionAuthority,
    ExecutionObservationSourceBinding,
    ObservedExecutionFactRecord,
)
from app.domain.attention import (
    AttentionFocusState,
    AttentionResponseSettlement,
    AttentionTurnStore,
)
from app.domain.contracts import ExecutionStatus
from app.domain.contracts.common import require_identifier
from app.domain.contracts.finalization import (
    AuthorityFinalizationFence,
    AuthorityFinalizationRequest,
    AuthorityFinalizationResult,
    AuthorityReadPublication,
    FinalizationError,
    FinalizationFailure,
)


class AttentionResponseSettlementCoordinator:
    """登録された観測Ownerの完了publicationをAttentionの既存Fenceへ渡す。"""

    def __init__(
        self,
        executions: ActivityExecutionAuthority,
        attention: AttentionTurnStore,
        expected_source: ExecutionObservationSourceBinding,
    ) -> None:
        if (
            not isinstance(executions, ActivityExecutionAuthority)
            or not isinstance(attention, AttentionTurnStore)
            or not isinstance(expected_source, ExecutionObservationSourceBinding)
        ):
            raise ValueError("観測Owner、Attention Owner、期待するsource bindingが必要です")
        self._executions = executions
        self._attention = attention
        self._expected_source = expected_source
        self._fence = AuthorityFinalizationFence()

    def prepare(
        self,
        publication: AuthorityReadPublication[ObservedExecutionFactRecord | None],
        *,
        expected_decision_id: str,
        attention: AuthorityReadPublication[AttentionFocusState],
    ) -> AuthorityFinalizationRequest[AttentionResponseSettlement, AttentionFocusState] | None:
        """current publicationを照合し、元tokenを保持した同期commit要求を作る。"""
        try:
            require_identifier(expected_decision_id, "expected_decision_id")
        except ValueError as exc:
            raise FinalizationError(FinalizationFailure.TARGET_REJECTED) from exc
        if (
            not isinstance(publication, AuthorityReadPublication)
            or not isinstance(publication.value, ObservedExecutionFactRecord)
            or not isinstance(attention, AuthorityReadPublication)
            or not isinstance(attention.value, AttentionFocusState)
        ):
            raise FinalizationError(FinalizationFailure.TARGET_REJECTED)
        record = publication.value
        if (
            record.source != self._expected_source
            or record.provenance.source_decision_id != expected_decision_id
        ):
            raise FinalizationError(FinalizationFailure.TARGET_REJECTED)
        # DTOの差し替えを拒否し、この照合後の競合は元publicationのtokenで検出する。
        if (
            publication
            != self._executions.observed_snapshot(
                record.source.source_contract_id, record.execution_id
            )
            or attention != self._attention.snapshot_publication()
        ):
            raise FinalizationError(FinalizationFailure.GENERATION_MISMATCH)
        if record.result.status is not ExecutionStatus.COMPLETED:
            return None
        settlement = AttentionResponseSettlement(
            observed_execution_id=record.result.command_id,
            observed_record_revision=record.record_revision,
            latest_observation_id=record.latest_observation_id,
            source_decision_id=record.provenance.source_decision_id,
            source_event_ids=record.provenance.source_event_ids,
            expected_attention_revision=attention.value.revision,
            expected_source_context_revision=attention.value.source_context_revision,
            completed_at=record.result.occurred_at,
        )
        return AuthorityFinalizationRequest(
            expected_tokens=(*publication.tokens, *attention.tokens),
            target=self._attention.finalization_participant,
            operation=self._attention.response_settlement_operation,
            payload=settlement,
        )

    def settle(
        self,
        publication: AuthorityReadPublication[ObservedExecutionFactRecord | None],
        *,
        expected_decision_id: str,
        attention: AuthorityReadPublication[AttentionFocusState],
    ) -> AuthorityFinalizationResult[AttentionFocusState] | None:
        """非完了は非対象、予想可能な拒否は正規failureとして返す。"""
        try:
            request = self.prepare(
                publication, expected_decision_id=expected_decision_id, attention=attention
            )
        except FinalizationError as exc:
            return AuthorityFinalizationResult(failure=exc.failure)
        return None if request is None else self._fence.finalize(request)
