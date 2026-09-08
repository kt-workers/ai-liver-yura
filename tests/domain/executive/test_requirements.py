"""必須要件の正本導出と最終確定の現在性を検証する。"""

from collections.abc import Mapping
from dataclasses import replace

import pytest

from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY as BOUNDS
from app.domain.contracts import CapabilityRequirement
from app.domain.contracts.finalization import (
    AuthorityFinalizationParticipant,
    FinalizationError,
    FinalizationFailure,
)
from app.domain.executive import (
    ExecutiveCommitState,
    ExecutiveContextSnapshot,
    ExecutiveDecisionAuthority,
    ExecutiveIntentKind,
    ExecutiveIntentRequirementRule,
    ExecutiveIntentRequirementsPolicy,
    ExecutivePreconditionRequirement,
    ExecutiveRequirementsOwner,
    RequirementMode,
    RequirementSelector,
    RequirementsFailureCode,
    RequirementSourcePublication,
    RequirementSourceSpec,
    RequirementsRejected,
    SpeechIntentPayload,
    UpstreamRequirementRecord,
)
from app.domain.executive.contracts import IntentPayload
from tests.domain.executive.test_executive import NOW, candidate, live_state, snapshot


def rule() -> ExecutiveIntentRequirementRule:
    return ExecutiveIntentRequirementRule(
        "speech-rule",
        1,
        "requirements",
        1,
        ExecutiveIntentKind.SPEECH,
        RequirementSelector(),
        RequirementMode.CONSTANT,
        (CapabilityRequirement("speech", "prepare"),),
        (ExecutivePreconditionRequirement("pre-turn", "available"),),
    )


def owner() -> ExecutiveRequirementsOwner:
    result = ExecutiveRequirementsOwner(BOUNDS)
    result.publish(ExecutiveIntentRequirementsPolicy("requirements", 1, (rule(),)))
    return result


def test_constant_requirements_commit_with_public_origin() -> None:
    requirements = owner()
    captured = requirements.capture(snapshot())
    current = requirements.prepare(captured, candidate(), live_state())
    authority = ExecutiveDecisionAuthority(requirements)
    committed = authority.commit(
        candidate(), captured, current=current, decision_id="decision", committed_at=NOW
    )
    assert committed.requirement_derivations[0].provenance.rule_id == "speech-rule"
    assert committed.to_dict()["requirement_derivations"]
    assert captured.to_dict()["requirements_generation"]
    assert authority.has_committed(captured.trigger_id)


@pytest.mark.parametrize("change", ["omit", "extra", "degraded", "expected"])
def test_candidate_cannot_choose_its_requirements(change: str) -> None:
    requirements = owner()
    captured = requirements.capture(snapshot())
    original = candidate()
    intent = original.intents[0]
    if change == "omit":
        intent = replace(intent, required_capabilities=())
    elif change == "extra":
        intent = replace(
            intent,
            required_capabilities=(
                *intent.required_capabilities,
                CapabilityRequirement("extra", "run"),
            ),
        )
    elif change == "degraded":
        intent = replace(
            intent, required_capabilities=(CapabilityRequirement("speech", "prepare", True),)
        )
    else:
        intent = replace(
            intent, preconditions=(ExecutivePreconditionRequirement("pre-turn", True),)
        )
    proposed = replace(original, intents=(intent,))
    current = requirements.prepare(captured, proposed, live_state())
    authority = ExecutiveDecisionAuthority(requirements)
    with pytest.raises(RequirementsRejected) as failure:
        authority.commit(
            proposed, captured, current=current, decision_id="decision", committed_at=NOW
        )
    assert failure.value.failure.code is RequirementsFailureCode.CANDIDATE_MISMATCH
    assert not authority.has_committed(captured.trigger_id)


