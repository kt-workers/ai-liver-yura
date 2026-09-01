import asyncio
from dataclasses import replace

import pytest

from app.domain.brain_operational_bounds import (
    V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    BrainOperationalBoundsPolicy,
)
from app.domain.speech_semantics import (
    SemanticCertainty,
    SemanticPolarity,
    SpeechProposition,
    SpeechPropositionDisposition,
    SpeechSemanticAuthority,
    SpeechSemanticBoundsError,
    SpeechSemanticBoundsFailureCode,
    SpeechSemanticContextSnapshot,
    SpeechSemanticFact,
    SpeechSemanticFactKind,
    SpeechSemanticsPlanner,
    SpeechTruthConstraint,
    SpeechTruthRule,
    build_bounded_speech_semantic_context,
    build_request,
    validate_speech_semantic_context_bounds,
    validate_speech_semantic_output_bounds,
)
from tests.domain.speech_semantics.test_speech_semantics import (
    NOW,
    REVISIONS,
    candidate,
    candidate_json,
    context,
    facts,
    policy,
    propositions,
    result_for,
)


def extra_fact(index: int) -> SpeechSemanticFact:
    return SpeechSemanticFact(
        f"optional-{index:03d}",
        SpeechSemanticFactKind.GENERAL,
        "optional-subject",
        f"optional-{index:03d}",
        {"index": index},
    )


def test_bounded_context_keeps_required_facts_and_stably_selects_optional() -> None:
    source = replace(
        context(deterministic=False),
        facts=facts() + tuple(extra_fact(index) for index in range(130)),
    )
    bounded = build_bounded_speech_semantic_context(
        source,
        V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    )
    selected_ids = {item.fact_id for item in bounded.facts}
    assert {"fact-goal", "fact-desire", "fact-forbidden", "fact-execution"}.issubset(
        selected_ids
    )
    assert len(bounded.facts) == 128
    assert len(source.facts) == 134


