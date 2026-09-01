import asyncio
from dataclasses import replace
from typing import cast

import pytest

from app.domain.brain_operational_bounds import (
    V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
    BrainOperationalBoundsPolicy,
)
from app.domain.contracts.common import JsonValue, thaw_json
from app.domain.llm import LLMRoleRequest, LLMRoleResult, StructuredPayload
from app.domain.semantic_verification import (
    BLIND_ROLE_ID,
    RELATION_ROLE_ID,
    BlindInteractionAct,
    BlindSemanticUnit,
    BlindSemanticUnitKind,
    BlindUnitAccounting,
    BlindUnitAccountingRelation,
    BlindUtteranceObservationCandidate,
    CertaintyRelation,
    DegreeRelation,
    ExecutionRelation,
    PlanRelationObservationCandidate,
    PolarityRelation,
    PropositionRelation,
    PropositionSemanticObservation,
    SelfDisclosureRelation,
    SemanticVerificationAuthority,
    SemanticVerificationBoundsError,
    SemanticVerificationBoundsFailureCode,
    SemanticVerificationContextSnapshot,
    SemanticVerifier,
    SpeechActBudgetObservation,
    UtteranceEvidenceRef,
    blind_output_schema,
    build_blind_request,
    parse_blind_candidate,
    parse_relation_candidate,
    relation_output_schema,
    validate_blind_candidate_bounds,
    validate_relation_candidate_bounds,
)
from tests.domain.semantic_verification.test_semantic_verification import (
    NOW,
    TEXT,
    _BlockingSequencePort,
    _LiveState,
    _SequencePort,
    _snapshot,
    verification_policy,
)


def evidence(quote: str = TEXT) -> UtteranceEvidenceRef:
    return UtteranceEvidenceRef("segment-1", quote, 0)


def unit(
    index: int,
    *,
    refs: tuple[UtteranceEvidenceRef, ...] | None = None,
    acts: tuple[BlindInteractionAct, ...] = (),
) -> BlindSemanticUnit:
    return BlindSemanticUnit(
        f"unit-{index:03d}",
        BlindSemanticUnitKind.MATERIAL_SEMANTIC_CONTENT,
        acts,
        refs or (evidence(),),
    )


def blind_candidate(count: int) -> BlindUtteranceObservationCandidate:
    snapshot = _snapshot()
    return BlindUtteranceObservationCandidate(
        "blind-bounds-candidate",
        snapshot.blind_request_id,
        snapshot.utterance.utterance_id,
        tuple(unit(index) for index in range(count)),
        NOW,
    )


def missing_observation(index: int) -> PropositionSemanticObservation:
    return PropositionSemanticObservation(
        f"proposition-{index:03d}",
        PropositionRelation.MISSING,
        PolarityRelation.NOT_APPLICABLE,
        CertaintyRelation.NOT_APPLICABLE,
        DegreeRelation.NOT_APPLICABLE,
        ExecutionRelation.NOT_APPLICABLE,
        (),
        (),
    )


def relation_candidate(
    *,
    observation_count: int = 1,
    accounting_count: int = 1,
) -> PlanRelationObservationCandidate:
    snapshot = _snapshot()
    return PlanRelationObservationCandidate(
        "relation-bounds-candidate",
        snapshot.relation_request_id,
        snapshot.semantic_plan.plan_id,
        snapshot.utterance.utterance_id,
        "blind-observation",
        tuple(missing_observation(index) for index in range(observation_count)),
        tuple(
            BlindUnitAccounting(
                f"unit-{index:03d}",
                BlindUnitAccountingRelation.UNSUPPORTED_EXTRA,
                (),
                (),
            )
            for index in range(accounting_count)
        ),
        SpeechActBudgetObservation(0, 0),
        SelfDisclosureRelation.WITHIN_POLICY,
        NOW,
    )


