import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.adapters.tts.contracts import (
    PreparedAudioArtifact,
    SpeechTimingKind,
    SpeechTimingTrack,
    SpeechTimingUnit,
)
from app.domain.body import (
    BodyPose,
    BodyState,
    BodyVelocity,
    JointTransform,
    JointVelocity,
    Quaternion,
    Vector3,
)
from app.domain.body_expression import (
    BodyExpressionAxis,
    BodyExpressionAxisValue,
    BodyExpressionContext,
    BodyFocusExpressionConstraint,
    NormalizedExpressionValue,
)
from app.domain.body_realtime import (
    BodyGazeTargetView,
    BodyRealtimeEngine,
    BodyRealtimeRuntime,
    RealtimeChannel,
    RealtimeLayer,
    RealtimeLayerStatus,
    RealtimeOverlayBundle,
    RealtimeSpeechView,
    RealtimeTickInput,
)
from app.domain.speech_runtime.contracts import (
    SpeechPresentationMode,
    SpeechPresentationReport,
    SpeechPresentationReportStatus,
)

NOW = datetime(2026, 8, 26, tzinfo=timezone.utc)


def _transform() -> JointTransform:
    return JointTransform(Vector3(0, 0, 0), Quaternion(0, 0, 0, 1))


def _body_state(revision: int = 2) -> BodyState:
    return BodyState(
        "body",
        revision,
        NOW,
        BodyPose(_transform(), ()),
        BodyVelocity(JointVelocity(Vector3(0, 0, 0), Vector3(0, 0, 0)), ()),
    )


def _expression(*, idle: float = 0, breath: float = 0, tempo: float = 0) -> BodyExpressionContext:
    axes = tuple(
        BodyExpressionAxisValue(
            axis,
            NormalizedExpressionValue(
                idle
                if axis is BodyExpressionAxis.IDLE_VARIATION
                else (
                    breath
                    if axis is BodyExpressionAxis.BREATHING_AMPLITUDE
                    else tempo
                    if axis is BodyExpressionAxis.BREATHING_TEMPO
                    else 0
                )
            ),
        )
        for axis in BodyExpressionAxis
    )
    return BodyExpressionContext(
        3,
        8,
        4,
        8,
        5,
        8,
        "yura",
        1,
        2,
        "expression",
        1,
        axes,
        BodyFocusExpressionConstraint(None, None, (), None, None),
        (),
        (),
        (),
        NOW,
    )


def _artifact() -> PreparedAudioArtifact:
    return PreparedAudioArtifact(
        "artifact",
        "request",
        "candidate",
        "utterance",
        "performance",
        "voice",
        1,
        1,
        1,
        1,
        "artifact://prepared/audio",
        "wav",
        "digest",
        NOW,
        1000,
    )


def _speech(*, timing: SpeechTimingTrack | None) -> RealtimeSpeechView:
    report = SpeechPresentationReport(
        "presentation",
        "candidate",
        SpeechPresentationReportStatus.STARTED,
        (SpeechPresentationMode.AUDIO_WITH_TEXT,),
        NOW,
        None,
        "artifact://prepared/audio",
        "timing",
    )
    return RealtimeSpeechView(report, _artifact(), timing)


def _status(bundle: RealtimeOverlayBundle, layer: RealtimeLayer) -> RealtimeLayerStatus:
    return next(item.status for item in bundle.layer_statuses if item.layer is layer)


def test_realtime_bundle_is_overlay_only_and_does_not_mutate_body_state() -> None:
    state = _body_state()
    bundle = BodyRealtimeEngine().tick(
        body_state=state, expression=_expression(), gaze_target=None, speech=None, now=NOW
    )
    assert bundle.based_on_body_state_revision == state.revision
    assert state.revision == 2
    assert all(item.layer is not RealtimeLayer.POSTURE_ASSIST for item in bundle.channel_overlays)


def test_focus_without_spatial_target_degrades_without_guessing_coordinates() -> None:
    target = BodyGazeTargetView("focus", None, None, 5, "attention", 0.8, NOW)
    bundle = BodyRealtimeEngine().tick(
        body_state=_body_state(), expression=None, gaze_target=target, speech=None, now=NOW
    )
    assert _status(bundle, RealtimeLayer.GAZE) is RealtimeLayerStatus.DEGRADED
    assert not {item.channel for item in bundle.channel_overlays} & {
        RealtimeChannel.GAZE_X,
        RealtimeChannel.GAZE_Y,
    }


