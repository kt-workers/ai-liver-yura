"""確定した入力意味を加工せず、深い状況評価の公開入口へ渡す。"""

from dataclasses import dataclass
from datetime import datetime

from app.domain.appraisal import (
    AppraisalCandidate,
    AppraisalStateCommit,
    DeepAppraisalContext,
    DeepAppraisalInterpreter,
    DeepAppraisalLiveStatePort,
    DeepAppraisalPolicy,
    InternalStateReducer,
    InternalStateSnapshot,
    build_deep_request,
)
from app.domain.attention import (
    AttentionCoordinator,
    AttentionSchedulingPolicy,
    AttentionTurnStore,
    ExecutiveTriggerEligibility,
)
from app.domain.contracts import EventEnvelope
from app.domain.contracts.common import JsonValue
from app.domain.input_meaning import StructuredInputMeaning
from app.usecases.attention import AppraisalAttentionProjector
from app.usecases.ports.llm import LLMRolePort

from .appraisal_executive import (
    AppraisalExecutiveBindings,
    AppraisalExecutiveSettings,
    deliberate_after_appraisal,
)
from .body import _project
from .llm_port import LabLLMPortFactory, ObservedLLMRolePort, resolve_port
from .runtime import RunContext


@dataclass(frozen=True)
class AppraisalStateCommitSettings:
    """局所的な状態所有者へ渡す確定時点を、試験入力として固定する。"""

    current_source_context_revision: int
    committed_at: datetime
    facts_revision: int | None = None


@dataclass(frozen=True)
class AppraisalAttentionSettings:
    """注意の本番方針と処理時点を試験入力として保持する。"""

    policy: AttentionSchedulingPolicy
    current_goal_revision: int
    observed_at: datetime


@dataclass(frozen=True)
class MeaningAppraisalSettings:
    state: InternalStateSnapshot
    context: DeepAppraisalContext
    policy: DeepAppraisalPolicy
    created_at: datetime
    state_commit: AppraisalStateCommitSettings | None = None
    attention: AppraisalAttentionSettings | None = None
    executive: AppraisalExecutiveSettings | None = None

    def __post_init__(self) -> None:
        if self.attention is not None and self.state_commit is None:
            raise ValueError("状態更新後の注意接続には状態確定の設定が必要です")

        if self.executive is not None and (
            self.state_commit is None or self.state_commit.facts_revision is None
        ):
            raise ValueError("実行判断への接続には状態と評価事実の同時確定が必要です")

    def typed_inputs(self) -> JsonValue:
        values: dict[str, object] = {
            "state": self.state,
            "context": self.context,
            "policy": self.policy,
            "created_at": self.created_at,
        }
        if self.state_commit is not None:
            current_revision = self.state_commit.current_source_context_revision
            values["state_commit"] = {
                "current_source_context_revision": current_revision,
                "committed_at": self.state_commit.committed_at,
                "facts_revision": self.state_commit.facts_revision,
            }
        if self.attention is not None:
            values["attention"] = {
                "policy": self.attention.policy,
                "current_goal_revision": self.attention.current_goal_revision,
                "observed_at": self.attention.observed_at,
            }
        if self.executive is not None:
            values["executive"] = self.executive.typed_inputs()
        return _project(values)


@dataclass(frozen=True)
class MeaningAppraisalBindings:
    port: LLMRolePort | LabLLMPortFactory
    live_state: DeepAppraisalLiveStatePort
    executive: AppraisalExecutiveBindings | None = None


async def appraise_meaning(
    context: RunContext,
    event: EventEnvelope,
    meaning: StructuredInputMeaning,
    settings: MeaningAppraisalSettings,
    bindings: MeaningAppraisalBindings,
) -> JsonValue:
    prefix = f"{context.run_id}:{context.iteration}:appraisal"
    request = build_deep_request(
        event,
        meaning,
        settings.state,
        settings.context,
        request_id=prefix,
        trace_id=event.trace_id,
        created_at=settings.created_at,
        policy=settings.policy,
    )
    owner = DeepAppraisalInterpreter(
        ObservedLLMRolePort(
            context, resolve_port(bindings.port, context), {request.role_id: "appraisal.llm"}
        ),
        bindings.live_state,
        settings.policy,
    )

    async def invoke() -> AppraisalCandidate:
        return await owner.appraise(
            event,
            meaning,
            settings.state,
            settings.context,
            request_id=prefix,
            trace_id=event.trace_id,
            created_at=settings.created_at,
        )

    candidate = await context.invoke_product("appraisal.appraise", invoke)
    if settings.state_commit is not None:
        reducer = InternalStateReducer(settings.state)
        before = reducer.snapshot()
        commit_settings = settings.state_commit

        committed: AppraisalStateCommit | None = None

        async def commit() -> InternalStateSnapshot:
            nonlocal committed
            if commit_settings.facts_revision is not None:
                committed = reducer.commit_with_facts(
                    candidate,
                    current_source_context_revision=commit_settings.current_source_context_revision,
                    committed_at=commit_settings.committed_at,
                    facts_revision=commit_settings.facts_revision,
                )
                return committed.internal_state
            return reducer.commit(
                candidate,
                current_source_context_revision=commit_settings.current_source_context_revision,
                committed_at=commit_settings.committed_at,
            )

        after = await context.invoke_product("appraisal.state_commit", commit)
        values: dict[str, object] = {
            "request_input": request.input.value,
            "candidate": candidate,
            "before": before,
            "after": after,
        }
        if committed is not None:
            values["appraisal_facts"] = committed.appraisal_facts
        if settings.attention is not None:
            attention_settings = settings.attention
            store = AttentionTurnStore(attention_settings.policy)
            enqueued: list[ExecutiveTriggerEligibility] = []
            coordinator = AttentionCoordinator(store, store, enqueued.append)
            signal = AppraisalAttentionProjector().project(candidate)

            async def handle() -> ExecutiveTriggerEligibility | None:
                return coordinator.handle(
                    signal,
                    attention_settings.current_goal_revision,
                    attention_settings.observed_at,
                )

            claimed = await context.invoke_product("attention.handle", handle)
            values["attention"] = {
                "signal": signal,
                "claimed": claimed,
                "enqueued_triggers": tuple(enqueued),
                "snapshot": store.snapshot(),
            }
        if settings.executive is not None:
            if bindings.executive is None or committed is None:
                raise ValueError("実行判断の接続または同時確定結果がありません")
            values["executive"] = await deliberate_after_appraisal(
                context, meaning, committed, settings.executive, bindings.executive
            )
        return _project(values)
    return _project({"request_input": request.input.value, "candidate": candidate})
