from __future__ import annotations

from cloud_validation import character_response_lab as base
from cloud_validation import character_semantic_response_lab as semantic


def _register_contract_completion_presets() -> None:
    """現行Semantic coreをEmotion以外の内部状態sourceでも横断確認する。"""

    common_emotion = {
        "current": {
            "reactive": {
                "joy": 0.22,
                "amusement": 0.08,
                "calm": 0.55,
                "anger": 0.0,
            }
        }
    }

    base._PRESETS["extended_drive_curiosity_high"] = base._preset(
        label="拡張E7: Drive Curiosity高",
        user_input="今、好奇心は強い？",
        target_id="curiosity",
        emotion=common_emotion,
        drive={"curiosity": 0.82, "engagement": 0.58, "energy": 0.7},
    )
    base._PRESETS["extended_drive_energy_low"] = base._preset(
        label="拡張E8: Drive Energy低",
        user_input="今、元気はある？",
        target_id="energy",
        emotion=common_emotion,
        drive={"curiosity": 0.48, "engagement": 0.52, "energy": 0.18},
    )

    for key, reason in (
        (
            "extended_drive_curiosity_high",
            "ユーザーは現在の好奇心の強さを直接尋ねている",
        ),
        (
            "extended_drive_energy_low",
            "ユーザーは現在の活力を直接尋ねている",
        ),
    ):
        semantic._fix_preset_reason(key, reason)


_register_contract_completion_presets()

settings = semantic.settings
service = semantic.service
app = semantic.app

__all__ = ["app", "service", "settings"]
