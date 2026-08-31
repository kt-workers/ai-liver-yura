from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from threading import Lock

from app.domain.brain_operational_bounds import BrainOperationalBoundsPolicy
from app.domain.contracts import CapabilityAvailability, EventEnvelope
from app.domain.contracts.common import thaw_json

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
        self,
        source_id: str,
        sample: InputSessionSample | None,
        *,
        max_active_sessions_per_source: int,
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
                active_for_source = sum(
                    1 for active_source_id, _ in self._active if active_source_id == source_id
                )
                if active_for_source >= max_active_sessions_per_source:
                    return InputRejectionReason.ACTIVE_SESSION_LIMIT_REACHED
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


def _canonical_json_utf8_bytes(value: object) -> int:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return len(encoded)


def _text_payload(observation: InputObservation) -> str | None:
    if observation.modality not in (InputModality.TEXT, InputModality.SPEECH):
        return None
    payload = thaw_json(observation.payload)
    if isinstance(payload, str):
        return payload
    if isinstance(payload, Mapping):
        text = payload.get("text")
        if isinstance(text, str):
            return text
        transcript = payload.get("transcript")
        if isinstance(transcript, str):
            return transcript
    return None


class InputNormalizer:
    def __init__(
        self,
        admission_ledger: InputAdmissionLedger | None = None,
        session_registry: InputSessionRegistry | None = None,
        *,
        bounds_policy: BrainOperationalBoundsPolicy,
    ) -> None:
        if not isinstance(bounds_policy, BrainOperationalBoundsPolicy):
            raise ValueError("bounds_policy は BrainOperationalBoundsPolicy でなければなりません")
        self._admission_ledger = admission_ledger or _PROCESS_ADMISSION_LEDGER
        self._session_registry = session_registry or _PROCESS_SESSION_REGISTRY
        self._bounds_policy = bounds_policy

    def normalize(self, observation: InputObservation) -> InputAdmission:
        if not self._admission_ledger.admit_once(observation.observation_id):
            return self._reject(InputRejectionReason.DUPLICATE, duplicate=True)

        source_reason = self._source_rejection(observation)
        if source_reason is not None:
            return self._reject(source_reason)

        bounds_reason = self._bounds_rejection(observation)
        if bounds_reason is not None:
            return self._reject(bounds_reason)

        session_reason = self._session_registry.admit(
            observation.source.source_id,
            observation.session,
            max_active_sessions_per_source=(
                self._bounds_policy.input.max_active_sessions_per_source
            ),
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

    def _bounds_rejection(self, observation: InputObservation) -> InputRejectionReason | None:
        bounds = self._bounds_policy.input
        text = _text_payload(observation)
        if text is not None and len(text) > bounds.max_text_codepoints:
            return InputRejectionReason.INPUT_TEXT_TOO_LARGE
        payload = thaw_json(observation.payload)
        if _canonical_json_utf8_bytes(payload) > bounds.max_payload_json_bytes:
            return InputRejectionReason.INPUT_PAYLOAD_TOO_LARGE
        if observation.session is not None and (
            _canonical_json_utf8_bytes(observation.session.to_dict())
            > bounds.max_session_metadata_json_bytes
        ):
            return InputRejectionReason.INPUT_SESSION_METADATA_TOO_LARGE
        return None

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
