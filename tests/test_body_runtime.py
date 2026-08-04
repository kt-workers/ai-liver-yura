from __future__ import annotations

import asyncio

import pytest

from app.domain.avatar_performance import AvatarPerformancePlan, AvatarTrackChannel
from app.domain.body import (
    BodyActivityContext,
    BodyExpressionRequest,
    BodyPostureTendency,
    EmbodiedExpressionIntent,
    SpeechEmphasis,
    SpeechPresentationRequest,
)
from app.runtime.body_runtime import BodyRuntime, BodyRuntimeConfig


class RecordingAvatarOutput:
    def __init__(self) -> None:
        self.performances: list[AvatarPerformancePlan] = []

    async def submit_performance(self, performance: AvatarPerformancePlan) -> None:
        self.performances.append(performance)

    async def set_expression(self, expression: str) -> None:
        return None

    async def play_gesture(self, gesture: str) -> None:
        return None

    async def set_gaze(self, gaze: object) -> None:
        return None


class FailingAvatarOutput(RecordingAvatarOutput):
    async def submit_performance(self, performance: AvatarPerformancePlan) -> None:
        raise RuntimeError("avatar unavailable")


@pytest.mark.asyncio
async def test_body_runtime_tick_composes_context_expression_and_autonomous_motion() -> None:
    output = RecordingAvatarOutput()
    performance_ids = iter(
        ("perf-baseline", "perf-expression", "perf-autonomous")
    )
    runtime = BodyRuntime(
        output,
        performance_id_factory=lambda: next(performance_ids),
    )
    await runtime.update_activity_context(
        BodyActivityContext(
            source_activity_id="activity-001",
            attention_target="conversation_partner",
            engagement=0.8,
            posture_tendency=BodyPostureTendency.OPEN,
            movement_energy=0.45,
            gaze_freedom=0.2,
        )
    )
    await runtime.request_expression(
        BodyExpressionRequest(
            source_activity_id="activity-001",
            output_unit_id="output-001",
            expression=EmbodiedExpressionIntent(
                attitude="firm_rejection",
                intensity=0.9,
                tension=0.8,
                openness=0.15,
                approach=-0.7,
                agreement=-0.9,
                assertiveness=0.75,
            ),
            speech_emphasis=(
                SpeechEmphasis("嫌", "reject", 0.9),
            ),
            priority=100,
            duration_hint_ms=2200,
        )
    )

    await runtime.tick_once(now=10.0)

    by_output_unit = {
        performance.output_unit_id: performance
        for performance in output.performances
    }
    assert set(by_output_unit) == {
        "body-activity-context",
        "output-001",
        "body-autonomous",
    }

    baseline = by_output_unit["body-activity-context"]
    assert any(
        track.channel == AvatarTrackChannel.ATTENTION and track.hold
        for track in baseline.tracks
    )
    assert any(
        track.motion is not None and track.motion.name == "posture_open"
        for track in baseline.tracks
    )

    expression = by_output_unit["output-001"]
    motion_names = {
        track.motion.name
        for track in expression.tracks
        if track.motion is not None
    }
    assert "head_shake" in motion_names
    assert "lean_back" in motion_names
    assert "draw_in" in motion_names

    autonomous = by_output_unit["body-autonomous"]
    assert any(
        track.motion is not None and track.motion.name == "breathing"
        for track in autonomous.tracks
    )

    snapshot = await runtime.snapshot()
    assert snapshot.tick_count == 1
    assert snapshot.active_activity_id == "activity-001"
    assert snapshot.pending_expression_count == 0
    assert snapshot.last_performance_id == "perf-autonomous"
    assert snapshot.last_error is None


@pytest.mark.asyncio
async def test_body_runtime_runs_autonomous_motion_without_character_llm_or_activity() -> None:
    output = RecordingAvatarOutput()
    runtime = BodyRuntime(
        output,
        performance_id_factory=lambda: "perf-autonomous",
    )

    await runtime.tick_once(now=1.0)

    assert len(output.performances) == 1
    performance = output.performances[0]
    assert performance.output_unit_id == "body-autonomous"
    assert any(
        track.motion is not None and track.motion.name == "breathing"
        for track in performance.tracks
    )


