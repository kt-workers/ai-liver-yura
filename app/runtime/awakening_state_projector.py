from __future__ import annotations

from dataclasses import dataclass

from app.domain.awakening import AwakeningContext
from app.domain.awakening_state import AwakeningAppraisal
from app.domain.desires import DesireState, DesireType
from app.domain.drives import DriveState
from app.domain.emotions import EmotionState, MoodType, ReactiveEmotionState
from app.runtime.emotion_state_updater import EmotionStateUpdater


@dataclass(frozen=True, slots=True)
class AwakeningStateProjection:
    emotion: EmotionState
    desire: DesireState
    drive: DriveState


class AwakeningStateProjector:
    """覚醒評価を既存の内的状態へ投影する。表現・発話・Bodyは決めない。"""

    def project(
        self,
        *,
        context: AwakeningContext,
        appraisal: AwakeningAppraisal,
        emotion: EmotionState,
        desire: DesireState,
        drive: DriveState,
    ) -> AwakeningStateProjection:
        previous = context.previous_inner_state
        residual = appraisal.residual_affect_weight

        previous_arousal = (
            previous.emotion.arousal if previous is not None else emotion.arousal
        )
        previous_valence = (
            previous.emotion.valence if previous is not None else emotion.valence
        )
        previous_talk = (
            previous.emotion.talkativeness
            if previous is not None
            else emotion.talkativeness
        )
        prior_reactive = (
            {
                "joy": previous.emotion.joy,
                "amusement": previous.emotion.amusement,
                "anger": previous.emotion.anger,
                "sadness": previous.emotion.sadness,
                "fear": previous.emotion.fear,
                "surprise": previous.emotion.surprise,
                "discomfort": previous.emotion.discomfort,
                "emotional_pressure": previous.emotion.emotional_pressure,
            }
            if previous is not None
            else emotion.reactive.as_dict()
        )
        reactive = ReactiveEmotionState(
            **{
                name: self._clamp(
                    value * residual
                    + emotion.reactive.as_dict()[name] * (1.0 - residual) * 0.35
                )
                for name, value in prior_reactive.items()
            }
        )
        arousal = self._clamp(
            previous_arousal * residual * 0.42
            + appraisal.activation_urge * 0.46
            + (1.0 - appraisal.sleepiness) * 0.18
            + appraisal.orientation_need * 0.08
        )
        valence = self._clamp_signed(
            previous_valence * residual * 0.62
            + emotion.valence * (1.0 - residual) * 0.28
            + (appraisal.restoration - 0.5) * 0.08
            - appraisal.security_need * 0.06
        )
        talkativeness = self._clamp(
            previous_talk * residual * 0.34
            + appraisal.social_urge * 0.48
            + appraisal.activation_urge * 0.16
            - appraisal.sleepiness * 0.20
            - appraisal.security_need * 0.08
        )
        fallback = self._fallback_mood(context, emotion)
        mood = EmotionStateUpdater.derive_mood(
            reactive,
            fallback=fallback,
            arousal=arousal,
            valence=valence,
        )
        if appraisal.sleepiness >= 0.62 and arousal < 0.62:
            mood = MoodType.TIRED
        elif (
            appraisal.activation_urge >= 0.78
            and appraisal.exploration_urge >= 0.72
            and valence >= -0.05
        ):
            mood = MoodType.EXCITED
        projected_emotion = EmotionState(
            mood=mood,
            arousal=arousal,
            valence=valence,
            talkativeness=talkativeness,
            reactive=reactive,
        )

        projected_desire = self._project_desire(
            desire,
            context=context,
            appraisal=appraisal,
        )
        prior_drive = previous.drive if previous is not None else None
        projected_drive = DriveState(
            curiosity=self._clamp(
                self._blend(
                    drive.curiosity,
                    prior_drive.curiosity if prior_drive is not None else drive.curiosity,
                    residual,
                )
                * 0.56
                + appraisal.exploration_urge * 0.44
            ),
            engagement=self._clamp(
                self._blend(
                    drive.engagement,
                    prior_drive.engagement if prior_drive is not None else drive.engagement,
                    residual,
                )
                * 0.48
                + appraisal.social_urge * 0.30
                + appraisal.activation_urge * 0.22
            ),
            boredom=self._clamp(
                self._blend(
                    drive.boredom,
                    prior_drive.boredom if prior_drive is not None else drive.boredom,
                    residual,
                )
                * 0.42
                + (1.0 - appraisal.exploration_urge) * 0.24
                + appraisal.sleepiness * 0.18
            ),
            energy=self._clamp(
                appraisal.activation_urge * 0.58
                + appraisal.restoration * 0.24
                + (1.0 - appraisal.sleepiness) * 0.18
            ),
        )
        return AwakeningStateProjection(
            emotion=projected_emotion,
            desire=projected_desire,
            drive=projected_drive,
        )

    def _project_desire(
        self,
        desire: DesireState,
        *,
        context: AwakeningContext,
        appraisal: AwakeningAppraisal,
    ) -> DesireState:
        previous = context.previous_inner_state
        previous_values = (
            previous.desire.as_context() if previous is not None else {}
        )
        residual = appraisal.residual_affect_weight
        influences = {
            DesireType.CONNECTION: appraisal.social_urge * 0.16,
            DesireType.CURIOSITY: appraisal.exploration_urge * 0.22,
            DesireType.EXPRESSION: (
                appraisal.social_urge * 0.10 + appraisal.activation_urge * 0.08
            ),
            DesireType.RECOGNITION: 0.0,
            DesireType.AUTONOMY: appraisal.activation_urge * 0.05,
            DesireType.SECURITY: appraisal.security_need * 0.20,
            DesireType.ACHIEVEMENT: appraisal.activation_urge * 0.07,
        }
        updated = desire
        for desire_type in DesireType:
            current = updated.get(desire_type)
            previous_effective = previous_values.get(desire_type.value)
            prior = (
                float(previous_effective)
                if isinstance(previous_effective, (int, float))
                else current.effective_level
            )
            carried = self._blend(current.level, prior, residual)
            target = self._clamp(carried + influences[desire_type])
            updated = updated.with_value(
                desire_type,
                current.adjusted(level_delta=(target - current.level) * 0.72),
            )
        return updated

    @staticmethod
    def _fallback_mood(context: AwakeningContext, current: EmotionState) -> MoodType:
        previous = context.previous_inner_state
        if previous is None:
            return current.mood
        try:
            return MoodType(previous.emotion.mood)
        except ValueError:
            return current.mood

    @staticmethod
    def _blend(current: float, previous: float, weight: float) -> float:
        return current * (1.0 - weight) + previous * weight

    @staticmethod
    def _clamp(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    @staticmethod
    def _clamp_signed(value: float) -> float:
        return max(-1.0, min(1.0, float(value)))


__all__ = ["AwakeningStateProjection", "AwakeningStateProjector"]
