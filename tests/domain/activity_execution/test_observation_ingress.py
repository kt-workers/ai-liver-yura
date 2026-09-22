from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from app.domain.activity_execution import (
    ActivityExecutionAuthority,
    ExecutionEffectKind,
    ExecutionEffectUncertainty,
    ExecutionObservationIngressPolicy,
    ExecutionObservationProvenance,
    ExecutionObservationSourceBinding,
    ExecutionObservationSourceRule,
    ObservedExecutionEffectEvidence,
    ObservedExecutionFactRecord,
    TrustedExecutionObservation,
)
from app.domain.activity_execution.observation import observation_identity
from app.domain.contracts import ExecutionStatus, RevisionVector

NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)
SOURCE = ExecutionObservationSourceBinding("test-source", 1)
POLICY = ExecutionObservationIngressPolicy(
    "test-policy",
    1,
    (
        ExecutionObservationSourceRule(
            SOURCE,
            (
                ExecutionStatus.OBSERVABLE,
                ExecutionStatus.APPLIED,
                ExecutionStatus.COMPLETED,
                ExecutionStatus.FAILED,
                ExecutionStatus.CANCELLED,
                ExecutionStatus.TIMED_OUT,
            ),
            ("text",),
            (ExecutionEffectKind.OBSERVABLE, ExecutionEffectKind.APPLIED),
        ),
    ),
)


def observation() -> TrustedExecutionObservation:
    return TrustedExecutionObservation(
        "observation",
        "execution",
        SOURCE,
        "subject",
        ExecutionStatus.OBSERVABLE,
        NOW,
        NOW + timedelta(seconds=1),
        NOW + timedelta(seconds=1),
        ExecutionObservationProvenance("decision", ("event",), RevisionVector(1, 2, 3), "trace"),
        effects=(
            ObservedExecutionEffectEvidence(
                "effect", "text", "subject", ExecutionEffectKind.OBSERVABLE, {"asset": "asset"}
            ),
        ),
    )


def ingest(
    owner: ActivityExecutionAuthority, o: TrustedExecutionObservation
) -> ObservedExecutionFactRecord:
    return owner.ingest_observation(
        o, policy_id=POLICY.policy_id, policy_revision=POLICY.policy_revision
    )


def test_allowed_source_duplicate_and_terminal_preserve_fact() -> None:
    owner = ActivityExecutionAuthority(observation_policy=POLICY)
    o = observation()
    record = ingest(owner, o)
    assert record.result.status is ExecutionStatus.OBSERVABLE
    assert record.result.effect_refs == ("effect",)
    assert record.provenance == o.provenance
    assert not hasattr(record, "invocation") and not hasattr(record.effects[0], "capability_id")
    assert ingest(owner, o) is record
    terminal = ingest(
        owner,
        replace(
            o,
            observation_id="done",
            status=ExecutionStatus.COMPLETED,
            effects=(),
            occurred_at=NOW + timedelta(seconds=2),
        ),
    )
    assert terminal.result.effect_refs == ("effect",)
    assert terminal.record_revision == 2
    assert ingest(owner, o) is terminal
    assert owner.observed_snapshot(SOURCE.source_contract_id, o.execution_id).value is terminal


@pytest.mark.parametrize(
    "source",
    [
        ExecutionObservationSourceBinding("unknown", 1),
        ExecutionObservationSourceBinding("test-source", 2),
    ],
)
def test_unknown_source_or_revision_rejected(source: ExecutionObservationSourceBinding) -> None:
    owner = ActivityExecutionAuthority(observation_policy=POLICY)
    with pytest.raises(ValueError):
        ingest(owner, replace(observation(), source=source))
    assert owner.observed_snapshot(source.source_contract_id, "execution").value is None


@pytest.mark.parametrize("revision", [0, 2, True])
def test_policy_generation_rejected(revision: int) -> None:
    owner = ActivityExecutionAuthority(observation_policy=POLICY)
    with pytest.raises(ValueError):
        owner.ingest_observation(
            observation(), policy_id=POLICY.policy_id, policy_revision=revision
        )


def test_unconfigured_policy_and_unknown_effect_rejected() -> None:
    with pytest.raises(ValueError):
        ingest(ActivityExecutionAuthority(), observation())
    o = observation()
    with pytest.raises(ValueError):
        ingest(
            ActivityExecutionAuthority(observation_policy=POLICY),
            replace(o, effects=(replace(o.effects[0], effect_type="unknown"),)),
        )


