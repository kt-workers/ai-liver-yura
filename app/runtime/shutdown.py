from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite

from app.domain.contracts.common import require_identifier, require_revision


class RuntimeShutdownStage(str, Enum):
    IN_FLIGHT_SETTLE = "in_flight_settle"
    FINAL_PERSISTENCE = "final_persistence"
    RESOURCE_CLOSE = "resource_close"
    OWNED_TASK_JOIN = "owned_task_join"
    PENDING_OWNED_WORK = "pending_owned_work"


@dataclass(frozen=True, slots=True)
class RuntimeShutdownFailure:
    stage: RuntimeShutdownStage
    error_class: str

    def __post_init__(self) -> None:
        if not isinstance(self.stage, RuntimeShutdownStage):
            raise ValueError("shutdown stageが不正です")
        require_identifier(self.error_class, "shutdown error_class")


@dataclass(frozen=True, slots=True)
class RuntimeShutdownPolicy:
    policy_id: str
    policy_revision: int
    in_flight_settle_grace_seconds: float
    final_persistence_grace_seconds: float
    resource_close_grace_seconds: float
    owned_task_join_grace_seconds: float

    def __post_init__(self) -> None:
        require_identifier(self.policy_id, "runtime shutdown policy_id")
        require_revision(self.policy_revision, "runtime shutdown policy_revision")
        for name in (
            "in_flight_settle_grace_seconds",
            "final_persistence_grace_seconds",
            "resource_close_grace_seconds",
            "owned_task_join_grace_seconds",
        ):
            value = getattr(self, name)
            if type(value) not in (int, float) or not isfinite(value) or value < 0:
                raise ValueError(f"{name}はfiniteな0以上のnumberでなければなりません")


class RuntimeShutdownError(RuntimeError):
    def __init__(self, failures: tuple[RuntimeShutdownFailure, ...]) -> None:
        if not failures:
            raise ValueError("shutdown failureは空にできません")
        if any(not isinstance(item, RuntimeShutdownFailure) for item in failures):
            raise ValueError("shutdown failureが不正です")
        self.failures = failures
        super().__init__("runtime shutdown did not complete cleanly")
