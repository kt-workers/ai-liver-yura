"""共有待ち行列から現在状態の再照合と連続提示へ接続する。"""

from dataclasses import dataclass, replace
from functools import partial

from app.domain.contracts.common import JsonValue
from app.domain.speech_runtime.contracts import CandidateLifecycle
from app.domain.speech_runtime.discard import (
    PreparedAudioDiscarder,
    PreparedAudioDiscardPort,
    PreparedAudioDiscardReason,
)
from app.domain.speech_runtime.presentation import PresentationAdapter
from app.domain.speech_runtime.queue import PreparedSpeechQueue, PreparedSpeechQueueCoordinator
from app.domain.speech_runtime.runtime import SpeechRuntime

from .body import _project
from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
)
from .runtime import LabTarget, ProductInvocationError, RunContext
from .speech_preparation import SpeechRevalidationStatePort
from .speech_presentation import SpeechPresentationCase, execute_presentation


@dataclass(frozen=True)
class SpeechQueueCase:
    fixture: ValidationFixture
    candidates: tuple[SpeechPresentationCase, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        ids = [x.candidate.candidate_id for x in self.candidates]
        if len(ids) < 2 or len(set(ids)) != len(ids):
            raise ValueError("共有待ち行列には異なる識別子の複数候補が必要です")
        if any(x.policy != self.candidates[0].policy for x in self.candidates):
            raise ValueError("共有待ち行列の運用方針は一致する必要があります")
        if any(x.candidate.lifecycle is not CandidateLifecycle.PREPARED for x in self.candidates):
            raise ValueError("待ち行列への入力は準備済み候補でなければなりません")

    def typed_inputs(self) -> JsonValue:
        return _project([x.typed_inputs() for x in self.candidates])


def speech_queue_target(
    cases: tuple[SpeechQueueCase, ...],
    state_port: SpeechRevalidationStatePort,
    adapter: PresentationAdapter,
    discard: PreparedAudioDiscardPort,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
) -> LabTarget:
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("共有待ち行列の検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or fixture != case.fixture or fixture.typed_inputs != case.typed_inputs():
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        if len(case.candidates) * 8 > context.policy.max_intervals:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        now = max(x.state.observed_at for x in case.candidates)
        runtime = SpeechRuntime(case.candidates[0].policy, lambda: now)
        discarder = PreparedAudioDiscarder(runtime, discard)
        queue = PreparedSpeechQueueCoordinator(
            runtime,
            PreparedSpeechQueue(case.candidates[0].policy),
            discarder,
        )

        async def close() -> None:
            queue.shutdown()
            failed = False
            try:
                for candidate_id in await runtime.active_candidate_ids():
                    try:
                        await discarder.discard_current(
                            candidate_id,
                            runtime.generation(candidate_id),
                            PreparedAudioDiscardReason.CANDIDATE_CANCELLED,
                        )
                    except Exception:
                        failed = True
            finally:
                await runtime.shutdown()
            if failed:
                raise RuntimeError("一部の候補音声を破棄できませんでした") from None

        context.add_cleanup("speech.shared_queue", close)
        admissions: list[object] = []
        ids: list[str] = []
        presentations: list[object] = []
        rejected: str | None = None
        states: list[object] = []
        for item in case.candidates:
            candidate = replace(
                item.candidate,
                candidate_id=(
                    f"{context.run_id}:{context.iteration}:{item.candidate.candidate_id}"
                ),
            )
            ids.append(candidate.candidate_id)
            await context.invoke_product(
                "speech.queue_register", partial(runtime.register, candidate)
            )
            admissions.append(
                await context.invoke_product(
                    "speech.queue_admission",
                    partial(
                        queue.enqueue_current,
                        candidate.candidate_id,
                        runtime.generation(candidate.candidate_id),
                    ),
                )
            )
        while (
            current := await context.invoke_product(
                "speech.queue_take",
                queue.pop_for_revalidation,
            )
        ) is not None:
            state = await context.invoke_port(
                "speech.revalidation_state",
                partial(state_port.current_state, current),
            )
            states.append({"candidate_id": current.candidate_id, "state": state})
            now = max(now, state.observed_at)
            try:
                validated = await context.invoke_product(
                    "speech.revalidation_commit",
                    partial(
                        runtime.revalidate_current,
                        current.candidate_id,
                        runtime.generation(current.candidate_id),
                        state,
                    ),
                )
            except ProductInvocationError:
                rejected = current.candidate_id
                break
            if validated is None:
                raise ValueError("再照合中に候補の世代が変わりました")
            if validated.lifecycle is CandidateLifecycle.READY_TO_PRESENT:
                result = await execute_presentation(
                    context,
                    runtime,
                    validated,
                    state,
                    adapter,
                    f"{validated.candidate_id}:presentation",
                )
                presentations.append(result.typed_outputs)
            else:
                await discarder.discard_current(
                    current.candidate_id,
                    runtime.generation(current.candidate_id),
                    PreparedAudioDiscardReason.CANDIDATE_STALE,
                )
        return TargetObservation(
            RunStatus.PRODUCT_FAILED if rejected is not None else RunStatus.COMPLETED,
            Gate.NOT_RUN,
            _project(
                {
                    "revalidation_failed": rejected,
                    "revalidation_states": states,
                    "admissions": admissions,
                    "presentations": presentations,
                    "candidates": [await runtime.candidate(candidate_id) for candidate_id in ids],
                    "queue_count": len(queue),
                }
            ),
        )

    return LabTarget(
        "speech_queue",
        contract_revision,
        frozenset({LabMode.ADJACENT}),
        (),
        provenance,
        run,
        frozenset({"speech.revalidation_state"}),
    )
