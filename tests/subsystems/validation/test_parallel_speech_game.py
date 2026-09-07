"""本番の発話経路が音声合成を待つ間もゲームの実行基盤が進むことを確認する。"""

import asyncio
from dataclasses import replace

import pytest

from app.adapters.tts.provider import ProviderSynthesisInput, TTSProviderResponse
from app.domain.speech_runtime.contracts import SpeechPresentationMode
from app.subsystems.validation.contracts import (
    Gate,
    LabMode,
    RunStatus,
    TargetObservation,
    ValidationFixture,
)
from app.subsystems.validation.game_monitor import GameMonitorFrame, game_monitor_target
from app.subsystems.validation.game_skill import game_fixture, game_target
from app.subsystems.validation.generated_audio import GeneratedAudioBindings
from app.subsystems.validation.parallel import ParallelCase, ParallelInput, parallel_target
from app.subsystems.validation.runtime import RunContext, ValidationRunner
from tests.adapters.tts import test_provider as synthesis
from tests.subsystems.game_skill import test_runtime as game_product
from tests.subsystems.validation import test_audio_presentation as output
from tests.subsystems.validation.json_values import array_at, integer_at, value_at
from tests.subsystems.validation.test_game_monitor import case as monitor_case
from tests.subsystems.validation.test_generated_audio import AudioLive, audio_settings
from tests.subsystems.validation.test_generated_presentation import configuration
from tests.subsystems.validation.test_runtime import FIXTURE, POLICY, PROVENANCE, spec
from tests.subsystems.validation.test_speech_generation import setup
from tests.subsystems.validation.test_speech_generation_chain import Verification, chain_spec


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel, duration", [(False, 0), (True, 0), (False, 20)])
async def test_game_advances_during_actual_speech_synthesis_and_both_close(
    cancel: bool, duration: int
) -> None:
    synthesis_started, release, stopped, game_done = (asyncio.Event() for _ in range(4))

    class SlowTTS:
        async def synthesize(
            self, voice_ref: str, texts: tuple[str, ...], provider_input: ProviderSynthesisInput
        ) -> TTSProviderResponse:
            synthesis_started.set()
            try:
                await release.wait()
                return synthesis._response()
            finally:
                stopped.set()

    audio = audio_settings()
    if duration:
        audio = replace(audio, operational=replace(audio.operational, timeout_seconds=duration + 5))
    settings = replace(
        configuration(),
        audio=audio,
        presentation_modes=(SpeechPresentationMode.AUDIO_WITH_TEXT,),
    )
    speech, speech_runner, _, _ = setup(
        verifier=Verification(accepted=True).build,
        preparation=settings,
        revalidation=AudioLive(),
        audio=GeneratedAudioBindings(SlowTTS(), output.Output().bind),
    )
    if duration:
        monitored = monitor_case(
            (GameMonitorFrame(),) * duration, sample_interval_s=1, loop_interval_s=0.05
        )
        game = game_monitor_target(
            (monitored,), game_product.Controller(), game_product.Policy(), PROVENANCE, "1"
        )
        game_input = monitored.fixture
    else:
        game = game_target(PROVENANCE)
        game_input = game_fixture()

    async def observed_game(context: RunContext, fixture: ValidationFixture) -> TargetObservation:
        await synthesis_started.wait()
        result = await game.run(context, fixture)
        game_done.set()
        return result

    game_spec = replace(
        spec(), run_id="game", scenario_id=game_input.scenario_id, target_module=game.module
    )
    item = ParallelCase(
        FIXTURE,
        (ParallelInput(chain_spec(), speech.fixture), ParallelInput(game_spec, game_input)),
    )
    item = replace(item, fixture=replace(FIXTURE, typed_inputs=item.typed_inputs()))
    targets = (*speech_runner._targets.values(), replace(game, run=observed_game))
    runner = ValidationRunner(
        (parallel_target((item,), targets, PROVENANCE, "1"),),
        replace(
            POLICY,
            max_tasks=8,
            max_intervals=128,
            max_export_bytes=1_000_000,
            timeout_seconds=duration + 5,
        ),
    )
    run_spec = replace(spec(), target_module="parallel", mode=LabMode.SYSTEM_SLICE)
    task = asyncio.create_task(runner.run(run_spec, item.fixture))
    await asyncio.wait_for(synthesis_started.wait(), 0.5)
    await asyncio.wait_for(game_done.wait(), duration + 2)
    assert not stopped.is_set()
    if cancel:
        await runner.cancel(run_spec.run_id)
    else:
        release.set()
    result = await task
    assert result.status is (RunStatus.CANCELLED if cancel else RunStatus.COMPLETED)
    assert stopped.is_set() and runner.pending_count == 0
    if not cancel:
        assert result.machine_gate is Gate.NOT_RUN
        children = array_at(result.stage_results[0].typed_outputs, "results")
        assert value_at(children[0], "run_spec", "mode") == "ADJACENT"
        assert value_at(children[1], "run_spec", "mode") == "ISOLATION"
        speech_intervals = array_at(children[0], "timeline")
        game_intervals = array_at(children[1], "timeline")
        wait = next(x for x in speech_intervals if value_at(x, "stage") == "tts.provider")
        frames = [x for x in game_intervals if value_at(x, "stage") == "game.controller"]
        if duration:
            samples = array_at(children[1], "stage_results", 0, "typed_outputs", "samples")
            assert len(samples) == duration
            assert all(
                integer_at(row, "after", "game_state_revision")
                > integer_at(row, "before", "game_state_revision")
                for row in samples
            )
            frames = [x for x in game_intervals if value_at(x, "stage") == "game.monitor_sample"]
            assert len(frames) == duration
            assert integer_at(frames[-1], "completed_ns") - integer_at(frames[0], "started_ns") >= (
                duration * 1_000_000_000
            )
        else:
            assert len(frames) == 3
        assert all(
            integer_at(wait, "started_ns") < integer_at(x, "completed_ns")
            and integer_at(x, "started_ns") < integer_at(wait, "completed_ns")
            for x in frames
        )
