from __future__ import annotations

from app.domain.cognitive_direction import StructuredInputMeaning
from app.runtime.body_motion_request_resolver import (
    normalize_body_motion_meaning,
)


def normalize_avatar_body_command(
    meaning: StructuredInputMeaning,
) -> StructuredInputMeaning:
    """互換入口から、身体指示を運動プリミティブへ正規化する。

    旧実装のように`right_hand_raise`等の完成動作名へ変換しない。対象、軌道、
    時間、反復、合成規則を持つ`BodyMotionRequest`をentitiesへ格納する。
    """

    return normalize_body_motion_meaning(meaning)
