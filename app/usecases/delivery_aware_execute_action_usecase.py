from __future__ import annotations

from app.usecases.execute_action_usecase import (
    ExecuteActionUsecase as BaseExecuteActionUsecase,
)


class ExecuteActionUsecase(BaseExecuteActionUsecase):
    """後方互換名。

    Coreの発話確定は基底UseCaseが担当する。TTS・音声再生は任意の出力
    チャネルであり、その障害をSPEAK Actionの失敗へ変換しない。
    """

    pass
