from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

from app.adapters.tts.contracts import (
    PreparedAudioArtifact,
    SpeechTimingKind,
    SpeechTimingTrack,
    SpeechTimingUnit,
)
from app.domain.body_expression import (
    BodyExpressionAxis,
    BodyExpressionAxisValue,
    BodyExpressionContext,
    NormalizedExpressionValue,
)
from app.domain.body_integration import BodyIntegrationRuntime
from app.domain.body_realtime import (
    BodyGazeTargetView,
    BodyRealtimeEngine,
    BodyRealtimeRuntime,
    RealtimeMotionConstraintView,
    RealtimeOverlayBundle,
    RealtimeSpeechView,
    RealtimeTickInput,
)
from app.domain.body_solver import (
    BodyContinuousController,
    BodyPoseFrame,
    BodyStateAuthority,
    LatestBodyFrameBuffer,
    v2_baseline_body_solver_policy,
)
from app.domain.speech_runtime.contracts import (
    SpeechPresentationMode,
    SpeechPresentationReport,
    SpeechPresentationReportStatus,
)
from app.subsystems.avatar import AvatarPresentationRuntime, StickAvatarRenderer
from tests.domain.body_solver.d10_fixtures import (
    SUPPORT_CONTACT_IDS,
    StaticTargetResolver,
    physical_model,
    physical_state,
    position_snapshot,
    reach_task,
    trajectory_for,
)

from .runtime import (
    VerificationEngine as _BaseVerificationEngine,
    VerificationPlanner,
    _LivePlanningState,
    _avatar_binding,
    _bounded_float,
    _expression,
    body_motion_candidate_output_schema,
)

_REALTIME_INTERVAL_S = 1.0 / 60.0
_SPEECH_DURATION_S = 1.0


class VerificationEngine(_BaseVerificationEngine):
    """#340実runtimeを#341/#346 Browser検証surfaceへ接続する。"""

    def __init__(self, *, tick_hz: float = 30.0) -> None:
        super().__init__(tick_hz=tick_hz)
        self._realtime_runtime_v2: BodyRealtimeRuntime | None = None
        self._latest_realtime_bundle: RealtimeOverlayBundle | None = None
        self._speech_sequence = 0
        self._speech_started_at: datetime | None = None
        self._speech_anchor_monotonic_s: float | None = None

    def _initialize_runtime(self) -> None:
        now = datetime.now(timezone.utc)
        model = physical_model()
        policy = v2_baseline_body_solver_policy()
        authority = BodyStateAuthority(model, physical_state())
        resolver = StaticTargetResolver(
            (position_snapshot(0.35, target_ref="target:verification:initial"),)
        )
        initial = trajectory_for(
            reach_task(extent=0.0, target_ref="target:verification:initial"),
            plan_id="plan:verification:initial",
            trajectory_id="trajectory:verification:initial",
            solver_policy_revision=policy.policy_revision,
            duration_s=0.01,
        )
        controller = BodyContinuousController(
            model,
            policy,
            initial,
            authority,
            resolver,
            started_monotonic_s=0.0,
        )
        frame_buffer = LatestBodyFrameBuffer(model.body_model_id)
        planner = VerificationPlanner(_LivePlanningState(authority))
        runtime = BodyIntegrationRuntime(
            model,
            policy,
            authority,
            controller,
            planner,
            frame_buffer,
        )
        renderer = StickAvatarRenderer()
        avatar_runtime = AvatarPresentationRuntime(model, _avatar_binding(now), renderer)

        self._runtime = runtime
        self._authority = authority
        self._planner = planner
        self._resolver = resolver
        self._avatar_runtime = avatar_runtime
        self._renderer = renderer

        realtime = BodyRealtimeRuntime(
            BodyRealtimeEngine(seed=23, target_interval_s=_REALTIME_INTERVAL_S),
            self._read_realtime_input,
            self._publish_realtime_overlay,
            target_interval_s=_REALTIME_INTERVAL_S,
        )
        self._realtime_runtime_v2 = realtime
        runtime.attach_realtime_runtime(realtime)
        runtime.start()
        self._publish_snapshot(now, 0.0)

    def _tick(self, now: datetime, monotonic_now: float) -> None:
        runtime = self._runtime
        avatar_runtime = self._avatar_runtime
        renderer = self._renderer
        if runtime is None or avatar_runtime is None or renderer is None:
            raise RuntimeError("verification runtimeが未初期化です")
        self._frame_count += 1
        result = runtime.tick_physical(
            observed_at=now,
            monotonic_now_s=monotonic_now,
            active_support_contact_ids=SUPPORT_CONTACT_IDS,
            frame_id=f"frame:verification:{self._frame_count}",
            trace_id="trace:verification:runtime",
        )
        avatar_runtime.submit_frame(result.frame)
        report = avatar_runtime.present_latest(started_at=now)
        if report is not None:
            self._last_avatar_report = {
                "status": report.status.value,
                "frame_id": report.frame_id,
                "dropped_or_coalesced_frames": report.dropped_or_coalesced_frames,
                "degraded_items": list(report.degraded_items),
                "diagnostics": list(report.sanitized_diagnostics),
            }
        self._publish_snapshot(now, monotonic_now, result.frame)

    def _apply_command(self, command: dict[str, object]) -> None:
        action = command.get("action")
        if action == "channels":
            self._gaze_x = _bounded_float(
                command.get("gaze_x", self._gaze_x), -1.0, 1.0
            )
            self._gaze_y = _bounded_float(
                command.get("gaze_y", self._gaze_y), -1.0, 1.0
            )
            return
        if action == "speech":
            self._speech_sequence += 1
            self._speech_started_at = datetime.now(timezone.utc)
            self._speech_anchor_monotonic_s = asyncio.get_running_loop().time()
            return
        if action == "speech_stop":
            self._speech_started_at = None
            self._speech_anchor_monotonic_s = None
            return
        if action == "blink":
            raise ValueError("blinkは#340の自律state machineが生成します")
        super()._apply_command(command)

    def _read_realtime_input(self) -> RealtimeTickInput:
        authority = self._authority
        runtime = self._runtime
        if authority is None or runtime is None:
            raise RuntimeError("realtime input sourceが未初期化です")
        now = datetime.now(timezone.utc)
        revision = max(authority.current.revision, 1)
        report = runtime.controller.execution_report
        gaze_target = BodyGazeTargetView(
            "focus:verification",
            self._gaze_x,
            self._gaze_y,
            revision,
            "verification.attention",
            1.0,
            now,
        )
        motion_constraint = RealtimeMotionConstraintView(
            "verification.activity",
            revision,
            report.plan_id,
            True,
        )
        return RealtimeTickInput(
            authority.current,
            _realtime_expression(revision, now),
            gaze_target,
            self._current_speech_view(now),
            motion_constraint,
        )

    def _publish_realtime_overlay(self, bundle: RealtimeOverlayBundle) -> None:
        runtime = self._runtime
        if runtime is None:
            raise RuntimeError("BodyIntegrationRuntimeが未初期化です")
        self._latest_realtime_bundle = bundle
        runtime.publish_overlay(bundle)

    def _current_speech_view(self, now: datetime) -> RealtimeSpeechView | None:
        started_at = self._speech_started_at
        anchor = self._speech_anchor_monotonic_s
        if started_at is None or anchor is None:
            return None
        elapsed = asyncio.get_running_loop().time() - anchor
        if elapsed >= _SPEECH_DURATION_S:
            self._speech_started_at = None
            self._speech_anchor_monotonic_s = None
            return None
        return _speech_view(
            sequence=self._speech_sequence,
            started_at=started_at,
            anchor_monotonic_s=anchor,
        )

    def _publish_snapshot(
        self,
        now: datetime,
        monotonic_now: float,
        frame: BodyPoseFrame | None = None,
    ) -> None:
        super()._publish_snapshot(now, monotonic_now, frame)
        realtime = self._realtime_runtime_v2
        bundle = self._latest_realtime_bundle
        with self._snapshot_lock:
            snapshot = dict(self._snapshot)
            snapshot["realtime"] = {
                "runtime": "BodyRealtimeRuntime",
                "engine": "BodyRealtimeEngine",
                "late_tick_count": None if realtime is None else realtime.late_tick_count,
                "overlay_bundle_id": None if bundle is None else bundle.overlay_bundle_id,
                "based_on_body_state_revision": (
                    None if bundle is None else bundle.based_on_body_state_revision
                ),
                "layer_statuses": (
                    {}
                    if bundle is None
                    else {item.layer.value: item.status.value for item in bundle.layer_statuses}
                ),
                "speech_sample_active": self._speech_anchor_monotonic_s is not None,
                "browser_direct_channel_overlay": False,
            }
            controls = snapshot.get("controls")
            if isinstance(controls, dict):
                controls = dict(controls)
                controls.pop("mouth_openness", None)
                snapshot["controls"] = controls
            self._snapshot = snapshot


