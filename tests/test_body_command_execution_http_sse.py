from __future__ import annotations

import asyncio

import pytest

from app.adapters.avatar.body_pose_http_config import HttpBodyPoseOutputConfig
from app.adapters.avatar.http_body_pose_output import HttpBodyPoseFrameOutput
from app.bootstrap.body_runtime_factory import BodyRuntimeFactory
from app.bootstrap.body_runtime_settings import BodyRuntimeSettings
from app.domain.body_instruction import (
    BodyConstraintExecutionStatus,
    BodyInstruction,
)
from app.domain.emotions.emotion_state import EmotionState
from app.runtime.body_instruction_executor import BodyInstructionExecutor
from app.runtime.state_driven_body_pose_runtime import StateDrivenBodyPoseRuntime
from tests.support.body_pose_lab_http_harness import BodyPoseLabHttpHarness


async def _wait_for_sent_count(
    output: HttpBodyPoseFrameOutput,
    expected: int,
) -> None:
    for _ in range(300):
        if output.snapshot().sent_count >= expected:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"BodyPoseFrame sent_count did not reach {expected}: "
        f"{output.snapshot().sent_count}"
    )


@pytest.mark.asyncio
async def test_explicit_body_instruction_reaches_real_http_sse_pose_output() -> None:
    with BodyPoseLabHttpHarness.start(local_simulation=False) as harness:
        output = HttpBodyPoseFrameOutput(
            HttpBodyPoseOutputConfig(
                base_url=harness.base_url,
                timeout_seconds=1.0,
                source_name="body-command-truth-boundary-test",
            )
        )
        body = BodyRuntimeFactory().create(
            settings=BodyRuntimeSettings(
                enabled=True,
                tick_hz=30.0,
                random_seed=31,
            ),
            avatar_output=None,
            pose_output=output,
            emotion_provider=EmotionState,
        )
        assert isinstance(body, StateDrivenBodyPoseRuntime)
        executor = BodyInstructionExecutor(body_provider=lambda: body)

        try:
            await body.start()
            await _wait_for_sent_count(output, 3)

            before_look = output.snapshot().sent_count
            look_result = await executor.execute(
                BodyInstruction("head", "right", magnitude=1.0)
            )
            assert look_result.status is BodyConstraintExecutionStatus.APPLIED
            await _wait_for_sent_count(output, before_look + 10)

            look_event, look_payload = harness.first_sse_event()
            assert look_event == "body-pose-frame"
            assert look_payload["source"] == "body-command-truth-boundary-test"
            look_pose = look_payload["pose"]
            assert isinstance(look_pose, dict)
            assert float(look_pose["head_yaw"]) > 0.05
            assert float(look_pose["gaze_x"]) > 0.05

            before_arm = output.snapshot().sent_count
            arm_result = await executor.execute(
                BodyInstruction("arm", "up", side="right", magnitude=1.0)
            )
            assert arm_result.status is BodyConstraintExecutionStatus.APPLIED
            await _wait_for_sent_count(output, before_arm + 10)

            arm_event, arm_payload = harness.first_sse_event()
            assert arm_event == "body-pose-frame"
            arm_pose = arm_payload["pose"]
            assert isinstance(arm_pose, dict)
            assert float(arm_pose["right_arm_raise"]) > 0.05
        finally:
            await body.stop()
