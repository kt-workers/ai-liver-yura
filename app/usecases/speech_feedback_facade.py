"""Speech Feedbackの互換入口。処理の実装はUse Casesが所有する。"""

from app.usecases.speech_feedback import CoreSpeechFeedback as CoreSpeechFeedback
from app.usecases.speech_feedback import (
    SpeechFactDeliveryDisposition as SpeechFactDeliveryDisposition,
)
from app.usecases.speech_presentation_observation import (
    ObservedSpeechPresentationBoundary as ObservedSpeechPresentationBoundary,
)
