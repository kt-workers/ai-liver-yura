from __future__ import annotations

from dataclasses import dataclass

from app.domain.contracts import CapabilityAvailability, EventEnvelope

from .contracts import (
    InputAdmission,
    InputAdmissionStatus,
    InputModality,
    InputObservation,
    InputPermission,
    InputRejectionReason,
    InputSessionPhase,
    NormalizedInputEvent,
    observation_payload,
)


@dataclass(slots=True)
class _ActiveSession:
    sequence: int


class InputNormalizer:
    def __init__(self) -> None:
        self._observations: set[str] = set()
        self._active_sessions: dict[tuple[str, str], _ActiveSession] = {}
        self._terminated_sessions: set[tuple[str, str]] = set()

    def normalize(self, observation: InputObservation) -> InputAdmission:
        if observation.observation_id in self._observations:
            return self._reject(InputRejectionReason.DUPLICATE, duplicate=True)
        self._observations.add(observation.observation_id)

        source_reason = self._source_rejection(observation)
        if source_reason is not None:
            return self._reject(source_reason)

        session_reason = self._session_rejection(observation)
        if session_reason is not None:
            return self._reject(session_reason)

        envelope = EventEnvelope(
            event_id=f"input:{observation.observation_id}",
            event_type=f"input.{observation.modality.value}.{observation.semantic_unit}",
            source=observation.source.source_id,
            occurred_at=observation.observed_at,
            trace_id=observation.trace_id,
            correlation_id=observation.correlation_id,
            causation_event_id=observation.causation_event_id,
            revisions=observation.revisions,
            payload=observation_payload(observation),
        )
        self._apply_session(observation)
        return InputAdmission(
            InputAdmissionStatus.ACCEPTED,
            NormalizedInputEvent(
                envelope,
                observation.modality,
                observation.source,
                observation.session,
                observation.pointer,
                observation.contact,
            ),
        )

    @staticmethod
    def _source_rejection(observation: InputObservation) -> InputRejectionReason | None:
        if observation.modality is InputModality.LIFECYCLE:
            return None
        if observation.source.availability not in (
            CapabilityAvailability.AVAILABLE,
            CapabilityAvailability.DEGRADED,
        ):
            return InputRejectionReason.SOURCE_UNAVAILABLE
        if observation.source.permission is InputPermission.DENIED:
            return InputRejectionReason.PERMISSION_DENIED
        if observation.source.permission is InputPermission.UNKNOWN:
            return InputRejectionReason.PERMISSION_UNKNOWN
        return None

    def _session_rejection(self, observation: InputObservation) -> InputRejectionReason | None:
        sample = observation.session
        if sample is None:
            return None
        key = (observation.source.source_id, sample.session_id)
        if key in self._terminated_sessions:
            return InputRejectionReason.SESSION_TERMINATED
        active = self._active_sessions.get(key)
        if sample.phase is InputSessionPhase.START:
            if active is not None:
                return InputRejectionReason.SESSION_ALREADY_EXISTS
            return None
        if active is None:
            return InputRejectionReason.SESSION_NOT_ACTIVE
        if sample.sequence <= active.sequence:
            return InputRejectionReason.SESSION_SEQUENCE_OUT_OF_ORDER
        return None

    def _apply_session(self, observation: InputObservation) -> None:
        sample = observation.session
        if sample is None:
            return
        key = (observation.source.source_id, sample.session_id)
        if sample.phase in (InputSessionPhase.END, InputSessionPhase.CANCEL):
            self._active_sessions.pop(key, None)
            self._terminated_sessions.add(key)
        else:
            self._active_sessions[key] = _ActiveSession(sample.sequence)

    @staticmethod
    def _reject(reason: InputRejectionReason, *, duplicate: bool = False) -> InputAdmission:
        return InputAdmission(
            InputAdmissionStatus.DUPLICATE if duplicate else InputAdmissionStatus.REJECTED,
            reason=reason,
        )
