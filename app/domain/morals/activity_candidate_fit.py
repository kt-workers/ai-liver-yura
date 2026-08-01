from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.domain.activities import ActivityType
from app.domain.morals.moral_state import MoralProfile, MoralState
from app.shared.contracts.activity import ActivityDefinition


@dataclass(frozen=True, slots=True)
class MoralActivityCandidateFit:
    """Activity候補に付与する観測専用の価値判断適合度。"""

    activity_type: str
    moral_fit: float
    profiled: bool
    observation_only: bool = True
    reason: str = "moral_fit_observation_only"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "moral_fit",
            max(0.0, min(1.0, float(self.moral_fit))),
        )

    def as_context(self) -> dict[str, object]:
        return {
            "activity_type": self.activity_type,
            "moral_fit": self.moral_fit,
            "profiled": self.profiled,
            "observation_only": self.observation_only,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class _MoralPolicy:
    profile_weights: Mapping[str, float]
    state_weights: Mapping[str, float]


class MoralActivityCandidateEvaluator:
    """候補順序や許可状態を変えず、moral fitだけを算出する。"""

    _SOCIAL_POLICY = _MoralPolicy(
        profile_weights={
            "compassion": 0.35,
            "honesty": 0.20,
            "altruism": 0.15,
        },
        state_weights={
            "empathy_activation": 0.25,
            "selfish_impulse": -0.15,
            "aggressive_impulse": -0.20,
        },
    )
    _LISTENING_POLICY = _MoralPolicy(
        profile_weights={"compassion": 0.35, "altruism": 0.20},
        state_weights={
            "empathy_activation": 0.30,
            "restraint": 0.20,
            "selfish_impulse": -0.20,
        },
    )
    _ASSERTIVE_POLICY = _MoralPolicy(
        profile_weights={
            "honesty": 0.25,
            "dominance": 0.15,
            "competitiveness": 0.10,
        },
        state_weights={
            "restraint": 0.10,
            "aggressive_impulse": -0.10,
        },
    )
    _RULED_EXECUTION_POLICY = _MoralPolicy(
        profile_weights={
            "rule_respect": 0.35,
            "honesty": 0.15,
            "fairness": 0.10,
        },
        state_weights={
            "restraint": 0.25,
            "selfish_impulse": -0.10,
        },
    )
    _EXPLORATION_POLICY = _MoralPolicy(
        profile_weights={
            "honesty": 0.25,
            "fairness": 0.15,
            "rule_respect": 0.20,
        },
        state_weights={
            "restraint": 0.15,
            "aggressive_impulse": -0.05,
        },
    )
    _OBSERVATION_POLICY = _MoralPolicy(
        profile_weights={"rule_respect": 0.20, "compassion": 0.10},
        state_weights={"restraint": 0.30, "empathy_activation": 0.10},
    )

    _POLICIES: Mapping[str, _MoralPolicy] = {
        ActivityType.CONVERSATION_WITH_USER.value: _SOCIAL_POLICY,
        ActivityType.STREAM_COMMENT_RESPONSE.value: _SOCIAL_POLICY,
        ActivityType.STREAM_OPENING_GREETING.value: _SOCIAL_POLICY,
        ActivityType.STREAM_CLOSING_GREETING.value: _SOCIAL_POLICY,
        ActivityType.LISTENING_MODE.value: _LISTENING_POLICY,
        ActivityType.DIRECTED_TALK.value: _ASSERTIVE_POLICY,
        ActivityType.AUTONOMOUS_TALK.value: _ASSERTIVE_POLICY,
        ActivityType.BODY_EXPRESSION_LOOP.value: _ASSERTIVE_POLICY,
        ActivityType.PLUGIN_ACTIVITY.value: _RULED_EXECUTION_POLICY,
        ActivityType.STREAM_MAIN_SEGMENT.value: _RULED_EXECUTION_POLICY,
        ActivityType.CURIOSITY_RESEARCH.value: _EXPLORATION_POLICY,
        ActivityType.TOPIC_EXPLORATION.value: _EXPLORATION_POLICY,
        ActivityType.EXTERNAL_TREND_WATCH.value: _EXPLORATION_POLICY,
        ActivityType.AWAKENING.value: _OBSERVATION_POLICY,
        ActivityType.BEHAVIOR_PLANNING.value: _OBSERVATION_POLICY,
        ActivityType.IDLE_OBSERVATION.value: _OBSERVATION_POLICY,
        ActivityType.STARTUP_REACTION.value: _OBSERVATION_POLICY,
        ActivityType.STIMULUS_REACTION.value: _OBSERVATION_POLICY,
    }

    def evaluate_context(
        self,
        definitions: Sequence[ActivityDefinition],
        moral: Mapping[str, object] | None,
    ) -> tuple[MoralActivityCandidateFit, ...]:
        profile = self._profile_from_context(moral)
        state = self._state_from_context(moral)
        if profile is None or state is None:
            return tuple(
                MoralActivityCandidateFit(
                    activity_type=definition.activity_type,
                    moral_fit=0.5,
                    profiled=False,
                    reason="moral_context_unavailable_neutral",
                )
                for definition in definitions
            )
        return self.evaluate(definitions, profile=profile, state=state)

    def evaluate(
        self,
        definitions: Sequence[ActivityDefinition],
        *,
        profile: MoralProfile,
        state: MoralState,
    ) -> tuple[MoralActivityCandidateFit, ...]:
        return tuple(
            self.evaluate_activity(
                definition.activity_type,
                profile=profile,
                state=state,
            )
            for definition in definitions
        )

    def evaluate_activity(
        self,
        activity_type: str,
        *,
        profile: MoralProfile,
        state: MoralState,
    ) -> MoralActivityCandidateFit:
        policy = self._POLICIES.get(activity_type)
        if policy is None:
            return MoralActivityCandidateFit(
                activity_type=activity_type,
                moral_fit=0.5,
                profiled=False,
                reason="unprofiled_activity_neutral",
            )

        score = 0.5
        for name, weight in policy.profile_weights.items():
            score += (float(getattr(profile, name)) - 0.5) * weight
        for name, weight in policy.state_weights.items():
            score += (float(getattr(state, name)) - 0.5) * weight
        return MoralActivityCandidateFit(
            activity_type=activity_type,
            moral_fit=score,
            profiled=True,
        )

    @staticmethod
    def _profile_from_context(
        moral: Mapping[str, object] | None,
    ) -> MoralProfile | None:
        if moral is None:
            return None
        raw = moral.get("profile")
        if not isinstance(raw, Mapping):
            return None
        try:
            return MoralProfile(
                compassion=float(raw["compassion"]),
                honesty=float(raw["honesty"]),
                fairness=float(raw["fairness"]),
                altruism=float(raw["altruism"]),
                rule_respect=float(raw["rule_respect"]),
                dominance=float(raw["dominance"]),
                competitiveness=float(raw["competitiveness"]),
                jealousy_tendency=float(raw["jealousy_tendency"]),
                possessiveness=float(raw["possessiveness"]),
                malice=float(raw["malice"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _state_from_context(
        moral: Mapping[str, object] | None,
    ) -> MoralState | None:
        if moral is None:
            return None
        raw = moral.get("state")
        if not isinstance(raw, Mapping):
            return None
        try:
            return MoralState(
                restraint=float(raw["restraint"]),
                empathy_activation=float(raw["empathy_activation"]),
                selfish_impulse=float(raw["selfish_impulse"]),
                aggressive_impulse=float(raw["aggressive_impulse"]),
                guilt=float(raw["guilt"]),
            )
        except (KeyError, TypeError, ValueError):
            return None
