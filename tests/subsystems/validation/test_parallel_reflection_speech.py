"""振り返りの待機中に発話が提示を終え、取消時も所有処理が回収されることを確認する。"""

import asyncio
from dataclasses import replace

import pytest

from app.domain.memory_reflection import MemoryCandidateProposal, ReflectionContextSnapshot
from app.domain.speech_runtime.contracts import SpeechPresentationMode
from app.subsystems.validation.contracts import (
    Gate,
    LabMode,
    RunStatus,
    TargetObservation,
    ValidationFixture,
)
from app.subsystems.validation.generated_audio import GeneratedAudioBindings
from app.subsystems.validation.parallel import ParallelCase, ParallelInput, parallel_target
from app.subsystems.validation.reflection import reflection_target
from app.subsystems.validation.runtime import RunContext, ValidationRunner
from tests.adapters.tts import test_provider as synthesis
from tests.domain.memory_reflection import test_memory_reflection as owner
from tests.subsystems.validation import test_audio_presentation as output
from tests.subsystems.validation import test_reflection_memory as memory
from tests.subsystems.validation import test_reflection_target as reflection
from tests.subsystems.validation.json_values import array_at, integer_at, value_at
from tests.subsystems.validation.test_generated_audio import AudioLive, audio_settings
from tests.subsystems.validation.test_generated_presentation import configuration
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec
from tests.subsystems.validation.test_speech_generation import setup
from tests.subsystems.validation.test_speech_generation_chain import Verification, chain_spec


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel,delay_seconds", [(False, 0), (True, 0), (False, 20)])
async def test_speech_finishes_while_reflection_waits_and_cleanup_collects_both(
    cancel: bool, delay_seconds: int
) -> None:
    started, release, stopped, speech_done = (asyncio.Event() for _ in range(4))

    class SlowProposal:
        async def propose(
            self, snapshot: ReflectionContextSnapshot
        ) -> tuple[MemoryCandidateProposal, ...]:
            started.set()
            try:
                await asyncio.sleep(delay_seconds)
                await release.wait()
                return (owner.proposal("execution-1", predicate="executed_activity"),)
            finally:
                stopped.set()

    item, _ = memory.setup(("execution-1",))
    background = reflection_target(
        (item,),
        SlowProposal(),
        reflection.Support(),
        reflection.ACCEPTANCE,
        reflection.OPERATIONAL,
        PROVENANCE,
        "1",
    )
    sink = output.Output()
    speech, existing, _, _ = setup(
        verifier=Verification(accepted=True).build,
        preparation=replace(
            configuration(),
            audio=audio_settings(),
            presentation_modes=(SpeechPresentationMode.AUDIO_WITH_TEXT,),
        ),
        revalidation=AudioLive(),
        audio=GeneratedAudioBindings(synthesis.FakeTTS([synthesis._response()]), sink.bind),
    )
    foreground = next(iter(existing._targets.values()))

    async def observed_speech(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        await started.wait()
        result = await foreground.run(context, fixture)
        speech_done.set()
        return result

    case = ParallelCase(
        FIXTURE,
        (
            ParallelInput(replace(memory.run_spec(), run_id="reflection"), item.fixture),
            ParallelInput(chain_spec(), speech.fixture),
        ),
    )
    case = replace(case, fixture=replace(FIXTURE, typed_inputs=case.typed_inputs()))
    runner = ValidationRunner(
        (
            parallel_target(
                (case,), (background, replace(foreground, run=observed_speech)), PROVENANCE, "1"
            ),
        ),
        replace(
            POLICY, max_tasks=8, max_intervals=64, max_export_bytes=500_000, timeout_seconds=30
        ),
    )
    request = replace(spec(), target_module="parallel", mode=LabMode.SYSTEM_SLICE)
    task = asyncio.create_task(runner.run(request, case.fixture))
    try:
        await asyncio.wait_for(speech_done.wait(), 1)
        assert len(sink.commands) == 1
        assert not stopped.is_set() and not task.done()
        if cancel:
            await runner.cancel(request.run_id)
        else:
            release.set()
        result = await task
    finally:
        await runner.close()
        await asyncio.gather(task, return_exceptions=True)
    assert stopped.is_set() and runner.pending_count == 0
    assert sink.commands[0].audio_ref is not None
    assert sink.stores[0].resolve(sink.commands[0].audio_ref) is None
    assert result.status is (RunStatus.CANCELLED if cancel else RunStatus.COMPLETED)
    assert not any(
        t.get_name().startswith("reflection:") and not t.done() for t in asyncio.all_tasks()
    )
    if not cancel:
        assert result.machine_gate is Gate.NOT_RUN
        children = array_at(result.stage_results[0].typed_outputs, "results")
        wait = next(
            x
            for x in array_at(children[0], "timeline")
            if value_at(x, "stage") == "reflection.proposal"
        )
        assert (
            integer_at(wait, "completed_ns") - integer_at(wait, "started_ns")
            >= delay_seconds * 1_000_000_000
        )
        intervals = [
            x for x in array_at(children[1], "timeline") if value_at(x, "stage") != "target"
        ]
        assert intervals
        assert all(
            integer_at(wait, "started_ns")
            <= integer_at(x, "started_ns")
            <= integer_at(x, "completed_ns")
            <= integer_at(wait, "completed_ns")
            for x in intervals
        )
        prepared = value_at(
            children[1], "stage_results", 0, "typed_outputs", "evaluation", "prepared_candidate"
        )
        assert value_at(prepared, "candidate", "lifecycle") == "completed"
        writes = array_at(children[0], "stage_results", 0, "typed_outputs", "memory", "writes")
        assert value_at(writes[0], "result", "disposition") == "store_new"