def test_gaze_smooths_and_saturates_without_full_body_authority() -> None:
    engine = BodyRealtimeEngine()
    target = BodyGazeTargetView("focus", 1.0, -1.0, 5, "attention", 1.0, NOW)
    first = engine.tick(
        body_state=_body_state(), expression=None, gaze_target=target, speech=None, now=NOW
    )
    second = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=target,
        speech=None,
        now=NOW + timedelta(milliseconds=10),
    )
    first_x = next(
        item.value for item in first.channel_overlays if item.channel is RealtimeChannel.GAZE_X
    )
    second_x = next(
        item.value for item in second.channel_overlays if item.channel is RealtimeChannel.GAZE_X
    )
    assert 0 < first_x < 1
    assert first_x < second_x <= 1
    assert all(item.layer is not RealtimeLayer.POSTURE_ASSIST for item in second.channel_overlays)


def test_breath_and_blink_continue_when_speech_is_absent() -> None:
    bundle = BodyRealtimeEngine().tick(
        body_state=_body_state(),
        expression=_expression(breath=0.6),
        gaze_target=None,
        speech=None,
        now=NOW,
        monotonic_now_s=0,
    )
    assert _status(bundle, RealtimeLayer.BREATH) is RealtimeLayerStatus.ACTIVE
    assert _status(bundle, RealtimeLayer.BLINK) is RealtimeLayerStatus.ACTIVE
    assert (
        _status(bundle, RealtimeLayer.SPEECH_ARTICULATION) is RealtimeLayerStatus.INACTIVE_NO_SOURCE
    )


def test_expression_change_interpolates_breath_without_phase_reset_and_emits_interval_metrics() -> (
    None
):
    engine = BodyRealtimeEngine(target_interval_s=0.02)
    first = engine.tick(
        body_state=_body_state(),
        expression=_expression(breath=-1, tempo=-0.9),
        gaze_target=None,
        speech=None,
        now=NOW,
    )
    second = engine.tick(
        body_state=_body_state(),
        expression=_expression(breath=1, tempo=1),
        gaze_target=None,
        speech=None,
        now=NOW + timedelta(milliseconds=20),
        monotonic_now_s=0.02,
    )
    first_phase = next(
        item.value
        for item in first.channel_overlays
        if item.channel is RealtimeChannel.BREATH_PHASE
    )
    second_phase = next(
        item.value
        for item in second.channel_overlays
        if item.channel is RealtimeChannel.BREATH_PHASE
    )
    second_amplitude = next(
        item.value
        for item in second.channel_overlays
        if item.channel is RealtimeChannel.BREATH_AMPLITUDE
    )
    assert second_phase > first_phase
    assert second_phase - first_phase < 0.008
    assert 0 < second_amplitude < 1
    assert second.actual_interval_ms == pytest.approx(20)
    assert second.jitter_ms == pytest.approx(0)


def test_blink_state_machine_is_seed_reproducible_and_has_bounded_interval_variation() -> None:
    def phases(seed: int) -> list[str]:
        engine = BodyRealtimeEngine(seed=seed)
        result: list[str] = []
        for offset in (index / 10 for index in range(25)):
            bundle = engine.tick(
                body_state=_body_state(),
                expression=None,
                gaze_target=None,
                speech=None,
                now=NOW + timedelta(seconds=offset),
                monotonic_now_s=offset,
            )
            detail = next(
                item.detail for item in bundle.layer_statuses if item.layer is RealtimeLayer.BLINK
            )
            assert detail is not None
            result.append(detail)
        return result

    assert phases(4) == phases(4)
    assert phases(4)[0] == "open"
    assert "closing" in phases(4)
    assert phases(4) != phases(90)


def test_prepared_or_nonstarted_presentation_cannot_activate_viseme() -> None:
    report = SpeechPresentationReport(
        "presentation",
        "candidate",
        SpeechPresentationReportStatus.COMPLETED,
        (SpeechPresentationMode.AUDIO_WITH_TEXT,),
        NOW,
        NOW,
        "artifact://prepared/audio",
        "timing",
    )
    with pytest.raises(ValueError, match="STARTED"):
        RealtimeSpeechView(report, _artifact(), None)


def test_started_presentation_with_trusted_timing_activates_canonical_articulation() -> None:
    track = SpeechTimingTrack(
        "timing",
        "artifact",
        (SpeechTimingUnit("unit", "segment", SpeechTimingKind.VISEME, "A", 0, 100),),
        NOW,
        1000,
    )
    engine = BodyRealtimeEngine()
    engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW,
        monotonic_now_s=0,
    )
    bundle = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW + timedelta(milliseconds=20),
        monotonic_now_s=0.1,
    )
    values = {item.channel: item.value for item in bundle.channel_overlays}
    assert _status(bundle, RealtimeLayer.SPEECH_ARTICULATION) is RealtimeLayerStatus.ACTIVE
    assert values[RealtimeChannel.MOUTH_OPENNESS] == pytest.approx(0.9)
    assert values[RealtimeChannel.JAW_OPENNESS] == pytest.approx(0.8)


