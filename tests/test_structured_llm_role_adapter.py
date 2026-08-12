from __future__ import annotations

from collections.abc import Mapping

import pytest

from app.domain.activities import Activity, ActivityType
from app.ports.llm_roles import ResponseGeneratorRoleAdapter
from app.ports.structured_output import (
    StructuredOutputContract,
    StructuredOutputUnsupportedError,
)


class _TextOnlyGenerator:
    async def generate_response(self, activity: Activity) -> str:
        del activity
        return "legacy text"


class _StructuredGenerator(_TextOnlyGenerator):
    def __init__(self) -> None:
        self.calls: list[tuple[Activity, StructuredOutputContract]] = []

    async def generate_structured_response(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]:
        self.calls.append((activity, contract))
        return {"ok": True}


def _contract() -> StructuredOutputContract:
    return StructuredOutputContract(
        name="role_contract",
        schema={
            "type": "object",
            "additionalProperties": False,
            "required": ["ok"],
            "properties": {"ok": {"type": "boolean"}},
        },
    )


def _activity(role: str) -> Activity:
    return Activity(
        activity_type=ActivityType.BEHAVIOR_PLANNING,
        goal="structured role test",
        context={"llm_role": role},
    )


@pytest.mark.asyncio
async def test_structured_character_role_delegates_to_provider_capability() -> None:
    generator = _StructuredGenerator()
    adapter = ResponseGeneratorRoleAdapter(generator)  # type: ignore[arg-type]

    result = await adapter.generate_structured_character_response(
        _activity("character_language_realizer"),
        _contract(),
    )

    assert result == {"ok": True}
    assert len(generator.calls) == 1


@pytest.mark.asyncio
async def test_semantic_verifier_role_uses_same_provider_neutral_structured_boundary() -> None:
    generator = _StructuredGenerator()
    adapter = ResponseGeneratorRoleAdapter(generator)  # type: ignore[arg-type]

    result = await adapter.verify_character_semantics(
        _activity("character_semantic_verifier"),
        _contract(),
    )

    assert result == {"ok": True}
    assert generator.calls[0][0].context["llm_role"] == "character_semantic_verifier"


@pytest.mark.asyncio
async def test_structured_role_does_not_silently_fallback_to_text_generator() -> None:
    adapter = ResponseGeneratorRoleAdapter(_TextOnlyGenerator())  # type: ignore[arg-type]

    with pytest.raises(StructuredOutputUnsupportedError):
        await adapter.verify_character_semantics(
            _activity("character_semantic_verifier"),
            _contract(),
        )
