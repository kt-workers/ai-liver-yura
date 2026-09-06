"""採用待ち中の合成、拒否時の破棄、提示と取消の境界を確認する。"""

import asyncio
from dataclasses import replace

import pytest

from app.adapters.tts.provider import ProviderSynthesisInput, TTSProviderResponse
from app.domain.speech_runtime.contracts import SpeechPresentationMode, TTSPreparationMode
from app.subsystems.validation.contracts import RunStatus
from app.subsystems.validation.generated_audio import GeneratedAudioBindings
from app.subsystems.validation.speech_preparation import SpeechPreparationSettings
from tests.adapters.tts import test_provider as tts
from tests.subsystems.validation import test_audio_presentation as output
from tests.subsystems.validation.json_values import value_at
from tests.subsystems.validation.test_generated_audio import AudioLive, audio_settings
from tests.subsystems.validation.test_generated_presentation import configuration
from tests.subsystems.validation.test_runtime import POLICY
from tests.subsystems.validation.test_speech_generation import setup
from tests.subsystems.validation.test_speech_generation_chain import Verification, chain_spec


class ControlledTTS(tts.FakeTTS):
    def __init__(self, *, blocked: bool = False) -> None:
        super().__init__([tts._response(raw_audio_ref="private-speculative-audio")])
        self.started, self.finished, self.cancelled, self.release = (
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
            asyncio.Event(),
        )
        if not blocked:
            self.release.set()

    async def synthesize(
        self, voice_ref: str, texts: tuple[str, ...], parameters: ProviderSynthesisInput
    ) -> TTSProviderResponse:
        self.started.set()
        try:
            await self.release.wait()
            result = await super().synthesize(voice_ref, texts, parameters)
            self.finished.set()
            return result
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


def settings(limit: int = 1) -> SpeechPreparationSettings:
    original = configuration()
    return replace(
        original,
        policy=replace(original.policy, speculative_tts_limit=limit),
        audio=audio_settings(),
        tts_mode=TTSPreparationMode.SPECULATIVE_AFTER_PERFORMANCE,
        presentation_modes=(SpeechPresentationMode.AUDIO_WITH_TEXT,),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [False, True])
async def test_completed_audio_waits_for_acceptance_and_rejection_discards(accepted: bool) -> None:
    verifier, client, sink = (
        Verification(blocking=True, accepted=accepted),
        ControlledTTS(),
        output.Output(),
    )
    item, runner, _, _ = setup(
        verifier=verifier.build,
        preparation=settings(),
        revalidation=AudioLive(),
        audio=GeneratedAudioBindings(client, sink.bind),
        lab_policy=replace(POLICY, max_intervals=40),
    )
    task = asyncio.create_task(runner.run(chain_spec(), item.fixture))
    await asyncio.wait_for(verifier.started.wait(), 0.5)
    await asyncio.wait_for(client.finished.wait(), 0.5)
    assert not verifier.release.is_set() and sink.commands == [] and not task.done()
    verifier.release.set()
    result = await task
    assert result.status is RunStatus.COMPLETED
    prepared = value_at(result.stage_results[0].typed_outputs, "evaluation", "prepared_candidate")
    scheduling = value_at(prepared, "scheduling")
    assert value_at(scheduling, "candidate_before_acceptance_commit", "lifecycle") == "preparing"
    assert (
        value_at(scheduling, "candidate_before_acceptance_commit", "readiness", "audio") == "ready"
    )
    assert value_at(scheduling, "speculative_count_after_start") == 1
    assert value_at(scheduling, "speculative_count_after_settlement") == 0
    assert value_at(scheduling, "admission_count_after_settlement") == 0
    assert value_at(scheduling, "pending_task_count") == 0
    if accepted:
        assert value_at(prepared, "candidate", "lifecycle") == "completed"
        assert len(client.calls) == len(sink.commands) == 1
        assert sink.resources == ["private-speculative-audio"]
    else:
        assert value_at(prepared, "candidate", "lifecycle") == "rejected"
        assert value_at(prepared, "candidate", "prepared_audio_ref") is None
        assert value_at(prepared, "candidate", "readiness", "audio") == "discarded"
        assert sink.commands == []
    audio_ref = value_at(prepared, "synthesis", "artifact", "audio_ref")
    assert isinstance(audio_ref, str) and sink.stores[0].resolve(audio_ref) is None
    assert "private-speculative-audio" not in result.export_json(POLICY.max_export_bytes)
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_zero_limit_defers_but_does_not_prohibit_accepted_synthesis() -> None:
    verifier, client, sink = (
        Verification(blocking=True, accepted=True),
        ControlledTTS(),
        output.Output(),
    )
    item, runner, _, _ = setup(
        verifier=verifier.build,
        preparation=settings(0),
        revalidation=AudioLive(),
        audio=GeneratedAudioBindings(client, sink.bind),
        lab_policy=replace(POLICY, max_intervals=40),
    )
    task = asyncio.create_task(runner.run(chain_spec(), item.fixture))
    await asyncio.wait_for(verifier.started.wait(), 0.5)
    await asyncio.sleep(0.02)
    assert not client.started.is_set() and not task.done()
    verifier.release.set()
    result = await task
    assert result.status is RunStatus.COMPLETED and len(sink.commands) == 1
    prepared = value_at(result.stage_results[0].typed_outputs, "evaluation", "prepared_candidate")
    assert value_at(prepared, "scheduling", "speculative_count_after_start") == 0
    assert value_at(prepared, "scheduling", "speculative_count_after_settlement") == 0
    assert runner.pending_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_run", [False, True])
