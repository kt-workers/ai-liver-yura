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
from app.domain.body_realtime.contracts import articulation_for
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


def _artifact(*, candidate_id: str = "candidate") -> PreparedAudioArtifact:
    return PreparedAudioArtifact(
        "artifact",
        "request",
        candidate_id,
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


def _speech(
    *,
    timing: SpeechTimingTrack | None,
    output_modes: tuple[SpeechPresentationMode, ...] = (SpeechPresentationMode.AUDIO_WITH_TEXT,),
    artifact: PreparedAudioArtifact | None = None,
    presentation_monotonic_started_at_s: float = 0,
) -> RealtimeSpeechView:
    report = SpeechPresentationReport(
        "presentation",
        "candidate",
        SpeechPresentationReportStatus.STARTED,
        output_modes,
        NOW,
        None,
        "artifact://prepared/audio",
        "timing",
    )
    return RealtimeSpeechView(
        report,
        _artifact() if artifact is None else artifact,
        timing,
        presentation_monotonic_started_at_s,
    )


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


def test_gaze_release_keeps_a_smoothed_overlay_instead_of_dropping_it() -> None:
    engine = BodyRealtimeEngine()
    target = BodyGazeTargetView("focus", 1.0, 0.0, 5, "attention", 1.0, NOW)
    acquired = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=target,
        speech=None,
        now=NOW,
        monotonic_now_s=0,
    )
    released = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=None,
        now=NOW + timedelta(milliseconds=20),
        monotonic_now_s=0.02,
    )
    acquired_x = next(
        item.value for item in acquired.channel_overlays if item.channel is RealtimeChannel.GAZE_X
    )
    released_x = next(
        item.value for item in released.channel_overlays if item.channel is RealtimeChannel.GAZE_X
    )
    assert 0 < released_x < acquired_x


def test_gaze_confidence_changes_are_smoothed_with_the_spatial_target() -> None:
    engine = BodyRealtimeEngine()
    first_target = BodyGazeTargetView("focus", 1.0, 0.0, 5, "attention", 1.0, NOW)
    first = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=first_target,
        speech=None,
        now=NOW,
        monotonic_now_s=0,
    )
    reduced_target = BodyGazeTargetView("focus", 1.0, 0.0, 6, "attention", 0.0, NOW)
    reduced = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=reduced_target,
        speech=None,
        now=NOW + timedelta(milliseconds=20),
        monotonic_now_s=0.02,
    )
    first_strength = next(
        item.strength for item in first.channel_overlays if item.channel is RealtimeChannel.GAZE_X
    )
    reduced_strength = next(
        item.strength for item in reduced.channel_overlays if item.channel is RealtimeChannel.GAZE_X
    )
    assert 0 < reduced_strength < first_strength


def test_late_gaze_tick_has_bounded_displacement_without_snap() -> None:
    engine = BodyRealtimeEngine()
    initial = BodyGazeTargetView("first", -1.0, 0.0, 5, "attention", 1.0, NOW)
    first = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=initial,
        speech=None,
        now=NOW,
        monotonic_now_s=0,
    )
    retargeted = BodyGazeTargetView("second", 1.0, 0.0, 6, "attention", 1.0, NOW)
    late = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=retargeted,
        speech=None,
        now=NOW + timedelta(milliseconds=200),
        monotonic_now_s=0.2,
    )
    first_x = next(
        item.value for item in first.channel_overlays if item.channel is RealtimeChannel.GAZE_X
    )
    late_x = next(
        item.value for item in late.channel_overlays if item.channel is RealtimeChannel.GAZE_X
    )
    assert 0 < late_x - first_x <= 0.12


def test_late_blink_tick_consumes_phase_overshoot_without_replaying_a_full_blink() -> None:
    engine = BodyRealtimeEngine(seed=4)
    engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=None,
        now=NOW,
        monotonic_now_s=0,
    )
    late = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=None,
        now=NOW + timedelta(seconds=3),
        monotonic_now_s=3,
    )
    detail = next(item.detail for item in late.layer_statuses if item.layer is RealtimeLayer.BLINK)
    assert detail == "open"


