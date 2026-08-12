from __future__ import annotations

from typing import Mapping

from app.domain.activities import Activity
from app.ports.structured_output import (
    StructuredCharacterModel,
    StructuredOutputContract,
    StructuredResponseModel,
)


class StructuredCharacterModelAdapter(StructuredCharacterModel):
    """Provider非依存StructuredResponseModelをCharacter roleへ限定するAdapter。"""

    def __init__(self, model: StructuredResponseModel) -> None:
        self._model = model

    async def generate_character_utterance(
        self,
        activity: Activity,
        contract: StructuredOutputContract,
    ) -> Mapping[str, object]:
        return await self._model.generate_structured(activity, contract)
