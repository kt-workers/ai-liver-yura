from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .common import JsonValue, freeze_json, require_identifier, require_revision, thaw_json


class CapabilityAvailability(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    capability_type: str
    operation: str
    allow_degraded: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.capability_type, "capability_type")
        require_identifier(self.operation, "operation")

    def to_dict(self) -> dict[str, object]:
        return {
            "capability_type": self.capability_type,
            "operation": self.operation,
            "allow_degraded": self.allow_degraded,
        }


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    capability_id: str
    capability_type: str
    operations: tuple[str, ...]
    availability: CapabilityAvailability
    revision: int
    attributes: JsonValue

    def __post_init__(self) -> None:
        require_identifier(self.capability_id, "capability_id")
        require_identifier(self.capability_type, "capability_type")
        operations = tuple(self.operations)
        if not operations or any(
            not isinstance(item, str) or not item.strip() for item in operations
        ):
            raise ValueError("operations must contain non-empty strings")
        if len(set(operations)) != len(operations):
            raise ValueError("operations must be unique")
        object.__setattr__(self, "operations", operations)
        require_revision(self.revision, "revision")
        object.__setattr__(self, "attributes", freeze_json(self.attributes))

    def satisfies(self, requirement: CapabilityRequirement) -> bool:
        if self.capability_type != requirement.capability_type:
            return False
        if requirement.operation not in self.operations:
            return False
        if self.availability is CapabilityAvailability.AVAILABLE:
            return True
        return self.availability is CapabilityAvailability.DEGRADED and requirement.allow_degraded

    def to_dict(self) -> dict[str, object]:
        return {
            "capability_id": self.capability_id,
            "capability_type": self.capability_type,
            "operations": list(self.operations),
            "availability": self.availability.value,
            "revision": self.revision,
            "attributes": thaw_json(self.attributes),
        }
