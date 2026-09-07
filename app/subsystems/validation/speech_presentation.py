"""本番の提示前照合と提示結果の受入れを公開入口から検証する。"""

import asyncio
from collections.abc import AsyncIterator, Coroutine
from dataclasses import dataclass, replace
from typing import Any

from app.domain.contracts.common import JsonValue
from app.domain.speech_runtime.contracts import (
    PreparedSpeechCandidate,
    SpeechPresentationCommand,
    SpeechPresentationCommitState,
    SpeechPresentationReport,
)
from app.domain.speech_runtime.discard import (
    PreparedAudioDiscarder,
    PreparedAudioDiscardPort,
    PreparedAudioDiscardReason,
)
from app.domain.speech_runtime.policy import SpeechRuntimeOperationalPolicy
from app.domain.speech_runtime.presentation import PresentationAdapter, SpeechPresentationExecutor
from app.domain.speech_runtime.runtime import SpeechRuntime
from app.domain.speech_runtime.tasks import CandidateTaskKey, CandidateTaskRegistry

from .body import _project
from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
)
from .runtime import LabTarget, RunContext


@dataclass(frozen=True)
class SpeechPresentationCase:
    fixture: ValidationFixture
    candidate: PreparedSpeechCandidate
    state: SpeechPresentationCommitState
    policy: SpeechRuntimeOperationalPolicy

    def typed_inputs(self) -> JsonValue:
        return _project({"candidate": self.candidate, "state": self.state, "policy": self.policy})


class _ObservedTasks(CandidateTaskRegistry):
    """本番の登録・取消を保ち、起動した提示処理の完了を待てるようにする。"""

    def __init__(self) -> None:
        super().__init__()
        self.started: list[asyncio.Task[object]] = []

    def start(
        self, key: CandidateTaskKey, work: Coroutine[Any, Any, object]
    ) -> asyncio.Task[object]:
        task = super().start(key, work)
        self.started.append(task)
        return task


def speech_presentation_target(
    cases: tuple[SpeechPresentationCase, ...],
    adapter: PresentationAdapter,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
) -> LabTarget:
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("発話提示の検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or case.fixture != fixture or case.typed_inputs() != fixture.typed_inputs:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        return await present_speech(context, case, adapter)

    return LabTarget(
        "speech_presentation",
        contract_revision,
        frozenset({LabMode.ISOLATION}),
        (),
        provenance,
        run,
    )


async def present_speech(
    context: RunContext,
    case: SpeechPresentationCase,
    adapter: PresentationAdapter,
    discard: PreparedAudioDiscardPort | None = None,
) -> TargetObservation:
    """同じ公開入口を単独検証と結合検証で共用する。"""
    prefix = f"{context.run_id}:{case.fixture.scenario_id}:{context.iteration}"
    # 時刻は検証条件が所有する。実際の現在時刻で過去の条件を失効させない。
    runtime = SpeechRuntime(case.policy, lambda: case.state.observed_at)

    async def close_runtime() -> None:
        if discard is not None:
            discarder = PreparedAudioDiscarder(runtime, discard)
            for candidate_id in await runtime.active_candidate_ids():
                await discarder.discard_current(
                    candidate_id,
                    runtime.generation(candidate_id),
                    PreparedAudioDiscardReason.CANDIDATE_CANCELLED,
                )
        await runtime.shutdown()

    context.add_cleanup("speech.runtime", close_runtime)
    candidate = replace(case.candidate, candidate_id=f"{prefix}:candidate")
    await context.invoke_product("speech.register", lambda: runtime.register(candidate))
    return await execute_presentation(
        context, runtime, candidate, case.state, adapter, f"{prefix}:presentation"
    )


async def execute_presentation(
    context: RunContext,
    runtime: SpeechRuntime,
    candidate: PreparedSpeechCandidate,
    state: SpeechPresentationCommitState,
    adapter: PresentationAdapter,
    presentation_id: str,
) -> TargetObservation:
    """候補を登録し直さず、準備から継続して同じ実行基盤で提示する。"""
    tasks = _ObservedTasks()
    context.add_cleanup("speech.presentation_tasks", tasks.shutdown)
    accepted_reports: list[SpeechPresentationReport] = []

    async def observed_adapter(
        command: SpeechPresentationCommand,
    ) -> AsyncIterator[SpeechPresentationReport]:
        stream = adapter(command)
        try:
            async for report in stream:
                if len(accepted_reports) >= context.policy.max_intervals:
                    raise ValueError("提示結果の記録容量を超えました")
                yield report
                accepted_reports.append(report)
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()

    command = await context.invoke_product(
        "speech.presentation_commit",
        lambda: SpeechPresentationExecutor(runtime, tasks).commit_and_present(
            candidate_id=candidate.candidate_id,
            state=state,
            presentation_id=presentation_id,
            adapter=observed_adapter,
        ),
    )

    async def await_reports() -> list[object]:
        return list(await asyncio.gather(*tasks.started))

    reports = await context.invoke_product("speech.presentation_reports", await_reports)
    final = await runtime.candidate(candidate.candidate_id)
    return TargetObservation(
        RunStatus.COMPLETED,
        Gate.NOT_RUN,
        _project(
            {
                "command": command,
                "terminal_reports": reports,
                "accepted_reports": accepted_reports,
                "candidate": final,
            }
        ),
    )
