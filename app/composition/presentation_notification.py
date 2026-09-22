"""#329の実Fact参照と、一度限りのGateway通知を分離する。"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from uuid import NAMESPACE_URL, uuid5

from app.composition.execution_observation import SPEECH_OBSERVATION_SOURCE
from app.composition.input_reference_context import (
    CoreInputReferenceContextBinding,
    PresentationReferenceCapacityError,
    PresentationReferenceStaleError,
)
from app.composition.speech_feedback import SpeechFactDeliveryDisposition as Delivery
from app.domain.activity_execution import ActivityExecutionAuthority
from app.domain.activity_execution.observation import (
    ExecutionObservationProvenance,
    ObservedExecutionFactRecord,
)
from app.domain.attention import AttentionTurnStore
from app.domain.brain_integration import BrainWorkAdmission
from app.domain.contracts import ExecutionStatus, RevisionVector
from app.domain.contracts.common import freeze_json
from app.domain.contracts.finalization import (
    AuthorityFinalizationFence,
    FinalizationError,
    FinalizationFailure,
)
from app.domain.contracts.snapshots import SnapshotIncoherentError
from app.domain.input_gateway import (
    InputAdmission,
    InputAdmissionStatus,
    InputModality,
    InputObservation,
    InputSourceState,
)
from app.domain.input_gateway.normalizer import InputNormalizer
from app.usecases.attention import AttentionResponseSettlementCoordinator


class PresentationNotificationState(str, Enum):
    NEW = "new"
    ADMITTED = "admitted"
    SUBMITTED = "submitted"
    TERMINAL_REJECTED = "terminal_rejected"
    STALE = "stale"


def presentation_notification_identity(record: ObservedExecutionFactRecord) -> str:
    return str(
        uuid5(
            NAMESPACE_URL,
            json.dumps(
                (
                    record.source.source_contract_id,
                    record.source.source_contract_revision,
                    record.execution_id,
                    record.record_revision,
                    record.latest_observation_id,
                ),
                separators=(",", ":"),
            ),
        )
    )


@dataclass
class CorePresentationNotification:
    """一つの提示のcurrent/直近recordだけを保持する配送状態。"""

    authority: ActivityExecutionAuthority
    attention: AttentionTurnStore
    reference: CoreInputReferenceContextBinding
    normalizer: InputNormalizer
    source: InputSourceState
    provenance: ExecutionObservationProvenance
    root_trigger_id: str
    presentation_id: str
    submit_input: Callable[[InputAdmission, str], BrainWorkAdmission]
    state: PresentationNotificationState = PresentationNotificationState.NEW
    admission: InputAdmission | None = None
    _key: str | None = None
    _revision: int = -1
    last_error: Exception | None = field(default=None, init=False, repr=False)

    def deliver(self, record: ObservedExecutionFactRecord) -> Delivery:
        if (
            record.source != SPEECH_OBSERVATION_SOURCE
            or record.provenance != self.provenance
            or record.execution_id != self.presentation_id
        ):
            raise ValueError("Presentation通知の元decision/source/trace相関が一致しません")
        publication = self.authority.observed_snapshot(
            record.source.source_contract_id, record.execution_id
        )
        if publication.value != record:
            # 古い通知のupgradeはせず、terminal recordの別配送へ任せる。
            return Delivery.TERMINAL
        key = presentation_notification_identity(record)
        if record.record_revision < self._revision:
            return Delivery.TERMINAL
        if key != self._key:
            self._key, self._revision = key, record.record_revision
            self.state, self.admission = PresentationNotificationState.NEW, None
        if self.state in (
            PresentationNotificationState.SUBMITTED,
            PresentationNotificationState.TERMINAL_REJECTED,
            PresentationNotificationState.STALE,
        ):
            return Delivery.TERMINAL
        if record.result.status is ExecutionStatus.COMPLETED:
            coordinator = AttentionResponseSettlementCoordinator(
                self.authority, self.attention, SPEECH_OBSERVATION_SOURCE
            )
            # prepareでの相関/型拒否と、Ownerのtarget拒否を区別する。
            try:
                request = coordinator.prepare(
                    publication,
                    expected_decision_id=self.provenance.source_decision_id,
                    attention=self.attention.snapshot_publication(),
                )
                assert request is not None
                result = AuthorityFinalizationFence().finalize(request)
                if result.failure not in (None, FinalizationFailure.TARGET_REJECTED):
                    raise FinalizationError(result.failure)
            except FinalizationError as error:
                if error.failure not in (
                    FinalizationFailure.GENERATION_MISMATCH,
                    FinalizationFailure.PARTICIPANT_BUSY,
                ):
                    raise
                self.last_error = error
                return Delivery.RETRY
        try:
            current = self.reference.set_presentation_reference(record)
        except (
            PresentationReferenceCapacityError,
            PresentationReferenceStaleError,
            SnapshotIncoherentError,
        ) as error:
            self.last_error = error
            return Delivery.RETRY
        if self.admission is None:
            # 呼出し中の例外も再normalizeしない。正規rejectのreasonはadmissionに残す。
            self.state = PresentationNotificationState.TERMINAL_REJECTED
            observation = InputObservation(
                key,
                self.source,
                InputModality.SUBSYSTEM,
                "presentation_fact",
                record.result.occurred_at,
                self.provenance.trace_id or self.root_trigger_id,
                RevisionVector(
                    current.context.source_context_revision, current.goals.goal_revision, None
                ),
                freeze_json(
                    {
                        "presentation_fact_id": record.result.command_id,
                        "execution_id": record.execution_id,
                        "subject_ref": record.subject_ref,
                        "status": record.result.status.value,
                        "record_revision": record.record_revision,
                        "effect_refs": record.result.effect_refs,
                        "effect_uncertainty": record.effect_uncertainty.value,
                        "source_decision_id": self.provenance.source_decision_id,
                        "source_event_ids": self.provenance.source_event_ids,
                    }
                ),
                correlation_id=self.provenance.source_decision_id,
            )
            self.admission = self.normalizer.normalize(observation)
            if self.admission.status is not InputAdmissionStatus.ACCEPTED:
                return Delivery.TERMINAL
            self.state = PresentationNotificationState.ADMITTED
        assert self.admission.event is not None
        if (
            self.admission.event.envelope.revisions.source_context_revision
            != current.context.source_context_revision
        ):
            self.state = PresentationNotificationState.STALE
            return Delivery.TERMINAL
        try:
            if not self.submit_input(self.admission, self.root_trigger_id).accepted:
                self.last_error = ValueError("Presentation通知の認知受付が失敗しました")
                return Delivery.RETRY
        except Exception as error:
            # exact Admissionを保ち、同期受付失敗をPresentationへ逆流させない。
            self.last_error = error
            return Delivery.RETRY
        self.state = PresentationNotificationState.SUBMITTED
        return Delivery.DELIVERED