@pytest.mark.parametrize(
    "field", ["details", "subject", "revision", "events", "trace", "decision", "execution"]
)
def test_conflicting_duplicate_rejected_without_mutation(field: str) -> None:
    owner = ActivityExecutionAuthority(observation_policy=POLICY)
    o = observation()
    record = ingest(owner, o)
    if field == "details":
        changed = replace(o, details={"code": "changed"})
    elif field == "subject":
        changed = replace(
            o, subject_ref="other", effects=(replace(o.effects[0], subject_ref="other"),)
        )
    elif field == "execution":
        changed = replace(o, execution_id="other")
    else:
        p = o.provenance
        p = {
            "revision": replace(p, revisions=RevisionVector(2)),
            "events": replace(p, source_event_ids=("other",)),
            "trace": replace(p, trace_id="other"),
            "decision": replace(p, source_decision_id="other"),
        }[field]
        changed = replace(o, provenance=p)
    with pytest.raises(ValueError):
        ingest(owner, changed)
    assert owner.observed_snapshot(SOURCE.source_contract_id, o.execution_id).value is record
    if field not in {"details", "execution"}:
        with pytest.raises(ValueError):
            ingest(owner, replace(changed, observation_id="different"))


@pytest.mark.parametrize(
    "status", [ExecutionStatus.FAILED, ExecutionStatus.CANCELLED, ExecutionStatus.TIMED_OUT]
)
@pytest.mark.parametrize("uncertainty", list(ExecutionEffectUncertainty))
def test_failure_retains_effect_and_uncertainty(
    status: ExecutionStatus, uncertainty: ExecutionEffectUncertainty
) -> None:
    owner = ActivityExecutionAuthority(observation_policy=POLICY)
    o = observation()
    ingest(owner, o)
    terminal = replace(
        o,
        observation_id="terminal",
        status=status,
        effects=(),
        effect_uncertainty=uncertainty,
        occurred_at=NOW + timedelta(seconds=2),
    )
    record = ingest(owner, terminal)
    assert record.result.effect_refs == ("effect",)
    assert record.effects == o.effects and record.effect_uncertainty is uncertainty
    with pytest.raises(ValueError):
        replace(terminal, effects=o.effects)
    with pytest.raises(ValueError):
        ingest(owner, replace(o, observation_id="reopen", occurred_at=NOW + timedelta(seconds=3)))


def test_uncertainty_does_not_create_refs_and_before_start_is_distinct() -> None:
    o = replace(
        observation(),
        effects=(),
        status=ExecutionStatus.FAILED,
        effect_uncertainty=ExecutionEffectUncertainty.UNKNOWN,
    )
    result = ingest(ActivityExecutionAuthority(observation_policy=POLICY), o)
    assert result.result.effect_refs == ()
    before = replace(o, started_at=None, effect_uncertainty=ExecutionEffectUncertainty.NONE)
    result = ingest(ActivityExecutionAuthority(observation_policy=POLICY), before)
    assert result.started_at is None and result.result.effect_refs == ()


def test_applied_and_effect_conflict_and_timestamp_order() -> None:
    o = observation()
    applied = replace(
        o,
        status=ExecutionStatus.APPLIED,
        effects=(replace(o.effects[0], kind=ExecutionEffectKind.APPLIED),),
    )
    owner = ActivityExecutionAuthority(observation_policy=POLICY)
    assert ingest(owner, applied).result.status is ExecutionStatus.APPLIED
    with pytest.raises(ValueError):
        ingest(
            owner,
            replace(
                applied,
                observation_id="other",
                effects=(replace(applied.effects[0], payload={"asset": "changed"}),),
            ),
        )
    with pytest.raises(ValueError):
        replace(o, occurred_at=NOW)
    with pytest.raises(ValueError):
        replace(o, committed_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        ingest(
            owner,
            replace(
                applied,
                observation_id="done",
                status=ExecutionStatus.COMPLETED,
                effects=(),
                occurred_at=NOW,
            ),
        )


def test_concurrent_same_observation_commits_once() -> None:
    owner = ActivityExecutionAuthority(observation_policy=POLICY)
    o = observation()
    barrier = Barrier(8)

    def run(_: int) -> ObservedExecutionFactRecord:
        barrier.wait()
        return ingest(owner, o)

    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(run, range(8)))
    assert all(r is records[0] for r in records)
    assert records[0].record_revision == 1


