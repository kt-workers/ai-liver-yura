from __future__ import annotations

import json
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

    async def evaluate(self, activity: Activity) -> str:
        if self._uses_separated_user_input_path(activity):
            separated = await self._evaluate_user_input_with_separated_roles(activity)
            if separated is not None:
                return separated
        raw = await self._generate(activity)
        return self._normalize_situation_evaluation(raw)

    async def interpret_input_meaning(self, activity: Activity) -> str:
        return await self._generate(activity)

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
        return (
            activity.context.get("llm_role") == "situation_evaluator"
            and bool(str(activity.context.get("user_input") or "").strip())
        )

    async def _evaluate_user_input_with_separated_roles(
        self,
        activity: Activity,
    ) -> str | None:
        if self._separated_situation_evaluator is None:
            from app.runtime.separated_situation_evaluator import (
                SeparatedSituationEvaluationAdapter,
            )

            self._separated_situation_evaluator = SeparatedSituationEvaluationAdapter(
                self,
                self,
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
    def _normalize_situation_evaluation(raw: str) -> str:
        """LLMが返すCore内部の会話名をSituation契約へ正規化する。"""

        text = raw.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) < 3 or lines[-1].strip() != "```":
                return raw
            text = "\n".join(lines[1:-1]).strip()
            if text.startswith("json"):
                text = text[4:].strip()
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return raw
        if not isinstance(payload, dict):
            return raw
        if payload.get("activity_type") != "conversation_with_user":
            return raw

        normalized = dict(payload)
        normalized["activity_type"] = "conversation"
        if normalized.get("operation") in {"start", "continue"}:
            normalized["operation"] = "discuss"
        return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
