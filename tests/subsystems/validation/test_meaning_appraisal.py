"""入力意味の確定結果が深い状況評価へ渡り、失敗時には後続を呼ばないことを確認する。"""

from collections.abc import Mapping
from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.appraisal import DeepAppraisalContext, DeepAppraisalFreshnessStamp
from app.domain.attention import AttentionPriority, AttentionSchedulingPolicy
from app.domain.contracts.common import JsonValue, freeze_json
from app.domain.input_meaning import InputMeaningFreshnessStamp, build_request
from app.domain.llm import LLMRoleRequest, LLMRoleResult
from app.subsystems.validation.appraisal_executive import (
    AppraisalExecutiveBindings,
    AppraisalExecutiveSettings,
)
from app.subsystems.validation.contracts import (
    FailureInjection,
    Gate,
    InjectedFailure,
    LabMode,
    LabRunSpec,
    RunStatus,
    ValidationFixture,
)
from app.subsystems.validation.input_meaning import InputMeaningLabCase, input_meaning_target
from app.subsystems.validation.meaning_appraisal import (
    AppraisalAttentionSettings,
    AppraisalStateCommitSettings,
    MeaningAppraisalBindings,
    MeaningAppraisalSettings,
)
from app.subsystems.validation.runtime import ValidationRunner
from tests.domain.appraisal import test_appraisal_paths as appraisal
from tests.domain.input_meaning import test_input_meaning as meaning
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec


def setup(
    *,
    stale_meaning: bool = False,
    stale_appraisal: bool = False,
    state_commit: AppraisalStateCommitSettings | None = None,
    attention: AppraisalAttentionSettings | None = None,
    executive: AppraisalExecutiveSettings | None = None,
    executive_bindings: AppraisalExecutiveBindings | None = None,
) -> tuple[ValidationFixture, ValidationRunner, list[LLMRoleRequest]]:
    event, refs, policy = meaning.event(), meaning.context(), meaning.policy()
    state = replace(
        appraisal.state(),
        source_context_revision=4,
        updated_at=meaning.NOW,
        facets=tuple(replace(facet, updated_at=meaning.NOW) for facet in appraisal.state().facets),
    )
    settings = MeaningAppraisalSettings(
        state,
        DeepAppraisalContext(),
        appraisal.policy(),
        meaning.NOW + timedelta(seconds=1),
        state_commit,
        attention,
        executive,
    )
    request = build_request(
        event,
        refs,
        request_id="fixture",
        trace_id=event.envelope.trace_id,
        created_at=meaning.NOW,
        policy=policy,
    )
    fixture = replace(
        FIXTURE,
        typed_inputs=freeze_json(
            {
                "input_meaning": request.input.value,
                "appraisal": settings.typed_inputs(),
            }
        ),
    )
    calls: list[LLMRoleRequest] = []

    class MeaningPort:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            return meaning.result(request)

    class MeaningLive:
        async def current_freshness_stamp(self) -> InputMeaningFreshnessStamp:
            return meaning.freshness_stamp(5 if stale_meaning else 4)

    class AppraisalPort:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            calls.append(request)
            return replace(
                appraisal.result(request, appraisal.output(cause_ref=event.envelope.event_id)),
                completed_at=meaning.NOW + timedelta(seconds=2),
                started_at=meaning.NOW + timedelta(seconds=1),
            )

    class AppraisalLive:
        async def freshness_stamp(self) -> DeepAppraisalFreshnessStamp:
            return DeepAppraisalFreshnessStamp(4, 4 if stale_appraisal else 3)

    target = input_meaning_target(
        (InputMeaningLabCase(fixture, event, refs, meaning.NOW, settings),),
        MeaningPort(),
        MeaningLive(),
        policy,
        PROVENANCE,
        "1",
        (),
        appraisal_bindings=MeaningAppraisalBindings(
            AppraisalPort(), AppraisalLive(), executive_bindings
        ),
    )
    return fixture, ValidationRunner((target,), POLICY), calls


