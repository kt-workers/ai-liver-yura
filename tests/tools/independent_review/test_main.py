import json
from pathlib import Path

import pytest

from tools.independent_review import main as review_main
from tools.independent_review.github_client import GitHubApiError
from tools.independent_review.main import (
    EXIT_BLOCKED,
    EXIT_CHANGES_REQUESTED,
    EXIT_PASS,
    _exit_for_verdict,
    _integer_setting,
    _is_supported_target,
    _live_target_matches,
    _set_status,
    _status_for_verdict,
)
from tools.independent_review.models import ReviewVerdict


def test_status_mapping_is_stable() -> None:
    assert _status_for_verdict(ReviewVerdict.PASS) == (
        "success",
        "独立AIレビューに合格しました",
    )
    assert _status_for_verdict(ReviewVerdict.CHANGES_REQUESTED) == (
        "failure",
        "独立AIレビューで修正必須の指摘があります",
    )
    assert _status_for_verdict(ReviewVerdict.BLOCKED) == (
        "error",
        "独立AIレビューを完了できませんでした",
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
    def __init__(self) -> None:
        self.repository = "ktan514/ai-liver-yura"
        self.head_sha = "a" * 40
        self.base_ref = "rebuild/v2-foundation"
        self.draft = False
        self.labels = [{"name": "v2"}]

    def get_pull(self, pr_number: int) -> dict[str, object]:
        return {
            "draft": self.draft,
            "labels": self.labels,
            "base": {
                "ref": self.base_ref,
                "sha": "b" * 40,
                "repo": {"full_name": self.repository},
            },
            "head": {
                "ref": "feature/test",
                "sha": self.head_sha,
                "repo": {"full_name": self.repository},
            },
        }


def test_live_target_requires_full_current_scope() -> None:
    reader = _PullReader()
    assert (
        _live_target_matches(
            reader,
            repository=reader.repository,
            pr_number=1,
            expected_head_sha=reader.head_sha,
        )
        is True
    )

    reader.labels = []
    assert (
        _live_target_matches(
            reader,
            repository=reader.repository,
            pr_number=1,
            expected_head_sha=reader.head_sha,
        )
        is False
    )

    reader.labels = [{"name": "v2"}]
    reader.base_ref = "main"
    assert (
        _live_target_matches(
            reader,
            repository=reader.repository,
            pr_number=1,
            expected_head_sha=reader.head_sha,
        )
        is False
    )


class _FailingStatusWriter:
    def create_commit_status(self, *args: object, **kwargs: object) -> None:
        raise GitHubApiError("状態書込に失敗しました")


def test_status_write_failure_is_not_treated_as_success() -> None:
    assert (
        _set_status(
            _FailingStatusWriter(),
            "a" * 40,
            state="success",
            description="合格として扱わない",
            target_url=None,
        )
        is False
    )


def test_invalid_numeric_setting_is_rejected_before_pending_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps(
            {
                "pull_request": {
                    "number": 1,
                    "draft": False,
                    "base": {
                        "repo": {"full_name": "o/r"},
                        "ref": "rebuild/v2-foundation",
                    },
                    "head": {
                        "repo": {"full_name": "o/r"},
                        "sha": "a" * 40,
                    },
                    "labels": [{"name": "v2"}],
                    "user": {"login": "author"},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("YURA_TRUSTED_BASE_SHA", "b" * 40)
    monkeypatch.setenv("YURA_REVIEW_MAX_CONTEXT_CHARS", "not-a-number")
    monkeypatch.setattr(
        review_main,
        "GitHubClient",
        lambda *_args, **_kwargs: pytest.fail("pending前にGitHub clientを生成してはいけません"),
    )
    assert review_main.main() == EXIT_BLOCKED
    with pytest.raises(ValueError, match="YURA_REVIEW_MAX_CONTEXT_CHARS"):
        _integer_setting("YURA_REVIEW_MAX_CONTEXT_CHARS", "600000")
