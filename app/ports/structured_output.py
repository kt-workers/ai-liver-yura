from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from app.domain.activities import Activity


@dataclass(frozen=True, slots=True)
class StructuredOutputContract:
    """Provider非依存のJSON Schema structured output契約。"""

    name: str
    schema: Mapping[str, object]
    strict: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("StructuredOutputContract.nameは空にできません。")
        if len(self.name) > 64:
            raise ValueError("StructuredOutputContract.nameは64文字以下にしてください。")
        if not all(
            char.isascii() and (char.isalnum() or char in {"_", "-"})
            for char in self.name
        ):
            raise ValueError(
                "StructuredOutputContract.nameはASCII英数字・underscore・hyphenだけを使用してください。"
            )
        if not isinstance(self.schema, Mapping) or not self.schema:
            raise ValueError("StructuredOutputContract.schemaは空にできません。")
        if not isinstance(self.strict, bool):
            raise TypeError("StructuredOutputContract.strictはboolにしてください。")


class StructuredOutputError(RuntimeError):
    """Provider structured outputが契約どおり取得できなかったことを表す。"""


class StructuredResponseModel(Protocol):
    async def generate_structured(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]: ...


class StructuredCharacterModel(Protocol):
    async def generate_character_utterance(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]: ...
