from __future__ import annotations

from app.domain.speech_runtime.policy import (
    SpeechCandidatePriority,
    SpeechExpiryRule,
    SpeechQueueOverflowPolicy,
    SpeechRuntimeOperationalPolicy,
)
from app.domain.speech_runtime.runtime import SpeechRuntime


def runtime_policy(
    *,
    revision: int = 1,
    queue_capacity: int = 4,
    max_in_flight: int = 4,
    max_background_in_flight: int = 2,
    max_regeneration_attempts: int = 1,
    speculative_tts_limit: int = 2,
    overflow_policy: SpeechQueueOverflowPolicy = SpeechQueueOverflowPolicy.REJECT_NEW,
    background_age_seconds: float = 120.0,
    normal_age_seconds: float = 120.0,
    foreground_age_seconds: float = 120.0,
    direct_user_age_seconds: float = 120.0,
) -> SpeechRuntimeOperationalPolicy:
    return SpeechRuntimeOperationalPolicy(
        policy_id="test.speech-runtime",
        policy_revision=revision,
        prepared_queue_capacity=queue_capacity,
        max_in_flight_preparations=max_in_flight,
        max_background_in_flight_preparations=max_background_in_flight,
        max_regeneration_attempts=max_regeneration_attempts,
        expiry_rules=(
            SpeechExpiryRule(SpeechCandidatePriority.BACKGROUND, background_age_seconds),
            SpeechExpiryRule(SpeechCandidatePriority.NORMAL, normal_age_seconds),
            SpeechExpiryRule(SpeechCandidatePriority.FOREGROUND, foreground_age_seconds),
            SpeechExpiryRule(SpeechCandidatePriority.DIRECT_USER, direct_user_age_seconds),
        ),
        speculative_tts_limit=speculative_tts_limit,
        queue_overflow_policy=overflow_policy,
    )


class TestSpeechRuntime(SpeechRuntime):
    """既存unit testへ明示test policyを注入するtest-only runtime。"""

    __test__ = False

    def __init__(self) -> None:
        super().__init__(runtime_policy())