def request(
    *,
    repeat_count: int = 1,
    failure_injections: tuple[FailureInjection, ...] = (),
) -> LabRunSpec:
    return replace(
        spec(),
        target_module="meaning_appraisal",
        mode=LabMode.ADJACENT,
        repeat_count=repeat_count,
        failure_injections=failure_injections,
    )


def object_value(value: JsonValue) -> Mapping[str, JsonValue]:
    assert isinstance(value, Mapping)
    return value


def first_object(value: JsonValue) -> Mapping[str, JsonValue]:
    assert isinstance(value, (tuple, list)) and value
    return object_value(value[0])


@pytest.mark.asyncio
async def test_exact_accepted_meaning_and_source_reach_appraisal() -> None:
    fixture, runner, calls = setup()
    result = await runner.run(request(), fixture)
    assert result.status is RunStatus.COMPLETED and result.machine_gate is Gate.NOT_RUN
    value = object_value(result.stage_results[0].typed_outputs)
    accepted = object_value(object_value(value["input_meaning"])["meaning"])
    assert len(calls) == 1
    assert object_value(calls[0].input.value)["meaning"] == accepted
    assert object_value(value["appraisal"])["request_input"] == calls[0].input.value
    candidate = object_value(object_value(value["appraisal"])["candidate"])
    assert candidate["source_event_ids"] == (accepted["source_event_id"],)
    assert candidate["source_context_revision"] == accepted["source_context_revision"]
    assert runner.pending_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", [False, True])
async def test_unavailable_or_stale_meaning_never_invokes_appraisal(stale: bool) -> None:
    fixture, runner, calls = setup(stale_meaning=stale)
    injections = (
        ()
        if stale
        else (FailureInjection("input_meaning.llm", InjectedFailure.PROVIDER_UNAVAILABLE, 1),)
    )
    result = await runner.run(request(failure_injections=injections), fixture)
    assert result.status is (RunStatus.BLOCKED_UPSTREAM if stale else RunStatus.PROVIDER_FAILED)
    assert calls == []
    assert object_value(result.stage_results[0].typed_outputs)["appraisal"] is None


@pytest.mark.asyncio
async def test_actual_appraisal_rejects_stale_state() -> None:
    fixture, runner, calls = setup(stale_appraisal=True)
    result = await runner.run(request(), fixture)
    assert len(calls) == 1 and result.status is RunStatus.PRODUCT_FAILED
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_deep_candidate_reaches_state_owner_and_repeats_are_isolated() -> None:
    fixture, runner, calls = setup(
        state_commit=AppraisalStateCommitSettings(4, meaning.NOW + timedelta(seconds=3))
    )
    result = await runner.run(request(repeat_count=2), fixture)
    assert result.status is RunStatus.COMPLETED and result.machine_gate is Gate.NOT_RUN
    assert len(calls) == 2
    for stage in result.stage_results:
        value = object_value(object_value(stage.typed_outputs)["appraisal"])
        before, after = object_value(value["before"]), object_value(value["after"])
        assert before["revision"] == 3 and after["revision"] == 4
        old_facet, new_facet = first_object(before["facets"]), first_object(after["facets"])
        proposal = first_object(object_value(value["candidate"])["proposals"])
        assert new_facet["cause_refs"] == proposal["cause_refs"]
        old, delta = old_facet["current"], proposal["delta"]
        assert isinstance(old, (int, float)) and isinstance(delta, (int, float))
        assert new_facet["current"] == pytest.approx(old + delta)
    assert [item.stage for item in result.timeline].count("appraisal.state_commit") == 2
    assert runner.pending_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("stale_context", [False, True])
