import json
from typing import cast

import pytest

from app.domain.contracts import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityRequirement,
    JsonInput,
)


def test_capability_requirement_matches_available_descriptor() -> None:
    descriptor = CapabilityDescriptor(
        capability_id="body-runtime",
        capability_type="body.motion",
        operations=("plan", "execute"),
        availability=CapabilityAvailability.AVAILABLE,
        revision=3,
        attributes={"supports_realtime": True},
    )

    assert descriptor.supports(
        CapabilityRequirement(capability_type="body.motion", operation="execute")
    )
    assert not descriptor.supports(
        CapabilityRequirement(capability_type="speech.tts", operation="execute")
    )
    json.dumps(descriptor.to_dict())


def test_degraded_capability_requires_explicit_opt_in() -> None:
    descriptor = CapabilityDescriptor(
        capability_id="speech-output",
        capability_type="speech.output",
        operations=("present",),
        availability=CapabilityAvailability.DEGRADED,
    )

    assert not descriptor.supports(
        CapabilityRequirement(capability_type="speech.output", operation="present")
    )
    assert descriptor.supports(
        CapabilityRequirement(
            capability_type="speech.output",
            operation="present",
            allow_degraded=True,
        )
    )


def test_capability_descriptor_rejects_duplicate_operations() -> None:
    with pytest.raises(ValueError, match="must not contain duplicates"):
        CapabilityDescriptor(
            capability_id="duplicate",
            capability_type="test",
            operations=("run", "run"),
            availability=CapabilityAvailability.AVAILABLE,
        )


def test_capability_descriptor_owns_operations_snapshot() -> None:
    operations = ["plan"]

    descriptor = CapabilityDescriptor(
        capability_id="mutable-operations",
        capability_type="test",
        operations=cast(tuple[str, ...], operations),
        availability=CapabilityAvailability.AVAILABLE,
    )
    operations.append("mutated")

    assert descriptor.operations == ("plan",)
    assert descriptor.to_dict()["operations"] == ["plan"]


def test_capability_descriptor_rejects_non_string_attribute_key() -> None:
    attributes = cast(dict[str, JsonInput], {1: True})

    with pytest.raises(TypeError, match="JSON object keys must be strings"):
        CapabilityDescriptor(
            capability_id="invalid-attributes",
            capability_type="test",
            operations=("run",),
            availability=CapabilityAvailability.AVAILABLE,
            attributes=attributes,
        )
