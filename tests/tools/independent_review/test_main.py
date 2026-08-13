from tools.independent_review.main import (
    EXIT_BLOCKED,
    EXIT_CHANGES_REQUESTED,
    EXIT_PASS,
    _exit_for_verdict,
    _is_supported_target,
    _status_for_verdict,
)
from tools.independent_review.models import ReviewVerdict


def test_status_mapping_is_stable() -> None:
    assert _status_for_verdict(ReviewVerdict.PASS) == (
        "success",
        "Independent AI review passed",
    )
    assert _status_for_verdict(ReviewVerdict.CHANGES_REQUESTED) == (
        "failure",
        "Independent AI review found blocking changes",
    )
    assert _status_for_verdict(ReviewVerdict.BLOCKED) == (
        "error",
        "Independent AI review is blocked",
    )


def test_exit_mapping_is_stable() -> None:
    assert _exit_for_verdict(ReviewVerdict.PASS) == EXIT_PASS
    assert _exit_for_verdict(ReviewVerdict.CHANGES_REQUESTED) == EXIT_CHANGES_REQUESTED
    assert _exit_for_verdict(ReviewVerdict.BLOCKED) == EXIT_BLOCKED


def test_supported_target_requires_exact_v2_base() -> None:
    repo = "ktan514/ai-liver-yura"
    assert _is_supported_target(repo, repo, "rebuild/v2-foundation") is True
    assert _is_supported_target(repo, repo, "main") is False
    assert _is_supported_target(repo, "fork/ai-liver-yura", "rebuild/v2-foundation") is False
