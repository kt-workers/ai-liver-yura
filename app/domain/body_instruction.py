from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


BODY_EXPRESSION_ACTIVITY_TYPE = "body_expression_loop"
BODY_ACTION_INTENT_CONSTRAINT = "body_action_intent"


@dataclass(frozen=True, slots=True)
class BodyInstruction:
    """入力意味またはInternal Directiveが保持するモデル非依存の身体意味。

    StructuredInputMeaning上では「ユーザーが要求した身体行動」、Internal Directiveの
    body_action_intent上では「ゆら自身が意識的に行うと決めた身体行動」を表す。
    Pose軸、角度、モーション名、再生時刻は含めない。

    単一の身体意味はeffector/direction/side/magnitudeで表す。複数部位を同時に動かす
    一つの意識的行動はcomponentsへ複数のBodyInstructionを保持する。componentsは
    プリセット列ではなく、同時に満たす高レベル身体意味の集合である。

    left/right は常に行為主体である「ゆら自身」を基準にする。side の left/right は
    ゆら自身の解剖学的左/右、direction の left/right はゆら自身から見て左/右を表し、
    視聴者・カメラ・画面の左右へ読み替えない。表示上の鏡像変換は Renderer / Avatar
    Adapter の責務であり、この意味契約へ持ち込まない。
    """

    effector: str
    direction: str
    side: str | None = None
    magnitude: float = 1.0
    components: tuple[BodyInstruction, ...] = ()

    def __post_init__(self) -> None:
        effector = self.effector.strip().lower()
        direction = self.direction.strip().lower()
        side = self.side.strip().lower() if isinstance(self.side, str) else None
        if not effector or len(effector) > 64:
            raise ValueError("effector must be a non-empty string up to 64 characters")
        if not direction or len(direction) > 64:
            raise ValueError("direction must be a non-empty string up to 64 characters")
        if side is not None and (not side or len(side) > 32):
            raise ValueError("side must be null or a non-empty string up to 32 characters")
        if isinstance(self.magnitude, bool) or not isinstance(
            self.magnitude, (int, float)
        ):
            raise TypeError("magnitude must be a number")
        magnitude = float(self.magnitude)
        if not 0.0 <= magnitude <= 1.0:
            raise ValueError("magnitude must be between 0.0 and 1.0")
        if not isinstance(self.components, tuple):
            raise TypeError("components must be a tuple")
        if len(self.components) > 8:
            raise ValueError("components must contain at most 8 body meanings")
        if any(not isinstance(component, BodyInstruction) for component in self.components):
            raise TypeError("components must contain only BodyInstruction values")
        if any(component.components for component in self.components):
            raise ValueError("nested body instruction components are not supported")
        object.__setattr__(self, "effector", effector)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "magnitude", magnitude)

    @property
    def is_composite(self) -> bool:
        return bool(self.components)

    def as_context(self) -> dict[str, object]:
        context: dict[str, object] = {
            "effector": self.effector,
            "direction": self.direction,
            "side": self.side,
            "magnitude": self.magnitude,
        }
        if self.components:
            context["components"] = [component.as_context() for component in self.components]
        return context

    @classmethod
    def from_context(cls, value: object) -> BodyInstruction | None:
        return cls._from_context(value, allow_components=True)

    @classmethod
    def _from_context(
        cls,
        value: object,
        *,
        allow_components: bool,
    ) -> BodyInstruction | None:
        if not isinstance(value, dict):
            return None
        effector = value.get("effector")
        direction = value.get("direction")
        side = value.get("side")
        magnitude = value.get("magnitude", 1.0)
        if not isinstance(effector, str) or not isinstance(direction, str):
            return None
        if side is not None and not isinstance(side, str):
            return None

        components_value = value.get("components", [])
        if not allow_components and components_value not in (None, []):
            return None
        if components_value is None:
            components_value = []
        if not isinstance(components_value, list) or len(components_value) > 8:
            return None
        components: list[BodyInstruction] = []
        for item in components_value:
            component = cls._from_context(item, allow_components=False)
            if component is None:
                return None
            components.append(component)

        try:
            return cls(
                effector=effector,
                direction=direction,
                side=side,
                magnitude=magnitude,  # type: ignore[arg-type]
                components=tuple(components),
            )
        except (TypeError, ValueError):
            return None


class BodyConstraintExecutionStatus(str, Enum):
    ACCEPTED = "accepted"
    APPLIED = "applied"
    REJECTED = "rejected"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class BodyConstraintExecutionResult:
    """Speechとは独立した、一時Body制約の実行結果。

    ACCEPTEDは受付のみ、APPLIEDはBody Controllerの権威状態へ制約を
    コミット済みであることを表す。ブラウザ描画完了までは保証しない。
    """

    status: BodyConstraintExecutionStatus
    constraint_id: str | None
    reason: str
    target_axes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        reason = self.reason.strip()
        if not reason:
            raise ValueError("reason must not be empty")
        if self.constraint_id is not None:
            constraint_id = self.constraint_id.strip()
            if not constraint_id:
                raise ValueError("constraint_id must not be blank")
            object.__setattr__(self, "constraint_id", constraint_id[:128])
        object.__setattr__(self, "reason", reason[:240])
        object.__setattr__(
            self,
            "target_axes",
            tuple(str(axis).strip() for axis in self.target_axes if str(axis).strip()),
        )

    @property
    def accepted(self) -> bool:
        return self.status in {
            BodyConstraintExecutionStatus.ACCEPTED,
            BodyConstraintExecutionStatus.APPLIED,
        }

    @property
    def applied(self) -> bool:
        return self.status is BodyConstraintExecutionStatus.APPLIED

    def as_context(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "constraint_id": self.constraint_id,
            "reason": self.reason,
            "target_axes": list(self.target_axes),
        }


__all__ = [
    "BODY_ACTION_INTENT_CONSTRAINT",
    "BODY_EXPRESSION_ACTIVITY_TYPE",
    "BodyConstraintExecutionResult",
    "BodyConstraintExecutionStatus",
    "BodyInstruction",
]