def test_very_late_blink_tick_does_not_hidden_catch_up_multiple_blink_cycles() -> None:
    engine = BodyRealtimeEngine(seed=4)
    engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=None,
        now=NOW,
        monotonic_now_s=0,
    )
    engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=None,
        now=NOW + timedelta(seconds=10),
        monotonic_now_s=10,
    )
    after_late = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=None,
        now=NOW + timedelta(seconds=10, milliseconds=20),
        monotonic_now_s=10.02,
    )
    detail = next(
        item.detail for item in after_late.layer_statuses if item.layer is RealtimeLayer.BLINK
    )
    assert detail == "open"


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


def test_delayed_expression_revision_bounds_breath_parameter_displacement() -> None:
    engine = BodyRealtimeEngine()
    first = engine.tick(
        body_state=_body_state(),
        expression=_expression(breath=-1, tempo=-0.9),
        gaze_target=None,
        speech=None,
        now=NOW,
        monotonic_now_s=0,
    )
    delayed = engine.tick(
        body_state=_body_state(),
        expression=_expression(breath=1, tempo=1),
        gaze_target=None,
        speech=None,
        now=NOW + timedelta(milliseconds=250),
        monotonic_now_s=0.25,
    )
    first_amplitude = next(
        item.value
        for item in first.channel_overlays
        if item.channel is RealtimeChannel.BREATH_AMPLITUDE
    )
    delayed_amplitude = next(
        item.value
        for item in delayed.channel_overlays
        if item.channel is RealtimeChannel.BREATH_AMPLITUDE
    )
    assert 0 < delayed_amplitude - first_amplitude <= 0.12


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
        RealtimeSpeechView(report, _artifact(), None, 0)


def test_text_only_presentation_cannot_activate_speech_realtime() -> None:
    with pytest.raises(ValueError, match="音声再生なし"):
        _speech(timing=None, output_modes=(SpeechPresentationMode.TEXT_ONLY,))


def test_speech_realtime_rejects_artifact_from_another_candidate() -> None:
    with pytest.raises(ValueError, match="candidate identity"):
        _speech(timing=None, artifact=_artifact(candidate_id="other-candidate"))


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
        monotonic_now_s=0.05,
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
        monotonic_now_s=0.05,
    )
    assert next(
        item.value
        for item in bundle.channel_overlays
        if item.channel is RealtimeChannel.MOUTH_OPENNESS
    ) == pytest.approx(0.9)


def test_ordinary_japanese_mora_normalizes_to_canonical_vowel_or_closure() -> None:
    assert articulation_for("か", SpeechTimingKind.MORA) == pytest.approx((0.9, 0.0, 0.8, 0.0))
    assert articulation_for("キャ", SpeechTimingKind.MORA) == pytest.approx((0.9, 0.0, 0.8, 0.0))
    assert articulation_for("カー", SpeechTimingKind.MORA) == pytest.approx((0.9, 0.0, 0.8, 0.0))
    assert articulation_for("ん", SpeechTimingKind.MORA) == pytest.approx((0.0, 0.0, 0.0, 1.0))


def test_trusted_japanese_consonant_phonemes_map_to_canonical_consonant_or_closure() -> None:
    assert articulation_for("k", SpeechTimingKind.PHONEME) == pytest.approx((0.2, 0.0, 0.15, 0.0))
    assert articulation_for("s", SpeechTimingKind.PHONEME) == pytest.approx((0.2, 0.0, 0.15, 0.0))
    assert articulation_for("t", SpeechTimingKind.PHONEME) == pytest.approx((0.2, 0.0, 0.15, 0.0))
    assert articulation_for("m", SpeechTimingKind.PHONEME) == pytest.approx((0.0, 0.0, 0.0, 1.0))