async def test_pending_synthesis_is_cancelled_on_rejection_or_run_cancel(cancel_run: bool) -> None:
    verifier, client, sink = (
        Verification(blocking=True),
        ControlledTTS(blocked=True),
        output.Output(),
    )
    item, runner, _, _ = setup(
        verifier=verifier.build,
        preparation=settings(),
        revalidation=AudioLive(),
        audio=GeneratedAudioBindings(client, sink.bind),
        lab_policy=replace(POLICY, max_intervals=40),
    )
    task = asyncio.create_task(runner.run(chain_spec(), item.fixture))
    await asyncio.wait_for(client.started.wait(), 0.5)
    if cancel_run:
        await runner.cancel(chain_spec().run_id)
    else:
        verifier.release.set()
    result = await task
    assert result.status is (RunStatus.CANCELLED if cancel_run else RunStatus.COMPLETED)
    assert client.cancelled.is_set() and sink.commands == []
    assert runner.pending_count == 0
    if not cancel_run:
        prepared = value_at(
            result.stage_results[0].typed_outputs, "evaluation", "prepared_candidate"
        )
        assert value_at(prepared, "candidate", "lifecycle") == "rejected"
        assert value_at(prepared, "scheduling", "speculative_count_after_settlement") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [False, True])
async def test_already_finished_verification_does_not_leave_preparation_slots(
    accepted: bool,
) -> None:
    client, sink = ControlledTTS(), output.Output()
    item, runner, _, _ = setup(
        verifier=Verification(accepted=accepted).build,
        preparation=settings(),
        revalidation=AudioLive(),
        audio=GeneratedAudioBindings(client, sink.bind),
        lab_policy=replace(POLICY, max_intervals=40),
    )
    result = await runner.run(chain_spec(), item.fixture)
    assert result.status is RunStatus.COMPLETED
    prepared = value_at(result.stage_results[0].typed_outputs, "evaluation", "prepared_candidate")
    assert value_at(prepared, "scheduling", "speculative_count_after_settlement") == 0
    assert value_at(prepared, "scheduling", "admission_count_after_settlement") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [False, True])
async def test_failed_speculative_provider_never_reaches_presentation(accepted: bool) -> None:
    from app.adapters.tts.contracts import TTSFailureCode
    from app.adapters.tts.provider import TTSProviderError

    verifier, client, sink = (
        Verification(blocking=True, accepted=accepted),
        ControlledTTS(),
        output.Output(),
    )
    client.outcomes = [TTSProviderError(TTSFailureCode.PROVIDER_REJECTED, False)]
    item, runner, _, _ = setup(
        verifier=verifier.build,
        preparation=settings(),
        revalidation=AudioLive(),
        audio=GeneratedAudioBindings(client, sink.bind),
        lab_policy=replace(POLICY, max_intervals=40),
    )
    task = asyncio.create_task(runner.run(chain_spec(), item.fixture))
    await asyncio.wait_for(client.started.wait(), 0.5)
    verifier.release.set()
    result = await task
    assert result.status is (RunStatus.PROVIDER_FAILED if accepted else RunStatus.COMPLETED)
    prepared = value_at(result.stage_results[0].typed_outputs, "evaluation", "prepared_candidate")
    assert value_at(prepared, "synthesis", "failure_code") == "provider_rejected"
    assert value_at(prepared, "candidate", "prepared_audio_ref") is None
    assert sink.commands == [] and runner.pending_count == 0


@pytest.mark.asyncio
async def test_timeout_after_audio_completion_revokes_unaccepted_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.subsystems.validation import speech_preparation
    from app.subsystems.validation.audio_presentation import LabAudioResources

    stores: list[LabAudioResources] = []
    refs: list[str] = []

    class ObservedResources(LabAudioResources):
        def __init__(self) -> None:
            super().__init__()
            stores.append(self)

        def store(self, artifact_id: str, request_id: str, raw_resource_ref: str) -> str:
            ref = super().store(artifact_id, request_id, raw_resource_ref)
            refs.append(ref)
            return ref

    monkeypatch.setattr(speech_preparation, "LabAudioResources", ObservedResources)
    verifier, client, sink = Verification(blocking=True), ControlledTTS(), output.Output()
    item, runner, _, _ = setup(
        verifier=verifier.build,
        preparation=settings(),
        revalidation=AudioLive(),
        audio=GeneratedAudioBindings(client, sink.bind),
        lab_policy=replace(POLICY, max_intervals=40, timeout_seconds=0.05),
    )
    result = await runner.run(chain_spec(), item.fixture)
    assert result.status is RunStatus.TIMED_OUT
    assert client.finished.is_set() and verifier.cancelled.is_set()
    assert len(refs) == len(stores) == 1
    assert stores[0].resolve(refs[0]) is None
    assert sink.commands == [] and runner.pending_count == 0
