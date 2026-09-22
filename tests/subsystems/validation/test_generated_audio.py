"""生成から音声合成・提示までの同一性と失敗時の停止を確認する。"""

from dataclasses import replace

import pytest

from app.adapters.tts.contracts import TTSFailureCode
from app.adapters.tts.provider import TTSProviderError
from app.domain.speech_runtime.contracts import (
    PreparedSpeechCandidate,
    SpeechPresentationCommitState,
    SpeechPresentationMode,
)
from app.subsystems.validation.contracts import RunStatus
from app.subsystems.validation.generated_audio import GeneratedAudioBindings, GeneratedAudioSettings
from tests.adapters.tts import test_provider as tts
from tests.subsystems.validation import test_audio_presentation as output
from tests.subsystems.validation import test_tts as synthesis
from tests.subsystems.validation.json_values import value_at
from tests.subsystems.validation.test_generated_presentation import Live, configuration
from tests.subsystems.validation.test_runtime import POLICY
from tests.subsystems.validation.test_speech_generation import setup
from tests.subsystems.validation.test_speech_generation_chain import Verification, chain_spec


def audio_settings() -> GeneratedAudioSettings:
    item = synthesis.case()
    request = item.request
    return GeneratedAudioSettings(
        request.voice_binding,
        request.capability,
        request.pronunciation_overrides,
        request.provider_config_revision,
        request.pronunciation_config_revision,
        request.priority,
        item.mapping,
        item.operational,
        item.retry,
    )


class AudioLive(Live):
    async def current_state(
        self, candidate: PreparedSpeechCandidate
    ) -> SpeechPresentationCommitState:
        assert candidate.prepared_audio_ref is not None
        state = await super().current_state(candidate)
        return replace(
            state,
            prepared_audio_ref=candidate.prepared_audio_ref,
            capability=replace(state.capability, audio_available=True),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("succeeded", [False, True])
async def test_generated_audio_reaches_presentation_only_after_success(succeeded: bool) -> None:
    settings = replace(
        configuration(),
        audio=audio_settings(),
        presentation_modes=(SpeechPresentationMode.AUDIO_WITH_TEXT,),
    )
    response = (
        tts._response(raw_audio_ref="private-generated-audio")
        if succeeded
        else TTSProviderError(TTSFailureCode.PROVIDER_REJECTED, False)
    )
    client, sink = tts.FakeTTS([response]), output.Output()
    item, runner, _, _ = setup(
        verifier=Verification(accepted=True).build,
        preparation=settings,
        revalidation=AudioLive(),
        audio=GeneratedAudioBindings(client, sink.bind),
        lab_policy=replace(POLICY, max_intervals=32),
    )
    result = await runner.run(chain_spec(), item.fixture)
    assert result.status is (RunStatus.COMPLETED if succeeded else RunStatus.PROVIDER_FAILED)
    value = result.stage_results[0].typed_outputs
    prepared = value_at(value, "evaluation", "prepared_candidate")
    if succeeded:
        candidate = value_at(prepared, "candidate")
        assert value_at(candidate, "lifecycle") == "completed"
        assert value_at(candidate, "candidate_id") == value_at(
            prepared, "synthesis", "artifact", "candidate_id"
        )
        assert value_at(candidate, "utterance_id") == value_at(value, "utterance", "utterance_id")
        assert sink.resources == ["private-generated-audio"]
        assert sink.commands[0].audio_ref is not None
        assert sink.stores[0].resolve(sink.commands[0].audio_ref) is None
    else:
        assert sink.commands == []
        assert value_at(prepared, "synthesis", "failure_code") == "provider_rejected"
    assert "private-generated-audio" not in result.export_json(POLICY.max_export_bytes)
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_state_drift_after_synthesis_prevents_presentation_and_releases_reference() -> None:
    class StaleLive(AudioLive):
        async def current_state(
            self, candidate: PreparedSpeechCandidate
        ) -> SpeechPresentationCommitState:
            state = await super().current_state(candidate)
            return replace(state, source_context_revision=state.source_context_revision + 1)

    settings = replace(
        configuration(),
        audio=audio_settings(),
        presentation_modes=(SpeechPresentationMode.AUDIO_WITH_TEXT,),
    )
    client, sink = tts.FakeTTS([tts._response()]), output.Output()
    item, runner, _, _ = setup(
        verifier=Verification(accepted=True).build,
        preparation=settings,
        revalidation=StaleLive(),
        audio=GeneratedAudioBindings(client, sink.bind),
        lab_policy=replace(POLICY, max_intervals=32),
    )
    result = await runner.run(chain_spec(), item.fixture)
    assert result.status is RunStatus.PRODUCT_FAILED
    assert len(client.calls) == 1 and sink.commands == []
    assert runner.pending_count == 0


@pytest.mark.asyncio
async def test_rejected_generated_utterance_is_not_synthesized() -> None:
    settings = replace(
        configuration(),
        audio=audio_settings(),
        presentation_modes=(SpeechPresentationMode.AUDIO_WITH_TEXT,),
    )
    client, sink = tts.FakeTTS([]), output.Output()
    item, runner, _, _ = setup(
        verifier=Verification().build,
        preparation=settings,
        revalidation=AudioLive(),
        audio=GeneratedAudioBindings(client, sink.bind),
        lab_policy=replace(POLICY, max_intervals=32),
    )
    result = await runner.run(chain_spec(), item.fixture)
    assert result.status is RunStatus.COMPLETED
    assert client.calls == [] and sink.commands == []
    assert (
        value_at(
            result.stage_results[0].typed_outputs, "evaluation", "prepared_candidate", "lifecycle"
        )
        == "rejected"
    )
