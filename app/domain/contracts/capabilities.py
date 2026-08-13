from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import cast

from .common import (
    JsonInput,
    JsonValue,
    freeze_json_mapping,
    jsonable,
    owned_tuple,
    require_non_empty,
    require_non_negative,
)


class CapabilityAvailability(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    capability_type: str
    operation: str | None = None
    capability_id: str | None = None
    allow_degraded: bool = False

    def __post_init__(self) -> None:
        require_non_empty("capability_type", self.capability_type)
        if self.operation is not None:
            require_non_empty("operation", self.operation)
        if self.capability_id is not None:
            require_non_empty("capability_id", self.capability_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "capability_type": self.capability_type,
            "operation": self.operation,
            "capability_id": self.capability_id,
            "allow_degraded": self.allow_degraded,
        }


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    capability_id: str
    capability_type: str
    operations: tuple[str, ...]
    availability: CapabilityAvailability
    revision: int = 0
    attributes: Mapping[str, JsonInput] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_non_empty("capability_id", self.capability_id)
        require_non_empty("capability_type", self.capability_type)
        require_non_negative("revision", self.revision)
        operations = owned_tuple("operations", self.operations)
        object.__setattr__(self, "operations", operations)
        if len(set(operations)) != len(operations):
            raise ValueError("operations must not contain duplicates")
        for operation in operations:
            require_non_empty("operation", operation)
        object.__setattr__(
            self,
            "attributes",
            freeze_json_mapping("attributes", self.attributes),
        )

    def supports(self, requirement: CapabilityRequirement) -> bool:
        if requirement.capability_type != self.capability_type:
            return False
        if (
            requirement.capability_id is not None
            and requirement.capability_id != self.capability_id
        ):
            return False
        if requirement.operation is not None and requirement.operation not in self.operations:
            return False
        if self.availability is CapabilityAvailability.AVAILABLE:
            return True
        return requirement.allow_degraded and self.availability is CapabilityAvailability.DEGRADED

    def to_dict(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "capability_type": self.capability_type,
            "operations": list(self.operations),
            "availability": self.availability.value,
            "revision": self.revision,
            "attributes": jsonable(cast(JsonValue, self.attributes)),
        }
