from __future__ import annotations

from app.domain.actions import ActionPlanGroup, ActionType
from app.domain.activity_turn_result import ActionExecutionStatus, ActivityOutputResult
from app.domain.output_delivery import is_optional_output_degraded


def completed_speech_text(
    group: ActionPlanGroup,
    output_result: ActivityOutputResult,
) -> str | None:
    """Core出力境界を通過したSPEAK本文を返す。

    通常完了に加え、テキスト出力コミット後に任意の音声チャネルだけが
    縮退した結果も発話成立として扱う。キャンセル、出力前失敗、その他の
    Action失敗は発話成立に含めない。
    """

    delivered_ids = {
        result.action_id
        for result in output_result.action_results
        if result.action_type == ActionType.SPEAK.value
        and (
            result.status == ActionExecutionStatus.COMPLETED
            or (
                result.status == ActionExecutionStatus.FAILED
                and is_optional_output_degraded(result.error)
            )
        )
    }
    return next(
        (
            action.text
            for action in group.action_plans
            if action.action_type == ActionType.SPEAK
            and action.action_id in delivered_ids
        ),
        None,
    )