def test_trusted_consonant_phoneme_timing_keeps_speech_layer_active() -> None:
    track = SpeechTimingTrack(
        "timing",
        "artifact",
        (SpeechTimingUnit("k", "segment", SpeechTimingKind.PHONEME, "k", 0, 100),),
        NOW,
        1000,
    )
    bundle = BodyRealtimeEngine().tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW,
        monotonic_now_s=0,
    )
    assert _status(bundle, RealtimeLayer.SPEECH_ARTICULATION) is RealtimeLayerStatus.ACTIVE
    assert any(item.channel is RealtimeChannel.MOUTH_OPENNESS for item in bundle.channel_overlays)


def test_standalone_long_vowel_mora_keeps_preceding_mora_articulation() -> None:
    track = SpeechTimingTrack(
        "timing",
        "artifact",
        (
            SpeechTimingUnit("ka", "segment", SpeechTimingKind.MORA, "か", 0, 100),
            SpeechTimingUnit("long", "segment", SpeechTimingKind.MORA, "ー", 100, 200),
        ),
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
    engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW + timedelta(milliseconds=90),
        monotonic_now_s=0.09,
    )
    long_vowel = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW + timedelta(milliseconds=100),
        monotonic_now_s=0.1,
    )
    assert _status(long_vowel, RealtimeLayer.SPEECH_ARTICULATION) is RealtimeLayerStatus.ACTIVE
    assert next(
        item.value
        for item in long_vowel.channel_overlays
        if item.channel is RealtimeChannel.MOUTH_OPENNESS
    ) == pytest.approx(0.9)


def test_consecutive_standalone_long_vowel_mora_inherits_canonical_articulation() -> None:
    track = SpeechTimingTrack(
        "timing",
        "artifact",
        (
            SpeechTimingUnit("ka", "segment", SpeechTimingKind.MORA, "か", 0, 100),
            SpeechTimingUnit("long-one", "segment", SpeechTimingKind.MORA, "ー", 100, 200),
            SpeechTimingUnit("long-two", "segment", SpeechTimingKind.MORA, "ー", 200, 300),
        ),
        NOW,
        1000,
    )
    engine = BodyRealtimeEngine()
    for now, monotonic_now_s in ((NOW, 0), (NOW + timedelta(milliseconds=90), 0.09)):
        engine.tick(
            body_state=_body_state(),
            expression=None,
            gaze_target=None,
            speech=_speech(timing=track),
            now=now,
            monotonic_now_s=monotonic_now_s,
        )
    engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW + timedelta(milliseconds=100),
        monotonic_now_s=0.1,
    )
    long_chain = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW + timedelta(milliseconds=200),
        monotonic_now_s=0.2,
    )
    assert _status(long_chain, RealtimeLayer.SPEECH_ARTICULATION) is RealtimeLayerStatus.ACTIVE
    assert next(
        item.value
        for item in long_chain.channel_overlays
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


def test_presentation_end_fades_retained_articulation_before_releasing_speech_source() -> None:
    track = SpeechTimingTrack(
        "timing",
        "artifact",
        (SpeechTimingUnit("a", "segment", SpeechTimingKind.VISEME, "A", 0, 100),),
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
    speaking = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW + timedelta(milliseconds=90),
        monotonic_now_s=0.09,
    )
    ended = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=None,
        now=NOW + timedelta(milliseconds=100),
        monotonic_now_s=0.1,
    )
    speaking_openness = next(
        item.value
        for item in speaking.channel_overlays
        if item.channel is RealtimeChannel.MOUTH_OPENNESS
    )
    ended_openness = next(
        item.value
        for item in ended.channel_overlays
        if item.channel is RealtimeChannel.MOUTH_OPENNESS
    )
    assert 0 < ended_openness < speaking_openness
    assert _status(ended, RealtimeLayer.SPEECH_ARTICULATION) is RealtimeLayerStatus.ACTIVE


