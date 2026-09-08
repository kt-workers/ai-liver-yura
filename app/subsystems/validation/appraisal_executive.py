"""状態所有者が同時確定した状態と評価事実を、実行判断の公開入口へ渡す。"""

from dataclasses import dataclass, replace
from datetime import datetime

from app.domain.appraisal import AppraisalStateCommit
from app.domain.contracts.common import JsonValue
from app.domain.executive import (
    ExecutiveContextSnapshot,
    ExecutiveDecisionAuthority,
    ExecutiveDeliberator,
    ExecutiveLiveStatePort,
    ExecutivePolicy,
)
from app.domain.executive.requirements import ExecutiveRequirementsOwner
from app.domain.input_meaning import StructuredInputMeaning
from app.usecases.ports.llm import LLMRolePort

from .body import _project
from .contracts import aware
from .llm_port import LabLLMPortFactory, ObservedLLMRolePort, resolve_port
from .runtime import RunContext


@dataclass(frozen=True)
class AppraisalExecutiveSettings:
    """実行判断の周辺入力を固定し、意味・状態・評価事実は実際の前段結果を使う。"""

    context_template: ExecutiveContextSnapshot
    policy: ExecutivePolicy
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.context_template, ExecutiveContextSnapshot):
            raise ValueError("実行判断の公開型の入力ひな形が必要です")
        if not isinstance(self.policy, ExecutivePolicy):
            raise ValueError("実行判断の本番方針が必要です")
        aware(self.created_at)

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "context_template": self.context_template.to_dict(),
                "policy": self.policy,
                "created_at": self.created_at,
            }
        )


@dataclass(frozen=True)
class AppraisalExecutiveBindings:
    port: LLMRolePort | LabLLMPortFactory
    live_state: ExecutiveLiveStatePort
    requirements_owner: ExecutiveRequirementsOwner | None = None


async def deliberate_after_appraisal(
    context: RunContext,
    meaning: StructuredInputMeaning,
    committed: AppraisalStateCommit,
    settings: AppraisalExecutiveSettings,
    bindings: AppraisalExecutiveBindings,
) -> JsonValue:
    # 周辺の事実・能力・リビジョン・由来はひな形から変更しない。不一致は公開型が拒否する。
    snapshot = replace(
        settings.context_template,
        meaning=meaning,
        internal_state=committed.internal_state,
        appraisal_facts=committed.appraisal_facts,
        captured_at=settings.created_at,
    )
    owner = ExecutiveDeliberator(
        ObservedLLMRolePort(
            context,
            resolve_port(bindings.port, context),
            {"executive_deliberation": "executive.llm"},
        ),
        bindings.live_state,
        settings.policy,
        ExecutiveDecisionAuthority(bindings.requirements_owner),
    )
    prefix = f"{context.run_id}:{context.iteration}:executive"
    decision = await context.invoke_product(
        "executive.deliberate",
        lambda: owner.deliberate(
            snapshot,
            request_id=prefix,
            trace_id=prefix,
            decision_id=f"{prefix}:decision",
            created_at=settings.created_at,
        ),
    )
    return _project({"snapshot": snapshot.to_dict(), "decision": decision.to_dict()})
