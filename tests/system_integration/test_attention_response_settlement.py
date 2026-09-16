from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.activity_execution import (
    ActivityExecutionAuthority,
    ExecutionObservationSourceBinding,
    ObservedExecutionFactRecord,
)
from app.domain.attention import AttentionTurnStore
from app.domain.contracts import ExecutionStatus
from app.domain.contracts.finalization import (
    AuthorityFinalizationFence,
    AuthorityReadPublication,
    FinalizationFailure,
)
from app.usecases.attention import AttentionResponseSettlementCoordinator
from tests.domain.activity_execution.test_observation_ingress import (
    NOW,
    POLICY,
    SOURCE,
    ingest,
    observation,
)
from tests.domain.attention.test_attention_response_settlement import prepared_store
from tests.domain.attention.test_attention_turn_store import signal


def setup(
    status: ExecutionStatus = ExecutionStatus.COMPLETED,
) -> tuple[
    ActivityExecutionAuthority,
    AttentionTurnStore,
    AttentionResponseSettlementCoordinator,
    AuthorityReadPublication[ObservedExecutionFactRecord | None],
]:
    executions = ActivityExecutionAuthority(observation_policy=POLICY)
    initial = replace(
        observation(), provenance=replace(observation().provenance, source_event_ids=("user-a",))
    )
    if status is ExecutionStatus.APPLIED:
        initial = replace(initial, status=status)
    ingest(executions, initial)
    if status not in (ExecutionStatus.OBSERVABLE, ExecutionStatus.APPLIED):
        ingest(
            executions,
            replace(
                initial,
                observation_id="terminal",
                status=status,
                effects=(),
                occurred_at=NOW + timedelta(seconds=2),
            ),
        )
    attention = prepared_store()
    coordinator = AttentionResponseSettlementCoordinator(executions, attention, SOURCE)
    return (
        executions,
        attention,
        coordinator,
        executions.observed_snapshot(SOURCE.source_contract_id, initial.execution_id),
    )


def test_real_completed_publication_and_retry() -> None:
    executions, attention, coordinator, publication = setup()
    observed_before = executions.observed_snapshot(SOURCE.source_contract_id, "execution")
    before = attention.snapshot()
    request = coordinator.prepare(
        publication, expected_decision_id="decision", attention=attention.snapshot_publication()
    )
    assert request is not None and publication.value is not None
    assert request.expected_tokens == (
        *publication.tokens,
        *attention.snapshot_publication().tokens,
    )
    assert request.payload.observed_execution_id == publication.value.result.command_id
    assert request.payload.observed_record_revision == publication.value.record_revision
    assert request.payload.latest_observation_id == publication.value.latest_observation_id
    assert request.payload.source_event_ids == publication.value.provenance.source_event_ids
    result = AuthorityFinalizationFence().finalize(request)
    assert result.failure is None
    after = attention.snapshot()
    assert after.revision == before.revision + 1
    assert after.current_turn_owner is None and after.response_obligation is None
    assert {s.source_ref for s in after.sources} == {"user-b", "other"}
    retry = coordinator.settle(
        publication, expected_decision_id="decision", attention=attention.snapshot_publication()
    )
    assert retry is not None and retry.failure is None and retry.value is after
    assert attention.snapshot() is after
    assert executions.observed_snapshot(SOURCE.source_contract_id, "execution") == observed_before
    assert (
        AuthorityFinalizationFence().finalize(request).failure
        is FinalizationFailure.GENERATION_MISMATCH
    )
    assert attention.snapshot() is after


@pytest.mark.parametrize(
    "status",
    [
        ExecutionStatus.OBSERVABLE,
        ExecutionStatus.APPLIED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.TIMED_OUT,
    ],
)
def test_non_completed_never_settles(status: ExecutionStatus) -> None:
    executions, attention, coordinator, publication = setup(status)
    before = attention.snapshot_publication()
    assert (
        coordinator.settle(publication, expected_decision_id="decision", attention=before) is None
    )
    assert attention.snapshot_publication() == before
    assert executions.observed_snapshot(SOURCE.source_contract_id, "execution") == publication
    assert publication.value is not None and publication.value.result.effect_refs == ("effect",)


