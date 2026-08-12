from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from app.domain.activities import Activity


class StructuredOutputUnsupportedError(RuntimeError):
    """Provider/Modelがschema-critical structured outputを提供できない。"""


class StructuredOutputGenerationError(RuntimeError):
    """Structured output requestが正常なtyped payloadを返せなかった。"""


@dataclass(frozen=True, slots=True)
class StructuredOutputContract:
    """Provider非依存のJSON Schema出力契約。"""

    name: str
    schema: Mapping[str, object]
    strict: bool = True

    def __post_init__(self) -> None:
        name = self.name.strip()
        if not name:
            raise ValueError("StructuredOutputContract.nameは空にできません。")
        if len(name) > 64:
            raise ValueError("StructuredOutputContract.nameは64文字以下にしてください。")
        if any(not (char.isalnum() or char in {"_", "-"}) for char in name):
            raise ValueError("StructuredOutputContract.nameに使用できない文字があります。")
        if self.schema.get("type") != "object":
            raise ValueError("StructuredOutputContract.schemaはobject schemaにしてください。")
        object.__setattr__(self, "name", name)

    def as_context(self) -> dict[str, object]:
        return {
            "name": self.name,
            "schema": dict(self.schema),
            "strict": self.strict,
        }


class StructuredResponseGenerator(Protocol):
    async def generate_structured_response(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]: ...