def test_unregistered_and_changed_policy_fail_without_empty_success() -> None:
    requirements = ExecutiveRequirementsOwner(BOUNDS)
    with pytest.raises(RequirementsRejected):
        requirements.capture(snapshot())
    requirements = owner()
    captured = requirements.capture(snapshot())
    requirements.publish(
        ExecutiveIntentRequirementsPolicy("requirements", 2, (replace(rule(), policy_revision=2),))
    )
    derived = requirements.derive(captured, candidate())
    assert derived.failure is not None
    assert derived.failure.code is RequirementsFailureCode.STALE_POLICY
    assert derived.values == ()


class Source:
    """型付き上流記録を公開する試験用の正規所有者。"""

    def __init__(self) -> None:
        self.participant = AuthorityFinalizationParticipant(self, "source", 15)


def test_upstream_source_mutation_after_derive_never_commits() -> None:
    source = Source()
    record = UpstreamRequirementRecord(
        "source",
        "typed-requirements",
        "record",
        1,
        "answer-user",
        ExecutiveIntentKind.SPEECH,
        SpeechIntentPayload("answer-user"),
        rule().capabilities,
        rule().preconditions,
    )
    publication = RequirementSourcePublication("source", 1, record, (source.participant.token(),))
    upstream_rule = replace(
        rule(),
        mode=RequirementMode.UPSTREAM,
        capabilities=(),
        preconditions=(),
        source=RequirementSourceSpec("source", "typed-requirements", "semantic_goal_ref"),
    )
    requirements = ExecutiveRequirementsOwner(BOUNDS)
    requirements.publish(
        ExecutiveIntentRequirementsPolicy("requirements", 1, (upstream_rule,)), (publication,)
    )
    captured = requirements.capture(snapshot())
    current = requirements.prepare(captured, candidate(), live_state())
    with source.participant.mutation():
        pass
    authority = ExecutiveDecisionAuthority(requirements)
    with pytest.raises(FinalizationError):
        authority.commit(
            candidate(), captured, current=current, decision_id="decision", committed_at=NOW
        )
    assert not authority.has_committed(captured.trigger_id)


def test_busy_requirements_owner_does_not_block_commit() -> None:
    from concurrent.futures import ThreadPoolExecutor

    requirements = owner()
    captured = requirements.capture(snapshot())
    current = requirements.prepare(captured, candidate(), live_state())
    authority = ExecutiveDecisionAuthority(requirements)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with requirements.finalization_participant:
            pending = pool.submit(
                authority.commit,
                candidate(),
                captured,
                current=current,
                decision_id="busy",
                committed_at=NOW,
            )
            with pytest.raises(FinalizationError, match="PARTICIPANT_BUSY"):
                pending.result(timeout=0.2)
    assert not authority.has_committed(captured.trigger_id)


@pytest.mark.parametrize("matches", [0, 1, 2])
def test_rule_selection_requires_exactly_one_match(matches: int) -> None:
    requirements = ExecutiveRequirementsOwner(BOUNDS)
    rules = tuple(replace(rule(), rule_id=f"rule-{i}") for i in range(matches))
    requirements.publish(ExecutiveIntentRequirementsPolicy("requirements", 1, rules))
    result = requirements.derive(requirements.capture(snapshot()), candidate())
    if matches == 1:
        assert result.failure is None and len(result.values) == 1
    else:
        assert result.values == () and result.failure is not None
        expected = (
            RequirementsFailureCode.RULE_UNREGISTERED
            if matches == 0
            else RequirementsFailureCode.AMBIGUOUS_RULE
        )
        assert result.failure.code is expected


