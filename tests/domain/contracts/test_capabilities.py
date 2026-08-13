import json

import pytest

from app.domain.contracts import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityRequirement,
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
