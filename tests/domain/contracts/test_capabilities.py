import pytest

from app.domain.contracts import (
    CapabilityAvailability,
    CapabilityDescriptor,
    CapabilityRequirement,
)


def descriptor(
    availability: CapabilityAvailability = CapabilityAvailability.AVAILABLE,
) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id="voice-1",
        capability_type="speech.output",
        operations=("synthesize", "cancel"),
        availability=availability,
        revision=2,
        attributes={"languages": ["ja-JP"]},  # type: ignore[dict-item]
    )


def test_descriptor_matches_available_requirement() -> None:
    requirement = CapabilityRequirement("speech.output", "synthesize")
    assert descriptor().satisfies(requirement)


def test_degraded_requires_explicit_permission() -> None:
    degraded = descriptor(CapabilityAvailability.DEGRADED)
    assert not degraded.satisfies(CapabilityRequirement("speech.output", "synthesize"))
    assert degraded.satisfies(
        CapabilityRequirement("speech.output", "synthesize", allow_degraded=True)
    )


@pytest.mark.parametrize(
    "requirement",
    [
        CapabilityRequirement("body.output", "synthesize"),
        CapabilityRequirement("speech.output", "stream"),
    ],
)
def test_descriptor_rejects_wrong_type_or_operation(requirement: CapabilityRequirement) -> None:
    assert not descriptor().satisfies(requirement)


def test_unavailable_and_unknown_never_satisfy() -> None:
    requirement = CapabilityRequirement("speech.output", "synthesize", allow_degraded=True)
    assert not descriptor(CapabilityAvailability.UNAVAILABLE).satisfies(requirement)
    assert not descriptor(CapabilityAvailability.UNKNOWN).satisfies(requirement)


def test_descriptor_owns_operations_and_attributes() -> None:
    operations = ["synthesize"]
    languages = ["ja-JP"]
    value = CapabilityDescriptor(
        "voice-1",
        "speech.output",
        operations,  # type: ignore[arg-type]
        CapabilityAvailability.AVAILABLE,
        0,
        {"languages": languages},  # type: ignore[dict-item]
    )
    operations.append("cancel")
    languages.append("en-US")

    assert value.operations == ("synthesize",)
    assert value.to_dict()["attributes"] == {"languages": ["ja-JP"]}


@pytest.mark.parametrize("revision", [-1, True, 1.0, "1"])
def test_descriptor_revision_is_strict(revision: object) -> None:
    with pytest.raises(ValueError):
        CapabilityDescriptor(
            "voice-1",
            "speech.output",
            ("synthesize",),
            CapabilityAvailability.AVAILABLE,
            revision,  # type: ignore[arg-type]
            {},
        )


def test_descriptor_rejects_duplicate_operations() -> None:
    with pytest.raises(ValueError, match="unique"):
        CapabilityDescriptor(
            "voice-1",
            "speech.output",
            ("synthesize", "synthesize"),
            CapabilityAvailability.AVAILABLE,
            0,
            {},
        )


def test_descriptor_serializes_provider_independent_snapshot() -> None:
    assert descriptor().to_dict() == {
        "capability_id": "voice-1",
        "capability_type": "speech.output",
        "operations": ["synthesize", "cancel"],
        "availability": "available",
        "revision": 2,
        "attributes": {"languages": ["ja-JP"]},
    }