@pytest.mark.parametrize("expected,claimed", [(True, 1), (1, "1"), ([1, 2], [2, 1])])
def test_expected_json_never_coerces_types_or_array_order(
    expected: object, claimed: object
) -> None:
    from app.domain.contracts.common import freeze_json

    requirements = ExecutiveRequirementsOwner(BOUNDS)
    selected = replace(
        rule(), preconditions=(ExecutivePreconditionRequirement("pre-turn", freeze_json(expected)),)
    )
    requirements.publish(ExecutiveIntentRequirementsPolicy("requirements", 1, (selected,)))
    captured = requirements.capture(snapshot())
    original = candidate()
    proposed = replace(
        original,
        intents=(
            replace(
                original.intents[0],
                preconditions=(ExecutivePreconditionRequirement("pre-turn", freeze_json(claimed)),),
            ),
        ),
    )
    current = requirements.prepare(captured, proposed, live_state())
    with pytest.raises(RequirementsRejected) as failure:
        ExecutiveDecisionAuthority(requirements).commit(
            proposed, captured, current=current, decision_id="typed", committed_at=NOW
        )
    assert failure.value.failure.code is RequirementsFailureCode.CANDIDATE_MISMATCH


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["llm", "live"])
async def test_policy_change_during_await_never_reuses_old_candidate(phase: str) -> None:
    from app.domain.executive import (
        ExecutiveCommitState,
        ExecutiveContextSnapshot,
        ExecutiveDecisionCandidate,
        ExecutiveDeliberator,
    )
    from app.domain.llm import LLMRoleRequest, LLMRoleResult
    from tests.domain.executive.test_executive import policy, success

    requirements = owner()
    authority = ExecutiveDecisionAuthority(requirements)

    def update() -> None:
        requirements.publish(
            ExecutiveIntentRequirementsPolicy(
                "requirements", 2, (replace(rule(), policy_revision=2),)
            )
        )

    class Port:
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            assert isinstance(request.input.value, Mapping)
            assert request.input.value["requirements_generation"]
            if phase == "llm":
                update()
            return success(request)

    class Live:
        async def current_for_commit(
            self, context: ExecutiveContextSnapshot, proposed: ExecutiveDecisionCandidate
        ) -> ExecutiveCommitState:
            if phase == "live":
                update()
            return live_state()

    with pytest.raises((RequirementsRejected, FinalizationError)):
        await ExecutiveDeliberator(Port(), Live(), policy(), authority).deliberate(
            snapshot(),
            request_id="changing-policy",
            trace_id="changing-policy",
            decision_id="changing-policy",
            created_at=NOW,
        )
    assert not authority.has_committed("trigger-1")


def test_failed_and_noop_publications_invalidate_old_capture() -> None:
    requirements = owner()
    captured = requirements.capture(snapshot())
    generation = captured.requirements_generation
    assert generation is not None
    requirements.publish(generation.policy)
    assert requirements.derive(captured, candidate()).failure is not None
    captured = requirements.capture(snapshot())
    with pytest.raises(RequirementsRejected):
        requirements.publish(replace(generation.policy, rules=(replace(rule(), capabilities=()),)))
    assert requirements.derive(captured, candidate()).failure is not None


