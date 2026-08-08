from __future__ import annotations

from app.domain.body_instruction import BodyInstruction
from app.runtime.body_instruction_constraint_resolver import (
    BodyInstructionConstraintResolver,
)


def _compound(*components: dict[str, object]) -> BodyInstruction:
    instruction = BodyInstruction.from_context(
        {
            "effector": "body",
            "direction": "compose",
            "side": None,
            "magnitude": 1.0,
            "components": list(components),
        }
    )
    assert instruction is not None
    return instruction


def test_compound_body_instruction_round_trips_all_simultaneous_components() -> None:
    instruction = _compound(
        {
            "effector": "head",
            "direction": "left",
            "side": None,
            "magnitude": 1.0,
        },
        {
            "effector": "arm",
            "direction": "raise",
            "side": "right",
            "magnitude": 1.0,
        },
    )

    assert instruction.is_composite is True
    assert tuple(component.effector for component in instruction.components) == (
        "head",
        "arm",
    )
    assert instruction.as_context()["components"] == [
        {
            "effector": "head",
            "direction": "left",
            "side": None,
            "magnitude": 1.0,
        },
        {
            "effector": "arm",
            "direction": "raise",
            "side": "right",
            "magnitude": 1.0,
        },
    ]


def test_compound_head_and_arm_action_resolves_to_one_atomic_constraint() -> None:
    instruction = _compound(
        {
            "effector": "head",
            "direction": "left",
            "side": None,
            "magnitude": 1.0,
        },
        {
            "effector": "arm",
            "direction": "raise",
            "side": "right",
            "magnitude": 1.0,
        },
    )

    result = BodyInstructionConstraintResolver().resolve(instruction)

    assert result.supported is True
    assert result.reason == "body_instruction_composite_resolved"
    assert result.constraint is not None
    assert {target.axis.value for target in result.constraint.targets} == {
        "head_yaw",
        "gaze_x",
        "right_arm_raise",
    }
    assert result.constraint.duration_ms == 1900


def test_compound_body_action_rejects_conflicting_targets() -> None:
    instruction = _compound(
        {
            "effector": "head",
            "direction": "left",
            "side": None,
            "magnitude": 1.0,
        },
        {
            "effector": "head",
            "direction": "right",
            "side": None,
            "magnitude": 1.0,
        },
    )

    result = BodyInstructionConstraintResolver().resolve(instruction)

    assert result.supported is False
    assert result.reason == "unsupported_or_conflicting_body_instruction_component"


def test_nested_compound_body_instruction_is_rejected() -> None:
    instruction = BodyInstruction.from_context(
        {
            "effector": "body",
            "direction": "compose",
            "side": None,
            "magnitude": 1.0,
            "components": [
                {
                    "effector": "body",
                    "direction": "compose",
                    "side": None,
                    "magnitude": 1.0,
                    "components": [
                        {
                            "effector": "head",
                            "direction": "left",
                            "side": None,
                            "magnitude": 1.0,
                        }
                    ],
                }
            ],
        }
    )

    assert instruction is None
