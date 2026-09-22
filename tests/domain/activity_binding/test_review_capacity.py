"""レビューFinding 2の公開可能件数と最終確定容量の不一致を実測する。"""

from dataclasses import replace
from threading import Event

import pytest

from app.domain.activity_binding import (
    ActivityBindingAuthority,
    ActivityExecutionBindingPublication,
    ArgumentKind,
    ArgumentSourceFact,
    ArgumentSourceOwner,
    ArgumentSourceRelation,
    BindingInputPublicationOwner,
    OperationInputContract,
)
from app.domain.contracts import CapabilityRequirement
from app.domain.contracts.finalization import (
    AuthorityFinalizationFence,
    AuthorityFinalizationRequest,
    AuthorityFinalizationResult,
    FinalizationError,
    FinalizationFailure,
)
from app.domain.executive import CommittedExecutiveDecision
from app.domain.executive.authority import ExecutiveFinalizationInput
from app.domain.plugin_registry.activity_binding import PluginActivityOperationAdapter
from tests.domain.activity_binding.test_binding import direct_fixture
from tests.domain.plugin_registry.test_plugin_registry_adjacent import available_registry
from tests.helpers.executive_requirements import PlanSources, fence_clock, make_authority


def publication(count: int, identity: str, target: str) -> ActivityExecutionBindingPublication:
    schema_ref = "plugin.run.input.v1"
    schema = BindingInputPublicationOwner(
        identity + "-schema",
        OperationInputContract(
            schema_ref, 1, tuple((f"arg-{i}", ArgumentKind.STRING) for i in range(count))
        ),
    )
    sources = tuple(
        ArgumentSourceOwner(
            f"{identity}-source-{i}",
            (
                ArgumentSourceFact(
                    f"{identity}-fact-{i}", f"{identity}-source-{i}", 1, schema_ref, "値"
                ),
            ),
        )
        for i in range(count)
    )
    owner = ActivityBindingAuthority(
        identity, PluginActivityOperationAdapter(available_registry()), schema, sources
    )
    return owner.publish(
        revision=1,
        activity_type="activity",
        operation_ref="run",
        target_ref=target,
        capability_id="capability-a",
        relations=tuple(
            ArgumentSourceRelation(f"arg-{i}", f"{identity}-fact-{i}") for i in range(count)
        ),
    )


@pytest.mark.parametrize("total", [15, 16, 17])
@pytest.mark.parametrize("path", ["direct", "direct_evidence", "two_step_plan"])
def test_actual_finalization_capacity(
    monkeypatch: pytest.MonkeyPatch, total: int, path: str
) -> None:
    from app.domain.activity_binding.projector import plan_execution_inputs
    from app.domain.goal_planning import GoalPlanningAuthority
    from tests.domain.executive.test_executive import NOW, REVISIONS
    from tests.domain.executive.test_plan_authorization import inputs
    from tests.domain.goal_planning.test_goal_planning import candidate, context, current
    from tests.helpers.executive_requirements import capture_plans

    evidence = PlanSources()
    if path != "two_step_plan":
        _, _, _, captured, proposed, live = direct_fixture()
        count = total - 5 - (path == "direct_evidence")
        pub = publication(count, "binding-1", "target")
        captured = replace(captured, capabilities=(pub.descriptor,), activity_bindings=(pub,))
        live = replace(live, capabilities=(pub.descriptor,), activity_bindings=(pub,))
    else:
        from tests.domain.goal_planning.test_goal_planning import NOW

        # 2 binding + 2 Registry + 2 schema + Requirements + provenance + evidence + target。
        pubs = (publication(2, "plan-a", "target-1"), publication(total - 12, "plan-b", "target-1"))
        requirement = CapabilityRequirement("activity", "run")
        base = candidate()
        steps = tuple(
            replace(
                base.steps[0],
                step_id=f"step-{i}",
                activity_type="activity",
                operation_ref="run",
                required_capabilities=(requirement,),
                binding_ref=p.value.binding_id,
            )
            for i, p in enumerate(pubs)
        )
        plan_candidate = replace(
            base,
            revisions=REVISIONS,
            steps=steps,
            checkpoint_step_ids=tuple(s.step_id for s in steps),
        )
        snap = context(deterministic=False)
        assert REVISIONS.goal_revision is not None
        snap = replace(
            snap,
            revisions=REVISIONS,
            goal_context=replace(snap.goal_context, goal_revision=REVISIONS.goal_revision),
            capabilities=(pubs[0].descriptor,),
            planning_requirements=(requirement,),
            activity_bindings=pubs,
        )
        owner = GoalPlanningAuthority()
        plan = owner.commit(
            plan_candidate,
            snap,
            replace(
                current(),
                revisions=REVISIONS,
                capabilities=(pubs[0].descriptor,),
                activity_bindings=pubs,
            ),
            plan_id="capacity-plan",
            committed_at=NOW,
        )
        proposed, captured, live = inputs()
        original_scope = captured.plan_scopes[0]
        bindings, _ = plan_execution_inputs(plan, owner, original_scope.bindings[0].preconditions)
        scope = replace(original_scope, plan=plan, bindings=bindings)
        from app.domain.executive import ExecutiveFactKind, ExecutiveFactRef

        facts = tuple(
            ExecutiveFactRef(f.reference_id, ExecutiveFactKind.ENVIRONMENT, f.revision, {})
            for p in pubs
            for f in p.value.sources
        )
        captured = capture_plans(
            replace(
                captured,
                plan_scopes=(scope,),
                capabilities=(pubs[0].descriptor,),
                facts=(*captured.facts, *facts),
            )
        )
        proposed = replace(
            proposed, intents=(replace(proposed.intents[0], required_capabilities=(requirement,)),)
        )
        live = replace(live, plan_scopes=(scope,), capabilities=(pubs[0].descriptor,))
    if path != "direct":
        live = replace(live, evidence_tokens=(evidence.participant.token(),))
    assert captured.requirements_generation is not None
    live = captured.requirements_generation.owner.prepare(captured, proposed, live)
    original = AuthorityFinalizationFence.finalize
    observed: list[int] = []

    def counted(
        self: AuthorityFinalizationFence,
        request: AuthorityFinalizationRequest[
            ExecutiveFinalizationInput, CommittedExecutiveDecision
        ],
        *,
        cancellation: Event | None = None,
    ) -> AuthorityFinalizationResult[CommittedExecutiveDecision]:
        observed.append(len({t._participant for t in request.expected_tokens} | {request.target}))
        return original(self, request, cancellation=cancellation)

    monkeypatch.setattr(AuthorityFinalizationFence, "finalize", counted)
    authority = make_authority(captured)
    with fence_clock(lambda: NOW):
        if total <= 16:
            authority.commit(proposed, captured, current=live, decision_id="capacity")
            assert authority.has_committed(captured.trigger_id)
        else:
            with pytest.raises(FinalizationError) as caught:
                authority.commit(proposed, captured, current=live, decision_id="capacity")
            assert caught.value.failure is FinalizationFailure.INVALID_LOCK_CONFIGURATION
            assert not authority.has_committed(captured.trigger_id)
    assert observed == [total]