@pytest.mark.parametrize(
    "kind",
    [
        ExecutiveIntentKind.SPEECH,
        ExecutiveIntentKind.BODY,
        ExecutiveIntentKind.ACTIVITY,
        ExecutiveIntentKind.ATTENTION,
    ],
)
@pytest.mark.parametrize("mode", [RequirementMode.CONSTANT, RequirementMode.UPSTREAM])
def test_typed_selector_and_explicit_empty_requirements(
    kind: ExecutiveIntentKind, mode: RequirementMode
) -> None:
    from app.domain.executive import (
        ActivityIntentPayload,
        AttentionIntentPayload,
        BodyIntentPayload,
        ExecutiveIntent,
        ExecutiveOutcome,
        RequirementSelectorField,
    )

    payloads: dict[ExecutiveIntentKind, IntentPayload] = {
        ExecutiveIntentKind.SPEECH: SpeechIntentPayload("answer-user"),
        ExecutiveIntentKind.BODY: BodyIntentPayload("answer-user"),
        ExecutiveIntentKind.ACTIVITY: ActivityIntentPayload("prepare"),
        ExecutiveIntentKind.ATTENTION: AttentionIntentPayload("answer-user", "focus"),
    }
    selectors = {
        ExecutiveIntentKind.SPEECH: (
            RequirementSelectorField.SEMANTIC_GOAL,
            "answer-user",
            "semantic_goal_ref",
            "answer-user",
        ),
        ExecutiveIntentKind.BODY: (
            RequirementSelectorField.MOTION_GOAL,
            "answer-user",
            "motion_goal_ref",
            "answer-user",
        ),
        ExecutiveIntentKind.ACTIVITY: (
            RequirementSelectorField.ACTIVITY_TYPE,
            "prepare",
            "activity_type",
            "prepare",
        ),
        ExecutiveIntentKind.ATTENTION: (
            RequirementSelectorField.ATTENTION_MODE,
            "focus",
            "target_ref",
            "answer-user",
        ),
    }
    field, value, reference_field, reference = selectors[kind]
    intent = ExecutiveIntent("selected", kind, "型付き規則を選択する", payloads[kind])
    source = Source()
    record = UpstreamRequirementRecord(
        "source", "typed", "record", 1, reference, kind, payloads[kind], (), ()
    )
    published = RequirementSourcePublication("record", 1, record, (source.participant.token(),))
    selected = replace(
        rule(),
        intent_kind=kind,
        selector=RequirementSelector(field, value),
        mode=mode,
        capabilities=(),
        preconditions=(),
        source=RequirementSourceSpec("source", "typed", reference_field)
        if mode is RequirementMode.UPSTREAM
        else None,
    )
    requirements = ExecutiveRequirementsOwner(BOUNDS)
    requirements.publish(
        ExecutiveIntentRequirementsPolicy("requirements", 1, (selected,)),
        (published,) if mode is RequirementMode.UPSTREAM else (),
    )
    proposed = replace(candidate(), intents=(intent,), outcome=ExecutiveOutcome.CONTINUE_ACTIVITY)
    result = requirements.derive(requirements.capture(snapshot()), proposed)
    assert result.failure is None and len(result.values) == 1
    assert result.values[0].requirements.capabilities == ()
    assert result.values[0].requirements.preconditions == ()
    assert result.values[0].provenance.rule_id == selected.rule_id
    assert bool(result.values[0].provenance.sources) is (mode is RequirementMode.UPSTREAM)


def test_removed_rule_cannot_change_content_without_advancing_its_revision() -> None:
    requirements = owner()
    requirements.publish(ExecutiveIntentRequirementsPolicy("requirements", 2, ()))
    with pytest.raises(RequirementsRejected) as failure:
        requirements.publish(
            ExecutiveIntentRequirementsPolicy(
                "requirements", 3, (replace(rule(), policy_revision=3, capabilities=()),)
            )
        )
    assert failure.value.failure.code is RequirementsFailureCode.STALE_POLICY


def test_rule_revision_history_is_bounded_and_allows_new_revision() -> None:
    bounded = replace(BOUNDS, executive=replace(BOUNDS.executive, max_fact_refs=1))
    requirements = ExecutiveRequirementsOwner(bounded)
    requirements.publish(ExecutiveIntentRequirementsPolicy("requirements", 1, (rule(),)))
    requirements.publish(ExecutiveIntentRequirementsPolicy("requirements", 2, ()))
    updated = replace(rule(), policy_revision=3, revision=2, capabilities=())
    requirements.publish(ExecutiveIntentRequirementsPolicy("requirements", 3, (updated,)))
    with pytest.raises(RequirementsRejected) as failure:
        requirements.publish(
            ExecutiveIntentRequirementsPolicy(
                "requirements", 4, (replace(updated, rule_id="second", policy_revision=4),)
            )
        )
    assert failure.value.failure.code is RequirementsFailureCode.INVALID_PROJECTION


def test_same_rule_revision_distinguishes_boolean_and_number() -> None:
    requirements = ExecutiveRequirementsOwner(BOUNDS)
    original = replace(rule(), preconditions=(ExecutivePreconditionRequirement("pre-turn", True),))
    requirements.publish(ExecutiveIntentRequirementsPolicy("requirements", 1, (original,)))
    changed = replace(
        original,
        policy_revision=2,
        preconditions=(ExecutivePreconditionRequirement("pre-turn", 1),),
    )
    with pytest.raises(RequirementsRejected) as failure:
        requirements.publish(ExecutiveIntentRequirementsPolicy("requirements", 2, (changed,)))
    assert failure.value.failure.code is RequirementsFailureCode.STALE_POLICY


