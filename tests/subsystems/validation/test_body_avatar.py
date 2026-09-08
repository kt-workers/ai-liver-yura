"""描画先の遅延と失敗を本番の姿勢投影経路へ通す。"""

from dataclasses import replace
from datetime import datetime
from threading import Event
from threading import enumerate as threads

import pytest

from app.domain.body_solver import BodyPoseFrame
from app.subsystems.avatar import (
    AvatarProjectionCommand,
    AvatarRendererResult,
    AvatarRendererStatus,
)
from app.subsystems.validation import body_avatar
from app.subsystems.validation.body_avatar import BodyAvatarLabSettings
from app.subsystems.validation.body_execution import BodyRealtimeLabSettings
from app.subsystems.validation.contracts import LabMode, RunStatus
from tests.subsystems.avatar.test_avatar_presentation import _binding
from tests.subsystems.validation.json_values import array_at, integer_at, value_at
from tests.subsystems.validation.test_body_execution import runner_for, setup
from tests.subsystems.validation.test_runtime import FIXTURE, spec


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", list(AvatarRendererStatus))
async def test_renderer_outcomes_do_not_stop_physical_updates(
    outcome: AvatarRendererStatus,
) -> None:
    case, _ = setup()
    case = replace(case, tick_count=12, avatar=BodyAvatarLabSettings(_binding(), 0.015, (outcome,)))
    case = replace(case, fixture=replace(FIXTURE, typed_inputs=case.typed_inputs()))
    result = await runner_for(case).run(
        replace(spec(), target_module="body_execution", mode=LabMode.ADJACENT), case.fixture
    )
    assert result.status is RunStatus.COMPLETED
    output = result.stage_results[0].typed_outputs
    assert integer_at(output, "final_state", "revision") == case.initial_state.revision + 12
    assert value_at(output, "avatar", "worker_failed") is False
    statuses = {
        value_at(item, "report", "status") for item in array_at(output, "avatar", "reports")
    }
    expected = {
        AvatarRendererStatus.APPLIED: "applied",
        AvatarRendererStatus.FAILED: "failed",
        AvatarRendererStatus.UNAVAILABLE: "output_unavailable",
    }[outcome]
    assert expected in statuses
    assert integer_at(output, "avatar", "pending_worker_count") == 0
    assert not [thread for thread in threads() if thread.name == "validation-body-avatar"]


@pytest.mark.asyncio
async def test_slow_renderer_overlaps_body_ticks_and_coalesces_old_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, release, next_render = Event(), Event(), Event()
    present = body_avatar._InterruptibleRenderer.present
    submit = body_avatar.BodyAvatarLabSession.submit
    submitted = 0

    def synchronized_present(
        self: body_avatar._InterruptibleRenderer,
        command: AvatarProjectionCommand,
        *,
        started_at: datetime,
    ) -> AvatarRendererResult:
        if self.calls == 0:
            entered.set()
            assert release.wait(5), "複数フレームの投入が完了しませんでした"
        else:
            next_render.set()
        return present(self, command, started_at=started_at)

    def synchronized_submit(self: body_avatar.BodyAvatarLabSession, frame: BodyPoseFrame) -> None:
        nonlocal submitted
        submit(self, frame)
        submitted += 1
        if submitted == 1:
            assert entered.wait(5), "描画処理が開始されませんでした"
        elif submitted == 4:
            release.set()
            assert next_render.wait(5), "集約済みフレームの描画が開始されませんでした"

    monkeypatch.setattr(body_avatar._InterruptibleRenderer, "present", synchronized_present)
    monkeypatch.setattr(body_avatar.BodyAvatarLabSession, "submit", synchronized_submit)
    case, _ = setup()
    case = replace(
        case,
        tick_count=16,
        realtime=BodyRealtimeLabSettings(13, 0.005),
        avatar=BodyAvatarLabSettings(_binding(), 0.045, (AvatarRendererStatus.APPLIED,)),
    )
    case = replace(case, fixture=replace(FIXTURE, typed_inputs=case.typed_inputs()))
    result = await runner_for(case).run(
        replace(spec(), target_module="body_execution", mode=LabMode.ADJACENT), case.fixture
    )
    assert result.status is RunStatus.COMPLETED
    output = result.stage_results[0].typed_outputs
    reports = array_at(output, "avatar", "reports")
    assert any(integer_at(item, "report", "dropped_or_coalesced_frames") > 0 for item in reports)
    intervals = [item for item in result.timeline if item.stage == "body.execution.tick"]
    assert any(
        sum(
            integer_at(report, "started_ns") < tick.started_ns < integer_at(report, "completed_ns")
            for tick in intervals
        )
        >= 2
        for report in reports
    )
    assert integer_at(output, "final_state", "revision") == case.initial_state.revision + 16
    assert integer_at(output, "realtime", "overlay_count") > 1
    assert integer_at(output, "avatar", "pending_worker_count") == 0


