from __future__ import annotations

from app.domain.causal_diagnostics import CausalRouteDescriptor, RouteLifecycle


class LegacyRouteInventory:
    """因果再設計後に残る旧・互換経路の役割を明示する台帳。"""

    _ROUTES = (
        CausalRouteDescriptor(
            name="interaction_intention_appraisal",
            lifecycle=RouteLifecycle.ACTIVE,
            removable=False,
            reason="CharacterとBodyの共通上流意図を導出する現行経路",
        ),
        CausalRouteDescriptor(
            name="internal_directive_activity_selection",
            lifecycle=RouteLifecycle.ACTIVE,
            removable=False,
            reason="Activity Registryと検証済みActivity選択がまだ依存する現行経路",
        ),
        CausalRouteDescriptor(
            name="internal_directive_to_intention_projection",
            lifecycle=RouteLifecycle.COMPATIBILITY,
            removable=False,
            reason="旧Internal Directiveと新Interaction Intentionの比較に必要",
            replacement="interaction_intention_appraisal",
        ),
        CausalRouteDescriptor(
            name="drive_should_start_autonomous_talk",
            lifecycle=RouteLifecycle.COMPATIBILITY,
            removable=False,
            reason="Phase 4の保守的ANDゲートとして自律発話の拡張を抑止する",
            replacement="autonomous_interaction_decider",
        ),
        CausalRouteDescriptor(
            name="autonomous_interaction_decider",
            lifecycle=RouteLifecycle.ACTIVE,
            removable=False,
            reason="Emotion・Motivation・会話状態から自律開始を因果判断する",
        ),
        CausalRouteDescriptor(
            name="autonomous_topic_should_complete_tuple",
            lifecycle=RouteLifecycle.COMPATIBILITY,
            removable=False,
            reason="既存呼出し向けのtuple API。内部処理は型付き継続判断へ移行する",
            replacement="autonomous_topic_evaluate_completion",
        ),
        CausalRouteDescriptor(
            name="legacy_expression_name",
            lifecycle=RouteLifecycle.COMPATIBILITY,
            removable=False,
            reason="既存Avatar OutputとCharacter JSON parserが参照する互換表現",
            replacement="interaction_expression_projection",
        ),
        CausalRouteDescriptor(
            name="legacy_gesture_name",
            lifecycle=RouteLifecycle.COMPATIBILITY,
            removable=False,
            reason="既存Avatar Adapterの移行完了まで必要な互換表現",
            replacement="embodied_expression_intent",
        ),
        CausalRouteDescriptor(
            name="character_self_reported_claims",
            lifecycle=RouteLifecycle.COMPATIBILITY,
            removable=False,
            reason="Character JSON互換の診断入力。事実判定権限は持たない",
            replacement="deterministic_fact_validator",
        ),
        CausalRouteDescriptor(
            name="deterministic_fact_validator",
            lifecycle=RouteLifecycle.ACTIVE,
            removable=False,
            reason="ActivityExecutionResultと発話本文を独立照合する現行事実境界",
        ),
        CausalRouteDescriptor(
            name="user_body_command_as_primary_motion_driver",
            lifecycle=RouteLifecycle.DEPRECATED,
            removable=True,
            reason="BodyはEmotion・Drive・Interaction Intentionから自律生成するため主経路にしない",
            replacement="state_driven_body_pose_runtime",
        ),
    )

    @classmethod
    def all(cls) -> tuple[CausalRouteDescriptor, ...]:
        return cls._ROUTES

    @classmethod
    def get(cls, name: str) -> CausalRouteDescriptor:
        normalized = name.strip()
        for route in cls._ROUTES:
            if route.name == normalized:
                return route
        raise KeyError(normalized)

    @classmethod
    def as_context(cls) -> list[dict[str, object]]:
        return [route.as_context() for route in cls._ROUTES]