def upstream_inputs(
    used_count: int = 1,
) -> tuple[
    ExecutiveRequirementsOwner,
    ExecutiveContextSnapshot,
    ExecutiveCommitState,
    tuple[Source, ...],
    tuple[Source, ...],
]:
    used = tuple(Source() for _ in range(used_count))
    unused = tuple(Source() for _ in range(20))
    record = UpstreamRequirementRecord(
        "source",
        "typed",
        "record",
        1,
        "answer-user",
        ExecutiveIntentKind.SPEECH,
        SpeechIntentPayload("answer-user"),
        rule().capabilities,
        rule().preconditions,
    )
    selected = replace(
        rule(),
        mode=RequirementMode.UPSTREAM,
        capabilities=(),
        preconditions=(),
        source=RequirementSourceSpec("source", "typed", "semantic_goal_ref"),
    )
    requirements = ExecutiveRequirementsOwner(BOUNDS)
    requirements.publish(
        ExecutiveIntentRequirementsPolicy("requirements", 1, (selected,)),
        (
            RequirementSourcePublication(
                "used", 1, record, tuple(x.participant.token() for x in used)
            ),
            RequirementSourcePublication(
                "unused",
                1,
                replace(record, reference="unused"),
                tuple(x.participant.token() for x in unused),
            ),
        ),
    )
    captured = requirements.capture(snapshot())
    current = requirements.prepare(captured, candidate(), live_state())
    return requirements, captured, current, used, unused


