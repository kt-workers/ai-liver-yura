from __future__ import annotations

from app.domain.body_instruction import BodyInstruction
from app.domain.body_pose_dynamics import BodyPoseAxis
from app.prompting.body_aware_input_meaning_prompt_builder import (
    BodyAwareInputMeaningPromptBuilder,
)
from app.runtime.body_instruction_constraint_resolver import (
    BodyInstructionConstraintResolver,
)


def test_input_meaning_prompt_uses_yura_anatomical_left_right() -> None:
    prompt = BodyAwareInputMeaningPromptBuilder().build(
        {
            "event": {
                "type": "user_text",
                "source_event_id": "event-left-right-contract",
                "user_text": "左手を挙げて",
            }
        }
    )

    assert "left/rightは常に行為主体であるゆら自身を基準" in prompt
    assert "side=left/rightはゆら自身の解剖学的左/右" in prompt
    assert "視聴者・カメラ・画面の左右へ読み替えない" in prompt


def test_left_arm_semantics_map_only_to_left_arm_axis() -> None:
    resolution = BodyInstructionConstraintResolver().resolve(
        BodyInstruction("arm", "raise", side="left", magnitude=1.0)
    )

    assert resolution.constraint is not None
    assert tuple(target.axis for target in resolution.constraint.targets) == (
        BodyPoseAxis.LEFT_ARM_RAISE,
    )


def test_right_arm_semantics_map_only_to_right_arm_axis() -> None:
    resolution = BodyInstructionConstraintResolver().resolve(
        BodyInstruction("arm", "raise", side="right", magnitude=1.0)
    )

    assert resolution.constraint is not None
    assert tuple(target.axis for target in resolution.constraint.targets) == (
        BodyPoseAxis.RIGHT_ARM_RAISE,
    )