def test_delayed_presentation_end_keeps_a_bounded_articulation_fade() -> None:
    track = SpeechTimingTrack(
        "timing",
        "artifact",
        (SpeechTimingUnit("a", "segment", SpeechTimingKind.VISEME, "A", 0, 100),),
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
    speaking = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW + timedelta(milliseconds=20),
        monotonic_now_s=0.02,
    )
    delayed_end = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=None,
        now=NOW + timedelta(milliseconds=220),
        monotonic_now_s=0.22,
    )
    speaking_openness = next(
        item.value
        for item in speaking.channel_overlays
        if item.channel is RealtimeChannel.MOUTH_OPENNESS
    )
    ended_openness = next(
        item.value
        for item in delayed_end.channel_overlays
        if item.channel is RealtimeChannel.MOUTH_OPENNESS
    )
    assert 0 < ended_openness < speaking_openness
    assert speaking_openness - ended_openness <= 0.45


def test_new_presentation_without_timing_releases_prior_articulation_in_its_degraded_frame() -> (
    None
):
    track = SpeechTimingTrack(
        "timing",
        "artifact",
        (SpeechTimingUnit("a", "segment", SpeechTimingKind.VISEME, "A", 0, 100),),
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
    engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW + timedelta(milliseconds=90),
        monotonic_now_s=0.09,
    )
    unavailable = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=None),
        now=NOW + timedelta(milliseconds=100),
        monotonic_now_s=0.1,
    )
    assert _status(unavailable, RealtimeLayer.SPEECH_ARTICULATION) is RealtimeLayerStatus.DEGRADED
    assert any(
        item.channel is RealtimeChannel.MOUTH_OPENNESS for item in unavailable.channel_overlays
    )


def test_unsupported_timing_symbol_fades_retained_articulation_while_degrading() -> None:
    track = SpeechTimingTrack(
        "timing",
        "artifact",
        (
            SpeechTimingUnit("a", "segment", SpeechTimingKind.VISEME, "A", 0, 100),
            SpeechTimingUnit(
                "unknown", "segment", SpeechTimingKind.PHONEME, "unsupported", 100, 200
            ),
        ),
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
    engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW + timedelta(milliseconds=90),
        monotonic_now_s=0.09,
    )
    unsupported = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW + timedelta(milliseconds=100),
        monotonic_now_s=0.1,
    )
    assert _status(unsupported, RealtimeLayer.SPEECH_ARTICULATION) is RealtimeLayerStatus.DEGRADED
    assert any(
        item.channel is RealtimeChannel.MOUTH_OPENNESS for item in unsupported.channel_overlays
    )


def test_articulation_blends_at_timing_unit_boundary_and_fades_in_gap() -> None:
    track = SpeechTimingTrack(
        "timing",
        "artifact",
        (
            SpeechTimingUnit("a", "segment", SpeechTimingKind.VISEME, "A", 0, 100),
            SpeechTimingUnit("i", "segment", SpeechTimingKind.VISEME, "I", 100, 110),
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
        now=NOW + timedelta(milliseconds=90),
        monotonic_now_s=0.09,
    )
    third = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW + timedelta(milliseconds=100),
        monotonic_now_s=0.1,
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
    assert second_open == pytest.approx(0.9)
    assert 0 < third_open < second_open


def test_speech_timeline_uses_monotonic_clock_after_started_admission() -> None:
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
    engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW,
        monotonic_now_s=0,
    )
    after_wall_clock_jump = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW - timedelta(days=1),
        monotonic_now_s=0.15,
    )
    assert next(
        item.value
        for item in after_wall_clock_jump.channel_overlays
        if item.channel is RealtimeChannel.MOUTH_OPENNESS
    ) == pytest.approx(0.35)


def test_speech_timeline_uses_started_monotonic_reference_without_wall_clock_offset() -> None:
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
    bundle = BodyRealtimeEngine().tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track, presentation_monotonic_started_at_s=99.85),
        now=NOW + timedelta(hours=12),
        monotonic_now_s=100,
    )
    assert _status(bundle, RealtimeLayer.SPEECH_ARTICULATION) is RealtimeLayerStatus.ACTIVE
    assert (
        next(
            item.value
            for item in bundle.channel_overlays
            if item.channel is RealtimeChannel.MOUTH_ROUNDNESS
        )
        < 0
    )