@pytest.mark.asyncio
async def test_reconnection_resumes_with_newer_body_output() -> None:
    case, _ = setup()
    case = replace(
        case,
        tick_count=16,
        avatar=BodyAvatarLabSettings(
            _binding(), 0.02, (AvatarRendererStatus.UNAVAILABLE, AvatarRendererStatus.APPLIED)
        ),
    )
    case = replace(case, fixture=replace(FIXTURE, typed_inputs=case.typed_inputs()))
    result = await runner_for(case).run(
        replace(spec(), target_module="body_execution", mode=LabMode.ADJACENT), case.fixture
    )
    assert result.status is RunStatus.COMPLETED
    output = result.stage_results[0].typed_outputs
    reports = array_at(output, "avatar", "reports")
    assert value_at(reports[0], "report", "status") == "output_unavailable"
    assert any(value_at(item, "report", "status") == "applied" for item in reports[1:])
    assert integer_at(output, "avatar", "latest_command", "body_state_revision") > 1


@pytest.mark.asyncio
async def test_timeout_interrupts_renderer_wait_and_collects_thread() -> None:
    case, _ = setup()
    case = replace(
        case,
        tick_count=100,
        avatar=BodyAvatarLabSettings(_binding(), 20.0, (AvatarRendererStatus.APPLIED,)),
    )
    case = replace(case, fixture=replace(FIXTURE, typed_inputs=case.typed_inputs()))
    result = await runner_for(case, timeout=0.03).run(
        replace(spec(), target_module="body_execution", mode=LabMode.ADJACENT), case.fixture
    )
    assert result.status is RunStatus.TIMED_OUT
    assert not [thread for thread in threads() if thread.name == "validation-body-avatar"]


@pytest.mark.asyncio
async def test_binding_exchange_uses_new_generation_while_body_keeps_advancing() -> None:
    case, _ = setup()
    replacement = replace(_binding(generation=2), model_identity="model:replacement")
    case = replace(
        case,
        tick_count=20,
        avatar=BodyAvatarLabSettings(
            _binding(), 0.035, (AvatarRendererStatus.APPLIED,), ((2, replacement),)
        ),
    )
    case = replace(case, fixture=replace(FIXTURE, typed_inputs=case.typed_inputs()))
    result = await runner_for(case).run(
        replace(spec(), target_module="body_execution", mode=LabMode.ADJACENT), case.fixture
    )
    assert result.status is RunStatus.COMPLETED
    output = result.stage_results[0].typed_outputs
    assert value_at(output, "avatar", "latest_command", "model_identity") == "model:replacement"
    assert integer_at(output, "avatar", "latest_command", "binding_generation") == 2
    assert integer_at(output, "final_state", "revision") == case.initial_state.revision + 20
    assert value_at(output, "avatar", "worker_failed") is False
    assert integer_at(output, "avatar", "pending_worker_count") == 0
