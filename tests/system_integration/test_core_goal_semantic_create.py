"""空のGoal/Commitment Ownerからproduction evidenceを経て最初のStateを作る。"""

from collections.abc import Mapping
from dataclasses import replace

import pytest

from app.composition.executive import CoreExecutiveBinding
from app.domain.contracts.common import freeze_json
from app.domain.executive import CommitmentTransitionOperation as C
from app.domain.executive import (
    CommitmentTransitionPayload,
    CommittedExecutiveDecision,
    GoalTransitionPayload,
)
from app.domain.executive import GoalTransitionOperation as G
from app.domain.llm import LLMRoleRequest, LLMRoleResult, StructuredPayload
from app.runtime.kernel import CancellationToken
from tests.domain.executive.test_executive import policy
from tests.domain.goals.test_goal_commitment_store import commitment_transition, goal_transition
from tests.helpers.executive_requirements import make_authority
from tests.helpers.goal_semantics import semantic_spec
from tests.system_integration.test_core_executive import Port
from tests.system_integration.test_core_input_evidence import wired


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["goal", "commitment"])
@pytest.mark.parametrize("oversize", [False, True])
async def test_first_create_with_real_input_evidence(kind: str, oversize: bool) -> None:
    value = await wired()
    before = value.core.goals.snapshot()
    assert not before.goals and not before.commitments
    assert (await value.reader.read(value.dispatch.selected_source)).facts == ()
    spec = semantic_spec("new-semantic")
    if oversize:
        spec = replace(spec, value="あ" * 16384)

    class CreatePort(Port):
        async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
            result = await super().invoke(request)
            assert result.output is not None and isinstance(result.output.value, Mapping)
            payload: dict[str, object] = dict(result.output.value)
            revision = payload["goal_revision"]
            assert isinstance(revision, int)
            if kind == "goal":
                t = goal_transition(G.CREATE, revision, goal_id="first-goal")
                t = replace(
                    t,
                    payload=GoalTransitionPayload(
                        "new-semantic",
                        50,
                        goal_kind="general",
                        interruption_policy="resumable",
                        semantic_goal_spec=spec,
                    ),
                    reason_refs=("event:1",),
                )
                payload["goal_transition_intents"] = (t.to_dict(),)
            else:
                c = commitment_transition(C.CREATE, revision, commitment_id="first-commitment")
                c = replace(
                    c,
                    payload=CommitmentTransitionPayload(
                        "new-semantic", strength=50, priority=50, semantic_commitment_spec=spec
                    ),
                    reason_refs=("event:1",),
                )
                payload["commitment_transition_intents"] = (c.to_dict(),)
            payload.update(outcome="continue_activity", intents=(), rationale_refs=("event:1",))
            return replace(
                result, output=StructuredPayload("executive.candidate.v2", freeze_json(payload))
            )

    authority = make_authority()
    binding = CoreExecutiveBinding(
        value.attention, value.reader, CreatePort(), policy(), authority, value.core.clock
    )

    async def commit() -> CommittedExecutiveDecision:
        return await binding.deliberate(
            value.dispatch,
            request_id="first",
            trace_id="trace",
            decision_id="first",
            cancellation=CancellationToken(),
        )

    if oversize:
        with pytest.raises(ValueError, match="semantic spec transport"):
            await commit()
        assert value.core.goals.snapshot() == before
        assert (await value.reader.read(value.dispatch.selected_source)).facts == ()
        assert binding.latest_decision() is None
        return
    committed = await commit()
    value.core.goals.apply(committed)
    publication = (
        value.core.goals.goal_semantic_publication("first-goal")
        if kind == "goal"
        else value.core.goals.commitment_semantic_publication("first-commitment")
    )
    assert publication is not None
    assert publication.value.semantic_spec == spec
    assert publication.value.source_decision_id == "first"
    assert publication.value.reason_refs == ("event:1",)
