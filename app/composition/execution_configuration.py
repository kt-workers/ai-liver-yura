"""Activity / Planの既存Ownerと提供先を本体の配送へ明示登録する。"""

from dataclasses import dataclass, replace

from app.composition.cognition import CoreCognitionDelivery
from app.composition.execution import CoreExecutionDelivery, ExecutionFeedbackRetentionPolicy
from app.composition.executive import CoreExecutiveEvidence, CoreExecutiveEvidenceReader
from app.composition.input_reference_context import CoreInputReferenceContextBinding
from app.domain.activity_binding import ActivityBindingAuthority
from app.domain.activity_execution import ActivityExecutionCoordinator
from app.domain.activity_execution.coordinator import ActivityExecutionPort, ExecutionPreflightPort
from app.domain.attention import AttentionSource
from app.domain.brain_operational_bounds import BrainOperationalBoundsPolicy
from app.domain.contracts.finalization import AuthorityReadPublication
from app.domain.executive import (
    AuthoritativeIntentRequirements,
    ExecutiveContextSnapshot,
    ExecutiveDecisionCandidate,
    ExecutiveRequirementsOwner,
)
from app.domain.executive.requirements import RequirementSourcePublication
from app.domain.goal_planning import GoalPlanningAuthority
from app.domain.input_gateway import InputSourceState
from app.domain.input_gateway.normalizer import InputNormalizer
from app.domain.plan_execution.contracts import PlanExecutionPolicy, PlanExecutionScope
from app.domain.plan_execution.coordinator import PlanExecutionContextPort, PlanExecutionCoordinator
from app.domain.plan_execution.owner import PlanExecutionOwner
from app.domain.plan_execution.progress_contracts import PlanProgressContext
from app.runtime.kernel import RuntimeClock


class _ExecutionEvidence:
    def __init__(
        self,
        base: CoreExecutiveEvidenceReader,
        bindings: tuple[ActivityBindingAuthority, ...],
        execution: CoreExecutionDelivery,
        requirements: ExecutiveRequirementsOwner,
    ) -> None:
        self.base, self.bindings = base, bindings
        self.execution, self.requirements = execution, requirements

    async def read(self, source: AttentionSource) -> CoreExecutiveEvidence:
        value = await self.base.read(source)
        scopes = tuple(
            dict.fromkeys(
                self.execution._plan_events[event.event_id]
                for event in value.source_events
                if event.event_id in self.execution._plan_events
            )
        )
        progress = tuple(
            dict.fromkeys(
                self.execution._scope_events[event.event_id]
                for event in value.source_events
                if event.event_id in self.execution._scope_events
            )
        )
        publications: tuple[
            AuthorityReadPublication[PlanExecutionScope]
            | AuthorityReadPublication[PlanProgressContext],
            ...,
        ] = (
            *(self.execution.plans.scope_publication(scope) for scope in scopes),
            *(self.execution.plans.observation_publication(scope) for scope in progress),
        )
        generation = self.requirements.current_generation()
        sources = {item.source_id: item for item in generation.sources}
        changed = False
        for scope, publication in zip((*scopes, *progress), publications, strict=True):
            source_id = f"execution:{type(publication.value).__name__}:{scope}"
            old = sources.get(source_id)
            if old is None or old.value != publication.value or old.tokens != publication.tokens:
                sources[source_id] = RequirementSourcePublication(
                    source_id,
                    1 if old is None else old.revision + 1,
                    publication.value,
                    publication.tokens,
                )
                changed = True
        if changed:
            self.requirements.publish(generation.policy, tuple(sources.values()))
        return replace(
            value,
            activity_bindings=tuple(owner.capture() for owner in self.bindings),
            plan_scopes=tuple(
                p.value for p in publications if isinstance(p.value, PlanExecutionScope)
            ),
            plan_progress_contexts=tuple(
                p.value for p in publications if isinstance(p.value, PlanProgressContext)
            ),
        )

    def reclaim_sources(self) -> None:
        """消費済み配送根拠をRequirementsの入力集合からも回収する。"""
        active = {
            *(
                f"execution:PlanExecutionScope:{scope}"
                for scope in self.execution._plan_events.values()
            ),
            *(
                f"execution:PlanProgressContext:{scope}"
                for scope in self.execution._scope_events.values()
            ),
        }
        generation = self.requirements.current_generation()
        sources = tuple(
            source
            for source in generation.sources
            if not source.source_id.startswith("execution:") or source.source_id in active
        )
        if sources != generation.sources:
            self.requirements.publish(generation.policy, sources)

    async def requirements_for(
        self, snapshot: ExecutiveContextSnapshot, candidate: ExecutiveDecisionCandidate
    ) -> tuple[AuthoritativeIntentRequirements, ...]:
        return await self.base.requirements_for(snapshot, candidate)


@dataclass(frozen=True, slots=True)
class CoreExecutionConfiguration:
    planning: GoalPlanningAuthority
    plan_policy: PlanExecutionPolicy
    plan_context: PlanExecutionContextPort
    preflight: ExecutionPreflightPort
    adapter: ActivityExecutionPort
    normalizer: InputNormalizer
    feedback_source: InputSourceState
    bindings: tuple[ActivityBindingAuthority, ...]
    retention_policy: ExecutionFeedbackRetentionPolicy

    def compose(
        self,
        delivery: CoreCognitionDelivery,
        reference: CoreInputReferenceContextBinding,
        clock: RuntimeClock,
        bounds: BrainOperationalBoundsPolicy,
        requirements: ExecutiveRequirementsOwner,
    ) -> CoreExecutionDelivery:
        activity = ActivityExecutionCoordinator(
            self.preflight, self.adapter, reference._activities, clock
        )
        plans = PlanExecutionOwner(
            self.planning, reference._goals, reference._activities, self.plan_policy, bounds
        )
        progression = PlanExecutionCoordinator(plans, activity, self.plan_context, clock)
        execution = CoreExecutionDelivery(
            delivery.brain,
            activity,
            self.planning,
            plans,
            progression,
            reference,
            self.normalizer,
            self.feedback_source,
            lambda admission, root: delivery.submit_input(admission, root_trigger_id=root),
            clock,
            retention_policy=self.retention_policy,
        )
        execution.register()
        delivery.execution = execution
        delivery._decision_delivery = execution.accept_decision
        evidence = _ExecutionEvidence(
            delivery._executive._evidence, self.bindings, execution, requirements
        )
        delivery._executive._evidence = evidence
        execution._sources_consumed = evidence.reclaim_sources
        return execution
