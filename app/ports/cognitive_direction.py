from __future__ import annotations

from typing import Protocol

from app.domain.activities import Activity
from app.domain.cognitive_direction import (
    InternalDirective,
    StructuredInputMeaning,
)


class InputMeaningModel(Protocol):
    async def interpret_input_meaning(self, activity: Activity) -> str: ...


class InternalDirectiveModel(Protocol):
    async def plan_internal_directive(self, activity: Activity) -> str: ...


class InputMeaningPromptBuilder(Protocol):
    def build(self, planning_input: dict[str, object]) -> str: ...


class InternalDirectivePromptBuilder(Protocol):
    def build(
        self,
        meaning: StructuredInputMeaning,
        planning_input: dict[str, object],
        *,
        character_profile: dict[str, object],
    ) -> str: ...


class InputMeaningInterpreterPort(Protocol):
    async def interpret(
        self,
        activity: Activity,
        planning_input: dict[str, object],
    ) -> StructuredInputMeaning | None: ...


class InternalDirectivePlannerPort(Protocol):
    async def plan(
        self,
        activity: Activity,
        meaning: StructuredInputMeaning,
        planning_input: dict[str, object],
        *,
        character_profile: dict[str, object],
    ) -> InternalDirective | None: ...
