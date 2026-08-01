from __future__ import annotations

from dataclasses import dataclass, fields


def _clamp_01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _validate_01(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} は 0.0 以上 1.0 以下で指定してください。")


@dataclass(frozen=True, slots=True)
class MoralProfile:
    """欲望をどのような方法で満たしやすいかを表す長期的価値判断傾向。"""

    compassion: float = 0.72
    honesty: float = 0.68
    fairness: float = 0.66
    altruism: float = 0.58
    rule_respect: float = 0.62
    dominance: float = 0.38
    competitiveness: float = 0.48
    jealousy_tendency: float = 0.28
    possessiveness: float = 0.24
    malice: float = 0.18

    def __post_init__(self) -> None:
        for item in fields(self):
            _validate_01(item.name, float(getattr(self, item.name)))

    def as_dict(self) -> dict[str, float]:
        return {
            item.name: float(getattr(self, item.name))
            for item in fields(self)
        }

    def compose(self, state: MoralState) -> MoralComposite:
        prosocial_profile = (
            self.compassion
            + self.honesty
            + self.fairness
            + self.altruism
            + self.rule_respect
        ) / 5.0
        adversarial_profile = (
            self.dominance
            + self.competitiveness
            + self.jealousy_tendency
            + self.possessiveness
            + self.malice
        ) / 5.0
        return MoralComposite(
            prosocial_activation=_clamp_01(
                prosocial_profile * 0.60
                + state.empathy_activation * 0.25
                + state.restraint * 0.15
            ),
            adversarial_activation=_clamp_01(
                adversarial_profile * 0.60
                + state.selfish_impulse * 0.20
                + state.aggressive_impulse * 0.20
            ),
            effective_restraint=_clamp_01(
                state.restraint * 0.65
                + self.rule_respect * 0.20
                + self.compassion * 0.15
                - state.aggressive_impulse * 0.20
            ),
        )


@dataclass(frozen=True, slots=True)
class MoralState:
    """感情や状況に応じて一時的に変化する価値判断状態。"""

    restraint: float = 0.65
    empathy_activation: float = 0.55
    selfish_impulse: float = 0.20
    aggressive_impulse: float = 0.10
    guilt: float = 0.08

    def __post_init__(self) -> None:
        for item in fields(self):
            _validate_01(item.name, float(getattr(self, item.name)))

    @classmethod
    def from_profile(cls, profile: MoralProfile) -> MoralState:
        return cls(
            restraint=_clamp_01(
                0.35
                + profile.rule_respect * 0.35
                + profile.compassion * 0.15
                - profile.dominance * 0.10
            ),
            empathy_activation=_clamp_01(
                0.20
                + profile.compassion * 0.45
                + profile.altruism * 0.15
            ),
            selfish_impulse=_clamp_01(
                0.10
                + profile.dominance * 0.20
                + profile.possessiveness * 0.25
                + profile.malice * 0.10
            ),
            aggressive_impulse=_clamp_01(
                0.05
                + profile.dominance * 0.15
                + profile.competitiveness * 0.10
                + profile.malice * 0.25
            ),
            guilt=_clamp_01(
                0.05
                + profile.honesty * 0.20
                + profile.compassion * 0.15
            ),
        )

    def adjusted(
        self,
        *,
        restraint: float = 0.0,
        empathy_activation: float = 0.0,
        selfish_impulse: float = 0.0,
        aggressive_impulse: float = 0.0,
        guilt: float = 0.0,
    ) -> MoralState:
        return MoralState(
            restraint=_clamp_01(self.restraint + restraint),
            empathy_activation=_clamp_01(
                self.empathy_activation + empathy_activation
            ),
            selfish_impulse=_clamp_01(self.selfish_impulse + selfish_impulse),
            aggressive_impulse=_clamp_01(
                self.aggressive_impulse + aggressive_impulse
            ),
            guilt=_clamp_01(self.guilt + guilt),
        )

    def as_dict(self) -> dict[str, float]:
        return {
            item.name: float(getattr(self, item.name))
            for item in fields(self)
        }


@dataclass(frozen=True, slots=True)
class MoralComposite:
    """ProfileとStateを合成した観測用の要約値。"""

    prosocial_activation: float
    adversarial_activation: float
    effective_restraint: float

    def __post_init__(self) -> None:
        for item in fields(self):
            _validate_01(item.name, float(getattr(self, item.name)))

    def as_dict(self) -> dict[str, float]:
        return {
            item.name: float(getattr(self, item.name))
            for item in fields(self)
        }