def test_trusted_mora_timing_maps_to_canonical_articulation_without_provider_parameter() -> None:
    track = SpeechTimingTrack(
        "timing",
        "artifact",
        (SpeechTimingUnit("unit", "segment", SpeechTimingKind.MORA, "あ", 0, 100),),
        NOW,
        1000,
    )
    engine = BodyRealtimeEngine()
    engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW,
        monotonic_now_s=0,
    )
    bundle = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW + timedelta(milliseconds=20),
        monotonic_now_s=0.1,
    )
    assert next(
        item.value
        for item in bundle.channel_overlays
        if item.channel is RealtimeChannel.MOUTH_OPENNESS
    ) == pytest.approx(0.9)


def test_timing_unavailable_degrades_only_speech_layer_without_fake_mouth_motion() -> None:
    bundle = BodyRealtimeEngine().tick(
        body_state=_body_state(),
        expression=_expression(),
        gaze_target=None,
        speech=_speech(timing=None),
        now=NOW,
    )
    assert _status(bundle, RealtimeLayer.SPEECH_ARTICULATION) is RealtimeLayerStatus.DEGRADED
    assert not {item.channel for item in bundle.channel_overlays} & {
        RealtimeChannel.MOUTH_OPENNESS,
        RealtimeChannel.MOUTH_ROUNDNESS,
        RealtimeChannel.JAW_OPENNESS,
        RealtimeChannel.LIP_CLOSURE,
    }
    assert _status(bundle, RealtimeLayer.BREATH) is RealtimeLayerStatus.ACTIVE


def test_articulation_blends_at_timing_unit_boundary_and_fades_in_gap() -> None:
    track = SpeechTimingTrack(
        "timing",
        "artifact",
        (
            SpeechTimingUnit("a", "segment", SpeechTimingKind.VISEME, "A", 0, 100),
            SpeechTimingUnit("i", "segment", SpeechTimingKind.VISEME, "I", 100, 200),
        ),
        NOW,
        1000,
    )
    engine = BodyRealtimeEngine()
    first = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW,
        monotonic_now_s=0,
    )
    second = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW + timedelta(milliseconds=110),
        monotonic_now_s=0.02,
    )
    third = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW + timedelta(milliseconds=250),
        monotonic_now_s=0.04,
    )
    first_open = next(
        item.value
        for item in first.channel_overlays
        if item.channel is RealtimeChannel.MOUTH_OPENNESS
    )
    second_open = next(
        item.value
        for item in second.channel_overlays
        if item.channel is RealtimeChannel.MOUTH_OPENNESS
    )
    third_open = next(
        item.value
        for item in third.channel_overlays
        if item.channel is RealtimeChannel.MOUTH_OPENNESS
    )
    assert 0 < first_open < 0.9
    assert 0 < second_open < 0.9
    assert 0 < third_open < second_open


def test_presentation_timing_ref_must_exactly_bind_the_track() -> None:
    track = SpeechTimingTrack("other-timing", "artifact", (), NOW, 1000)
    with pytest.raises(ValueError, match="Presentationとtiming"):
        _speech(timing=track)


def test_speech_timing_must_bind_to_started_audio_artifact() -> None:
    track = SpeechTimingTrack("timing", "other-artifact", (), NOW, 1000)
    with pytest.raises(ValueError, match="timing track"):
        _speech(timing=track)


def test_subtle_motion_is_seed_reproducible_and_not_framewise_white_noise() -> None:
    first = BodyRealtimeEngine(seed=7).tick(
        body_state=_body_state(),
        expression=_expression(idle=1),
        gaze_target=None,
        speech=None,
        now=NOW,
    )
    second = BodyRealtimeEngine(seed=7).tick(
        body_state=_body_state(),
        expression=_expression(idle=1),
        gaze_target=None,
        speech=None,
        now=NOW,
    )
    first_value = next(
        item.value for item in first.channel_overlays if item.channel is RealtimeChannel.SUBTLE_SWAY
    )
    second_value = next(
        item.value
        for item in second.channel_overlays
        if item.channel is RealtimeChannel.SUBTLE_SWAY
    )
    assert first_value == second_value


@pytest.mark.asyncio
async def test_runtime_is_cancellable_without_pending_task_and_does_not_mutate_body() -> None:
    published: list[RealtimeOverlayBundle] = []
    state = _body_state()
    runtime = BodyRealtimeRuntime(
        BodyRealtimeEngine(),
        lambda: RealtimeTickInput(state, _expression(), None, None),
        published.append,
        target_interval_s=0.001,
    )
    runtime.start()
    await asyncio.sleep(0.005)
    await runtime.close()
    assert published
    assert state.revision == 2
    assert runtime.pending_task_count == 0


def test_realtime_domain_does_not_take_over_adjacent_authority() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("app/domain/body_realtime").glob("*.py")
    )
    assert "BodyPoseFrame" not in source
    assert "CharacterUtterance" not in source
    assert "TTSProviderAdapter" not in source
    assert "BodySolver" not in source
