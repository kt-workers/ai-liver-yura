from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .context_builder import ContextBuildError
from .gemini_backend import GeminiReviewerBackend
from .github_client import GitHubApiError, GitHubClient
from .models import AgentIdentity, CredentialScope, ReviewVerdict
from .orchestrator import ReviewOrchestrator

EXIT_PASS = 0
EXIT_CHANGES_REQUESTED = 2
EXIT_BLOCKED = 3
EXIT_INTERNAL_ERROR = 4
STATUS_CONTEXT = "yura/independent-ai-review"
SUPPORTED_BASE_REF = "rebuild/v2-foundation"


def _write_summary(text: str) -> None:
    print(text)
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def _exit_for_verdict(verdict: ReviewVerdict) -> int:
    if verdict == ReviewVerdict.PASS:
        return EXIT_PASS
    if verdict == ReviewVerdict.CHANGES_REQUESTED:
        return EXIT_CHANGES_REQUESTED
    return EXIT_BLOCKED


def _status_for_verdict(verdict: ReviewVerdict) -> tuple[str, str]:
    if verdict == ReviewVerdict.PASS:
        return "success", "Independent AI review passed"
    if verdict == ReviewVerdict.CHANGES_REQUESTED:
        return "failure", "Independent AI review found blocking changes"
    return "error", "Independent AI review is blocked"


def _is_supported_target(repository: str, base_full_name: object, base_ref: object) -> bool:
    return base_full_name == repository and base_ref == SUPPORTED_BASE_REF


def _workflow_run_url(repository: str) -> str | None:
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    run_id = os.getenv("GITHUB_RUN_ID")
    if not run_id:
        return None
    return f"{server}/{repository}/actions/runs/{run_id}"


def _set_status(
    client: GitHubClient,
    head_sha: str,
    *,
    state: str,
    description: str,
    target_url: str | None,
) -> bool:
    try:
        client.create_commit_status(
            head_sha,
            state=state,
            context=STATUS_CONTEXT,
            description=description,
            target_url=target_url,
        )
        return True
    except GitHubApiError as exc:
        _write_summary(
            f"Independent AI Review infrastructure error while writing status: {exc}"
        )
        return False


