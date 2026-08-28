from dataclasses import replace

from tools.loop_engine.models import MissionSnapshot
from tools.loop_engine.scheduler import is_duplicate, schedule_key, select_work

from .conftest import epoch, identity, work


def test_current_actionable_work_continues() -> None:
    chosen = select_work(epoch(works=(work(465, priority="P2"), work(500, priority="P0"))))
    assert chosen is not None and chosen.issue_number == 465


def test_review_and_verification_wait_select_independent_work() -> None:
    review_wait = work(465, actionable=False, wait_only=True, wait_reason="review pending")
    verification_wait = work(
        465, actionable=False, wait_only=True, wait_reason="verification pending"
    )
    independent = work(500, priority="P1", status="Ready")
    review_choice = select_work(epoch(works=(review_wait, independent)))
    verification_choice = select_work(epoch(works=(verification_wait, independent)))
    assert review_choice is not None and review_choice.issue_number == 500
    assert verification_choice is not None and verification_choice.issue_number == 500


def test_generated_loop_improvement_work_reenters_normal_scheduler() -> None:
    product_review_wait = work(
        465,
        actionable=False,
        wait_only=True,
        wait_reason="canonical review pending",
    )
    generated_improvement = work(900, priority="P0", status="Ready")
    choice = select_work(epoch(works=(product_review_wait, generated_improvement)))
    assert choice is not None and choice.issue_number == 900


def test_priority_and_stable_issue_number_tie_break() -> None:
    choices = (
        work(600, priority="P1", status="Ready"),
        work(700, priority="P0", status="Ready"),
        work(500, priority="P0", status="Ready"),
    )
    choice = select_work(
        epoch(mission=MissionSnapshot(identity("issue", "450"), None), works=choices)
    )
    assert choice is not None and choice.issue_number == 500


def test_schedule_key_is_restart_stable_and_checkpoint_suppresses_duplicate() -> None:
    first_epoch = epoch()
    key = schedule_key(first_epoch, work(), "IMPLEMENT")
    restarted = epoch(observation_id="epoch-2", checkpoint_schedule_keys=(key,))
    assert key == schedule_key(restarted, work(), "IMPLEMENT")
    assert is_duplicate(restarted, key)


def test_schedule_key_changes_for_dependency_and_checkpoint_identities() -> None:
    observed = epoch()
    initial = schedule_key(observed, observed.works[0], "IMPLEMENT")
    dependency_changed = replace(
        observed,
        works=(replace(observed.works[0], dependency_completion_identities=("dep:done:2",)),),
    )
    work_checkpoint_changed = replace(
        observed,
        works=(replace(observed.works[0], checkpoint_identity="resume:2"),),
    )
    mission_checkpoint_changed = replace(
        observed,
        mission=replace(observed.mission, checkpoint_identity="mission:2"),
    )
    assert initial != schedule_key(dependency_changed, dependency_changed.works[0], "IMPLEMENT")
    assert initial != schedule_key(
        work_checkpoint_changed, work_checkpoint_changed.works[0], "IMPLEMENT"
    )
    assert initial != schedule_key(
        mission_checkpoint_changed, mission_checkpoint_changed.works[0], "IMPLEMENT"
    )
