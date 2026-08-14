from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from app.domain.contracts import CapabilityAvailability, EventEnvelope

from .contracts import (
    InputAdmission,
    InputAdmissionStatus,
    InputModality,
    InputObservation,
    InputPermission,
    InputRejectionReason,
    InputSessionPhase,
    InputSessionSample,
    NormalizedInputEvent,
    observation_payload,
)


@dataclass(slots=True)
class _ActiveSession:
    sequence: int


class InputAdmissionLedger:
    def __init__(self) -> None:
        self._observation_ids: set[str] = set()
        self._lock = Lock()

    def admit_once(self, observation_id: str) -> bool:
        with self._lock:
            if observation_id in self._observation_ids:
                return False
            self._observation_ids.add(observation_id)
            return True


_PROCESS_ADMISSION_LEDGER = InputAdmissionLedger()


class InputSessionRegistry:
    def __init__(self) -> None:
        self._active: dict[tuple[str, str], _ActiveSession] = {}
        self._terminated: set[tuple[str, str]] = set()
        self._lock = Lock()

    def admit(
        self, source_id: str, sample: InputSessionSample | None
    ) -> InputRejectionReason | None:
        if sample is None:
            return None
        key = (source_id, sample.session_id)
        with self._lock:
            if key in self._terminated:
                return InputRejectionReason.SESSION_TERMINATED
            active = self._active.get(key)
            if sample.phase is InputSessionPhase.START:
                if active is not None:
                    return InputRejectionReason.SESSION_ALREADY_EXISTS
                self._active[key] = _ActiveSession(sample.sequence)
                return None
            if active is None:
                return InputRejectionReason.SESSION_NOT_ACTIVE
            if sample.sequence <= active.sequence:
                return InputRejectionReason.SESSION_SEQUENCE_OUT_OF_ORDER
            if sample.phase in (InputSessionPhase.END, InputSessionPhase.CANCEL):
                self._active.pop(key)
                self._terminated.add(key)
            else:
                active.sequence = sample.sequence
            return None


_PROCESS_SESSION_REGISTRY = InputSessionRegistry()


class InputNormalizer:
    def __init__(
        self,
        admission_ledger: InputAdmissionLedger | None = None,
        session_registry: InputSessionRegistry | None = None,
    ) -> None:
        self._admission_ledger = admission_ledger or _PROCESS_ADMISSION_LEDGER
        self._session_registry = session_registry or _PROCESS_SESSION_REGISTRY

    def normalize(self, observation: InputObservation) -> InputAdmission:
        if not self._admission_ledger.admit_once(observation.observation_id):
            return self._reject(InputRejectionReason.DUPLICATE, duplicate=True)

        source_reason = self._source_rejection(observation)
        if source_reason is not None:
            return self._reject(source_reason)

        session_reason = self._session_registry.admit(
            observation.source.source_id, observation.session
        )
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

    @staticmethod
    def _reject(reason: InputRejectionReason, *, duplicate: bool = False) -> InputAdmission:
        return InputAdmission(
            InputAdmissionStatus.DUPLICATE if duplicate else InputAdmissionStatus.REJECTED,
            reason=reason,
        )
