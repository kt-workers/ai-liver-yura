"""合成音声の同一性、提示前拒否、合成失敗時の未提示を確認する。"""

from collections.abc import AsyncIterator
from dataclasses import replace

import pytest

from app.adapters.tts import PreparedAudioResourceStore
from app.adapters.tts.contracts import TTSFailureCode
from app.adapters.tts.provider import TTSProviderClient, TTSProviderError
from app.domain.speech_runtime.contracts import (
    SpeechPresentationCommand,
    SpeechPresentationMode,
    SpeechPresentationReport,
    SpeechPresentationReportStatus,
)
from app.domain.speech_runtime.presentation import PresentationAdapter
from app.subsystems.validation.audio_presentation import (
    AudioPresentationCase,
    audio_presentation_target,
)
from app.subsystems.validation.contracts import Gate, LabMode, LabRunSpec, RunStatus
from app.subsystems.validation.runtime import ValidationRunner
from tests.adapters.tts import test_provider as tts
from tests.subsystems.validation import test_speech_presentation as presentation
from tests.subsystems.validation import test_tts as synthesis
from tests.subsystems.validation.json_values import value_at
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec


def case() -> AudioPresentationCase:
    audio, output = synthesis.case(), presentation.case()
    request = audio.request
    candidate = replace(
        output.candidate,
        candidate_id=request.candidate_id,
        utterance_id=request.utterance.utterance_id,
        performance_plan_id=request.performance_plan.performance_plan_id,
        speech_plan_id=request.utterance.candidate.semantic_plan_id,
        source_decision_id=request.utterance.candidate.source_decision_id,
        source_event_ids=request.utterance.candidate.source_event_ids,
        source_context_revision=request.utterance.candidate.revisions.source_context_revision,
        goal_revision=request.utterance.candidate.revisions.goal_revision,
        attention_revision=request.utterance.candidate.revisions.attention_revision,
        presentation_modes=(SpeechPresentationMode.AUDIO_WITH_TEXT,),
    )
    state = replace(
        output.state,
        performance_plan_id=candidate.performance_plan_id,
        source_context_revision=candidate.source_context_revision,
        goal_revision=candidate.goal_revision,
        attention_revision=candidate.attention_revision,
        capability=replace(output.state.capability, audio_available=True),
    )
    output = replace(output, candidate=candidate, state=state)
    item = AudioPresentationCase(FIXTURE, audio, output)
    return replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))


class Output:
    def __init__(self) -> None:
        self.commands: list[SpeechPresentationCommand] = []
        self.resources: list[str | None] = []
        self.stores: list[PreparedAudioResourceStore] = []

    def bind(self, resources: PreparedAudioResourceStore) -> PresentationAdapter:
        self.stores.append(resources)

        async def present(
            command: SpeechPresentationCommand,
        ) -> AsyncIterator[SpeechPresentationReport]:
            self.commands.append(command)
            assert command.audio_ref is not None
            self.resources.append(resources.resolve(command.audio_ref))
            for status in (
                SpeechPresentationReportStatus.STARTED,
                SpeechPresentationReportStatus.COMPLETED,
            ):
                yield replace(
                    presentation.report(command, status, command.committed_at),
                    output_modes=command.modes,
                    audio_ref=command.audio_ref,
                )

        return present


def run_spec() -> LabRunSpec:
    return replace(spec(), target_module="audio_presentation", mode=LabMode.ADJACENT)


def runner(
    item: AudioPresentationCase, client: TTSProviderClient, output: Output
) -> ValidationRunner:
    return ValidationRunner(
        (audio_presentation_target((item,), client, output.bind, PROVENANCE, "1"),), POLICY
    )


@pytest.mark.asyncio
async def test_synthesized_audio_resolves_at_presentation_without_exporting_raw_reference() -> None:
    item, output = case(), Output()
    client = tts.FakeTTS([tts._response(raw_audio_ref="private-audio-source")])
    result = await runner(item, client, output).run(run_spec(), item.fixture)
    assert result.status is RunStatus.COMPLETED and result.machine_gate is Gate.NOT_RUN
    assert output.resources == ["private-audio-source"]
    assert output.commands[0].audio_ref is not None
    assert output.stores[0].resolve(output.commands[0].audio_ref) is None
    values = result.stage_results[0].typed_outputs
    assert value_at(values, "synthesis", "artifact", "audio_ref") == output.commands[0].audio_ref
    assert value_at(values, "presentation", "candidate", "lifecycle") == "completed"
    assert "private-audio-source" not in result.export_json(POLICY.max_export_bytes)


@pytest.mark.asyncio
async def test_synthesis_failure_never_invokes_presentation() -> None:
    item, output = case(), Output()
    client = tts.FakeTTS([TTSProviderError(TTSFailureCode.PROVIDER_REJECTED, False)])
    result = await runner(item, client, output).run(run_spec(), item.fixture)
    assert result.status is RunStatus.PROVIDER_FAILED and output.commands == []


@pytest.mark.asyncio
async def test_successful_synthesis_does_not_override_presentation_rejection() -> None:
    item, output = case(), Output()
    item = replace(
        item,
        presentation=replace(
            item.presentation,
            state=replace(item.presentation.state, semantic_acceptance_id="different"),
        ),
    )
    item = replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))
    client = tts.FakeTTS([tts._response()])
    result = await runner(item, client, output).run(run_spec(), item.fixture)
    assert result.status is RunStatus.PRODUCT_FAILED and output.commands == []


def test_unrelated_candidate_cannot_be_substituted() -> None:
    item = case()
    with pytest.raises(ValueError, match="対応"):
        replace(
            item,
            presentation=replace(
                item.presentation,
                candidate=replace(item.presentation.candidate, utterance_id="different"),
            ),
        )
