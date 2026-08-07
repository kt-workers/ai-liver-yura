from __future__ import annotations

from datetime import datetime, timezone

from app.domain.awakening_state import (
    AwakeningAppraisal,
    AwakeningLifecyclePhase,
    AwakeningState,
)
from app.domain.body_activity_context import BodyActivityContext
from app.domain.body_awakening_affect import BodyAwakeningAffect
from app.domain.desires import DesireState, DesireType
from app.domain.drives import DriveState
from app.domain.emotions import EmotionState
from app.domain.autonomous_interaction import AutonomousInteractionAction
from app.runtime.agent_state import AgentState
from app.runtime.autonomous_interaction_decider import AutonomousInteractionDecider
from app.runtime.autonomous_motivation_context import AutonomousMotivationContextBuilder
from app.runtime.body_emotion_state_store import (
    BodyAgentStateObserver,
    LatestBodyEmotionStateStore,
)
from app.runtime.body_expression_input_builder import BodyExpressionInputBuilder
from app.runtime.body_motion_state_projector import BodyMotionStateProjector

NOW = datetime(2026, 8, 7, 3, 0, tzinfo=timezone.utc)


def _appraisal(
    *,
    sleepiness: float,
    activation: float,
    exploration: float,
    social: float,
    security: float,
    orientation: float,
    readiness: float,
) -> AwakeningAppraisal:
    return AwakeningAppraisal(
        restoration=0.6,
        sleepiness=sleepiness,
        activation_urge=activation,
        exploration_urge=exploration,
        social_urge=social,
        security_need=security,
        orientation_need=orientation,
        residual_affect_weight=0.5,
        readiness=readiness,
        reason="test",
    )


def _awakening_state(
    phase: AwakeningLifecyclePhase,
    appraisal: AwakeningAppraisal,
) -> AwakeningState:
    return AwakeningState(
        phase=phase,
        appraisal=appraisal,
        started_at=NOW,
        phase_started_at=NOW,
        completed_at=(NOW if phase is AwakeningLifecyclePhase.READY else None),
    )


def test_body_observer_projects_awakening_without_mutating_agent_state() -> None:
    store = LatestBodyEmotionStateStore()
    observer = BodyAgentStateObserver(store)
    awakening = _awakening_state(
        AwakeningLifecyclePhase.WAKING,
        _appraisal(
            sleepiness=0.72,
            activation=0.28,
            exploration=0.46,
            social=0.30,
            security=0.22,
            orientation=0.68,
            readiness=0.35,
        ),
    )
    state = AgentState(awakening_state=awakening)

    observer(state)
    shared = store.causal_snapshot()

    assert state.awakening_state is awakening
    assert shared.emotion is state.current_emotion
    assert shared.awakening.drowsiness == 0.72
    assert shared.awakening.orientation == 0.68
    assert shared.awakening.salience == 1.0


def test_ready_lifecycle_removes_awakening_expression_salience() -> None:
    store = LatestBodyEmotionStateStore()
    observer = BodyAgentStateObserver(store)
    appraisal = _appraisal(
        sleepiness=0.25,
        activation=0.82,
        exploration=0.85,
        social=0.72,
        security=0.12,
        orientation=0.20,
        readiness=0.88,
    )

    observer(AgentState(awakening_state=_awakening_state(AwakeningLifecyclePhase.READY, appraisal)))

    assert store.awakening_snapshot().salience == 0.0
    assert store.awakening_snapshot().active is False


