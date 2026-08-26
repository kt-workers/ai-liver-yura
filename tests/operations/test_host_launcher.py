import hashlib
from pathlib import Path

from app.operations.canonical_reviewer import ReviewStatus, _provider_failure_reason, review
from app.operations.host_launcher import build_launch_environment, build_reviewer_environment


class FakeSecrets:
    def github_token(self) -> str:
        return "secret"

    def reviewer_api_key(self) -> str:
        return "reviewer-secret"


def test_launcher_injects_goal_identity_and_path_without_persisting_token(tmp_path: Path) -> None:
    operations = tmp_path / "docs" / "operations"
    operations.mkdir(parents=True)
    content = b"version: 3\ngeneration: 9\nmission"
    (operations / "loop_mission_goal.md").write_bytes(content)

    environment = build_launch_environment(tmp_path, FakeSecrets(), {"PATH": "/opt/homebrew/bin"})

    assert environment.values["PATH"] == "/opt/homebrew/bin"
    assert environment.values["CODEX_MISSION_GOAL_VERSION"] == "3"
    assert environment.values["CODEX_MISSION_GOAL_GENERATION"] == "9"
    assert environment.values["CODEX_MISSION_GOAL_SHA256"] == hashlib.sha256(content).hexdigest()
    assert environment.values["GH_TOKEN"] == "secret"


def test_reviewer_environment_is_explicitly_sanitized(tmp_path: Path) -> None:
    operations = tmp_path / "docs" / "operations"
    operations.mkdir(parents=True)
    (operations / "reviewer_config.json").write_text(
        '{"default_model":"gpt-5.6-terra"}', encoding="utf-8"
    )
    parent = {
        "PATH": "/opt/homebrew/bin:/usr/bin",
        "GH_TOKEN": "github-secret",
        "GITHUB_TOKEN": "github-secret-too",
        "LOOP_DATABASE_URL": "postgresql://user:database-secret@localhost/db",
        "UNRELATED_SECRET": "must-not-cross-boundary",
    }

    environment = build_reviewer_environment(tmp_path, FakeSecrets(), parent)

    assert environment.values == {
        "PATH": "/opt/homebrew/bin:/usr/bin",
        "OPENAI_API_KEY": "reviewer-secret",
        "OPENAI_REVIEWER_MODEL": "gpt-5.6-terra",
        "OPENAI_REVIEWER_CONFIG": str(operations / "reviewer_config.json"),
    }
    assert "GH_TOKEN" not in environment.values
    assert "GITHUB_TOKEN" not in environment.values
    assert "database-secret" not in repr(environment)


def test_reviewer_without_key_is_typed_not_run() -> None:
    result = review(
        {
            "repository": "ktan514/ai-liver-yura",
            "pr_number": "464",
            "base_ref": "rebuild/v2-foundation",
            "base_sha": "a" * 40,
            "head_ref": "feature/test",
            "head_sha": "b" * 40,
            "diff": "diff --git a/a b/a\n",
        },
        "",
        "gpt-5.6-terra",
    )

    assert result.review_status is ReviewStatus.NOT_RUN
    assert result.reason == "OPENAI_CREDENTIAL_UNAVAILABLE"


def test_reviewer_provider_errors_have_secret_safe_typed_reasons() -> None:
    class AuthenticationError(Exception):
        status_code = 401

    class PermissionDeniedError(Exception):
        status_code = 403

    class RateLimitError(Exception):
        status_code = 429

        def __init__(self, code: str) -> None:
            self.code = code

    class APIConnectionError(Exception):
        pass

    class APITimeoutError(Exception):
        pass

    assert _provider_failure_reason(AuthenticationError()) == "OPENAI_CREDENTIAL_INVALID"
    assert _provider_failure_reason(PermissionDeniedError()) == "OPENAI_MODEL_ACCESS_DENIED"
    assert (
        _provider_failure_reason(RateLimitError("insufficient_quota"))
        == "OPENAI_BILLING_OR_TIER_UNAVAILABLE"
    )
    assert _provider_failure_reason(RateLimitError("rate_limit_exceeded")) == "OPENAI_RATE_LIMITED"
    assert _provider_failure_reason(APIConnectionError()) == "OPENAI_NETWORK_UNAVAILABLE"
    assert _provider_failure_reason(APITimeoutError()) == "OPENAI_HEALTHCHECK_TIMEOUT"