def _realtime_expression(revision: int, at: datetime) -> BodyExpressionContext:
    base = _expression(revision, at)
    axes = tuple(
        BodyExpressionAxisValue(
            item.axis,
            NormalizedExpressionValue(
                0.65
                if item.axis is BodyExpressionAxis.IDLE_VARIATION
                else 0.25
                if item.axis is BodyExpressionAxis.BREATHING_AMPLITUDE
                else 0.0
            ),
        )
        for item in base.axes
    )
    return replace(base, axes=axes)


def _speech_view(
    *,
    sequence: int,
    started_at: datetime,
    anchor_monotonic_s: float,
) -> RealtimeSpeechView:
    candidate_id = f"candidate:verification:speech:{sequence}"
    artifact_id = f"artifact:verification:speech:{sequence}"
    timing_id = f"timing:verification:speech:{sequence}"
    audio_ref = f"artifact://verification/speech/{sequence}"
    artifact = PreparedAudioArtifact(
        artifact_id,
        f"request:verification:speech:{sequence}",
        candidate_id,
        f"utterance:verification:speech:{sequence}",
        f"performance:verification:speech:{sequence}",
        "voice:verification",
        1,
        1,
        1,
        1,
        "verification.mapping",
        1,
        "verification.retry",
        1,
        audio_ref,
        "wav",
        f"digest-verification-{sequence}",
        started_at,
        1000,
    )
    units = tuple(
        SpeechTimingUnit(
            f"unit:verification:speech:{sequence}:{index}",
            f"segment:verification:speech:{sequence}",
            SpeechTimingKind.VISEME,
            symbol,
            start_ms,
            start_ms + 200,
        )
        for index, (symbol, start_ms) in enumerate(
            (("A", 0), ("I", 200), ("U", 400), ("E", 600), ("O", 800)),
            start=1,
        )
    )
    timing = SpeechTimingTrack(timing_id, artifact_id, units, started_at, 1000)
    presentation = SpeechPresentationReport(
        f"presentation:verification:speech:{sequence}",
        candidate_id,
        SpeechPresentationReportStatus.STARTED,
        (SpeechPresentationMode.AUDIO_WITH_TEXT,),
        started_at,
        None,
        audio_ref,
        timing_id,
    )
    return RealtimeSpeechView(presentation, artifact, timing, anchor_monotonic_s)


__all__ = ["VerificationEngine", "body_motion_candidate_output_schema"]
