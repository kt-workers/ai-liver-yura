from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from app.domain.activities import Activity
from app.ports.response_generator import ResponseGenerator


class SituationEvaluationModel(Protocol):
    async def evaluate(self, activity: Activity) -> str: ...


class OptionalSituationEvaluationModel(Protocol):
    async def evaluate(self, activity: Activity) -> str | None: ...


class CharacterModel(Protocol):
    async def generate_character_response(self, activity: Activity) -> str: ...


class ResponseValidationModel(Protocol):
    async def validate_character_response(self, activity: Activity) -> str: ...


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

    async def evaluate(self, activity: Activity) -> str:
        if self._uses_separated_user_input_path(activity):
            separated = await self._evaluate_user_input_with_separated_roles(activity)
            # USER_TEXTの意味解釈に失敗した場合、旧Situation JSONやraw textの
            # lexical fallbackへ戻らない。空結果を返し、上位のSituationEvaluatorで
            # semantic_unresolvedとして安全側へ処理する。
            return separated if separated is not None else ""
        raw = await self._generate(activity)
        return self._normalize_situation_evaluation(raw)

    async def interpret_input_meaning(self, activity: Activity) -> str:
        request = self._with_input_meaning_role_boundary(activity)
        return await self._generate(request)

    async def plan_internal_directive(self, activity: Activity) -> str:
        return await self._generate(activity)

    async def generate_character_response(self, activity: Activity) -> str:
        raw = await self._generate(activity)
        return self._normalize_closing_character_response(activity, raw)

    async def validate_character_response(self, activity: Activity) -> str:
        return await self._generate(activity)

    async def _generate(self, activity: Activity) -> str:
        result = await self._generator.generate_response(activity)
        return str(result)

    @staticmethod
    def _uses_separated_user_input_path(activity: Activity) -> bool:
        return bool(
            activity.context.get("llm_role") == "situation_evaluator"
            and str(activity.context.get("user_input") or "").strip()
        )

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