def test_word_boundary_fades_articulation_to_neutral_without_dropping_overlays() -> None:
    track = SpeechTimingTrack(
        "timing",
        "artifact",
        (
            SpeechTimingUnit("a", "segment", SpeechTimingKind.VISEME, "A", 0, 100),
            SpeechTimingUnit(
                "word", "segment", SpeechTimingKind.WORD_BOUNDARY, "boundary", 100, 200
            ),
        ),
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
    before_boundary = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW + timedelta(milliseconds=90),
        monotonic_now_s=0.09,
    )
    at_boundary = engine.tick(
        body_state=_body_state(),
        expression=None,
        gaze_target=None,
        speech=_speech(timing=track),
        now=NOW + timedelta(milliseconds=100),
        monotonic_now_s=0.1,
    )
    before_open = next(
        item.value
        for item in before_boundary.channel_overlays
        if item.channel is RealtimeChannel.MOUTH_OPENNESS
    )
    boundary_open = next(
        item.value
        for item in at_boundary.channel_overlays
        if item.channel is RealtimeChannel.MOUTH_OPENNESS
    )
    assert 0 < boundary_open < before_open
    assert _status(at_boundary, RealtimeLayer.SPEECH_ARTICULATION) is RealtimeLayerStatus.ACTIVE


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


def test_subtle_motion_intensity_revision_is_interpolated_locally() -> None:
    engine = BodyRealtimeEngine(seed=7)
    engine.tick(
        body_state=_body_state(),
        expression=_expression(idle=0),
        gaze_target=None,
        speech=None,
        now=NOW,
        monotonic_now_s=0,
    )
    revised = engine.tick(
        body_state=_body_state(),
        expression=_expression(idle=1),
        gaze_target=None,
        speech=None,
        now=NOW + timedelta(milliseconds=20),
        monotonic_now_s=0.02,
    )
    strength = next(
        item.strength
        for item in revised.channel_overlays
        if item.channel is RealtimeChannel.SUBTLE_SWAY
    )
    assert 0 < strength <= 0.12


def test_subtle_motion_intensity_uses_elapsed_scaling_beneath_displacement_cap() -> None:
    def strength_after(elapsed_s: float) -> float:
        engine = BodyRealtimeEngine()
        engine.tick(
            body_state=_body_state(),
            expression=_expression(idle=0),
            gaze_target=None,
            speech=None,
            now=NOW,
            monotonic_now_s=0,
        )
        bundle = engine.tick(
            body_state=_body_state(),
            expression=_expression(idle=0.1),
            gaze_target=None,
            speech=None,
            now=NOW + timedelta(seconds=elapsed_s),
            monotonic_now_s=elapsed_s,
        )
        return next(
            item.strength
            for item in bundle.channel_overlays
            if item.channel is RealtimeChannel.SUBTLE_SWAY
        )

    assert strength_after(0.02) == pytest.approx(0.008)
    assert strength_after(0.1) == pytest.approx(0.04)


@pytest.mark.asyncio
async def test_runtime_is_cancellable_without_pending_task_and_does_not_mutate_body() -> None:
    published: list[RealtimeOverlayBundle] = []
    state = _body_state()
    runtime = BodyRealtimeRuntime(
        BodyRealtimeEngine(target_interval_s=0.001),
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


def test_runtime_rejects_target_interval_that_would_skew_engine_telemetry() -> None:
    with pytest.raises(ValueError, match="target_interval_s"):
        BodyRealtimeRuntime(
            BodyRealtimeEngine(target_interval_s=1 / 60),
            lambda: RealtimeTickInput(_body_state(), None, None, None),
            lambda _overlay: None,
            target_interval_s=0.001,
        )


def test_realtime_domain_does_not_take_over_adjacent_authority() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in Path("app/domain/body_realtime").glob("*.py")
    )
    assert "BodyPoseFrame" not in source
    assert "CharacterUtterance" not in source
    assert "TTSProviderAdapter" not in source
    assert "BodySolver" not in source