@pytest.mark.parametrize("status", [ExecutionStatus.COMPLETED, ExecutionStatus.OBSERVABLE])
@pytest.mark.parametrize("mismatch", ["source", "source_revision", "decision", "type", "missing"])
def test_mismatch_fails_closed_even_when_not_completed(
    status: ExecutionStatus, mismatch: str
) -> None:
    executions, attention, coordinator, publication = setup(status)
    decision = "decision"
    if mismatch.startswith("source"):
        coordinator = AttentionResponseSettlementCoordinator(
            executions,
            attention,
            ExecutionObservationSourceBinding(
                "other" if mismatch == "source" else SOURCE.source_contract_id,
                2 if mismatch == "source_revision" else 1,
            ),
        )
    elif mismatch == "decision":
        decision = "unrelated"
    else:
        publication = AuthorityReadPublication(
            None if mismatch == "missing" else "invalid",  # type: ignore[arg-type]
            publication.tokens,
        )
    before = attention.snapshot_publication()
    result = coordinator.settle(publication, expected_decision_id=decision, attention=before)
    assert result is not None and result.failure is FinalizationFailure.TARGET_REJECTED
    assert attention.snapshot_publication() == before


@pytest.mark.parametrize("changed_owner", ["execution", "attention"])
def test_mutation_after_prepare_invalidates_real_token(changed_owner: str) -> None:
    executions, attention, coordinator, publication = setup()
    request = coordinator.prepare(
        publication, expected_decision_id="decision", attention=attention.snapshot_publication()
    )
    assert request is not None
    if changed_owner == "execution":
        ingest(
            executions,
            replace(
                observation(), observation_id="other-observation", execution_id="other-execution"
            ),
        )
    else:
        attention.offer(signal("new-source", revision=2, seconds=30))
    before = attention.snapshot()
    result = AuthorityFinalizationFence().finalize(request)
    assert result.failure is FinalizationFailure.GENERATION_MISMATCH
    assert attention.snapshot() is before


def test_observed_record_update_rejects_old_publication() -> None:
    executions, attention, coordinator, old = setup(ExecutionStatus.OBSERVABLE)
    ingest(
        executions,
        replace(
            observation(),
            observation_id="completed",
            status=ExecutionStatus.COMPLETED,
            effects=(),
            occurred_at=NOW + timedelta(seconds=2),
            provenance=replace(observation().provenance, source_event_ids=("user-a",)),
        ),
    )
    before = attention.snapshot_publication()
    result = coordinator.settle(old, expected_decision_id="decision", attention=before)
    assert result is not None and result.failure is FinalizationFailure.GENERATION_MISMATCH
    assert attention.snapshot_publication() == before
    current = executions.observed_snapshot(SOURCE.source_contract_id, "execution")
    result = coordinator.settle(current, expected_decision_id="decision", attention=before)
    assert result is not None and result.failure is None


@pytest.mark.parametrize(
    "forgery", ["record", "source_tokens", "attention_state", "attention_tokens"]
)
def test_detached_dto_or_wrong_owner_token_is_not_authority(forgery: str) -> None:
    executions, attention, coordinator, publication = setup()
    target = attention.snapshot_publication()
    assert publication.value is not None
    if forgery == "record":
        publication = replace(
            publication, value=replace(publication.value, latest_observation_id="forged")
        )
    elif forgery == "source_tokens":
        other, _, _, _ = setup()
        publication = replace(
            publication,
            tokens=other.observed_snapshot(SOURCE.source_contract_id, "execution").tokens,
        )
    elif forgery == "attention_state":
        target = replace(target, value=replace(target.value, revision=999))
    else:
        target = replace(target, tokens=prepared_store().snapshot_publication().tokens)
    before = attention.snapshot_publication()
    result = coordinator.settle(publication, expected_decision_id="decision", attention=target)
    assert result is not None and result.failure is FinalizationFailure.GENERATION_MISMATCH
    assert attention.snapshot_publication() == before


def test_ambiguous_target_is_rejected_without_target_fault() -> None:
    executions, _, _, publication = setup()
    attention = prepared_store("user-a", "user-b")
    initial = replace(
        observation(),
        execution_id="ambiguous",
        observation_id="start-ambiguous",
        provenance=replace(observation().provenance, source_event_ids=("user-a", "user-b")),
    )
    ingest(executions, initial)
    ingest(
        executions,
        replace(
            initial,
            status=ExecutionStatus.COMPLETED,
            observation_id="done-ambiguous",
            effects=(),
            occurred_at=NOW + timedelta(seconds=2),
        ),
    )
    publication = executions.observed_snapshot(SOURCE.source_contract_id, "ambiguous")
    coordinator = AttentionResponseSettlementCoordinator(executions, attention, SOURCE)
    before = attention.snapshot()
    result = coordinator.settle(
        publication, expected_decision_id="decision", attention=attention.snapshot_publication()
    )
    assert result is not None and result.failure is FinalizationFailure.TARGET_REJECTED
    assert attention.snapshot() is before
    assert attention.snapshot_publication().value is before
