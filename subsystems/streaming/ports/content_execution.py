"""Neutral boundary for Core-owned character and output execution."""

from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

SPEAK_ACTION_TYPE = "speak"


class StreamActionExecutionResult(Protocol):
    action_id: str
    action_type: str
    status: str


class StreamOutputExecutionResult(Protocol):
    action_results: tuple[StreamActionExecutionResult, ...]


class StreamCharacterExecutionResult(Protocol):
    result_id: str
    adopted_text: str | None


class StreamContentExecutionResult(Protocol):
    activity_turn_id: str
    final_status: str
    failure_stage: str | None
    character_result: StreamCharacterExecutionResult | None
    output_result: StreamOutputExecutionResult | None


@dataclass(frozen=True, slots=True)
class UnavailableStreamContentExecutionResult:
    """Stable result returned while the optional Core connection is absent."""

    activity_turn_id: str
    final_status: str = "unavailable"
    failure_stage: str | None = "content_execution.not_connected"
    character_result: None = None
    output_result: None = None


class UnavailableStreamContentExecutor:
    async def __call__(
        self, _request: dict[str, object], _trace_id: str
    ) -> UnavailableStreamContentExecutionResult:
        return UnavailableStreamContentExecutionResult(activity_turn_id=str(uuid4()))