def main() -> int:
    event_path = os.getenv("GITHUB_EVENT_PATH")
    repository = os.getenv("GITHUB_REPOSITORY")
    token = os.getenv("GITHUB_TOKEN")
    if not event_path or not repository or not token:
        _write_summary("Independent AI Review: missing required GitHub runtime environment.")
        return EXIT_INTERNAL_ERROR

    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pr_event = event.get("pull_request")
    if not isinstance(pr_event, dict):
        _write_summary("Independent AI Review: event does not contain a pull request.")
        return EXIT_INTERNAL_ERROR
    pr_number = pr_event.get("number")
    if not isinstance(pr_number, int):
        _write_summary("Independent AI Review: missing PR number.")
        return EXIT_INTERNAL_ERROR
    if bool(pr_event.get("draft")):
        _write_summary("Independent AI Review: draft PR; review deferred until ready_for_review.")
        return EXIT_PASS

    base = pr_event.get("base")
    head = pr_event.get("head")
    base_repo = base.get("repo") if isinstance(base, dict) else None
    head_repo = head.get("repo") if isinstance(head, dict) else None
    base_full_name = base_repo.get("full_name") if isinstance(base_repo, dict) else None
    base_ref = base.get("ref") if isinstance(base, dict) else None
    head_full_name = head_repo.get("full_name") if isinstance(head_repo, dict) else None
    head_sha = head.get("sha") if isinstance(head, dict) else None
    supported_target = _is_supported_target(repository, base_full_name, base_ref)
    if not supported_target or not isinstance(head_sha, str):
        _write_summary("Independent AI Review: PR target is outside the supported V2 base.")
        return EXIT_BLOCKED

    # V2's supported automatic path is a same-repository implementation lineage.
    # Fork PRs are never escalated to an unsafe PR-head execution path.
    if head_full_name != repository:
        _write_summary("Independent AI Review: fork/cross-repository PR is BLOCKED by MVP policy.")
        return EXIT_BLOCKED

    labels = pr_event.get("labels") or []
    label_names = {
        item.get("name")
        for item in labels
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    if "v2" not in label_names:
        _write_summary("Independent AI Review: V2 base PR is missing required `v2` label.")
        return EXIT_BLOCKED

    user = pr_event.get("user")
    author = user.get("login") if isinstance(user, dict) else None
    if not isinstance(author, str):
        _write_summary("Independent AI Review: PR author metadata is incomplete.")
        return EXIT_BLOCKED

    client = GitHubClient(repository, token, os.getenv("GITHUB_API_URL", "https://api.github.com"))
    run_url = _workflow_run_url(repository)
    if not _set_status(
        client,
        head_sha,
        state="pending",
        description="Independent AI review is running",
        target_url=run_url,
    ):
        return EXIT_INTERNAL_ERROR

    model = os.getenv("GEMINI_REVIEW_MODEL", "gemini-3.6-flash")
    run_id = os.getenv("GITHUB_RUN_ID", "local")
    run_attempt = os.getenv("GITHUB_RUN_ATTEMPT", "1")
    implementer = AgentIdentity(
        role="IMPLEMENTER",
        provider="github",
        agent_id=f"github-pr-author:{author}",
        session_id=f"implementation-lineage:{pr_number}:{head_sha}",
        principal=author,
        credential_scope=CredentialScope.IMPLEMENTATION_WRITE,
    )
    reviewer = AgentIdentity(
        role="REVIEWER",
        provider="google-gemini",
        model=model,
        agent_id="yura-independent-reviewer-gemini",
        session_id=f"github-actions:{run_id}:{run_attempt}:{head_sha}",
        principal="github-actions[bot]",
        credential_scope=CredentialScope.REVIEW_WRITE,
    )

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        if not _set_status(
            client,
            head_sha,
            state="error",
            description="GEMINI_API_KEY is not configured",
            target_url=run_url,
        ):
            return EXIT_INTERNAL_ERROR
        _write_summary(
            "Independent AI Review: `GEMINI_API_KEY` is not configured; live review is BLOCKED."
        )
        return EXIT_BLOCKED

    backend = GeminiReviewerBackend(api_key=api_key, model=model)
    orchestrator = ReviewOrchestrator(
        github=client,
        backend=backend,
        repository=repository,
        reviewer_identity=reviewer,
        max_context_chars=int(os.getenv("YURA_REVIEW_MAX_CONTEXT_CHARS", "600000")),
        max_backend_attempts=int(os.getenv("YURA_REVIEW_MAX_BACKEND_ATTEMPTS", "2")),
    )
    try:
        result = orchestrator.run(pr_number=pr_number, implementer_identity=implementer)
    except (ContextBuildError, GitHubApiError) as exc:
        _set_status(
            client,
            head_sha,
            state="error",
            description=f"Review blocked: {type(exc).__name__}",
            target_url=run_url,
        )
        _write_summary(f"Independent AI Review BLOCKED: {type(exc).__name__}: {exc}")
        return EXIT_BLOCKED
    except Exception as exc:
        _set_status(
            client,
            head_sha,
            state="error",
            description=f"Reviewer internal error: {type(exc).__name__}",
            target_url=run_url,
        )
        _write_summary(f"Independent AI Review internal error: {type(exc).__name__}")
        return EXIT_INTERNAL_ERROR

    state, description = _status_for_verdict(result.decision.verdict)
    if not _set_status(
        client,
        head_sha,
        state=state,
        description=description,
        target_url=run_url,
    ):
        return EXIT_INTERNAL_ERROR
    _write_summary(
        f"Independent AI Review: {result.decision.verdict.value} for "
        f"{result.decision.reviewed_head_sha}; published={result.published}."
    )
    return _exit_for_verdict(result.decision.verdict)


if __name__ == "__main__":
    sys.exit(main())
