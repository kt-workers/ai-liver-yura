"""本体が所有者の内部事実から次の認知を開始する接続。"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from app.domain.brain_operational_bounds import V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
from app.domain.contracts import CapabilityAvailability, RevisionVector
from app.domain.contracts.common import freeze_json
from app.domain.executive import CommittedExecutiveDecision
from app.domain.goals import GoalCommitmentCommitResult, GoalCommitmentSnapshot, autonomy_triggers
from app.domain.goals import CommitmentLifecycleProjectionFact, GoalLifecycleProjectionFact
from app.usecases.attention import CommitmentAttentionProjector, GoalAttentionProjector
from app.usecases.attention.projectors import AttentionProjectionEnvelope
from app.domain.input_gateway import (
    InputAdmissionLedger,
    InputAdmissionStatus,
    InputModality,
    InputNormalizer,
    InputObservation,
    InputPermission,
    InputSourceLifecycleChange,
    InputSourceState,
)
from app.runtime.kernel import RuntimeClock

if TYPE_CHECKING:
    from app.composition.cognition import CoreCognitionDelivery
    from app.composition.input_reference_context import CoreInputReferenceContextBinding
    from app.domain.brain_integration import BrainIntegrationWork


class GoalOwner(Protocol):
    def apply(self, decision: CommittedExecutiveDecision) -> object: ...

    def snapshot(self) -> GoalCommitmentSnapshot: ...


class CoreAutonomyDelivery:
    """固定発話を作らず、起動事実とGoal更新だけを内部入力へ戻す。"""

    def __init__(
        self,
        goals: GoalOwner,
        cognition: CoreCognitionDelivery,
        reference: CoreInputReferenceContextBinding,
        clock: RuntimeClock,
    ) -> None:
        if not hasattr(goals, "apply") or not hasattr(goals, "snapshot"):
            raise ValueError("自律配送には既存のGoal所有者が必要です")
        self._goals = goals
        self._cognition = cognition
        self._reference = reference
        self._clock = clock
        self._normalizer = InputNormalizer(
            InputAdmissionLedger(), bounds_policy=V2_BRAIN_OPERATIONAL_BOUNDS_POLICY
        )
        self._runtime_source = InputSourceState(
            "core_runtime", "core_runtime", CapabilityAvailability.AVAILABLE, InputPermission.NOT_REQUIRED
        )
        self._goal_source = InputSourceState(
            "goal_commitment", "goal_commitment", CapabilityAvailability.AVAILABLE, InputPermission.NOT_REQUIRED
        )
        self._started = False

    def start(self) -> None:
        """実際のRuntime開始を一度だけ内部契機として配送する。"""
        if self._started:
            return
        self._started = True
        current = self._reference.snapshot()
        admission = self._normalizer.normalize(
            InputObservation(
                "core-runtime-started",
                self._runtime_source,
                InputModality.LIFECYCLE,
                "source_state_changed",
                self._clock.now(),
                "core-runtime-started",
                RevisionVector(current.context.source_context_revision, current.goals.goal_revision),
                {},
                lifecycle_change=InputSourceLifecycleChange(
                    CapabilityAvailability.UNAVAILABLE, InputPermission.NOT_REQUIRED, "runtime_started"
                ),
            )
        )
        if admission.status is not InputAdmissionStatus.ACCEPTED:
            raise RuntimeError("本体起動の内部契機を受付できませんでした")
        if not self._cognition.submit_input(admission).accepted:
            raise RuntimeError("本体起動の認知配送を受付できませんでした")
        for trigger in autonomy_triggers(self._goals.snapshot()):
            self._submit_start_trigger(trigger.to_dict(), trigger.trigger_id)

    def _submit_start_trigger(self, payload: object, trigger_id: str) -> None:
        current = self._reference.snapshot()
        admission = self._normalizer.normalize(
            InputObservation(
                f"autonomy-start-{trigger_id}",
                self._goal_source,
                InputModality.TIMER,
                "goal_commitment_review",
                self._clock.now(),
                f"autonomy-start-{trigger_id}",
                RevisionVector(current.context.source_context_revision, current.goals.goal_revision),
                freeze_json(payload),
            )
        )
        if admission.status is not InputAdmissionStatus.ACCEPTED:
            raise RuntimeError("既存Goalの自律契機を受付できませんでした")
        if not self._cognition.submit_input(admission).accepted:
            raise RuntimeError("既存Goalの認知配送を受付できませんでした")

    def accept_decision(self, work: BrainIntegrationWork, result: object) -> None:
        """Executiveの正規決定だけをGoal所有者へ渡し、更新事実を還流する。"""
        if not isinstance(result, CommittedExecutiveDecision):
            raise ValueError("自律配送には確定済み判断が必要です")
        candidate = result.candidate
        if not (candidate.goal_transition_intents or candidate.commitment_transition_intents):
            return
        applied = self._goals.apply(result)
        committed = self._commit_result(applied)
        for fact in committed.lifecycle_facts:
            self._submit_lifecycle_fact(work, fact)

    @staticmethod
    def _commit_result(value: object) -> GoalCommitmentCommitResult:
        if isinstance(value, GoalCommitmentCommitResult):
            return value
        nested = getattr(value, "committed", None)
        if isinstance(nested, GoalCommitmentCommitResult):
            return nested
        raise ValueError("Goal所有者が型付きlifecycle事実を返しませんでした")

    def _submit_lifecycle_fact(self, work: BrainIntegrationWork, fact: object) -> None:
        if not is_dataclass(fact):
            raise ValueError("Goal lifecycle事実の型が不正です")
        current = self._reference.snapshot()
        fact_id = getattr(fact, "fact_id", None)
        if not isinstance(fact_id, str) or not fact_id:
            raise ValueError("Goal lifecycle事実の識別子が不正です")
        payload = asdict(fact)
        for key, value in tuple(payload.items()):
            if isinstance(value, datetime):
                payload[key] = value.isoformat()
            else:
                payload[key] = getattr(value, "value", value)
        admission = self._normalizer.normalize(
            InputObservation(
                f"autonomy-{fact_id}",
                self._goal_source,
                InputModality.SUBSYSTEM,
                "goal_commitment_lifecycle",
                self._clock.now(),
                work.envelope.trace_id,
                RevisionVector(current.context.source_context_revision, current.goals.goal_revision),
                freeze_json(payload),
                correlation_id=work.envelope.trigger_id,
                causation_event_id=work.envelope.source_event_ids[0],
            )
        )
        if admission.status is not InputAdmissionStatus.ACCEPTED:
            raise ValueError("Goal lifecycleの内部入力を受付できませんでした")
        assert admission.event is not None
        if isinstance(fact, GoalLifecycleProjectionFact):
            signal = GoalAttentionProjector().project(
                AttentionProjectionEnvelope(fact, current.context.source_context_revision)
            )
        elif isinstance(fact, CommitmentLifecycleProjectionFact):
            signal = CommitmentAttentionProjector().project(
                AttentionProjectionEnvelope(fact, current.context.source_context_revision)
            )
        else:
            raise ValueError("Goal lifecycle事実の型が不正です")
        state = self._cognition.attention_owner.offer(signal)
        source = next(
            (
                item for item in state.sources
                if item.source_ref == signal.source_ref and item.kind is signal.source_kind
            ),
            None,
        )
        if source is not None:
            self._cognition.register_internal_source(source, admission.event.envelope.event_id)
        if not self._cognition.submit_input(
            admission, root_trigger_id=work.envelope.root_trigger_id
        ).accepted:
            raise ValueError("Goal lifecycleの認知配送を受付できませんでした")
