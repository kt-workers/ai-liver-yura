from __future__ import annotations

from collections.abc import Mapping

from app.domain.character_response import ResponseContext
from app.domain.response_content_plan import ResponseContentPlan
from app.domain.semantic_utterance import (
    InterpersonalContentContext,
    SemanticProposition,
    SemanticTarget,
    SemanticUtterancePlan,
)


_INTERNAL_STATE_TYPES = frozenset({"internal_state", "agent_internal_state"})
_OVERVIEW_TARGETS = frozenset({"current_feeling", "current_mood", "feeling", "mood"})
_DISCOURSE_KEYS = frozenset(
    {
        "topic_transition",
        "acknowledgement_need",
        "selected_topic_source",
        "response_obligation",
    }
)
_STATE_PRIORITY = {
    "very_high": 5,
    "high": 4,
    "moderate": 3,
    "low": 2,
    "present": 1,
    "absent": 0,
    "unknown": -1,
}


class ResponseSemanticsPlanner:
    """内部状態・実行事実・対話制約をCharacter非依存の発言意味へ投影する。"""

    def plan(self, context: ResponseContext) -> SemanticUtterancePlan:
        envelope = self._validated_envelope(context)
        directive = self._directive(envelope)
        target = self._target(envelope)
        direct_internal = self._is_direct_internal_state_question(envelope, target)
        content_plan = ResponseContentPlan.from_context(
            context.memory.get("response_content_plan")
        )

        propositions: list[SemanticProposition] = []
        reasons: list[str] = []
        if direct_internal and target is not None:
            propositions.extend(
                self._internal_state_propositions(context, target, content_plan)
            )
            reasons.append("typed_internal_state_target_projected")

        question_budget = self._budget(
            directive.get("question_budget"),
            fallback=content_plan.question_budget,
        )
        new_direction_budget = self._budget(
            directive.get("new_direction_budget"),
            fallback=content_plan.new_direction_budget,
        )
        self_disclosure = self._self_disclosure(directive, content_plan)

        required_content = self._string_tuple(directive.get("content_requirements"))
        if direct_internal:
            # Internal-state direct answers use structured propositions as the source of truth.
            # Planner-generated natural-language state labels are not carried forward.
            required_content = ()

        forbidden_additions = list(self._string_tuple(directive.get("forbidden_claims")))
        forbidden_additions.extend(claim.value for claim in context.forbidden_claims)
        if direct_internal:
            forbidden_additions.extend(
                (
                    "contradict_target_state",
                    "substitute_non_target_state",
                    "unsupported_new_self_state",
                    "expose_internal_numeric_state",
                )
            )

        speech_act = "direct_answer" if direct_internal else (context.speech_act or "statement")
        response_length = (
            "short"
            if direct_internal and question_budget == 0 and new_direction_budget == 0
            else "normal"
        )

        return SemanticUtterancePlan(
            speech_act=speech_act,
            target=target,
            propositions=tuple(propositions),
            required_content=required_content,
            optional_content=(),
            forbidden_additions=self._dedupe(tuple(forbidden_additions)),
            response_length=response_length,
            self_disclosure=self_disclosure,
            question_budget=question_budget,
            new_direction_budget=new_direction_budget,
            interpersonal=self._interpersonal(context.relationship),
            discourse_context=self._discourse_context(context),
            reasons=tuple(reasons or ("semantic_plan_from_response_context",)),
        )

    @staticmethod
    def _validated_envelope(context: ResponseContext) -> dict[str, object]:
        value = context.constraints.get("_internal_directive")
        return dict(value) if isinstance(value, Mapping) else {}

    @staticmethod
    def _directive(envelope: Mapping[str, object]) -> dict[str, object]:
        value = envelope.get("internal_directive")
        return dict(value) if isinstance(value, Mapping) else {}

    @staticmethod
    def _target(envelope: Mapping[str, object]) -> SemanticTarget | None:
        meaning = envelope.get("structured_input_meaning")
        if not isinstance(meaning, Mapping):
            return None
        target = meaning.get("target")
        if not isinstance(target, Mapping):
            return None
        target_type = str(target.get("type") or "").strip()
        target_id = str(target.get("id") or "").strip()
        if not target_type or not target_id:
            return None
        return SemanticTarget(target_type, target_id)

    @staticmethod
    def _is_direct_internal_state_question(
        envelope: Mapping[str, object],
        target: SemanticTarget | None,
    ) -> bool:
        if target is None or target.type.casefold() not in _INTERNAL_STATE_TYPES:
            return False
        meaning = envelope.get("structured_input_meaning")
        if not isinstance(meaning, Mapping):
            return False
        speech_act = str(meaning.get("input_speech_act") or "").strip().casefold()
        expected = str(meaning.get("expected_response") or "").strip().casefold()
        return speech_act == "question" or expected == "direct_answer"

    def _internal_state_propositions(
        self,
        context: ResponseContext,
        target: SemanticTarget,
        content_plan: ResponseContentPlan,
    ) -> tuple[SemanticProposition, ...]:
        target_id = target.id.strip().casefold()
        if target_id in _OVERVIEW_TARGETS:
            overview = SemanticProposition(
                kind="self_state",
                predicate=target.id,
                state="overview" if context.emotion else "unknown",
                certainty="high" if context.emotion else "low",
                evidence_refs=("emotion",) if context.emotion else (),
            )
            dimensions = self._reactive_emotion_dimensions(context.emotion)
            return (overview, *dimensions)

        candidate_keys = self._candidate_dimension_keys(target_id)
        match = self._find_dimension(
            context.emotion,
            path="emotion",
            candidate_keys=candidate_keys,
        )
        if match is None:
            match = self._find_dimension(
                context.drive,
                path="drive",
                candidate_keys=candidate_keys,
            )
        if match is None:
            match = self._find_dimension(
                context.situation,
                path="situation",
                candidate_keys=candidate_keys,
            )

        if match is not None:
            path, value = match
            state, concept = self._semantic_state(value)
            return (
                SemanticProposition(
                    kind="self_state",
                    predicate=target.id,
                    state=state,
                    certainty="high",
                    concept=concept,
                    evidence_refs=(path,),
                ),
            )

        if target_id in {"current_desire", "desire"} and content_plan.primary_desire:
            return (
                SemanticProposition(
                    kind="self_state",
                    predicate=target.id,
                    state="present",
                    certainty="medium",
                    concept=content_plan.primary_desire,
                    evidence_refs=("response_content_plan.primary_desire",),
                ),
            )

        return (
            SemanticProposition(
                kind="self_state",
                predicate=target.id,
                state="unknown",
                certainty="low",
            ),
        )

    def _reactive_emotion_dimensions(
        self,
        emotion: object,
    ) -> tuple[SemanticProposition, ...]:
        reactive = self._find_named_mapping(emotion, "reactive")
        if reactive is None:
            return ()
        dimensions: list[SemanticProposition] = []
        for raw_key, value in reactive.items():
            if not self._is_scalar(value):
                continue
            key = str(raw_key).strip()
            if not key:
                continue
            state, concept = self._semantic_state(value)
            dimensions.append(
                SemanticProposition(
                    kind="self_state_dimension",
                    predicate=key,
                    state=state,
                    certainty="high",
                    concept=concept,
                    evidence_refs=(f"emotion.reactive.{key}",),
                )
            )
        dimensions.sort(
            key=lambda item: (_STATE_PRIORITY.get(item.state, -1), item.predicate),
            reverse=True,
        )
        return tuple(dimensions[:8])

    @classmethod
    def _find_named_mapping(
        cls,
        value: object,
        key_name: str,
    ) -> Mapping[str, object] | None:
        if not isinstance(value, Mapping):
            return None
        for raw_key, item in value.items():
            if str(raw_key).strip().casefold() == key_name.casefold() and isinstance(item, Mapping):
                return item
            if isinstance(item, Mapping):
                nested = cls._find_named_mapping(item, key_name)
                if nested is not None:
                    return nested
        return None

    @staticmethod
    def _candidate_dimension_keys(target_id: str) -> frozenset[str]:
        keys = {target_id}
        for prefix in ("current_", "agent_"):
            if target_id.startswith(prefix) and len(target_id) > len(prefix):
                keys.add(target_id[len(prefix) :])
        return frozenset(item.casefold() for item in keys if item)

    @classmethod
    def _find_dimension(
        cls,
        value: object,
        *,
        path: str,
        candidate_keys: frozenset[str],
    ) -> tuple[str, object] | None:
        if not isinstance(value, Mapping):
            return None
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.strip().casefold()
            item_path = f"{path}.{key}"
            if cls._matches_dimension_key(normalized, candidate_keys) and cls._is_scalar(item):
                return item_path, item
            if isinstance(item, Mapping):
                nested = cls._find_dimension(
                    item,
                    path=item_path,
                    candidate_keys=candidate_keys,
                )
                if nested is not None:
                    return nested
        return None

    @staticmethod
    def _matches_dimension_key(key: str, candidate_keys: frozenset[str]) -> bool:
        if key in candidate_keys:
            return True
        return any(key.endswith(f"_{candidate}") for candidate in candidate_keys)

    @staticmethod
    def _is_scalar(value: object) -> bool:
        return value is None or isinstance(value, (str, int, float, bool))

    @staticmethod
    def _semantic_state(value: object) -> tuple[str, str | None]:
        if isinstance(value, bool):
            return ("present" if value else "absent", None)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            numeric = max(0.0, min(1.0, float(value)))
            if numeric <= 0.05:
                return "absent", None
            if numeric < 0.35:
                return "low", None
            if numeric < 0.65:
                return "moderate", None
            if numeric < 0.85:
                return "high", None
            return "very_high", None
        if value is None:
            return "unknown", None
        concept = str(value).strip()
        return ("present", concept) if concept else ("unknown", None)

    @staticmethod
    def _budget(value: object, *, fallback: int) -> int:
        if value == 1:
            return 1
        if value == 0:
            return 0
        return 1 if fallback == 1 else 0

    @staticmethod
    def _self_disclosure(
        directive: Mapping[str, object],
        content_plan: ResponseContentPlan,
    ) -> str:
        value = directive.get("self_disclosure_level")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return "brief" if float(value) >= 0.35 else "none"
        return content_plan.self_disclosure_level

    @staticmethod
    def _string_tuple(value: object) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple)):
            return ()
        return tuple(
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        )

    @staticmethod
    def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
        result: list[str] = []
        for value in values:
            if value not in result:
                result.append(value)
        return tuple(result)

    @staticmethod
    def _interpersonal(value: object) -> InterpersonalContentContext:
        relationship = dict(value) if isinstance(value, Mapping) else {}

        def semantic_string(key: str, default: str) -> str:
            item = relationship.get(key)
            return str(item).strip() if isinstance(item, str) and item.strip() else default

        return InterpersonalContentContext(
            disclosure_permission=semantic_string("disclosure_permission", "normal"),
            boundary_sensitivity=semantic_string("boundary_sensitivity", "normal"),
            social_distance=semantic_string("social_distance", "unspecified"),
            current_tension=semantic_string("current_tension", "unspecified"),
        )

    @staticmethod
    def _discourse_context(context: ResponseContext) -> dict[str, str]:
        value = context.memory.get("discourse_appraisal")
        if not isinstance(value, Mapping):
            return {}
        result: dict[str, str] = {}
        for key in _DISCOURSE_KEYS:
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                result[key] = item.strip()
        return result