@pytest.mark.parametrize("used_source", [True, False])
@pytest.mark.parametrize("change", ["updated", "busy"])
def test_fence_checks_only_sources_used_by_verified_derivation(
    used_source: bool,
    change: str,
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import nullcontext

    requirements, captured, current, used, unused = upstream_inputs()
    selected = used[0] if used_source else unused[0]
    if change == "updated":
        with selected.participant.mutation():
            pass
    authority = ExecutiveDecisionAuthority(requirements)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with selected.participant if change == "busy" else nullcontext():
            pending = pool.submit(
                authority.commit,
                candidate(),
                captured,
                current=current,
                decision_id="selected-source",
                committed_at=NOW,
            )
            if used_source:
                with pytest.raises(FinalizationError) as failure:
                    pending.result(timeout=1)
                assert failure.value.failure is (
                    FinalizationFailure.GENERATION_MISMATCH
                    if change == "updated"
                    else FinalizationFailure.PARTICIPANT_BUSY
                )
            else:
                assert pending.result(timeout=1).decision_id == "selected-source"
    assert authority.has_committed(captured.trigger_id) is not used_source


@pytest.mark.parametrize("source_count", [14, 15])
def test_fence_keeps_foundation_participant_limit(source_count: int) -> None:
    requirements, captured, current, _, _ = upstream_inputs(source_count)
    authority = ExecutiveDecisionAuthority(requirements)
    if source_count == 14:
        result = authority.commit(candidate(), captured, current=current, decision_id="limit")
        assert result.decision_id == "limit"
        assert result.plan_authorizations == ()
        assert result.plan_progress_assessments == ()
    else:
        with pytest.raises(FinalizationError) as failure:
            authority.commit(candidate(), captured, current=current, decision_id="limit")
        assert failure.value.failure is FinalizationFailure.INVALID_LOCK_CONFIGURATION
        assert not authority.has_committed(captured.trigger_id)


@pytest.mark.parametrize("publication", ["success", "noop", "rejected"])
def test_fresh_capture_recovers_current_value_after_publication(publication: str) -> None:
    requirements, old, _, _, _ = upstream_inputs()
    generation = old.requirements_generation
    assert generation is not None
    policy = generation.policy
    if publication == "success":
        policy = replace(
            policy, revision=2, rules=tuple(replace(r, policy_revision=2) for r in policy.rules)
        )
    if publication == "rejected":
        with pytest.raises(RequirementsRejected):
            requirements.publish(replace(policy, rules=()), generation.sources)
    else:
        requirements.publish(policy, generation.sources)
    assert requirements.derive(old, candidate()).failure is not None
    fresh = requirements.capture(snapshot())
    fresh_generation = fresh.requirements_generation
    assert fresh_generation is not None
    assert fresh_generation.policy == policy
    assert fresh_generation.sources == generation.sources
    assert fresh_generation.token != generation.token
    assert requirements.derive(old, candidate()).failure is not None
    current = requirements.prepare(fresh, candidate(), live_state())
    assert (
        ExecutiveDecisionAuthority(requirements)
        .commit(
            candidate(),
            fresh,
            current=current,
            decision_id="fresh",
        )
        .decision_id
        == "fresh"
    )


@pytest.mark.parametrize("caller_days", [-10, 10])
def test_pre_fence_timestamp_cannot_override_final_time(caller_days: int) -> None:
    from datetime import timedelta

    from tests.helpers.executive_requirements import fence_clock

    requirements = owner()
    captured = requirements.capture(snapshot())
    current = requirements.prepare(captured, candidate(), live_state())
    final_time = NOW + timedelta(seconds=10)
    with fence_clock(lambda: final_time):
        decision = ExecutiveDecisionAuthority(requirements).commit(
            candidate(),
            captured,
            current=current,
            decision_id="fence-time",
            committed_at=NOW + timedelta(days=caller_days),
        )
    assert decision.committed_at == final_time


@pytest.mark.parametrize("kind", ["scope", "context"])
@pytest.mark.parametrize("used_source", [True, False])
@pytest.mark.parametrize("change", ["updated", "busy"])
def test_plan_sources_use_only_verified_scope_or_context(
    kind: str,
    used_source: bool,
    change: str,
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import nullcontext

    from tests.domain.executive.test_plan_authorization import inputs
    from tests.domain.executive.test_plan_progress import progress_inputs
    from tests.helpers.executive_requirements import fence_clock

    proposed, captured, current = inputs() if kind == "scope" else progress_inputs()
    generation = captured.requirements_generation
    assert generation is not None
    unused = Source()
    extra = RequirementSourcePublication(
        "unrelated",
        1,
        UpstreamRequirementRecord(
            "source",
            "unused",
            "unrelated",
            1,
            "unrelated",
            ExecutiveIntentKind.SPEECH,
            SpeechIntentPayload("unrelated"),
            (),
            (),
        ),
        (unused.participant.token(),),
    )
    requirements = generation.owner
    requirements.publish(generation.policy, (*generation.sources, extra))
    captured = requirements.capture(captured)
    current = requirements.prepare(captured, proposed, current)
    participant = (
        generation.sources[0].tokens[0]._participant if used_source else unused.participant
    )
    if change == "updated":
        with participant.mutation():
            pass
    authority = ExecutiveDecisionAuthority(requirements)
    with fence_clock(lambda: proposed.created_at), ThreadPoolExecutor(max_workers=1) as pool:
        with participant if change == "busy" else nullcontext():
            result = pool.submit(
                authority.commit, proposed, captured, current=current, decision_id="plan"
            )
            if used_source:
                with pytest.raises(FinalizationError) as failure:
                    result.result(timeout=1)
                assert failure.value.failure is (
                    FinalizationFailure.GENERATION_MISMATCH
                    if change == "updated"
                    else FinalizationFailure.PARTICIPANT_BUSY
                )
            else:
                decision = result.result(timeout=1)
                if kind == "scope":
                    assert len(decision.plan_authorizations) == 1
                    assert decision.plan_authorizations[0].committed_at == decision.committed_at
                else:
                    assert len(decision.plan_progress_assessments) == 1
                    assert (
                        decision.plan_progress_assessments[0].committed_at == decision.committed_at
                    )
    assert authority.has_committed(captured.trigger_id) is not used_source
