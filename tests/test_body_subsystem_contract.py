from __future__ import annotations

import json

import pytest

from app.adapters.prompt import CharacterPromptBuilder
from app.domain.activities import Activity, ActivityType
from app.domain.avatar_performance import AvatarTrackChannel
from app.domain.body import (
    BodyActivityContext,
    BodyAttentionBehavior,
    BodyAttentionIntent,
    BodyExpressionRequest,
    BodyPostureTendency,
    EmbodiedExpressionIntent,
    SpeechEmphasis,
    SpeechPresentationRequest,
)
from app.domain.character_response import (
    ActivityExecutionStatus,
    ReactionPlan,
    ReactionSegment,
    ResponseContext,
)
from app.runtime.avatar_performance_planner import AvatarPerformancePlanner
from app.runtime.body_activity_context_builder import BodyActivityContextBuilder
from app.runtime.body_expression_planner import BodyExpressionPlanner
from app.runtime.character_response_pipeline import CharacterLlmService


def test_embodied_expression_intent_validates_semantic_axes() -> None:
    intent = EmbodiedExpressionIntent(
        attitude="firm_rejection",
        intensity=0.8,
        valence=-0.6,
        arousal=0.7,
        tension=0.8,
        openness=0.2,
        approach=-0.7,
        agreement=-0.9,
        assertiveness=0.75,
    )

    assert intent.attitude == "firm_rejection"
    assert intent.agreement == -0.9
    with pytest.raises(ValueError, match="agreement"):
        EmbodiedExpressionIntent(agreement=-1.1)


def test_body_activity_context_builder_uses_activity_defaults_and_overrides() -> None:
    builder = BodyActivityContextBuilder()
    conversation = builder.build(
        Activity(
            activity_type=ActivityType.CONVERSATION_WITH_USER,
            goal="会話する",
            activity_id="activity-001",
        )
    )
    idle = builder.build(
        Activity(
            activity_type=ActivityType.IDLE_OBSERVATION,
            goal="周囲を見る",
            activity_id="activity-002",
            context={
                "body_context": {
                    "attention_target": "cursor",
                    "posture_tendency": "forward",
                    "movement_energy": 0.6,
                }
            },
        )
    )

    assert conversation.attention_target == "conversation_partner"
    assert conversation.posture_tendency == BodyPostureTendency.OPEN
    assert conversation.gaze_freedom < idle.gaze_freedom
    assert idle.attention_target == "cursor"
    assert idle.posture_tendency == BodyPostureTendency.FORWARD
    assert idle.movement_energy == 0.6


def test_body_expression_planner_composes_independent_overlapping_tracks() -> None:
    planner = BodyExpressionPlanner()
    request = BodyExpressionRequest(
        source_activity_id="activity-001",
        output_unit_id="output-001",
        expression=EmbodiedExpressionIntent(
            attitude="firm_rejection",
            intensity=0.9,
            valence=-0.7,
            arousal=0.8,
            tension=0.85,
            openness=0.12,
            approach=-0.75,
            agreement=-0.92,
            assertiveness=0.78,
        ),
        attention=BodyAttentionIntent(
            target="conversation_partner",
            behavior=BodyAttentionBehavior.AVOID,
            engagement=0.8,
            avoidance=0.65,
        ),
        speech_emphasis=(
            SpeechEmphasis(text="嫌", intent="reject", strength=0.9),
        ),
        priority=100,
        duration_hint_ms=2200,
    )

    tracks = planner.compile(
        request,
        activity_context=None,
        segment_index=0,
        start_offset_ms=0,
        duration_ms=2200,
    )

    channels = {track.channel for track in tracks}
    assert AvatarTrackChannel.ATTENTION in channels
    assert AvatarTrackChannel.HEAD in channels
    assert AvatarTrackChannel.TORSO in channels
    assert AvatarTrackChannel.LEFT_ARM in channels
    assert AvatarTrackChannel.RIGHT_ARM in channels

    motion_names = {
        track.motion.name for track in tracks if track.motion is not None
    }
    assert "head_shake" in motion_names
    assert "lean_back" in motion_names
    assert "draw_in" in motion_names
    assert "firm_rejection" not in motion_names

    head = next(
        track
        for track in tracks
        if track.motion is not None and track.motion.name == "head_shake"
    )
    torso = next(
        track
        for track in tracks
        if track.motion is not None and track.motion.name == "lean_back"
    )
    assert head.start_offset_ms < torso.end_offset_ms
    assert torso.start_offset_ms < head.end_offset_ms


