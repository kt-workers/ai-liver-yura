from __future__ import annotations

from app.domain.avatar_performance import AvatarGazeIntent
from app.domain.character_response import ReactionPlan, ReactionSegment, VoiceIntent
from app.runtime.character_response_pipeline import (
    CharacterLlmService as CoreCharacterLlmService,
)


class AvatarPerformanceCharacterLlmService(CoreCharacterLlmService):
    """既存Character応答Schemaへ高レベルAvatar演技Intentを追加する。"""

    @staticmethod
    def _parse_reaction_plan(
        value: object,
        *,
        default_expression: str,
        default_voice_intent: VoiceIntent,
    ) -> ReactionPlan | None:
        if value is None:
            return None
        if not isinstance(value, list) or not 1 <= len(value) <= 8:
            return None
        segments: list[ReactionSegment] = []
        for item in value:
            if not isinstance(item, dict):
                return None
            speech = item.get("speech")
            if not isinstance(speech, str) or not speech.strip():
                return None
            voice_intent = CoreCharacterLlmService._parse_voice_intent(
                item.get("voice_intent", {"style": default_voice_intent.style})
            )
            pause = item.get("pause_after_seconds", 0.0)
            expression_intensity = AvatarPerformanceCharacterLlmService._intensity(
                item.get("expression_intensity", 1.0)
            )
            gesture_intensity = AvatarPerformanceCharacterLlmService._intensity(
                item.get("gesture_intensity", 1.0)
            )
            gaze = AvatarPerformanceCharacterLlmService._gaze(item.get("gaze"))
            if (
                voice_intent is None
                or not isinstance(pause, (int, float))
                or isinstance(pause, bool)
                or expression_intensity is None
                or gesture_intensity is None
                or (item.get("gaze") is not None and gaze is None)
            ):
                return None
            try:
                segment = ReactionSegment(
                    speech=speech.strip(),
                    expression=str(item.get("expression") or default_expression),
                    gesture=(
                        str(item["gesture"])
                        if item.get("gesture") is not None
                        else None
                    ),
                    voice_intent=voice_intent,
                    pause_after_seconds=float(pause),
                    expression_intensity=expression_intensity,
                    gesture_intensity=gesture_intensity,
                    gaze=gaze,
                )
            except (TypeError, ValueError):
                return None
            segments.append(segment)
        return ReactionPlan(tuple(segments))

    @staticmethod
    def _intensity(value: object) -> float | None:
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and 0.0 <= float(value) <= 1.0
        ):
            return float(value)
        return None

    @staticmethod
    def _gaze(value: object) -> AvatarGazeIntent | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            return None
        target = value.get("target")
        behavior = value.get("behavior", "maintain")
        intensity = AvatarPerformanceCharacterLlmService._intensity(
            value.get("intensity", 1.0)
        )
        if (
            not isinstance(target, str)
            or not target.strip()
            or not isinstance(behavior, str)
            or not behavior.strip()
            or intensity is None
        ):
            return None
        try:
            return AvatarGazeIntent(
                target=target,
                behavior=behavior,
                intensity=intensity,
            )
        except (TypeError, ValueError):
            return None
