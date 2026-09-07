"""複数候補の共有準備枠から本番音声合成へ接続する検証入口。"""

import asyncio
from dataclasses import dataclass, replace

from app.adapters.tts.provider import TTSProviderClient
from app.domain.contracts.common import JsonValue
from app.domain.speech_runtime.admission import SpeechPreparationAdmission
from app.domain.speech_runtime.contracts import TTSPreparationMode
from app.domain.speech_runtime.orchestrator import SpeechPreparationOrchestrator
from app.domain.speech_runtime.policy import SpeechCandidatePriority, SpeechRuntimeOperationalPolicy
from app.domain.speech_runtime.tasks import CandidateTaskRegistry

from .contracts import (
    Gate,
    LabMode,
    ProductionTargetProvenance,
    RunStatus,
    TargetObservation,
    ValidationFixture,
)
from .runtime import LabTarget, RunContext
from .tts import TTSSynthesisCase, _project, synthesis_run_status, synthesize_audio


@dataclass(frozen=True)
class SpeechCapacityInput:
    synthesis: TTSSynthesisCase
    priority: SpeechCandidatePriority
    mode: TTSPreparationMode
    semantic_accepted: bool

    def __post_init__(self) -> None:
        if not isinstance(self.priority, SpeechCandidatePriority):
            raise ValueError("準備候補の優先順位が不正です")
        if (
            not isinstance(self.mode, TTSPreparationMode)
            or type(self.semantic_accepted) is not bool
        ):
            raise ValueError("合成方式または採否の検証前提が不正です")

    def typed_inputs(self) -> JsonValue:
        return _project(
            {
                "synthesis": self.synthesis.typed_inputs(),
                "priority": self.priority,
                "mode": self.mode,
                "semantic_accepted": self.semantic_accepted,
            }
        )


@dataclass(frozen=True)
class SpeechCapacityCase:
    fixture: ValidationFixture
    policy: SpeechRuntimeOperationalPolicy
    inputs: tuple[SpeechCapacityInput, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", tuple(self.inputs))
        if not isinstance(self.policy, SpeechRuntimeOperationalPolicy):
            raise ValueError("共有準備枠の運用方針が必要です")
        ids = [item.synthesis.request.candidate_id for item in self.inputs]
        if len(ids) < 2 or len(set(ids)) != len(ids):
            raise ValueError("共有枠の検証には識別子の異なる複数候補が必要です")

    def typed_inputs(self) -> JsonValue:
        return _project({"policy": self.policy, "inputs": [x.typed_inputs() for x in self.inputs]})


def speech_capacity_target(
    cases: tuple[SpeechCapacityCase, ...],
    client: TTSProviderClient,
    provenance: ProductionTargetProvenance,
    contract_revision: str,
) -> LabTarget:
    registered = {case.fixture.scenario_id: case for case in cases}
    if len(registered) != len(cases):
        raise ValueError("共有準備枠の検証条件は重複できません")

    async def run(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        case = registered.get(fixture.scenario_id)
        if case is None or fixture != case.fixture or fixture.typed_inputs != case.typed_inputs():
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        # 候補ごとの保持処理・生成引継ぎ・合成を実行前に上限へ算入する。
        if len(case.inputs) * 4 > context.policy.max_tasks:
            return TargetObservation(RunStatus.BLOCKED_UPSTREAM, Gate.NOT_RUN, None)
        tasks = CandidateTaskRegistry()
        admission = SpeechPreparationAdmission(case.policy)
        owner = SpeechPreparationOrchestrator(tasks, admission)
        context.add_cleanup("speech.shared_preparation", tasks.shutdown)
        records: list[dict[str, object]] = []
        work: list[asyncio.Task[object]] = []
        statuses: dict[str, RunStatus] = {}

        async def prepare(
            item: SpeechCapacityInput, record: dict[str, object], character: asyncio.Task[object]
        ) -> object:
            candidate_id = item.synthesis.request.candidate_id
            await character

            async def synthesize() -> object:
                prefix = f"{context.run_id}:{context.iteration}:{candidate_id}"
                scoped = replace(
                    item.synthesis,
                    request=replace(
                        item.synthesis.request,
                        request_id=f"{prefix}:tts",
                        candidate_id=f"{prefix}:candidate",
                    ),
                )
                request, result = await synthesize_audio(
                    context, scoped, client, preserve_identity=True
                )
                record["request"] = request
                record["result"] = result
                statuses[candidate_id] = synthesis_run_status(result)
                return result

            synthesis = owner.start_tts_if_permitted(
                candidate_id, 1, item.mode, item.semantic_accepted, synthesize
            )
            record["tts_started"] = synthesis is not None
            record["speculative_count_after_start"] = owner.active_speculative_tts_count
            if synthesis is not None:
                await synthesis
            owner.complete_preparation(candidate_id, 1)
            return None

        try:
            for item in case.inputs:
                candidate_id = item.synthesis.request.candidate_id

                async def generated(item: SpeechCapacityInput = item) -> object:
                    # 検証入力に保持された生成済み要求を引き継ぎ、文章を再生成しない。
                    return item.synthesis.request

                character = owner.start_preparation(candidate_id, 1, item.priority, generated)
                record: dict[str, object] = {
                    "candidate_id": candidate_id,
                    "admitted": character is not None,
                    "active_count_after_admission": admission.active_count,
                    "background_count_after_admission": admission.background_active_count,
                    "tts_started": False,
                }
                records.append(record)
                if character is not None:
                    work.append(asyncio.create_task(prepare(item, record, character)))
            await asyncio.gather(*work)
        finally:
            for task in work:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*work, return_exceptions=True)
            await tasks.shutdown()
        status = next(
            (
                statuses[x.synthesis.request.candidate_id]
                for x in case.inputs
                if statuses.get(x.synthesis.request.candidate_id, RunStatus.COMPLETED)
                is not RunStatus.COMPLETED
            ),
            RunStatus.COMPLETED,
        )
        return TargetObservation(
            status,
            Gate.NOT_RUN,
            _project(
                {
                    "candidates": records,
                    "admission_count_after_settlement": admission.active_count,
                    "background_count_after_settlement": admission.background_active_count,
                    "speculative_count_after_settlement": owner.active_speculative_tts_count,
                    "pending_task_count": tasks.pending_task_count,
                }
            ),
        )

    return LabTarget(
        "speech_capacity",
        contract_revision,
        frozenset({LabMode.ADJACENT}),
        (),
        provenance,
        run,
        frozenset({"tts.provider"}),
    )
