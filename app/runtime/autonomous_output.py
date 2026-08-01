from __future__ import annotations

from app.domain.actions import ActionPlanGroup, ActionType
from app.domain.activity_turn_result import ActionExecutionStatus, ActivityOutputResult


def completed_speech_text(
    group: ActionPlanGroup,
    output_result: ActivityOutputResult,
) -> str | None:
    """Core出力境界を通過して完了したSPEAK本文を返す。

    VOICEVOXやAudio Playerは任意の後段チャネルであり、その障害は
    ExecuteActionUsecase内でTraceへ記録される。CoreのSPEAK Actionは
    テキストコミット後に完了するため、ここでは通常の完了結果だけを
    発話成立として扱う。キャンセルや出力境界前の失敗は含めない。
    """

    completed_ids = {
        result.action_id
        for result in output_result.action_results
        if result.action_type == ActionType.SPEAK.value
        and result.status == ActionExecutionStatus.COMPLETED
    }
    return next(
        (
            action.text
            for action in group.action_plans
            if action.action_type == ActionType.SPEAK
            and action.action_id in completed_ids
        ),
        None,
    )
