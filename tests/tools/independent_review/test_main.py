from tools.independent_review.main import (
    EXIT_BLOCKED,
    EXIT_CHANGES_REQUESTED,
    EXIT_PASS,
    _current_head_matches,
    _exit_for_verdict,
    _is_supported_target,
    _set_status,
    _status_for_verdict,
)
from tools.independent_review.github_client import GitHubApiError
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


class _PullReader:
    def __init__(self, head_sha: str) -> None:
        self.head_sha = head_sha

    def get_pull(self, pr_number: int) -> dict[str, object]:
        return {"head": {"sha": self.head_sha}}


def test_event_head_must_match_live_current_head() -> None:
    expected = "a" * 40
    assert _current_head_matches(_PullReader(expected), 1, expected) is True
    assert _current_head_matches(_PullReader("b" * 40), 1, expected) is False


class _FailingStatusWriter:
    def create_commit_status(self, *args: object, **kwargs: object) -> None:
        raise GitHubApiError("status write failed")


def test_status_write_failure_is_not_treated_as_success() -> None:
    assert (
        _set_status(
            _FailingStatusWriter(),
            "a" * 40,
            state="success",
            description="should not pass",
            target_url=None,
        )
        is False
    )
