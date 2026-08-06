from __future__ import annotations

from dataclasses import replace

from app.domain.body_pose_dynamics import BodyPoseDynamicsState
from app.runtime.body_speech_mouth_driver import BodySpeechMouthSample


class BodySpeechPoseOverlay:
    """積分済み全身Poseへ低遅延の発話口形だけを重ねる。"""

    def apply(
        self,
        *,
        dynamics: BodyPoseDynamicsState,
        speech: BodySpeechMouthSample,
    ) -> BodyPoseDynamicsState:
        if not isinstance(dynamics, BodyPoseDynamicsState):
            raise TypeError("dynamics must be BodyPoseDynamicsState")
        if not isinstance(speech, BodySpeechMouthSample):
            raise TypeError("speech must be BodySpeechMouthSample")
        if speech.mouth_open <= dynamics.pose.mouth_open:
            return dynamics
        return replace(
            dynamics,
            pose=replace(
                dynamics.pose,
                mouth_open=speech.mouth_open,
            ),
        )