def test_context_fact_truth_and_constraint_pool_boundaries() -> None:
    at_limit = replace(
        context(deterministic=False),
        facts=facts() + tuple(extra_fact(index) for index in range(124)),
    )
    validate_speech_semantic_context_bounds(at_limit, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    with pytest.raises(SpeechSemanticBoundsError) as fact_error:
        validate_speech_semantic_context_bounds(
            replace(at_limit, facts=at_limit.facts + (extra_fact(999),)),
            V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
        )
    assert fact_error.value.code is SpeechSemanticBoundsFailureCode.CONTEXT_TOO_LARGE

    constraints = (
        SpeechTruthConstraint("truth-match", "fact-execution", SpeechTruthRule.REQUIRE_MATCH),
    ) + tuple(
        SpeechTruthConstraint(f"truth-{index}", "fact-execution", SpeechTruthRule.REQUIRE_MATCH)
        for index in range(127)
    )
    truth_limit = replace(context(deterministic=False), truth_constraints=constraints)
    validate_speech_semantic_context_bounds(truth_limit, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    with pytest.raises(SpeechSemanticBoundsError):
        validate_speech_semantic_context_bounds(
            replace(
                truth_limit,
                truth_constraints=constraints
                + (
                    SpeechTruthConstraint(
                        "truth-over", "fact-execution", SpeechTruthRule.REQUIRE_MATCH
                    ),
                ),
            ),
            V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
        )

    pool = ("relationship-soft", "discourse-answer") + tuple(
        f"constraint-{index}" for index in range(126)
    )
    pool_limit = replace(context(deterministic=False), available_constraint_refs=pool)
    validate_speech_semantic_context_bounds(pool_limit, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    with pytest.raises(SpeechSemanticBoundsError):
        validate_speech_semantic_context_bounds(
            replace(pool_limit, available_constraint_refs=pool + ("constraint-over",)),
            V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
        )


def test_fact_payload_16384_16385_byte_boundary() -> None:
    equal_fact = replace(facts()[0], value="x" * 16382)
    equal = replace(context(deterministic=False), facts=(equal_fact, *facts()[1:]))
    validate_speech_semantic_context_bounds(equal, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)

    above_fact = replace(facts()[0], value="x" * 16383)
    above = replace(context(deterministic=False), facts=(above_fact, *facts()[1:]))
    with pytest.raises(SpeechSemanticBoundsError) as error:
        validate_speech_semantic_context_bounds(above, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    assert error.value.code is SpeechSemanticBoundsFailureCode.CONTEXT_TOO_LARGE


def repeated_propositions(count: int) -> tuple[SpeechProposition, ...]:
    source = propositions()[0]
    return tuple(replace(source, proposition_id=f"proposition-{index}") for index in range(count))


@pytest.mark.parametrize("count", [64, 65])
def test_proposition_64_65_boundary(count: int) -> None:
    value = replace(candidate(), propositions=repeated_propositions(count))
    if count == 64:
        validate_speech_semantic_output_bounds(value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    else:
        with pytest.raises(SpeechSemanticBoundsError) as error:
            validate_speech_semantic_output_bounds(value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
        assert error.value.code is SpeechSemanticBoundsFailureCode.OUTPUT_TOO_LARGE


@pytest.mark.parametrize("count", [16, 17])
def test_evidence_16_17_boundary(count: int) -> None:
    proposition = SpeechProposition(
        "bounded-evidence",
        "subject",
        "predicate",
        {"value": True},
        SpeechPropositionDisposition.OPTIONAL,
        SemanticPolarity.AFFIRM,
        SemanticCertainty.CERTAIN,
        tuple(f"fact-{index}" for index in range(count)),
    )
    value = replace(candidate(), propositions=(proposition,))
    if count == 16:
        validate_speech_semantic_output_bounds(value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    else:
        with pytest.raises(SpeechSemanticBoundsError):
            validate_speech_semantic_output_bounds(value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)


@pytest.mark.parametrize("section", ["relationship", "discourse"])
@pytest.mark.parametrize("count", [64, 65])
def test_relationship_and_discourse_64_65_boundary(section: str, count: int) -> None:
    refs = tuple(f"{section}-{index}" for index in range(count))
    value = (
        replace(candidate(), relationship_constraint_refs=refs, discourse_constraint_refs=())
        if section == "relationship"
        else replace(candidate(), relationship_constraint_refs=(), discourse_constraint_refs=refs)
    )
    if count == 64:
        validate_speech_semantic_output_bounds(value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    else:
        with pytest.raises(SpeechSemanticBoundsError):
            validate_speech_semantic_output_bounds(value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)


def test_total_constraint_128_129_boundary() -> None:
    at_limit = replace(
        candidate(),
        truth_constraint_refs=tuple(f"truth-{index}" for index in range(64)),
        relationship_constraint_refs=tuple(f"relationship-{index}" for index in range(64)),
        discourse_constraint_refs=(),
    )
    validate_speech_semantic_output_bounds(at_limit, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    with pytest.raises(SpeechSemanticBoundsError):
        validate_speech_semantic_output_bounds(
            replace(at_limit, discourse_constraint_refs=("discourse-over",)),
            V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
        )


@pytest.mark.parametrize("field_name", ["question_budget", "new_direction_budget"])
@pytest.mark.parametrize("count", [16, 17])
def test_budget_16_17_boundary(field_name: str, count: int) -> None:
    value = (
        replace(candidate(), question_budget=count)
        if field_name == "question_budget"
        else replace(candidate(), new_direction_budget=count)
    )
    if count == 16:
        validate_speech_semantic_output_bounds(value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    else:
        with pytest.raises(SpeechSemanticBoundsError):
            validate_speech_semantic_output_bounds(value, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)


def test_request_rejects_authoritative_budget_above_technical_limit_without_clamp() -> None:
    snapshot = replace(
        context(deterministic=False),
        max_question_budget=17,
    )
    with pytest.raises(SpeechSemanticBoundsError) as error:
        build_request(
            snapshot,
            request_id="request-budget-over",
            trace_id="trace-budget-over",
            created_at=NOW,
            policy=policy(),
        )
    assert error.value.code is SpeechSemanticBoundsFailureCode.CONTEXT_TOO_LARGE
    assert snapshot.max_question_budget == 17


def test_oversized_provider_candidate_is_not_first_n_accepted() -> None:
    payload = candidate_json()
    source = payload["propositions"]
    assert isinstance(source, list)
    first = source[0]
    assert isinstance(first, dict)
    payload["propositions"] = [
        {**first, "proposition_id": f"provider-{index}"} for index in range(65)
    ]
    from app.domain.speech_semantics import parse_candidate

    with pytest.raises(SpeechSemanticBoundsError) as error:
        parse_candidate(payload, created_at=NOW)
    assert error.value.code is SpeechSemanticBoundsFailureCode.OUTPUT_TOO_LARGE


class MutablePolicyState:
    def __init__(self) -> None:
        self.current: BrainOperationalBoundsPolicy = V2_BRAIN_OPERATIONAL_BOUNDS_POLICY

    async def current_policy(
        self, snapshot: SpeechSemanticContextSnapshot
    ) -> BrainOperationalBoundsPolicy:
        return self.current


@pytest.mark.asyncio
async def test_late_llm_result_is_rejected_after_policy_revision_change() -> None:
    invoked = asyncio.Event()
    release = asyncio.Event()

    class Port:
        async def invoke(self, request):  # type: ignore[no-untyped-def]
            invoked.set()
            await release.wait()
            return result_for(request, candidate_json())

    class Live:
        async def current_revisions(self, snapshot):  # type: ignore[no-untyped-def]
            return REVISIONS

    policy_state = MutablePolicyState()
    planner = SpeechSemanticsPlanner(
        Port(),
        Live(),
        SpeechSemanticAuthority(),
        policy(),
        policy_state,
    )
    task = asyncio.create_task(
        planner.plan(
            context(deterministic=False),
            request_id="request-policy-stale",
            trace_id="trace-policy-stale",
            candidate_id="unused-candidate",
            plan_id="plan-policy-stale",
            created_at=NOW,
        )
    )
    await invoked.wait()
    policy_state.current = replace(
        V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
        policy_revision=V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.policy_revision + 1,
    )
    release.set()
    with pytest.raises(SpeechSemanticBoundsError) as error:
        await task
    assert error.value.code is SpeechSemanticBoundsFailureCode.POLICY_STALE
