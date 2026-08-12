from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Protocol

from app.domain.activities import Activity
from app.ports.response_generator import ResponseGenerator
from app.ports.structured_output import (
    StructuredOutputContract,
    StructuredOutputGenerationError,
    StructuredOutputUnsupportedError,
)


class SituationEvaluationModel(Protocol):
    async def evaluate(self, activity: Activity) -> str: ...


class OptionalSituationEvaluationModel(Protocol):
    async def evaluate(self, activity: Activity) -> str | None: ...


class CharacterModel(Protocol):
    async def generate_character_response(self, activity: Activity) -> str: ...


class ResponseValidationModel(Protocol):
    async def validate_character_response(self, activity: Activity) -> str: ...


class StructuredCharacterModel(Protocol):
    async def generate_structured_character_response(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]: ...


class CharacterSemanticVerificationModel(Protocol):
    async def verify_character_semantics(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]: ...


SeparatedSituationEvaluatorFactory = Callable[
    ["ResponseGeneratorRoleAdapter"],
    OptionalSituationEvaluationModel,
]


class ResponseGeneratorRoleAdapter:
    """既存ResponseGeneratorを明示した役割Portへ接続する移行用Adapter。"""

    def __init__(
        self,
        generator: ResponseGenerator,
        *,
        separated_situation_evaluator_factory: (
            SeparatedSituationEvaluatorFactory | None
        ) = None,
    ) -> None:
        self._generator = generator
        self._separated_situation_evaluator_factory = (
            separated_situation_evaluator_factory
        )
        self._separated_situation_evaluator: (
            OptionalSituationEvaluationModel | None
        ) = None
        self._last_input_meaning_raw: str | None = None

    async def evaluate(self, activity: Activity) -> str:
        if self._uses_separated_user_input_path(activity):
            self._last_input_meaning_raw = None
            separated = await self._evaluate_user_input_with_separated_roles(activity)
            if separated is not None:
                return separated
            if self._is_legacy_situation_evaluation(self._last_input_meaning_raw):
                return self._normalize_situation_evaluation(
                    self._last_input_meaning_raw or ""
                )
        raw = await self._generate(activity)
        return self._normalize_situation_evaluation(raw)

    async def interpret_input_meaning(self, activity: Activity) -> str:
        request = self._with_input_meaning_role_boundary(activity)
        raw = await self._generate(request)
        self._last_input_meaning_raw = raw
        return raw

    async def plan_internal_directive(self, activity: Activity) -> str:
        return await self._generate(activity)

    async def generate_character_response(self, activity: Activity) -> str:
        raw = await self._generate(activity)
        return self._normalize_closing_character_response(activity, raw)

    async def validate_character_response(self, activity: Activity) -> str:
        return await self._generate(activity)

    async def generate_structured_character_response(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]:
        return await self._generate_structured(activity, contract)

    async def verify_character_semantics(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]:
        return await self._generate_structured(activity, contract)

    async def _generate(self, activity: Activity) -> str:
        result = await self._generator.generate_response(activity)
        return str(result)

    async def _generate_structured(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]:
        method = getattr(self._generator, "generate_structured_response", None)
        if not callable(method):
            raise StructuredOutputUnsupportedError(
                "configured ResponseGenerator does not support structured output"
            )
        result = await method(activity, contract)
        if not isinstance(result, Mapping):
            raise StructuredOutputGenerationError(
                "structured response generator returned a non-mapping payload"
            )
        return dict(result)

    @staticmethod
    def _uses_separated_user_input_path(activity: Activity) -> bool:
        if activity.context.get("llm_role") != "situation_evaluator":
            return False
        if not str(activity.context.get("user_input") or "").strip():
            return False
        planner_state = activity.context.get("planner_state")
        if isinstance(planner_state, dict) and isinstance(
            planner_state.get("ongoing_activity"),
            dict,
        ):
            # 進行中Activityの入力意味はプラグイン契約に依存するため、
            # 専用契約が整うまでは既存の安全な継続判定へ委ねる。
            return False
        return True

    async def _evaluate_user_input_with_separated_roles(
        self,
        activity: Activity,
    ) -> str | None:
        factory = self._separated_situation_evaluator_factory
        if factory is None:
            factory = self._default_separated_situation_evaluator_factory
        if self._separated_situation_evaluator is None:
            self._separated_situation_evaluator = factory(self)
        return await self._separated_situation_evaluator.evaluate(activity)

    def _default_separated_situation_evaluator_factory(
        self,
        role_model: "ResponseGeneratorRoleAdapter",
    ) -> OptionalSituationEvaluationModel:
        """既存Compositionとの互換用既定Factory。

        PromptBuilderの正規実装は外部Adapterではなく、外部I/O非依存の
        ``app.prompting`` に置く。明示Factoryが注入された場合は使用しない。
        """

        from app.prompting import (
            InputMeaningPromptBuilder,
            InternalDirectivePromptBuilder,
        )
        from app.runtime.separated_situation_evaluator import (
            SeparatedSituationEvaluationAdapter,
        )

        return SeparatedSituationEvaluationAdapter(
            role_model,
            role_model,
            input_prompt_builder=InputMeaningPromptBuilder(),
            directive_prompt_builder=InternalDirectivePromptBuilder(),
            character_profile=getattr(
                self._generator,
                "_character_profile",
                None,
            ),
        )

    @staticmethod
    def _with_input_meaning_role_boundary(activity: Activity) -> Activity:
        prompt = activity.context.get("plugin_prompt_override")
        if not isinstance(prompt, str):
            return activity
        boundary = "\n".join(
            (
                "# 移行互換用の役割境界",
                "旧Situation Evaluatorの責務『入力を総合して次のActivityを決定』は、"
                "Input Meaning Interpreterでは行わない。",
                '{"available_activities":"not provided to Input Meaning Interpreter"}',
            )
        )
        context = dict(activity.context)
        context["plugin_prompt_override"] = f"{prompt}\n{boundary}"
        return replace(activity, context=context)

    @classmethod
    def _normalize_closing_character_response(
        cls,
        activity: Activity,
        raw: str,
    ) -> str:
        response_context = activity.context.get("response_context")
        if not isinstance(response_context, dict):
            return raw
        if str(response_context.get("conversation_phase") or "") != "winding_down":
            return raw
        payload = cls._json_object(raw)
        if payload is not None and cls._has_character_speech(payload):
            return raw
        return json.dumps(
            {
                "speech": "おやすみ。またね。",
                "expression": "soft_smile",
                "gesture": None,
                "voice_intent": {"style": "gentle"},
                "pause_after_seconds": 0.0,
                "reaction_segments": None,
                "claims": [
                    {
                        "claim_type": "conversation_only",
                        "activity_type": None,
                        "operation": None,
                        "status": None,
                        "target": None,
                        "confidence": 1.0,
                        "evidence": "終了意図に対する短い別れの挨拶",
                    }
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _has_character_speech(payload: dict[str, object]) -> bool:
        speech = payload.get("speech")
        if isinstance(speech, str) and speech.strip():
            return True
        segments = payload.get("reaction_segments")
        if not isinstance(segments, list):
            return False
        return any(
            isinstance(item, dict)
            and isinstance(item.get("speech"), str)
            and bool(str(item["speech"]).strip())
            for item in segments
        )

    @classmethod
    def _is_legacy_situation_evaluation(cls, raw: str | None) -> bool:
        if raw is None:
            return False
        payload = cls._json_object(raw)
        if payload is None:
            return False
        return {
            "decision",
            "activity_type",
            "operation",
            "confidence",
        }.issubset(payload)

    @classmethod
    def _normalize_situation_evaluation(cls, raw: str) -> str:
        """LLMが返すCore内部の会話名をSituation契約へ正規化する。"""

        payload = cls._json_object(raw)
        if payload is None:
            return raw
        if payload.get("activity_type") != "conversation_with_user":
            return raw

        normalized = dict(payload)
        normalized["activity_type"] = "conversation"
        if normalized.get("operation") in {"start", "continue"}:
            normalized["operation"] = "discuss"
        return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _json_object(raw: str) -> dict[str, object] | None:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) < 3 or lines[-1].strip() != "```":
                return None
            text = "\n".join(lines[1:-1]).strip()
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None
        return dict(payload) if isinstance(payload, dict) else None
