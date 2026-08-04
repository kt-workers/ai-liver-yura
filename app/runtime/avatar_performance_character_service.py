from __future__ import annotations

from app.domain.avatar_performance import AvatarGazeIntent
from app.domain.body import (
    BodyAttentionBehavior,
    BodyAttentionIntent,
    EmbodiedExpressionIntent,
    SpeechEmphasis,
)
from app.domain.character_response import ReactionPlan, ReactionSegment, VoiceIntent
from app.runtime.character_response_pipeline import (
    CharacterLlmService as CoreCharacterLlmService,
)


class AvatarPerformanceCharacterLlmService(CoreCharacterLlmService):
    """Character応答SchemaへBodyが解釈する高レベル表現Intentを追加する。"""

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
            embodied_expression = (
                AvatarPerformanceCharacterLlmService._embodied_expression(
                    item.get("embodied_expression")
                )
            )
            attention_intent = AvatarPerformanceCharacterLlmService._attention(
                item.get("attention_intent")
            )
            speech_emphasis = AvatarPerformanceCharacterLlmService._speech_emphasis(
                item.get("speech_emphasis", [])
            )
            if (
                voice_intent is None
                or not isinstance(pause, (int, float))
                or isinstance(pause, bool)
                or expression_intensity is None
                or gesture_intensity is None
                or (item.get("gaze") is not None and gaze is None)
                or (
                    item.get("embodied_expression") is not None
                    and embodied_expression is None
                )
                or (
                    item.get("attention_intent") is not None
                    and attention_intent is None
                )
                or speech_emphasis is None
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
                    embodied_expression=embodied_expression,
                    attention_intent=attention_intent,
                    speech_emphasis=speech_emphasis,
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
    def _signed_intensity(value: object) -> float | None:
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and -1.0 <= float(value) <= 1.0
        ):
            return float(value)
        return None

    @classmethod
    def _embodied_expression(
        cls,
        value: object,
    ) -> EmbodiedExpressionIntent | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            return None
        attitude = value.get("attitude")
        if not isinstance(attitude, str) or not attitude.strip():
            return None
        unit_defaults = {
            "intensity": 0.0,
            "arousal": 0.0,
            "tension": 0.0,
            "openness": 0.5,
            "surprise": 0.0,
            "assertiveness": 0.0,
            "warmth": 0.5,
        }
        signed_defaults = {
            "valence": 0.0,
            "approach": 0.0,
            "agreement": 0.0,
        }
        units = {
            name: cls._intensity(value.get(name, default))
            for name, default in unit_defaults.items()
        }
        signed = {
            name: cls._signed_intensity(value.get(name, default))
            for name, default in signed_defaults.items()
        }
        if any(item is None for item in (*units.values(), *signed.values())):
            return None
        try:
            return EmbodiedExpressionIntent(
                attitude=attitude,
                intensity=units["intensity"],
                valence=signed["valence"],
                arousal=units["arousal"],
                tension=units["tension"],
                openness=units["openness"],
                approach=signed["approach"],
                agreement=signed["agreement"],
                surprise=units["surprise"],
                assertiveness=units["assertiveness"],
                warmth=units["warmth"],
            )
        except (TypeError, ValueError):
            return None

    @classmethod
    def _attention(cls, value: object) -> BodyAttentionIntent | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            return None
        target = value.get("target")
        behavior_value = value.get("behavior", BodyAttentionBehavior.MAINTAIN.value)
        if (
            not isinstance(target, str)
            or not target.strip()
            or not isinstance(behavior_value, str)
        ):
            return None
        try:
            behavior = BodyAttentionBehavior(behavior_value.strip())
        except ValueError:
            return None
        defaults = {
            "engagement": 1.0,
            "avoidance": 0.0,
            "eye_follow": 1.0,
            "head_follow": 0.55,
            "body_follow": 0.15,
        }
        parsed = {
            name: cls._intensity(value.get(name, default))
            for name, default in defaults.items()
        }
        if any(item is None for item in parsed.values()):
            return None
        try:
            return BodyAttentionIntent(
                target=target,
                behavior=behavior,
                engagement=parsed["engagement"],
                avoidance=parsed["avoidance"],
                eye_follow=parsed["eye_follow"],
                head_follow=parsed["head_follow"],
                body_follow=parsed["body_follow"],
            )
        except (TypeError, ValueError):
            return None

    @classmethod
    def _speech_emphasis(
        cls,
        value: object,
    ) -> tuple[SpeechEmphasis, ...] | None:
        if not isinstance(value, list) or len(value) > 16:
            return None
        result: list[SpeechEmphasis] = []
        for item in value:
            if not isinstance(item, dict):
                return None
            text = item.get("text")
            intent = item.get("intent")
            strength = cls._intensity(item.get("strength", 1.0))
            if (
                not isinstance(text, str)
                or not text.strip()
                or not isinstance(intent, str)
                or not intent.strip()
                or strength is None
            ):
                return None
            try:
                result.append(
                    SpeechEmphasis(
                        text=text,
                        intent=intent,
                        strength=strength,
                    )
                )
            except (TypeError, ValueError):
                return None
        return tuple(result)

    @staticmethod
    def _gaze(value: object) -> AvatarGazeIntent | None:
        """移行期間中の旧gaze Schemaを受理する。"""

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
