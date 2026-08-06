from __future__ import annotations

from dataclasses import dataclass

from gui.body_pose_lab.application import BodyPoseLabApplicationService
from gui.body_pose_lab.frame_hub import BodyPoseLabFrameHub
from gui.body_pose_lab.payload_decoder import (
    BodyPoseLabPayloadDecoder,
    BodyPoseLabPayloadError,
)
from gui.body_pose_lab.tick_loop import BodyPoseLabTickLoop


@dataclass(frozen=True, slots=True)
class BodyPoseLabApiResponse:
    status: int
    payload: dict[str, object]


class BodyPoseLabApiController:
    """HTTPメソッドとPathを型付きLab操作へ割り当てる。"""

    def __init__(
        self,
        *,
        application: BodyPoseLabApplicationService,
        frame_hub: BodyPoseLabFrameHub,
        tick_loop: BodyPoseLabTickLoop,
        decoder: BodyPoseLabPayloadDecoder | None = None,
    ) -> None:
        self._application = application
        self._frame_hub = frame_hub
        self._tick_loop = tick_loop
        self._decoder = decoder or BodyPoseLabPayloadDecoder()

    def handle(
        self,
        method: str,
        path: str,
        payload: object | None = None,
    ) -> BodyPoseLabApiResponse:
        normalized_method = method.strip().upper()
        try:
            return self._dispatch(normalized_method, path, payload)
        except BodyPoseLabPayloadError as error:
            return self._error(400, "invalid_request", str(error))
        except (TypeError, ValueError) as error:
            return self._error(400, "invalid_request", str(error))
        except RuntimeError as error:
            return self._error(409, "request_conflict", str(error))

    def _dispatch(
        self,
        method: str,
        path: str,
        payload: object | None,
    ) -> BodyPoseLabApiResponse:
        if method == "GET" and path == "/health":
            return BodyPoseLabApiResponse(
                200,
                {
                    "status": "ok",
                    "tick_running": self._tick_loop.running,
                    "tick_error": self._tick_loop.last_error,
                },
            )
        if method == "GET" and path == "/api/snapshot":
            return BodyPoseLabApiResponse(
                200,
                {
                    "application": self._application.snapshot().as_payload(),
                    "frames": self._frame_hub.snapshot().as_payload(),
                    "tick": {
                        "running": self._tick_loop.running,
                        "last_error": self._tick_loop.last_error,
                    },
                },
            )
        if method == "POST" and path == "/api/emotion":
            self._application.update_emotion(
                self._decoder.decode_emotion(self._required_payload(payload))
            )
            return self._accepted("emotion_updated")
        if method == "POST" and path == "/api/activity-context":
            self._application.update_activity_context(
                self._decoder.decode_activity_context(
                    self._required_payload(payload)
                )
            )
            return self._accepted("activity_context_updated")
        if method == "POST" and path == "/api/attention-candidates":
            self._application.update_attention_candidates(
                self._decoder.decode_attention_candidates(
                    self._required_payload(payload)
                )
            )
            return self._accepted("attention_candidates_updated")
        if method == "POST" and path == "/api/external-constraint":
            self._application.apply_external_constraint(
                self._decoder.decode_external_constraint(
                    self._required_payload(payload)
                )
            )
            return self._accepted("external_constraint_applied")
        if method == "DELETE" and path == "/api/external-constraint":
            self._application.clear_external_constraint()
            return self._accepted("external_constraint_cleared")
        if method == "POST" and path == "/api/speech":
            request, energy = self._decoder.decode_speech(
                self._required_payload(payload)
            )
            self._application.present_speech(request, energy=energy)
            return self._accepted("speech_presented")
        if method == "POST" and path == "/api/blink":
            self._application.request_blink()
            return self._accepted("blink_requested")
        if method == "POST" and path == "/api/body-pose-frame":
            frame_payload = self._required_payload(payload)
            frame = self._decoder.decode_frame(frame_payload)
            source = "external-body-runtime"
            if isinstance(frame_payload, dict):
                raw_source = frame_payload.get("source")
                if isinstance(raw_source, str) and raw_source.strip():
                    source = raw_source.strip()
            accepted = self._frame_hub.publish(frame, source=source)
            return BodyPoseLabApiResponse(
                202 if accepted else 200,
                {
                    "status": "accepted" if accepted else "ignored",
                    "reason": None if accepted else "stale_sequence",
                    "sequence": frame.sequence,
                },
            )
        return self._error(404, "not_found", "route is not available")

    @staticmethod
    def _required_payload(payload: object | None) -> object:
        if payload is None:
            raise BodyPoseLabPayloadError("JSON request body is required")
        return payload

    @staticmethod
    def _accepted(operation: str) -> BodyPoseLabApiResponse:
        return BodyPoseLabApiResponse(
            202,
            {"status": "accepted", "operation": operation},
        )

    @staticmethod
    def _error(status: int, code: str, message: str) -> BodyPoseLabApiResponse:
        return BodyPoseLabApiResponse(
            status,
            {
                "error": code,
                "message": message[:240],
            },
        )
