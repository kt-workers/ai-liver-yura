"""前段の実結果だけを実行判断へ渡し、失敗・古いリビジョンでは先へ進めないことを確認する。"""

from dataclasses import replace
from datetime import timedelta

import pytest

from app.domain.contracts import RevisionVector
from app.domain.contracts.common import freeze_json
from app.domain.executive import (
    ExecutiveCommitState,
    ExecutiveContextSnapshot,
    ExecutiveDecisionCandidate,
)
from app.domain.llm import LLMRoleRequest, LLMRoleResult, StructuredPayload
from app.subsystems.validation.appraisal_executive import (
    AppraisalExecutiveBindings,
    AppraisalExecutiveSettings,
)
from app.subsystems.validation.contracts import Gate, RunStatus
from app.subsystems.validation.meaning_appraisal import AppraisalStateCommitSettings
from tests.domain.executive import test_executive as executive
from tests.domain.input_meaning import test_input_meaning as meaning
from tests.helpers.executive_requirements import SPEECH_OWNER
from tests.subsystems.validation.test_meaning_appraisal import object_value, request, setup


def bindings(stale: str | None = None) -> tuple[AppraisalExecutiveBindings, list[LLMRoleRequest]]:
    calls: list[LLMRoleRequest] = []

    class Port:
        async def invoke(self, item: LLMRoleRequest) -> LLMRoleResult:
            calls.append(item)
            payload = executive.candidate_json()
            payload["source_context_revision"] = 4
            payload["source_event_ids"] = [meaning.event().envelope.event_id]
            return replace(
                executive.success(item),
                output=StructuredPayload("executive.candidate.v1", freeze_json(payload)),
                started_at=meaning.NOW + timedelta(seconds=4),
                completed_at=meaning.NOW + timedelta(seconds=5),
            )

    class Live:
        async def current_for_commit(
            self, snapshot: ExecutiveContextSnapshot, candidate: ExecutiveDecisionCandidate
        ) -> ExecutiveCommitState:
            return executive.live_state(
                revisions=RevisionVector(4, 5, 3),
                internal_state_revision=5 if stale == "state" else 4,
                appraisal_facts_revision=10 if stale == "facts" else 9,
            )

    return AppraisalExecutiveBindings(Port(), Live(), SPEECH_OWNER), calls


def settings() -> AppraisalExecutiveSettings:
    template = executive.snapshot()
    # 周辺の事実・能力・判断条件は既存の有効な製品入力を使う。
    template = replace(
        template,
        source_context_revision=4,
        source_event_ids=(meaning.event().envelope.event_id,),
        internal_state=replace(template.internal_state, source_context_revision=4),
        appraisal_facts=replace(template.appraisal_facts, source_context_revision=4),
    )
    return AppraisalExecutiveSettings(
        template, executive.policy(), meaning.NOW + timedelta(seconds=4)
    )


@pytest.mark.asyncio
async def test_committed_state_and_facts_reach_executive_without_candidate_rewrite() -> None:
    port, calls = bindings()
    fixture, runner, _ = setup(
        state_commit=AppraisalStateCommitSettings(4, meaning.NOW + timedelta(seconds=3), 9),
        executive=settings(),
        executive_bindings=port,
    )
    result = await runner.run(request(), fixture)
    assert result.status is RunStatus.COMPLETED and result.machine_gate is Gate.NOT_RUN
    assert len(calls) == 1
    outputs = object_value(result.stage_results[0].typed_outputs)
    appraised = object_value(outputs["appraisal"])
    decided = object_value(appraised["executive"])
    snapshot = object_value(decided["snapshot"])
    assert object_value(appraised["candidate"])["base_state_revision"] == 3
    assert object_value(snapshot["internal_state"])["revision"] == 4
    assert object_value(snapshot["appraisal_facts"])["internal_state_revision"] == 4
    assert object_value(snapshot["appraisal_facts"])["revision"] == 9
    assert snapshot["internal_state"] == appraised["after"]
    assert snapshot["appraisal_facts"] == appraised["appraisal_facts"]
    assert snapshot["meaning"] == object_value(outputs["input_meaning"])["meaning"]
    assert runner.pending_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("stale", ["state", "facts"])
async def test_executive_rechecks_each_current_revision(stale: str) -> None:
    port, calls = bindings(stale)
    fixture, runner, _ = setup(
        state_commit=AppraisalStateCommitSettings(4, meaning.NOW + timedelta(seconds=3), 9),
        executive=settings(),
        executive_bindings=port,
    )
    result = await runner.run(request(), fixture)
    assert len(calls) == 1 and result.status is RunStatus.PRODUCT_FAILED
    assert runner.pending_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("stale_context", [False, True])
async def test_failed_meaning_or_state_commit_never_calls_executive(stale_context: bool) -> None:
    port, calls = bindings()
    fixture, runner, _ = setup(
        stale_meaning=not stale_context,
        state_commit=AppraisalStateCommitSettings(5, meaning.NOW + timedelta(seconds=3), 9),
        executive=settings(),
        executive_bindings=port,
    )
    result = await runner.run(request(), fixture)
    assert result.status is not RunStatus.COMPLETED
    assert calls == [] and runner.pending_count == 0


def test_executive_requires_atomic_facts_settings() -> None:
    port, _ = bindings()
    with pytest.raises(ValueError, match="同時確定"):
        setup(
            state_commit=AppraisalStateCommitSettings(4, meaning.NOW + timedelta(seconds=3)),
            executive=settings(),
            executive_bindings=port,
        )


@pytest.mark.asyncio
async def test_context_template_cannot_replace_actual_source() -> None:
    port, calls = bindings()
    configured = settings()
    configured = replace(
        configured,
        context_template=replace(configured.context_template, source_event_ids=("other-source",)),
    )
    fixture, runner, _ = setup(
        state_commit=AppraisalStateCommitSettings(4, meaning.NOW + timedelta(seconds=3), 9),
        executive=configured,
        executive_bindings=port,
    )
    result = await runner.run(request(), fixture)
    assert result.status is not RunStatus.COMPLETED
    assert calls == [] and runner.pending_count == 0


def test_missing_executive_binding_is_rejected_before_run() -> None:
    with pytest.raises(ValueError, match="接続指定"):
        setup(
            state_commit=AppraisalStateCommitSettings(4, meaning.NOW + timedelta(seconds=3), 9),
            executive=settings(),
        )
