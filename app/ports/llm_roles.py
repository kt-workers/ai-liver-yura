from __future__ import annotations

import json

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

    async def evaluate(self, activity: Activity) -> str:
        raw = await self._generate(activity)
        return self._normalize_situation_evaluation(raw)

    async def generate_character_response(self, activity: Activity) -> str:
        return await self._generate(activity)

    async def validate_character_response(self, activity: Activity) -> str:
        return await self._generate(activity)

    async def _generate(self, activity: Activity) -> str:
        result = await self._generator.generate_response(activity)
        return str(result)

    @staticmethod
    def _normalize_situation_evaluation(raw: str) -> str:
        """LLMが返すCore内部の会話名をSituation契約へ正規化する。"""

        text = raw.strip()
        fenced = text.startswith("```")
        if fenced:
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
