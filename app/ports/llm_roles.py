from __future__ import annotations

import json
from dataclasses import replace
from typing import Protocol

from app.domain.activities import Activity
from app.ports.response_generator import ResponseGenerator


class SituationEvaluationModel(Protocol):
    async def evaluate(self, activity: Activity) -> str: ...


class CharacterModel(Protocol):
    async def generate_character_response(self, activity: Activity) -> str: ...


class ResponseValidationModel(Protocol):
    async def validate_character_response(self, activity: Activity) -> str: ...


class ResponseGeneratorRoleAdapter:
    """既存ResponseGeneratorを明示した役割Portへ接続する移行用Adapter。"""

    def __init__(self, generator: ResponseGenerator) -> None:
        self._generator = generator
        self._separated_situation_evaluator: object | None = None
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
        return await self._generate(activity)

    async def validate_character_response(self, activity: Activity) -> str:
        return await self._generate(activity)

    async def _generate(self, activity: Activity) -> str:
        result = await self._generator.generate_response(activity)
        return str(result)

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
        if self._separated_situation_evaluator is None:
            from app.adapters.prompt.cognitive_direction_prompt_builders import (
                InputMeaningPromptBuilder,
                InternalDirectivePromptBuilder,
            )
            from app.runtime.separated_situation_evaluator import (
                SeparatedSituationEvaluationAdapter,
            )

            self._separated_situation_evaluator = SeparatedSituationEvaluationAdapter(
                self,
                self,
                input_prompt_builder=InputMeaningPromptBuilder(),
                directive_prompt_builder=InternalDirectivePromptBuilder(),
                character_profile=getattr(
                    self._generator,
                    "_character_profile",
                    None,
                ),
            )
        evaluate = getattr(self._separated_situation_evaluator, "evaluate")
        result = await evaluate(activity)
        return str(result) if result is not None else None

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
