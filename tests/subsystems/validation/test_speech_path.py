"""本体発話とprocess提示の証拠を共通Harnessで検証する。"""

import asyncio
import base64
import io
import wave
from dataclasses import replace
from typing import Any

import pytest

from app.domain.activity_execution.observation import ObservedExecutionFactRecord
from app.domain.brain_integration import BrainIntegrationWork
from app.subsystems.validation.contracts import Gate, LabMode, RunStatus
from app.subsystems.validation.runtime import RunContext, ValidationRunner
from app.subsystems.validation.speech_path import (
    SpeechPathAudioOutput,
    SpeechPathEvidence,
    SpeechPathLabCase,
    SpeechPathLLMPort,
    SpeechPathSession,
    speech_path_target,
)
from tests.helpers.speech_path import build_speech_path
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec


def waveform() -> bytes:
    target = io.BytesIO()
    with wave.open(target, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\x00\x00" * 1600)
    return target.getvalue()


async def setup(
    *,
    require_audio: bool = False,
    slow_stage: str | None = None,
    audio: bool = False,
    corrupt_audio: bool = False,
    pending_turn: bool = False,
) -> Any:
    value = await build_speech_path(slow_stage, pending_turn=pending_turn)
    case = SpeechPathLabCase(FIXTURE, value.work, value.decision, require_audio)
    fixture = replace(FIXTURE, typed_inputs=case.typed_inputs())
    case = replace(case, fixture=fixture)
    captured: list[SpeechPathEvidence] = []

    async def factory(context: RunContext, evidence: SpeechPathEvidence) -> SpeechPathSession:
        value.pipeline.evidence_sink = evidence
        captured.append(evidence)
        for planner in (
            value.pipeline.semantics,
            value.pipeline.character,
            value.pipeline.verifier,
        ):
            planner._port = SpeechPathLLMPort(evidence, planner._port)
        if audio:
            from app.domain.speech_runtime.discard import PreparedAudioDiscarder
            from app.domain.speech_runtime.queue import (
                PreparedSpeechQueue,
                PreparedSpeechQueueCoordinator,
            )
            from app.domain.speech_runtime.shutdown import SpeechRuntimeShutdown
            from app.subsystems.validation.audio_presentation import LabAudioResources
            from tests.adapters.tts.test_provider import FakeTTS, _response
            from tests.helpers.speech_path import now
            from tests.subsystems.validation.test_generated_audio import audio_settings

            resources = LabAudioResources()
            evidence.add_cleanup(resources.close)

            async def read_audio(reference: str) -> bytes:
                assert resources.resolve(reference) == "private-audio-resource"
                return b"invalid-wave" if corrupt_audio else waveform()

            output = SpeechPathAudioOutput(
                evidence,
                audio_settings(),
                FakeTTS([_response(raw_audio_ref="private-audio-resource")]),
                resources,
                now,
                read_audio,
            )
            old_state = value.pipeline.readers.presentation

            async def state(candidate: Any) -> Any:
                current = await old_state(candidate)
                return replace(
                    current,
                    prepared_audio_ref=candidate.prepared_audio_ref,
                    capability=replace(current.capability, audio_available=True),
                )

            value.pipeline.readers = replace(
                value.pipeline.readers, output=output, presentation=state
            )
            discarder = PreparedAudioDiscarder(value.pipeline.runtime, resources)
            value.pipeline.discarder = discarder
            value.cognition.speech.shutdown = SpeechRuntimeShutdown(
                value.pipeline.runtime,
                value.tasks,
                PreparedSpeechQueueCoordinator(
                    value.pipeline.runtime,
                    PreparedSpeechQueue(value.pipeline.runtime.operational_policy),
                    discarder,
                ),
                discarder,
            )
        return SpeechPathSession(value.cognition, value.tasks, value.start, value.close)

    target = speech_path_target(
        (case,), factory, PROVENANCE, "1", (), provenance_source=lambda: PROVENANCE
    )
    runner = ValidationRunner(
        (target,),
        replace(POLICY, max_intervals=100, timeout_seconds=10, max_export_bytes=4_000_000),
    )
    request = replace(spec(), target_module="speech_path", mode=LabMode.INTEGRATED)
    return runner, request, fixture, value, captured, target, case


@pytest.mark.asyncio
async def test_context_to_accepted_process_presentation() -> None:
    runner, request, fixture, value, captured, *_ = await setup()
    reflected: list[ObservedExecutionFactRecord] = []

    def observe(work: BrainIntegrationWork, record: ObservedExecutionFactRecord) -> None:
        assert work.envelope.trace_id == value.work.envelope.trace_id
        reflected.append(record)

    value.pipeline.reflection_observer = observe
    result = await runner.run(request, fixture)
    assert result.status is RunStatus.COMPLETED, result
    assert result.machine_gate is Gate.PASS
    output = result.stage_results[0].typed_outputs
    assert [r["stage"] for r in output["evidence"] if not r["stage"].startswith("llm_")] == [
        "semantic_context",
        "semantic_plan",
        "character_context",
        "utterance",
        "performance_context",
        "performance_plan",
        "verification_context",
        "verification",
        "prepared_candidate",
        "presentation_context",
    ]
    presentation = output["presentations"][0]
    assert [r["status"] for r in presentation["reports"]] == ["started", "completed"]
    assert presentation["candidate"]["lifecycle"] == "completed"
    assert presentation["execution_fact"]["record_revision"] == 2
    assert presentation["delivery"] == "delivered"
    assert [record.record_revision for record in reflected] == [1, 2]
    assert not value.pipeline.evidence_failed
    assert not presentation["audio_available"]
    assert value.tasks.pending_task_count == value.supervisor.active_execution_count == 0
    assert result.export_json(4_000_000)


@pytest.mark.asyncio
async def test_text_only_never_satisfies_audio_gate() -> None:
    runner, request, fixture, *_ = await setup(require_audio=True)
    result = await runner.run(request, fixture)
    assert result.status is RunStatus.PRODUCT_FAILED
    assert result.machine_gate is Gate.FAIL
    assert result.stage_results[0].typed_outputs["audio"] == ()


@pytest.mark.asyncio
async def test_wave_and_provenance_survive_resource_cleanup() -> None:
    runner, request, fixture, value, *_ = await setup(audio=True, require_audio=True)
    result = await runner.run(request, fixture)
    assert result.status is RunStatus.COMPLETED, result
    output = result.stage_results[0].typed_outputs
    artifact = output["audio"][0]
    assert base64.b64decode(artifact["data_base64"]) == waveform()
    presentation = output["presentations"][0]
    assert artifact["audio_ref"] == presentation["command"]["audio_ref"]
    assert presentation["audio_available"]
    synthesis = next(x["value"] for x in output["evidence"] if x["stage"] == "tts_result")
    assert synthesis["artifact"]["candidate_id"] == presentation["candidate"]["candidate_id"]
    assert "private-audio-resource" not in result.export_json(4_000_000)
    assert value.supervisor.active_execution_count == value.tasks.pending_task_count == 0


@pytest.mark.asyncio
async def test_corrupt_wave_prevents_presentation() -> None:
    runner, request, fixture, value, *_ = await setup(
        audio=True, require_audio=True, corrupt_audio=True
    )
    result = await runner.run(request, fixture)
    assert result.status is RunStatus.PRODUCT_FAILED
    assert result.stage_results[0].typed_outputs["presentations"] == ()
    assert value.supervisor.active_execution_count == 0


@pytest.mark.asyncio
async def test_failed_feedback_cognition_is_preserved() -> None:
    runner, request, fixture, *_ = await setup(pending_turn=True)
    result = await runner.run(request, fixture)
    assert result.status is RunStatus.PRODUCT_FAILED
    output = result.stage_results[0].typed_outputs
    assert output["presentations"][0]["candidate"]["lifecycle"] == "completed"
    assert any(o["status"] == "failed" for o in output["outcomes"])


@pytest.mark.asyncio
async def test_cancel_preparation_reaps_owned_tasks() -> None:
    runner, request, fixture, value, *_ = await setup(slow_stage="character")
    before = asyncio.all_tasks()
    task = asyncio.create_task(runner.run(request, fixture))
    await asyncio.wait_for(value.blocked.wait(), 3)
    await runner.cancel(request.run_id)
    result = await task
    assert result.status is RunStatus.CANCELLED
    assert value.supervisor.active_execution_count == value.tasks.pending_task_count == 0
    assert not (asyncio.all_tasks() - before - {asyncio.current_task()})


@pytest.mark.asyncio
async def test_changed_owner_rejects_prepared_meaning() -> None:
    runner, request, fixture, value, *_ = await setup(slow_stage="stale")
    task = asyncio.create_task(runner.run(request, fixture))
    await asyncio.wait_for(value.blocked.wait(), 3)
    with value.goals.finalization_participant.mutation():
        pass
    value.release.set()
    result = await task
    assert result.status is RunStatus.PRODUCT_FAILED
    assert result.stage_results[0].typed_outputs["presentations"] == ()
    assert value.supervisor.active_execution_count == 0


@pytest.mark.asyncio
async def test_observation_failure_does_not_change_presentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner, request, fixture, value, *_ = await setup()
    reflected: list[ObservedExecutionFactRecord] = []
    value.pipeline.reflection_observer = lambda work, record: reflected.append(record)

    def broken(self: SpeechPathEvidence, stage: str, value: object) -> None:
        raise ValueError("private-diagnostic-body")

    monkeypatch.setattr(SpeechPathEvidence, "__call__", broken)
    result = await runner.run(request, fixture)
    assert result.status is RunStatus.HARNESS_FAILED
    assert (
        result.stage_results[0].typed_outputs["presentations"][0]["candidate"]["lifecycle"]
        == "completed"
    )
    assert "private-diagnostic-body" not in result.export_json(4_000_000)
    assert value.pipeline.evidence_failed
    assert [record.record_revision for record in reflected] == [1, 2]
    assert result.stage_results[0].typed_outputs["presentations"][0]["delivery"] == "delivered"


@pytest.mark.asyncio
async def test_injected_llm_failure_keeps_role_evidence() -> None:
    from app.subsystems.validation.contracts import FailureInjection, InjectedFailure

    runner, request, fixture, value, *_ = await setup()
    request = replace(
        request,
        failure_injections=(
            FailureInjection("speech_path.llm", InjectedFailure.PROVIDER_UNAVAILABLE, 1),
        ),
    )
    result = await runner.run(request, fixture)
    assert result.status is RunStatus.PRODUCT_FAILED
    evidence = result.stage_results[0].typed_outputs["evidence"]
    role = next(e["value"] for e in evidence if e["stage"] == "llm_result")
    assert role["status"] == "failed"
    assert role["failure_code"] == "provider_unavailable"
    assert value.supervisor.active_execution_count == 0


@pytest.mark.asyncio
async def test_provenance_mismatch_never_starts_factory() -> None:
    _, request, fixture, _, _, _, case = await setup()

    async def forbidden(context: RunContext, evidence: SpeechPathEvidence) -> SpeechPathSession:
        raise AssertionError("来歴不一致では製品を起動できません")

    target = speech_path_target(
        (case,),
        forbidden,
        PROVENANCE,
        "1",
        (),
        provenance_source=lambda: replace(PROVENANCE, git_head="b" * 40),
    )
    result = await ValidationRunner((target,), POLICY).run(request, fixture)
    assert result.status is RunStatus.BLOCKED_UPSTREAM
    assert [i.stage for i in result.timeline] == ["target"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["timeout", "close"])
async def test_timeout_and_close_reap_session(operation: str) -> None:
    runner, request, fixture, value, _, target, _ = await setup(slow_stage="character")
    if operation == "timeout":
        runner = ValidationRunner(
            (target,), replace(POLICY, timeout_seconds=0.1, max_intervals=100)
        )
    before = asyncio.all_tasks()
    task = asyncio.create_task(runner.run(request, fixture))
    await asyncio.wait_for(value.blocked.wait(), 3)
    if operation == "close":
        await runner.close()
    result = await task
    assert result.status is (RunStatus.TIMED_OUT if operation == "timeout" else RunStatus.CANCELLED)
    assert runner.pending_count == 0
    assert not (asyncio.all_tasks() - before - {asyncio.current_task()})


@pytest.mark.asyncio
async def test_cancel_noncooperative_presentation_process() -> None:
    runner, request, fixture, value, *_ = await setup(slow_stage="playback")
    task = asyncio.create_task(runner.run(request, fixture))

    async def started() -> None:
        while not value.notifications:
            await asyncio.sleep(0.001)

    await asyncio.wait_for(started(), 3)
    await runner.cancel(request.run_id)
    result = await task
    assert result.status is RunStatus.CANCELLED
    assert value.supervisor.active_execution_count == value.tasks.pending_task_count == 0