def test_awake_and_drowsy_appraisals_create_continuous_body_differences_without_pose_preset() -> None:
    builder = BodyExpressionInputBuilder()
    projector = BodyMotionStateProjector()
    emotion = EmotionState()
    context = BodyActivityContext(
        source_activity_id="awakening-test",
        engagement=0.28,
        movement_energy=0.24,
        gaze_freedom=0.70,
    )
    active = BodyAwakeningAffect(
        activation=0.90,
        drowsiness=0.08,
        orientation=0.62,
        security=0.10,
        exploration=0.88,
        social=0.70,
        readiness=0.80,
        salience=1.0,
    )
    drowsy = BodyAwakeningAffect(
        activation=0.18,
        drowsiness=0.88,
        orientation=0.48,
        security=0.16,
        exploration=0.38,
        social=0.22,
        readiness=0.28,
        salience=1.0,
    )

    active_input = builder.build(
        emotion=emotion,
        context=context,
        awakening_affect=active,
    )
    drowsy_input = builder.build(
        emotion=emotion,
        context=context,
        awakening_affect=drowsy,
    )
    active_motion = projector.project(active_input)
    drowsy_motion = projector.project(drowsy_input)

    assert active_input.affect_baseline.channels == drowsy_input.affect_baseline.channels
    assert active_input.expression_overlay is None
    assert drowsy_input.expression_overlay is None
    assert active_input.facial_target.eye_widen > drowsy_input.facial_target.eye_widen
    assert drowsy_input.facial_target.eye_narrow > active_input.facial_target.eye_narrow
    assert active_motion.movement_energy > drowsy_motion.movement_energy
    assert active_motion.curiosity > drowsy_motion.curiosity
    assert active_input.as_payload()["contains_pose"] is False
    assert "gesture" not in active_input.as_payload()


def test_zero_salience_is_identical_to_emotion_only_body_input() -> None:
    builder = BodyExpressionInputBuilder()
    emotion = EmotionState()
    context = BodyActivityContext(source_activity_id="awakening-ready")
    no_awakening = builder.build(emotion=emotion, context=context)
    ready = builder.build(
        emotion=emotion,
        context=context,
        awakening_affect=BodyAwakeningAffect(
            activation=0.9,
            drowsiness=0.1,
            orientation=0.4,
            exploration=0.9,
            social=0.8,
            readiness=0.95,
            salience=0.0,
        ),
    )

    assert ready.affect_baseline == no_awakening.affect_baseline
    assert ready.facial_target == no_awakening.facial_target
    assert BodyMotionStateProjector().project(ready) == BodyMotionStateProjector().project(no_awakening)


def _desire_with_levels(**levels: float) -> DesireState:
    state = DesireState()
    for name, level in levels.items():
        desire_type = DesireType(name)
        current = state.get(desire_type)
        state = state.with_value(
            desire_type,
            current.adjusted(level_delta=level - current.level),
        )
    return state


def test_activated_curiosity_can_reach_existing_autonomous_interaction_path_without_forced_start_rule() -> None:
    state = AgentState(
        current_emotion=EmotionState(
            arousal=0.82,
            talkativeness=0.72,
        ),
        current_drive=DriveState(
            curiosity=0.90,
            engagement=0.78,
            boredom=0.05,
            energy=0.82,
        ),
        current_desire=_desire_with_levels(
            curiosity=0.94,
            expression=0.62,
            security=0.18,
        ),
    )
    motivation = AutonomousMotivationContextBuilder().build(state)

    decision, comparison = AutonomousInteractionDecider().decide(
        state,
        motivation=motivation,
        continuation_result=None,
        autonomous_topic=None,
        resume_reason=None,
        is_autonomous_lookahead=False,
    )

    assert motivation["primary_desire"] == "curiosity"
    assert decision.action is AutonomousInteractionAction.START
    assert comparison.legacy_drive_ready is True
    assert comparison.conservative_start_allowed is True


def test_security_or_low_energy_can_leave_awakened_agent_silent() -> None:
    state = AgentState(
        current_emotion=EmotionState(
            arousal=0.28,
            talkativeness=0.42,
        ),
        current_drive=DriveState(
            curiosity=0.82,
            engagement=0.48,
            boredom=0.08,
            energy=0.22,
        ),
        current_desire=_desire_with_levels(
            curiosity=0.72,
            expression=0.30,
            connection=0.26,
            security=0.96,
        ),
    )
    motivation = AutonomousMotivationContextBuilder().build(state)

    decision, comparison = AutonomousInteractionDecider().decide(
        state,
        motivation=motivation,
        continuation_result=None,
        autonomous_topic=None,
        resume_reason=None,
        is_autonomous_lookahead=False,
    )

    assert motivation["primary_desire"] == "security"
    assert decision.action is AutonomousInteractionAction.WAIT
    assert decision.interaction_intention.requires_response is False
    assert comparison.conservative_start_allowed is False
