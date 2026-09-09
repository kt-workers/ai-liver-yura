"""採用済みの所有者を使い、通常認知の処理を既存Runtimeへ配送する。"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from app.composition.accepted_input import CoreAcceptedInputStore
from app.composition.appraisal import (
    AppraisalBrainModulePort,
    AppraisalBrainWorkPayload,
    CoreAppraisalBinding,
)
from app.composition.attention import CoreAttentionBinding
from app.composition.executive import (
    CoreExecutiveBinding,
    ExecutiveBrainModulePort,
    ExecutiveBrainWorkPayload,
)
from app.domain.appraisal import AppraisalStateCommit, DeterministicAppraisalRule
from app.domain.attention import (
    AttentionIngressOperation,
    AttentionIngressSignal,
    AttentionSource,
    AttentionSourceKind,
    AttentionTurnStore,
)
from app.domain.brain_integration import (
    BrainIntegrationLane,
    BrainIntegrationModule,
    BrainIntegrationRuntime,
    BrainIntegrationWork,
    BrainWorkAdmission,
    BrainWorkEnvelope,
    BrainWorkPriority,
    BrainWorkStatus,
)
from app.domain.brain_integration.runtime import BrainIntegrationWorkOutcome
from app.domain.input_gateway import InputAdmission, InputAdmissionStatus, InputModality
from app.domain.input_meaning import InputMeaningInterpretationResult
from app.runtime.kernel import CancellationToken, RuntimeClock
from app.usecases.attention import UserInteractionAttentionProjector


class _Module(Protocol):
    def is_fresh(self, work: BrainIntegrationWork) -> bool: ...
    async def execute(
        self, work: BrainIntegrationWork, cancellation: CancellationToken
    ) -> object: ...


class _ForwardingModule:
    """成功した所有者の結果だけを次の受付へ渡す。独自taskは所有しない。"""

    def __init__(
        self, port: _Module, forward: Callable[[BrainIntegrationWork, object], None]
    ) -> None:
        self._port, self._forward = port, forward

    def is_fresh(self, work: BrainIntegrationWork) -> bool:
        return self._port.is_fresh(work)

    async def execute(self, work: BrainIntegrationWork, cancellation: CancellationToken) -> object:
        result = await self._port.execute(work, cancellation)
        if cancellation.cancelled:
            raise asyncio.CancelledError
        self._forward(work, result)
        return result


class _AppraisalModule(AppraisalBrainModulePort):
    def __init__(
        self, binding: CoreAppraisalBinding, rules: tuple[DeterministicAppraisalRule, ...]
    ) -> None:
        super().__init__(binding)
        self._rules = rules

    async def execute(
        self, work: BrainIntegrationWork, cancellation: CancellationToken
    ) -> AppraisalStateCommit:
        payload = self._validate(work)
        if cancellation.cancelled:
            raise asyncio.CancelledError
        fast = self._binding.appraise_fast(
            payload.event, self._rules, candidate_id=payload.request_id
        )
        if fast is not None:
            return fast
        return await super().execute(work, cancellation)


@dataclass(frozen=True, slots=True)
class CognitionDelivery:
    """配送の受付結果。確定判断の成功とは区別する。"""

    parent_work_id: str
    admission: BrainWorkAdmission


class CoreCognitionDelivery:
    """評価・注意・判断の意味は既存Ownerへ委譲し、由来付き処理だけをつなぐ。"""

    def __init__(
        self,
        brain: BrainIntegrationRuntime,
        appraisal: CoreAppraisalBinding,
        attention: CoreAttentionBinding,
        executive: CoreExecutiveBinding,
        fast_rules: tuple[DeterministicAppraisalRule, ...],
        inputs: CoreAcceptedInputStore,
        attention_owner: AttentionTurnStore,
        clock: RuntimeClock,
    ) -> None:
        self.brain, self.appraisal, self.attention = brain, appraisal, attention
        self._executive = executive
        self._clock = clock
        self._inputs, self._attention_owner = inputs, attention_owner
        self._fast_rules = tuple(fast_rules)
        self._pending_users: dict[str, AttentionSource] = {}
        self.latest_delivery: CognitionDelivery | None = None

    def register(self, input_port: _Module) -> None:
        self.brain.register_terminal_observer(
            BrainIntegrationModule.INPUT_MEANING, self._input_terminal
        )
        self.brain.register_module(
            BrainIntegrationModule.INPUT_MEANING,
            _ForwardingModule(input_port, self._input_completed),
        )
        self.brain.register_module(
            BrainIntegrationModule.APPRAISAL,
            _ForwardingModule(
                _AppraisalModule(self.appraisal, self._fast_rules), self._appraisal_completed
            ),
        )
        self.brain.register_module(
            BrainIntegrationModule.EXECUTIVE, ExecutiveBrainModulePort(self._executive)
        )

    def _submit(self, parent: BrainIntegrationWork, child: BrainIntegrationWork) -> None:
        admission = self.brain.submit(child)
        self.latest_delivery = CognitionDelivery(parent.work_id, admission)
        if not admission.accepted:
            raise ValueError("通常認知の次処理を受付できませんでした")

    def _input_completed(self, work: BrainIntegrationWork, result: object) -> None:
        from app.bootstrap import InputMeaningBrainWorkPayload

        if not isinstance(result, InputMeaningInterpretationResult) or result.meaning is None:
            return
        payload = work.payload
        if not isinstance(payload, InputMeaningBrainWorkPayload):
            raise ValueError("通常認知へ渡す入力の型が不正です")
        admission = payload.admission
        if (
            admission is None
            or admission.status is not InputAdmissionStatus.ACCEPTED
            or admission.event != payload.event
        ):
            raise ValueError("通常認知には一致するGateway採用根拠が必要です")
        child = BrainIntegrationWork(
            uuid4().hex,
            BrainIntegrationModule.APPRAISAL,
            BrainIntegrationLane.COGNITIVE_NORMAL,
            work.envelope,
            AppraisalBrainWorkPayload(payload.event.envelope, result.meaning, uuid4().hex),
            deadline_at=work.deadline_at,
        )
        self._submit(work, child)

    def _resolve_source(self, source: AttentionSource) -> None:
        state = self._attention_owner.snapshot()
        current = next(
            (
                s
                for s in state.sources
                if s.source_ref == source.source_ref and s.kind is source.kind
            ),
            None,
        )
        if current is None:
            return
        self._attention_owner.resolve(
            AttentionIngressSignal(
                uuid4().hex,
                AttentionIngressOperation.RESOLVE,
                current.source_ref,
                current.kind,
                state.source_context_revision,
                self._clock.now(),
                expected_source_revision=current.source_revision,
            )
        )

    def _input_terminal(
        self, work: BrainIntegrationWork, outcome: BrainIntegrationWorkOutcome
    ) -> None:
        result = outcome.result
        successful = (
            outcome.status is BrainWorkStatus.COMPLETED
            and isinstance(result, InputMeaningInterpretationResult)
            and result.meaning is not None
        )
        for event_id in work.envelope.source_event_ids:
            source = self._pending_users.pop(event_id, None)
            if source is not None and not successful:
                self._resolve_source(source)

    def _input_finished(self, work: BrainIntegrationWork) -> None:
        """Runtime所有前の同期失敗を冪等に撤回する。"""
        for event_id in work.envelope.source_event_ids:
            source = self._pending_users.pop(event_id, None)
            if source is not None:
                self._resolve_source(source)

    def _appraisal_completed(self, work: BrainIntegrationWork, result: object) -> None:
        if (
            not isinstance(result, AppraisalStateCommit)
            or self.appraisal.current_commit() != result
        ):
            raise ValueError("現在の採用済み評価と配送対象が一致しません")
        for source in self._attention_owner.snapshot().sources:
            if (
                source.kind is AttentionSourceKind.APPRAISAL
                and source.source_ref != result.candidate.candidate_id
            ):
                self._resolve_source(source)
        published = self.attention.offer_appraisal()
        if not any(
            source.source_ref == result.candidate.candidate_id
            and source.kind is AttentionSourceKind.APPRAISAL
            for source in published.sources
        ):
            raise ValueError("注意所有者が評価sourceを受付しませんでした")
        dispatch = self.attention.claim_next()
        if dispatch is None:
            return
        selected = dispatch.selected_appraisal
        if selected is not None:
            event_ids = selected.candidate.source_event_ids
        elif dispatch.selected_source.kind is AttentionSourceKind.USER_INTERACTION:
            event_ids = (dispatch.selected_source.source_ref,)
        else:
            raise ValueError("選択元の現在根拠が登録されていません")
        selected_input = self._inputs.read(
            event_ids[0], dispatch.reference.context.source_context_revision
        )
        envelope = replace(
            work.envelope,
            trace_id=selected_input.event.envelope.trace_id,
            root_trigger_id=selected_input.event.envelope.event_id,
            source_event_ids=event_ids,
            priority=BrainWorkPriority(dispatch.selected_source.effective_priority),
            trigger_id=dispatch.trigger.trigger_id,
            source_context_revision=dispatch.reference.context.source_context_revision,
            goal_revision=dispatch.reference.goals.goal_revision,
            attention_revision=dispatch.trigger.attention_revision,
        )
        child = BrainIntegrationWork(
            uuid4().hex,
            BrainIntegrationModule.EXECUTIVE,
            BrainIntegrationLane.COGNITIVE_NORMAL,
            envelope,
            ExecutiveBrainWorkPayload(dispatch, uuid4().hex, uuid4().hex),
            deadline_at=work.deadline_at,
        )
        self._submit(work, child)

    def submit_input(
        self, admission: InputAdmission, *, deadline_at: datetime | None = None
    ) -> BrainWorkAdmission:
        """正規Gatewayの採用イベントを、現在文脈と既存の有界受付へ渡す。"""
        from app.bootstrap import InputMeaningBrainWorkPayload

        if (
            not isinstance(admission, InputAdmission)
            or admission.status is not InputAdmissionStatus.ACCEPTED
            or admission.event is None
        ):
            raise ValueError("通常認知はGatewayの採用入力だけを受理します")
        event = admission.event
        reference = self.appraisal.current_reference()
        if (
            event.envelope.revisions.source_context_revision
            != reference.context.source_context_revision
        ):
            raise ValueError("入力の文脈が現在と一致しません")
        internal = event.modality in (
            InputModality.SUBSYSTEM,
            InputModality.LIFECYCLE,
            InputModality.TIMER,
        )
        module = (
            BrainIntegrationModule.APPRAISAL if internal else BrainIntegrationModule.INPUT_MEANING
        )
        lane = (
            BrainIntegrationLane.COGNITIVE_NORMAL
            if internal
            else BrainIntegrationLane.FOREGROUND_INTERACTION
        )
        payload: object
        if internal:
            self._inputs.retain_internal(admission)
            payload = AppraisalBrainWorkPayload(event.envelope, None, uuid4().hex)
        else:
            payload = InputMeaningBrainWorkPayload(event, reference.context, uuid4().hex, admission)
        envelope = BrainWorkEnvelope(
            event.envelope.trace_id,
            uuid4().hex,
            (event.envelope.event_id,),
            reference.context.source_context_revision,
            reference.goals.goal_revision,
            None,
            BrainWorkPriority.DIRECT_USER
            if event.modality
            in (
                InputModality.TEXT,
                InputModality.SPEECH,
                InputModality.AUDIO,
                InputModality.POINTER,
                InputModality.TOUCH,
            )
            else BrainWorkPriority.NORMAL,
            event.envelope.occurred_at,
            root_trigger_id=event.envelope.event_id,
        )
        work = BrainIntegrationWork(
            uuid4().hex, module, lane, envelope, payload, deadline_at=deadline_at
        )
        if envelope.priority is BrainWorkPriority.DIRECT_USER:
            if any(
                s.source_ref == event.envelope.event_id
                for s in self._attention_owner.snapshot().sources
            ):
                raise ValueError("同じ入力sourceは既に登録されています")
            signal = UserInteractionAttentionProjector().project(admission)
            published = self._attention_owner.offer(signal)
            source = next(
                (
                    s
                    for s in published.sources
                    if s.source_ref == signal.source_ref and s.kind is signal.source_kind
                ),
                None,
            )
            if source is None:
                raise ValueError("注意所有者が入力sourceを受付しませんでした")
            self._pending_users[source.source_ref] = source
        try:
            accepted = self.brain.submit(work)
        except BaseException:
            self._input_finished(work)
            raise
        if not accepted.accepted:
            self._input_finished(work)
        return accepted

    def cancel_trace(self, trace_id: str, reason: str, *, supersede: bool = False) -> int:
        """同じ追跡の未完処理を既存Runtimeへ取消依頼する。独自taskは増やさない。"""
        operation = self.brain.supersede if supersede else self.brain.cancel
        trace = self.brain.trace(trace_id)
        count = sum(operation(interval.work_id, reason) for interval in trace.intervals)
        event_ids = set(trace.source_event_ids)
        for event_id in event_ids:
            self._pending_users.pop(event_id, None)
        current_appraisal = self.appraisal.current_commit()
        state = self._attention_owner.snapshot()
        for source in state.sources:
            selected_input = (
                source.kind is AttentionSourceKind.USER_INTERACTION
                and source.source_ref in event_ids
            )
            selected_appraisal = (
                source.kind is AttentionSourceKind.APPRAISAL
                and current_appraisal is not None
                and source.source_ref == current_appraisal.candidate.candidate_id
                and set(current_appraisal.candidate.source_event_ids) <= event_ids
            )
            if selected_input or selected_appraisal:
                self._attention_owner.resolve(
                    AttentionIngressSignal(
                        uuid4().hex,
                        AttentionIngressOperation.RESOLVE,
                        source.source_ref,
                        source.kind,
                        state.source_context_revision,
                        self._clock.now(),
                        expected_source_revision=source.source_revision,
                    )
                )
        return count
