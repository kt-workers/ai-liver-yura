from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.body_speech import SpeechPresentationRequest
from gui.body_pose_lab.composition import BodyPoseLabComposition
from gui.body_pose_lab.config import BodyPoseLabConfig
from gui.body_pose_lab.payload_decoder import (
    BodyPoseLabPayloadDecoder,
    BodyPoseLabPayloadError,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_body_runtime_layer_does_not_depend_on_bootstrap() -> None:
    runtime_files = (
        "app/runtime/body_aware_agent_life_service.py",
        "app/runtime/body_emotion_bridge.py",
        "app/runtime/body_emotion_state_store.py",
        "app/runtime/state_driven_body_pose_runtime.py",
        "app/runtime/state_driven_body_controller.py",
    )

    for relative_path in runtime_files:
        content = (_REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
        assert "app.bootstrap" not in content, relative_path


def test_controller_does_not_use_fixed_body_command_names() -> None:
    controller = (
        _REPOSITORY_ROOT / "app/runtime/state_driven_body_controller.py"
    ).read_text(encoding="utf-8")
    forbidden_commands = (
        "right_hand_raise",
        "left_hand_raise",
        "both_hands_raise",
        "head_circle",
        "body_sway",
        "body_twist",
    )

    for command in forbidden_commands:
        assert command not in controller


def test_external_constraint_decoder_accepts_only_normalized_pose_axes() -> None:
    decoder = BodyPoseLabPayloadDecoder()

    with pytest.raises(BodyPoseLabPayloadError):
        decoder.decode_external_constraint(
            {
                "constraint_id": "legacy-command",
                "duration_ms": 1200,
                "targets": [
                    {
                        "axis": "right_hand_raise",
                        "value": 1.0,
                        "weight": 1.0,
                    }
                ],
            }
        )


def test_diagnostics_do_not_retain_speech_text_prompt_or_memory() -> None:
    components = BodyPoseLabComposition.create(
        BodyPoseLabConfig(port=0, local_simulation=False)
    )
    secret_text = "SECRET_USER_CONVERSATION_BODY_TEXT"
    try:
        components.application.present_speech(
            SpeechPresentationRequest(
                source_activity_id="activity-safe",
                output_unit_id="output-safe",
                text=secret_text,
                audio_reference="test://speech-safe",
                duration_ms=1200,
                presentation_id="presentation-safe",
            )
        )
        frame = components.application.tick_once(dt_seconds=1.0 / 30.0)
        diagnostic_payload = {
            "application": components.application.snapshot().as_payload(),
            "frames": components.frame_hub.snapshot().as_payload(),
            "frame": frame.as_payload(),
        }
        serialized = json.dumps(diagnostic_payload, ensure_ascii=False)

        assert secret_text not in serialized
        for forbidden_key in (
            "prompt",
            "memory",
            "raw_user_text",
            "character_response",
        ):
            assert forbidden_key not in serialized
    finally:
        components.http_server.close()