@pytest.mark.asyncio
async def test_body_runtime_shortest_autonomous_interval_keeps_fades_in_track_range() -> None:
    output = RecordingAvatarOutput()
    runtime = BodyRuntime(
        output,
        config=BodyRuntimeConfig(autonomous_interval_ms=250),
        performance_id_factory=lambda: "perf-autonomous",
    )
    await runtime.update_activity_context(
        BodyActivityContext(
            source_activity_id="activity-001",
            movement_energy=1.0,
        )
    )

    await runtime.tick_once(now=1.0)

    autonomous = next(
        performance
        for performance in output.performances
        if performance.output_unit_id == "body-autonomous"
    )
    assert any(
        track.motion is not None and track.motion.name == "micro_sway"
        for track in autonomous.tracks
    )
    assert all(track.fade_in_ms <= track.duration_ms for track in autonomous.tracks)
    assert all(track.fade_out_ms <= track.duration_ms for track in autonomous.tracks)


@pytest.mark.asyncio
async def test_body_runtime_keeps_tick_alive_when_avatar_submission_fails() -> None:
    runtime = BodyRuntime(
        FailingAvatarOutput(),
        performance_id_factory=lambda: "perf-failure",
    )
    await runtime.request_expression(
        BodyExpressionRequest(
            source_activity_id="activity-001",
            output_unit_id="output-001",
            expression=EmbodiedExpressionIntent(
                attitude="surprised",
                intensity=0.8,
                surprise=0.9,
            ),
            priority=100,
        )
    )

    await runtime.tick_once(now=1.0)
    await runtime.tick_once(now=1.1)

    snapshot = await runtime.snapshot()
    assert snapshot.tick_count == 2
    assert snapshot.last_performance_id is None
    assert snapshot.last_error is not None
    assert "RuntimeError" in snapshot.last_error
    assert "avatar unavailable" in snapshot.last_error


@pytest.mark.asyncio
async def test_body_runtime_expires_speech_by_generated_audio_duration() -> None:
    now = [10.0]
    runtime = BodyRuntime(
        None,
        monotonic_clock=lambda: now[0],
        performance_id_factory=lambda: "perf-autonomous",
    )
    request = SpeechPresentationRequest(
        source_activity_id="activity-001",
        output_unit_id="output-001",
        text="うん、そうだね",
        audio_reference="audio://utterance-001",
        duration_ms=1000,
        emphasis=(SpeechEmphasis("うん", "agree", 0.7),),
        presentation_id="speech-001",
    )

    await runtime.present_speech(request)
    now[0] = 10.5
    await runtime.tick_once(now=now[0])
    assert (await runtime.snapshot()).active_speech_id == "speech-001"

    now[0] = 11.1
    await runtime.tick_once(now=now[0])
    assert (await runtime.snapshot()).active_speech_id is None


@pytest.mark.asyncio
async def test_body_runtime_start_and_stop_are_idempotent() -> None:
    sleeping = asyncio.Event()

    async def wait_until_canceled(_: float) -> None:
        await sleeping.wait()

    runtime = BodyRuntime(
        None,
        sleep=wait_until_canceled,
        performance_id_factory=lambda: "perf-autonomous",
    )

    await runtime.start()
    await runtime.start()
    await asyncio.sleep(0)
    assert (await runtime.snapshot()).running is True

    await runtime.stop()
    await runtime.stop()
    assert (await runtime.snapshot()).running is False


def test_body_runtime_config_validates_tick_and_queue_ranges() -> None:
    assert BodyRuntimeConfig(tick_hz=60).tick_interval_seconds == pytest.approx(
        1 / 60
    )
    with pytest.raises(ValueError, match="tick_hz"):
        BodyRuntimeConfig(tick_hz=0)
    with pytest.raises(ValueError, match="expression_queue_limit"):
        BodyRuntimeConfig(expression_queue_limit=0)
