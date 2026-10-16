"""Speech Presentationの実行観測に関するドメイン契約。"""

from __future__ import annotations

from app.domain.activity_execution.observation import (
    ExecutionObservationIngressPolicy,
    ExecutionObservationSourceBinding,
    ExecutionObservationSourceRule,
)
from app.domain.contracts import ExecutionStatus

SPEECH_OBSERVATION_SOURCE = ExecutionObservationSourceBinding("speech-presentation-report", 1)
SPEECH_OBSERVATION_RULE = ExecutionObservationSourceRule(
    SPEECH_OBSERVATION_SOURCE,
    (
        ExecutionStatus.OBSERVABLE,
        ExecutionStatus.COMPLETED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.FAILED,
    ),
    ("text-presentation", "audio-presentation-started"),
    terminal_requires_prior_effect=True,
)
SPEECH_OBSERVATION_POLICY = ExecutionObservationIngressPolicy(
    "speech-execution-observation",
    1,
    (SPEECH_OBSERVATION_RULE,),
)