@pytest.mark.parametrize("count", [128, 129])
def test_blind_units_128_129_boundary(count: int) -> None:
    candidate = blind_candidate(count)
    if count == 128:
        validate_blind_candidate_bounds(candidate, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    else:
        with pytest.raises(SemanticVerificationBoundsError) as error:
            validate_blind_candidate_bounds(candidate, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
        assert error.value.code is SemanticVerificationBoundsFailureCode.OBSERVATION_TOO_LARGE
        assert len(candidate.units) == 129


@pytest.mark.parametrize("count", [16, 17])
def test_blind_unit_evidence_16_17_boundary(count: int) -> None:
    candidate = replace(
        blind_candidate(1),
        units=(unit(0, refs=tuple(evidence() for _ in range(count))),),
    )
    if count == 16:
        validate_blind_candidate_bounds(candidate, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    else:
        with pytest.raises(SemanticVerificationBoundsError):
            validate_blind_candidate_bounds(candidate, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)


@pytest.mark.parametrize("count", [512, 513])
def test_quote_512_513_unicode_codepoint_boundary(count: int) -> None:
    quote = "ゆ" * count
    candidate = replace(
        blind_candidate(1),
        units=(unit(0, refs=(evidence(quote),)),),
    )
    assert len(quote.encode("utf-8")) > count
    if count == 512:
        validate_blind_candidate_bounds(candidate, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    else:
        with pytest.raises(SemanticVerificationBoundsError):
            validate_blind_candidate_bounds(candidate, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
        assert candidate.units[0].evidence_refs[0].quote == quote


def test_interaction_act_bound_uses_policy_without_duplicate_enum_fabrication() -> None:
    one = unit(0, acts=(BlindInteractionAct.DIRECTED_QUESTION,))
    two = unit(
        0,
        acts=(BlindInteractionAct.DIRECTED_QUESTION, BlindInteractionAct.NEW_DIRECTION),
    )
    limited = replace(
        V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
        semantic_verification=replace(
            V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.semantic_verification,
            max_interaction_acts_per_unit=1,
        ),
    )
    validate_blind_candidate_bounds(replace(blind_candidate(1), units=(one,)), limited)
    with pytest.raises(SemanticVerificationBoundsError):
        validate_blind_candidate_bounds(replace(blind_candidate(1), units=(two,)), limited)


@pytest.mark.parametrize("count", [32, 33])
def test_supporting_units_32_33_boundary(count: int) -> None:
    observation = PropositionSemanticObservation(
        "prop-supported",
        PropositionRelation.ENTAILED,
        PolarityRelation.PRESERVED,
        CertaintyRelation.PRESERVED,
        DegreeRelation.PRESERVED,
        ExecutionRelation.NOT_APPLICABLE,
        (evidence(),),
        tuple(f"unit-{index:03d}" for index in range(count)),
    )
    candidate = replace(
        relation_candidate(),
        proposition_observations=(observation,),
    )
    if count == 32:
        validate_relation_candidate_bounds(candidate, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    else:
        with pytest.raises(SemanticVerificationBoundsError):
            validate_relation_candidate_bounds(candidate, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)


@pytest.mark.parametrize("count", [64, 65])
def test_proposition_relations_64_65_boundary(count: int) -> None:
    candidate = relation_candidate(observation_count=count)
    if count == 64:
        validate_relation_candidate_bounds(candidate, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    else:
        with pytest.raises(SemanticVerificationBoundsError):
            validate_relation_candidate_bounds(candidate, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)


@pytest.mark.parametrize("count", [128, 129])
def test_accounting_128_129_boundary(count: int) -> None:
    candidate = relation_candidate(accounting_count=count)
    if count == 128:
        validate_relation_candidate_bounds(candidate, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)
    else:
        with pytest.raises(SemanticVerificationBoundsError):
            validate_relation_candidate_bounds(candidate, V2_BRAIN_OPERATIONAL_BOUNDS_POLICY)


def test_provider_schemas_derive_d10_owned_limits_from_shared_policy() -> None:
    blind = blind_output_schema()
    blind_properties = cast(dict[str, object], blind["properties"])
    units = cast(dict[str, object], blind_properties["units"])
    unit_schema = cast(dict[str, object], units["items"])
    unit_properties = cast(dict[str, object], unit_schema["properties"])
    evidence_refs = cast(dict[str, object], unit_properties["evidence_refs"])
    evidence_schema = cast(dict[str, object], evidence_refs["items"])
    evidence_properties = cast(dict[str, object], evidence_schema["properties"])
    quote = cast(dict[str, object], evidence_properties["quote"])
    acts = cast(dict[str, object], unit_properties["interaction_acts"])
    bounds = V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.semantic_verification
    assert units["maxItems"] == bounds.max_blind_units
    assert evidence_refs["maxItems"] == bounds.max_evidence_refs_per_unit
    assert quote["maxLength"] == bounds.max_quote_codepoints
    assert acts["maxItems"] == bounds.max_interaction_acts_per_unit

    relation = relation_output_schema()
    relation_properties = cast(dict[str, object], relation["properties"])
    proposition_relations = cast(
        dict[str, object], relation_properties["proposition_observations"]
    )
    accounting = cast(dict[str, object], relation_properties["blind_unit_accounting"])
    assert proposition_relations["maxItems"] == bounds.max_proposition_relations
    assert accounting["maxItems"] == bounds.max_accounting_entries


def test_blind_request_binds_policy_generation() -> None:
    request = build_blind_request(
        _snapshot(),
        created_at=NOW,
        policy=verification_policy(),
    )
    payload = cast(dict[str, object], request.input.value)
    assert payload["bounds_policy_id"] == V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.policy_id
    assert (
        payload["bounds_policy_revision"]
        == V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.policy_revision
    )


def test_parse_blind_provider_129_units_is_not_first_n_accepted() -> None:
    snapshot = _snapshot()
    payload: dict[str, object] = {
        "candidate_id": "provider-blind-overflow",
        "request_id": snapshot.blind_request_id,
        "utterance_id": snapshot.utterance.utterance_id,
        "units": [
            {
                "unit_id": f"provider-unit-{index:03d}",
                "kind": "material_semantic_content",
                "interaction_acts": [],
                "evidence_refs": [
                    {
                        "segment_id": "segment-1",
                        "quote": TEXT,
                        "occurrence_index": 0,
                    }
                ],
            }
            for index in range(129)
        ],
    }
    with pytest.raises(SemanticVerificationBoundsError):
        parse_blind_candidate(payload, observed_at=NOW)
    assert len(cast(list[object], payload["units"])) == 129


def test_parse_relation_provider_65_relations_is_not_first_n_accepted() -> None:
    snapshot = _snapshot()
    payload: dict[str, object] = {
        "candidate_id": "provider-relation-overflow",
        "request_id": snapshot.relation_request_id,
        "semantic_plan_id": snapshot.semantic_plan.plan_id,
        "utterance_id": snapshot.utterance.utterance_id,
        "blind_observation_id": "blind-observation",
        "proposition_observations": [
            {
                "proposition_id": f"provider-proposition-{index:03d}",
                "relation": "missing",
                "polarity_relation": "not_applicable",
                "certainty_relation": "not_applicable",
                "degree_relation": "not_applicable",
                "execution_relation": "not_applicable",
                "evidence_refs": [],
                "supporting_blind_unit_ids": [],
            }
            for index in range(65)
        ],
        "blind_unit_accounting": [],
        "budget_observation": {
            "directed_question_count": 0,
            "new_direction_count": 0,
        },
        "self_disclosure_relation": "within_policy",
    }
    with pytest.raises(SemanticVerificationBoundsError):
        parse_relation_candidate(payload, observed_at=NOW)
    assert len(cast(list[object], payload["proposition_observations"])) == 65


class MutablePolicyState:
    def __init__(self) -> None:
        self.current: BrainOperationalBoundsPolicy = V2_BRAIN_OPERATIONAL_BOUNDS_POLICY

    async def current_policy(
        self, snapshot: SemanticVerificationContextSnapshot
    ) -> BrainOperationalBoundsPolicy:
        return self.current


@pytest.mark.asyncio
async def test_policy_change_during_role_a_await_stops_before_role_b_and_acceptance() -> None:
    snapshot = _snapshot()
    port = _BlockingSequencePort(snapshot)
    bounds_state = MutablePolicyState()
    verifier = SemanticVerifier(
        port,
        _LiveState(snapshot),
        SemanticVerificationAuthority(),
        verification_policy(),
        bounds_state,
    )
    task = asyncio.create_task(
        verifier.verify(
            snapshot,
            blind_observation_id="blind-observation",
            relation_observation_id="relation-observation",
            semantic_observation_id="semantic-observation",
            acceptance_id="acceptance",
            created_at=NOW,
        )
    )
    await port.blind_started.wait()
    bounds_state.current = replace(
        V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
        policy_revision=V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.policy_revision + 1,
    )
    port.blind_release.set()
    with pytest.raises(SemanticVerificationBoundsError) as error:
        await task
    assert error.value.code is SemanticVerificationBoundsFailureCode.POLICY_STALE
    assert len(port.requests) == 1
    assert not port.relation_started.is_set()


@pytest.mark.asyncio
async def test_policy_change_during_role_b_await_stops_before_acceptance() -> None:
    snapshot = _snapshot()
    port = _BlockingSequencePort(snapshot)
    bounds_state = MutablePolicyState()
    verifier = SemanticVerifier(
        port,
        _LiveState(snapshot),
        SemanticVerificationAuthority(),
        verification_policy(),
        bounds_state,
    )
    task = asyncio.create_task(
        verifier.verify(
            snapshot,
            blind_observation_id="blind-observation",
            relation_observation_id="relation-observation",
            semantic_observation_id="semantic-observation",
            acceptance_id="acceptance",
            created_at=NOW,
        )
    )
    await port.blind_started.wait()
    port.blind_release.set()
    await port.relation_started.wait()
    bounds_state.current = replace(
        V2_BRAIN_OPERATIONAL_BOUNDS_POLICY,
        policy_revision=V2_BRAIN_OPERATIONAL_BOUNDS_POLICY.policy_revision + 1,
    )
    port.relation_release.set()
    with pytest.raises(SemanticVerificationBoundsError) as error:
        await task
    assert error.value.code is SemanticVerificationBoundsFailureCode.POLICY_STALE
    assert len(port.requests) == 2


class OversizedBlindPort(_SequencePort):
    def _result_for(self, request: LLMRoleRequest) -> LLMRoleResult:
        result = super()._result_for(request)
        if request.role_id != BLIND_ROLE_ID or result.output is None:
            return result
        value = cast(dict[str, object], thaw_json(result.output.value))
        raw_units = cast(list[dict[str, object]], value["units"])
        first = raw_units[0]
        value["units"] = [
            {**first, "unit_id": f"overflow-unit-{index:03d}"}
            for index in range(129)
        ]
        return replace(
            result,
            output=StructuredPayload(result.output.schema_id, cast(JsonValue, value)),
        )


@pytest.mark.asyncio
async def test_role_a_overflow_never_invokes_role_b() -> None:
    snapshot = _snapshot()
    port = OversizedBlindPort(snapshot)
    verifier = SemanticVerifier(
        port,
        _LiveState(snapshot),
        SemanticVerificationAuthority(),
        verification_policy(),
    )
    with pytest.raises(SemanticVerificationBoundsError):
        await verifier.verify(
            snapshot,
            blind_observation_id="blind-observation",
            relation_observation_id="relation-observation",
            semantic_observation_id="semantic-observation",
            acceptance_id="acceptance",
            created_at=NOW,
        )
    assert [request.role_id for request in port.requests] == [BLIND_ROLE_ID]


class OversizedRelationPort(_SequencePort):
    def _result_for(self, request: LLMRoleRequest) -> LLMRoleResult:
        result = super()._result_for(request)
        if request.role_id != RELATION_ROLE_ID or result.output is None:
            return result
        value = cast(dict[str, object], thaw_json(result.output.value))
        raw = cast(list[dict[str, object]], value["proposition_observations"])
        template = raw[-1]
        value["proposition_observations"] = [
            {
                **template,
                "proposition_id": f"overflow-proposition-{index:03d}",
                "relation": "missing",
                "evidence_refs": [],
                "supporting_blind_unit_ids": [],
            }
            for index in range(65)
        ]
        return replace(
            result,
            output=StructuredPayload(result.output.schema_id, cast(JsonValue, value)),
        )


@pytest.mark.asyncio
async def test_role_b_overflow_fails_before_reconciliation() -> None:
    snapshot = _snapshot()
    port = OversizedRelationPort(snapshot)
    verifier = SemanticVerifier(
        port,
        _LiveState(snapshot),
        SemanticVerificationAuthority(),
        verification_policy(),
    )
    with pytest.raises(SemanticVerificationBoundsError):
        await verifier.verify(
            snapshot,
            blind_observation_id="blind-observation",
            relation_observation_id="relation-observation",
            semantic_observation_id="semantic-observation",
            acceptance_id="acceptance",
            created_at=NOW,
        )
    assert [request.role_id for request in port.requests] == [BLIND_ROLE_ID, RELATION_ROLE_ID]
