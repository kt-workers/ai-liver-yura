"""生成から意味検証・表現計画までの引継ぎと並行処理を確認する。"""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.llm import (
    LLMRoleRequest,
    LLMRoleResult,
    LLMRoleStatus,
    LLMTokenUsage,
    StructuredPayload,
)
from app.domain.semantic_verification import (
    BLIND_ROLE_ID,
    SemanticVerificationAuthority,
    SemanticVerificationContextSnapshot,
    SemanticVerifier,
)
from app.subsystems.validation.body import _project
from app.subsystems.validation.contracts import Gate, LabRunSpec, RunStatus
from app.subsystems.validation.runtime import RunContext
from tests.domain.semantic_verification import test_semantic_verification as semantic
from tests.subsystems.validation.json_values import value_at
from tests.subsystems.validation.test_speech_generation import run_spec, setup


class Verification:
    def __init__(self, *, blocking: bool = False, accepted: bool = False) -> None:
        self.accepted = accepted
        self.blocking = blocking
        self.started, self.release, self.cancelled = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )
        self.snapshots: list[SemanticVerificationContextSnapshot] = []
        self.contexts: list[RunContext] = []

    def build(
        self, context: RunContext, snapshot: SemanticVerificationContextSnapshot
    ) -> SemanticVerifier:
        self.snapshots.append(snapshot)
        self.contexts.append(context)
        outer = self
        segment = snapshot.utterance.candidate.segments[0]
        evidence = {"segment_id": segment.segment_id, "quote": segment.text, "occurrence_index": 0}

        class Port:
            async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
                value: dict[str, object]
                if request.role_id == BLIND_ROLE_ID:
                    if outer.blocking:
                        outer.started.set()
                        try:
                            await outer.release.wait()
                        except asyncio.CancelledError:
                            outer.cancelled.set()
                            raise
                    value = {
                        "candidate_id": "blind-candidate",
                        "request_id": request.request_id,
                        "utterance_id": snapshot.utterance.utterance_id,
                        "units": [
                            {
                                "unit_id": "unit-1",
                                "kind": "material_semantic_content",
                                "interaction_acts": [],
                                "evidence_refs": [evidence],
                            }
                        ],
                    }
                    schema = "semantic.verification.blind.candidate.v1"
                else:
                    # 模擬観測は全必須命題の欠落を報告する。採否は本番の判断主体に任せる。
                    value = {
                        "candidate_id": "relation-candidate",
                        "request_id": request.request_id,
                        "semantic_plan_id": snapshot.semantic_plan.plan_id,
                        "utterance_id": snapshot.utterance.utterance_id,
                        "blind_observation_id": value_at(
                            request.input.value, "blind_observation", "observation_id"
                        ),
                        "proposition_observations": [
                            {
                                "proposition_id": p.proposition_id,
                                "relation": "missing",
                                "polarity_relation": "not_applicable",
                                "certainty_relation": "not_applicable",
                                "degree_relation": "not_applicable",
                                "execution_relation": "not_applicable",
                                "evidence_refs": [],
                                "supporting_blind_unit_ids": [],
                            }
                            for p in snapshot.semantic_plan.candidate.propositions
                        ],
                        "blind_unit_accounting": [
                            {
                                "blind_unit_id": "unit-1",
                                "relation": "unsupported_extra",
                                "proposition_ids": [],
                                "evidence_refs": [evidence],
                            }
                        ],
                        "budget_observation": {
                            "directed_question_count": 0,
                            "new_direction_count": 0,
                        },
                        "self_disclosure_relation": "within_policy",
                    }
                    if outer.accepted:
                        supported: list[str] = []
                        observations = value["proposition_observations"]
                        assert isinstance(observations, list)
                        for observation, proposition in zip(
                            observations,
                            snapshot.semantic_plan.candidate.propositions,
                            strict=True,
                        ):
                            assert isinstance(observation, dict)
                            if proposition.disposition.value == "forbidden":
                                continue
                            supported.append(proposition.proposition_id)
                            observation.update(
                                {
                                    "relation": "entailed",
                                    "polarity_relation": "preserved",
                                    "certainty_relation": "preserved",
                                    "degree_relation": "preserved",
                                    "execution_relation": "preserved"
                                    if proposition.execution_status is not None
                                    else "not_applicable",
                                    "evidence_refs": [evidence],
                                    "supporting_blind_unit_ids": ["unit-1"],
                                }
                            )
                        accounting = value["blind_unit_accounting"]
                        assert isinstance(accounting, list) and isinstance(accounting[0], dict)
                        accounting[0].update(
                            {
                                "relation": "supported_by_plan",
                                "proposition_ids": supported,
                            }
                        )
                    schema = "semantic.verification.relation.candidate.v1"
                return LLMRoleResult(
                    request.request_id,
                    request.role_id,
                    LLMRoleStatus.SUCCEEDED,
                    request.revisions,
                    request.created_at + timedelta(seconds=1),
                    request.trace_id,
                    request.execution_policy.model_class,
                    1,
                    LLMTokenUsage(10, 10),
                    StructuredPayload(schema, _project(value)),
                    started_at=request.created_at,
                )

        return SemanticVerifier(
            Port(),
            semantic._LiveState(
                snapshot, [semantic._eligible(snapshot, revisions=snapshot.revisions)]
            ),
            SemanticVerificationAuthority(),
            semantic.verification_policy(),
        )


def chain_spec(*, repeat_count: int = 1) -> LabRunSpec:
    return replace(run_spec(repeat_count=repeat_count), target_module="speech_generation_chain")


@pytest.mark.asyncio
async def test_same_plan_and_utterance_reach_verification_and_performance() -> None:
    verification = Verification()
    item, runner, characters, _ = setup(verifier=verification.build)
    result = await runner.run(chain_spec(repeat_count=2), item.fixture)
    assert result.status is RunStatus.COMPLETED
    assert result.machine_gate is Gate.NOT_RUN
    for stage, character, observed in zip(
        result.stage_results, characters, verification.snapshots, strict=True
    ):
        output = stage.typed_outputs
        assert observed.semantic_plan is character.semantic_plan
        assert value_at(output, "utterance") == value_at(output, "evaluation", "utterance")
        assert (
            value_at(output, "evaluation", "performance_plan", "utterance_id")
            == observed.utterance.utterance_id
        )
        assert value_at(output, "evaluation", "verification", "acceptance", "state") == "rejected"
    assert len(characters) == 2
    assert runner.pending_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_performance_proceeds_during_verification_and_cancel_reaps_it(cancel: bool) -> None:
    verification = Verification(blocking=True)
    item, runner, _, _ = setup(verifier=verification.build)
    task = asyncio.create_task(runner.run(chain_spec(), item.fixture))
    await asyncio.wait_for(verification.started.wait(), 0.5)
    assert any(i.stage == "speech.performance" for i in verification.contexts[0].intervals)
    if cancel:
        await runner.cancel(chain_spec().run_id)
    else:
        verification.release.set()
    result = await task
    assert result.status is (RunStatus.CANCELLED if cancel else RunStatus.COMPLETED)
    assert verification.cancelled.is_set() is cancel
    if not cancel:
        intervals = {i.stage: i for i in result.timeline}
        assert intervals["speech.verification"].overlaps(intervals["speech.performance"])
    assert runner.pending_count == 0
