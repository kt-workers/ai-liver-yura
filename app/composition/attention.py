"""注意所有者の選択元と本体の現在状態を、由来を区別して搬送する。"""

from dataclasses import dataclass

from app.composition.appraisal import CoreAppraisalBinding
from app.composition.input_reference_context import CoreInputReferenceSnapshot
from app.domain.appraisal import AppraisalStateCommit, InternalStateSnapshot
from app.domain.attention import (
    AttentionFocusState,
    AttentionSource,
    AttentionSourceKind,
    AttentionTurnStore,
    ExecutiveTriggerEligibility,
)
from app.runtime.kernel import RuntimeClock
from app.usecases.attention import AppraisalAttentionProjector


@dataclass(frozen=True, slots=True)
class CoreAttentionDispatch:
    trigger: ExecutiveTriggerEligibility
    selected_source: AttentionSource
    reference: CoreInputReferenceSnapshot
    current_state: InternalStateSnapshot
    current_appraisal: AppraisalStateCommit | None

    @property
    def selected_appraisal(self) -> AppraisalStateCommit | None:
        """現在の評価が別の選択元に由来する場合は、対応する評価と扱わない。"""
        value, source = self.current_appraisal, self.selected_source
        if value is None or source.kind is not AttentionSourceKind.APPRAISAL:
            return None
        candidate = value.candidate
        if (
            source.source_ref != candidate.candidate_id
            or source.source_revision != candidate.base_state_revision
            or source.source_context_revision != candidate.source_context_revision
        ):
            return None
        return value


class CoreAttentionBinding:
    """選択や割込みの判断を既存所有者へ委ね、現在読取だけを接続する。"""

    def __init__(
        self,
        appraisal: CoreAppraisalBinding,
        attention: AttentionTurnStore,
        clock: RuntimeClock,
    ) -> None:
        if not isinstance(appraisal, CoreAppraisalBinding):
            raise ValueError("注意接続には本体の評価接続が必要です")
        if not isinstance(attention, AttentionTurnStore):
            raise ValueError("注意接続には既存の注意所有者が必要です")
        self._appraisal = appraisal
        self._attention = attention
        self._clock = clock
        self._latest_dispatch: CoreAttentionDispatch | None = None

    def offer_appraisal(self) -> AttentionFocusState:
        value = self._appraisal.current_commit()
        if value is None:
            raise ValueError("現在の確定済み評価がありません")
        return self._attention.offer(AppraisalAttentionProjector().project(value.candidate))

    def claim_next(self) -> CoreAttentionDispatch | None:
        reference = self._appraisal.current_reference()
        before = self._attention.snapshot()
        if before.source_context_revision != reference.context.source_context_revision:
            raise ValueError("注意の文脈が現在の入力参照と一致しません")
        trigger = self._attention.claim_next(reference.goals.goal_revision, self._clock.now())
        if trigger is None:
            return None
        state = self._attention.snapshot()
        if state.revision != trigger.attention_revision:
            raise ValueError("選択後に注意の状態が変更されました")
        source = next(
            (item for item in state.sources if item.source_ref == trigger.source_ref), None
        )
        if source is None:
            raise ValueError("選択された元情報が注意状態にありません")
        if self._appraisal.current_reference() != reference:
            raise ValueError("選択中に入力参照が変更されました")
        dispatch = CoreAttentionDispatch(
            trigger,
            source,
            reference,
            self._appraisal.current_state(),
            self._appraisal.current_commit(),
        )
        self._latest_dispatch = dispatch
        return dispatch

    def is_current(self, dispatch: CoreAttentionDispatch) -> bool:
        if not isinstance(dispatch, CoreAttentionDispatch):
            raise ValueError("注意の選択結果は型付きの搬送結果が必要です")
        if dispatch is not self._latest_dispatch:
            return False
        state = self._attention.snapshot()
        return (
            state.revision == dispatch.trigger.attention_revision
            and state.source_context_revision == dispatch.trigger.source_context_revision
            and self._appraisal.current_reference() == dispatch.reference
            and self._appraisal.current_state() == dispatch.current_state
            and self._appraisal.current_commit() == dispatch.current_appraisal
        )