@pytest.mark.parametrize("terminal", [False, True])
def test_conflicting_or_terminal_race_has_one_commit(terminal: bool) -> None:
    owner = ActivityExecutionAuthority(observation_policy=POLICY)
    o = observation()
    if terminal:
        ingest(owner, o)
        choices = [
            replace(
                o,
                observation_id=s.value,
                status=s,
                effects=(),
                occurred_at=NOW + timedelta(seconds=2),
            )
            for s in (ExecutionStatus.COMPLETED, ExecutionStatus.CANCELLED)
        ]
    else:
        choices = [o, replace(o, details={"code": "conflict"})]
    barrier = Barrier(2)

    def run(item: TrustedExecutionObservation) -> bool:
        barrier.wait()
        try:
            ingest(owner, item)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, choices))
    assert sorted(results) == [False, True]
    record = owner.observed_snapshot(SOURCE.source_contract_id, "execution").value
    assert record is not None and record.record_revision == (2 if terminal else 1)


def test_identity_encoding_is_collision_free_and_source_revision_conflict_rejected() -> None:
    assert observation_identity("a:b", "c") != observation_identity("a", "b:c")
    second = replace(SOURCE, source_contract_revision=2)
    policy = replace(
        POLICY, source_rules=(*POLICY.source_rules, replace(POLICY.source_rules[0], source=second))
    )
    owner = ActivityExecutionAuthority(observation_policy=policy)
    ingest(owner, observation())
    with pytest.raises(ValueError):
        ingest(owner, replace(observation(), source=second, observation_id="next"))


def test_json_type_conflicts_and_immutable_inputs() -> None:
    owner = ActivityExecutionAuthority(observation_policy=POLICY)
    o = replace(observation(), details={"flag": True})
    ingest(owner, o)
    with pytest.raises(ValueError):
        ingest(owner, replace(o, details={"flag": 1}))
    o = observation()
    source_payload = {"flag": True}
    o = replace(o, effects=(replace(o.effects[0], payload=source_payload),))
    source_payload["flag"] = False
    assert o.effects[0].payload == {"flag": True}
    owner = ActivityExecutionAuthority(observation_policy=POLICY)
    ingest(owner, o)
    changed = replace(o, effects=(replace(o.effects[0], payload={"flag": 1}),))
    with pytest.raises(ValueError):
        ingest(owner, changed)
    with pytest.raises(ValueError):
        ingest(owner, replace(changed, observation_id="next"))


def test_monotonic_effects_and_rejected_update_is_atomic() -> None:
    owner = ActivityExecutionAuthority(observation_policy=POLICY)
    o = observation()
    ingest(owner, o)
    new = replace(
        o,
        observation_id="more",
        occurred_at=NOW + timedelta(seconds=2),
        effects=(replace(o.effects[0], effect_id="second"),),
    )
    record = ingest(owner, new)
    assert record.result.effect_refs == ("effect", "second")
    assert record.record_revision == 2
    with pytest.raises(ValueError):
        ingest(
            owner,
            replace(
                new,
                observation_id="late",
                occurred_at=NOW + timedelta(seconds=1),
                effects=(replace(o.effects[0], effect_id="third"),),
            ),
        )
    assert owner.observed_snapshot(SOURCE.source_contract_id, "execution").value is record
    with pytest.raises(ValueError):
        ingest(owner, replace(new, observation_id="no-new-effect"))
    assert owner.observed_snapshot(SOURCE.source_contract_id, "execution").value is record


def test_source_status_and_kind_constraints() -> None:
    rule = replace(
        POLICY.source_rules[0],
        allowed_statuses=(ExecutionStatus.OBSERVABLE,),
        allowed_effect_kinds=(ExecutionEffectKind.OBSERVABLE,),
    )
    owner = ActivityExecutionAuthority(observation_policy=replace(POLICY, source_rules=(rule,)))
    o = observation()
    with pytest.raises(ValueError):
        ingest(owner, replace(o, status=ExecutionStatus.APPLIED))
    with pytest.raises(ValueError):
        replace(o, effects=(replace(o.effects[0], kind=ExecutionEffectKind.APPLIED),))
    with pytest.raises(ValueError):
        replace(o, effects=())
    with pytest.raises(ValueError):
        replace(o, effect_uncertainty=ExecutionEffectUncertainty.UNKNOWN)