def test_body_expression_planner_uses_activity_attention_without_character_llm() -> None:
    context = BodyActivityContext(
        source_activity_id="activity-001",
        attention_target="conversation_partner",
        engagement=0.7,
        gaze_freedom=0.2,
    )
    request = BodyExpressionRequest(
        source_activity_id="activity-001",
        output_unit_id="output-001",
        expression=EmbodiedExpressionIntent(),
    )

    tracks = BodyExpressionPlanner().compile(
        request,
        activity_context=context,
        segment_index=0,
        start_offset_ms=0,
        duration_ms=1200,
    )

    assert len(tracks) == 1
    assert tracks[0].channel == AvatarTrackChannel.ATTENTION
    assert tracks[0].attention is not None
    assert tracks[0].attention.target == "conversation_partner"


def test_avatar_performance_planner_does_not_require_gesture_preset() -> None:
    performance = AvatarPerformancePlanner(
        performance_id_factory=lambda: "perf-001"
    ).plan(
        ReactionPlan(
            (
                ReactionSegment(
                    speech="それは嫌。",
                    expression="displeased",
                    embodied_expression=EmbodiedExpressionIntent(
                        attitude="rejection",
                        intensity=0.85,
                        agreement=-0.9,
                        approach=-0.6,
                        openness=0.2,
                        tension=0.75,
                    ),
                    speech_emphasis=(
                        SpeechEmphasis("嫌", "reject", 0.9),
                    ),
                ),
            )
        ),
        source_activity_id="activity-001",
        output_unit_id="output-001",
        priority=100,
    )

    assert performance.segments[0].gesture is None
    motion_names = {
        track.motion.name
        for track in performance.tracks
        if track.motion is not None
    }
    assert "head_shake" in motion_names
    assert "lean_back" in motion_names


def test_character_llm_parser_accepts_semantic_body_intent() -> None:
    response = CharacterLlmService.parse(
        json.dumps(
            {
                "speech": "それは嫌。",
                "expression": "displeased",
                "gesture": None,
                "voice_intent": {"style": "firm"},
                "pause_after_seconds": 0.0,
                "reaction_segments": [
                    {
                        "speech": "それは嫌。",
                        "expression": "displeased",
                        "embodied_expression": {
                            "attitude": "firm_rejection",
                            "intensity": 0.85,
                            "valence": -0.7,
                            "arousal": 0.65,
                            "tension": 0.8,
                            "openness": 0.2,
                            "approach": -0.6,
                            "agreement": -0.9,
                            "surprise": 0.0,
                            "assertiveness": 0.75,
                            "warmth": 0.2,
                        },
                        "attention_intent": {
                            "target": "conversation_partner",
                            "behavior": "avoid",
                            "engagement": 0.75,
                            "avoidance": 0.65,
                            "eye_follow": 1.0,
                            "head_follow": 0.45,
                            "body_follow": 0.12,
                        },
                        "speech_emphasis": [
                            {
                                "text": "嫌",
                                "intent": "reject",
                                "strength": 0.9,
                            }
                        ],
                        "voice_intent": {"style": "firm"},
                        "pause_after_seconds": 0.0,
                    }
                ],
                "claims": [],
            },
            ensure_ascii=False,
        )
    )

    assert response is not None
    segment = response.effective_reaction_plan().segments[0]
    assert segment.gesture is None
    assert segment.embodied_expression is not None
    assert segment.embodied_expression.agreement == -0.9
    assert segment.attention_intent is not None
    assert segment.attention_intent.behavior == BodyAttentionBehavior.AVOID
    assert segment.speech_emphasis[0].text == "嫌"


def test_character_prompt_forbids_body_part_and_motion_preset_commands() -> None:
    context = ResponseContext(
        user_input="嫌？",
        activity_type=ActivityType.CONVERSATION_WITH_USER.value,
        operation=None,
        status=ActivityExecutionStatus.WAITING_INPUT,
        failure_reason=None,
        result_summary="",
        allowed_claims=(),
        forbidden_claims=(),
        activity_goal="応答する",
    )

    prompt = CharacterPromptBuilder().build(
        context,
        character_profile=None,
        correction=None,
    )

    assert "embodied_expression" in prompt
    assert "attention_intent" in prompt
    assert "speech_emphasis" in prompt
    assert "身体部位" in prompt
    assert "モーション名" in prompt
    assert "Body Subsystem" in prompt


def test_speech_presentation_contract_keeps_tts_generation_outside_body() -> None:
    request = SpeechPresentationRequest(
        source_activity_id="activity-001",
        output_unit_id="output-001",
        text="うん、そうだね",
        audio_reference="audio://utterance-001",
        duration_ms=1300,
        emphasis=(SpeechEmphasis("うん", "agree", 0.7),),
    )

    assert request.audio_reference == "audio://utterance-001"
    assert request.duration_ms == 1300
    assert request.emphasis[0].intent == "agree"