async def test_state_owner_rejects_old_commit_time_or_changed_context(stale_context: bool) -> None:
    settings = AppraisalStateCommitSettings(
        5 if stale_context else 4,
        meaning.NOW + timedelta(seconds=3) if stale_context else meaning.NOW,
    )
    fixture, runner, calls = setup(state_commit=settings)
    result = await runner.run(request(), fixture)
    assert len(calls) == 1 and result.status is RunStatus.PRODUCT_FAILED
    assert any(
        item.stage == "appraisal.state_commit" and item.status is RunStatus.PRODUCT_FAILED
        for item in result.timeline
    )
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_rejected_meaning_never_commits_internal_state() -> None:
    fixture, runner, calls = setup(
        stale_meaning=True,
        state_commit=AppraisalStateCommitSettings(4, meaning.NOW + timedelta(seconds=3)),
    )
    result = await runner.run(request(), fixture)
    assert result.status is RunStatus.BLOCKED_UPSTREAM
    assert calls == []
    assert not any(item.stage == "appraisal.state_commit" for item in result.timeline)
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_committed_appraisal_reaches_attention_with_owner_lineage() -> None:
    fixture, runner, calls = setup(
        state_commit=AppraisalStateCommitSettings(4, meaning.NOW + timedelta(seconds=3)),
        attention=AppraisalAttentionSettings(
            AttentionSchedulingPolicy.production(), 7, meaning.NOW + timedelta(seconds=4)
        ),
    )
    result = await runner.run(request(repeat_count=2), fixture)
    assert result.status is RunStatus.COMPLETED and result.machine_gate is Gate.NOT_RUN
    assert len(calls) == 2
    for stage in result.stage_results:
        value = object_value(object_value(stage.typed_outputs)["appraisal"])
        candidate = object_value(value["candidate"])
        attention = object_value(value["attention"])
        signal, claim = object_value(attention["signal"]), object_value(attention["claimed"])
        assert signal["source_ref"] == claim["source_ref"] == candidate["candidate_id"]
        assert (
            signal["source_revision"]
            == claim["source_revision"]
            == candidate["base_state_revision"]
        )
        assert signal["source_context_revision"] == claim["source_context_revision"] == 4
        assert claim["goal_revision"] == 7 and claim["reason_kind"] == "appraisal"
        assert attention["enqueued_triggers"] == (claim,)
        assert object_value(value["after"])["revision"] == 4
        assert object_value(attention["snapshot"])["selection_epoch"] == 1
    stages = [item.stage for item in result.timeline]
    assert stages.index("appraisal.state_commit") < stages.index("attention.handle")
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_idle_attention_start_does_not_use_interruption_threshold() -> None:
    policy = AttentionSchedulingPolicy.production()
    policy = replace(
        policy,
        interruption_thresholds=tuple(
            replace(t, minimum_challenger_priority=AttentionPriority.DIRECT_USER)
            for t in policy.interruption_thresholds
        ),
    )
    fixture, runner, _ = setup(
        state_commit=AppraisalStateCommitSettings(4, meaning.NOW + timedelta(seconds=3)),
        attention=AppraisalAttentionSettings(policy, 7, meaning.NOW + timedelta(seconds=4)),
    )
    result = await runner.run(request(), fixture)
    assert result.status is RunStatus.COMPLETED
    value = object_value(object_value(result.stage_results[0].typed_outputs)["appraisal"])
    attention = object_value(value["attention"])
    claim = object_value(attention["claimed"])
    assert claim["claim_relation"] == "idle_start"
    assert claim["interruption_allowed"] is False
    assert attention["enqueued_triggers"] == (claim,)
    assert object_value(attention["snapshot"])["selection_epoch"] == 1
    assert object_value(value["after"])["revision"] == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("stale_meaning", [False, True])
async def test_failed_upstream_never_reaches_attention(stale_meaning: bool) -> None:
    fixture, runner, _ = setup(
        stale_meaning=stale_meaning,
        state_commit=AppraisalStateCommitSettings(5, meaning.NOW + timedelta(seconds=3)),
        attention=AppraisalAttentionSettings(
            AttentionSchedulingPolicy.production(), 7, meaning.NOW + timedelta(seconds=4)
        ),
    )
    result = await runner.run(request(), fixture)
    assert result.status is (
        RunStatus.BLOCKED_UPSTREAM if stale_meaning else RunStatus.PRODUCT_FAILED
    )
    assert not any(item.stage == "attention.handle" for item in result.timeline)
    assert runner.pending_count == 0


def test_attention_after_commit_cannot_skip_state_commit() -> None:
    with pytest.raises(ValueError, match="状態確定"):
        setup(
            attention=AppraisalAttentionSettings(
                AttentionSchedulingPolicy.production(), 7, meaning.NOW + timedelta(seconds=4)
            )
        )
