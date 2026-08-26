#!/usr/bin/env python3
"""Host-side launcher: injected environment -> VS Code/reviewer."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

if TYPE_CHECKING:
    from app.operations.host_launcher import (
        ReviewerCredentialUnavailable,
        ReviewerLaunchEnvironment,
        SecretProvider,
    )


def main() -> int:
    from app.operations.host_launcher import (
        EnvironmentSecretProvider,
        GitHubCredentialUnavailable,
        ReviewerCredentialUnavailable,
        build_launch_environment,
        build_reviewer_environment,
        launch_vscode,
        run_reviewer_subprocess,
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--canonical-review-pr", type=int)
    parser.add_argument("--expected-head")
    args = parser.parse_args()
    if args.canonical_review_pr and not args.expected_head:
        parser.error("--canonical-review-pr requires --expected-head")
    if args.expected_head and not args.canonical_review_pr:
        parser.error("--expected-head requires --canonical-review-pr")

    secrets = EnvironmentSecretProvider(os.environ)
    try:
        environment = build_launch_environment(root, secrets, os.environ)
    except GitHubCredentialUnavailable:
        return _not_run("GITHUB_CREDENTIAL_UNAVAILABLE")
    if args.preflight:
        return subprocess.run(
            (sys.executable, "-m", "app.operations.preflight"),
            cwd=root,
            env=dict(environment.values),
            check=False,
        ).returncode
    if args.canonical_review_pr:
        return _canonical_review(
            args.canonical_review_pr,
            args.expected_head,
            environment.values,
            secrets,
            build_reviewer_environment,
            run_reviewer_subprocess,
            ReviewerCredentialUnavailable,
        )
    launch_vscode(root, environment)
    return 0


def _not_run(reason: str) -> int:
    print(json.dumps({"review_status": "NOT_RUN", "reason": reason}, sort_keys=True))
    return 0


def _pr_target(pr_number: int, environment: Mapping[str, str]) -> dict[str, str] | None:
    result = subprocess.run(
        (
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--json",
            "headRefName,headRefOid,baseRefName,baseRefOid",
        ),
        cwd=root,
        env=environment,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=10,
    )
    try:
        value = json.loads(result.stdout)
        return {
            "head_ref": value["headRefName"],
            "head_sha": value["headRefOid"],
            "base_ref": value["baseRefName"],
            "base_sha": value["baseRefOid"],
        }
    except (KeyError, TypeError, json.JSONDecodeError):
        return None


def _canonical_review(
    pr_number: int,
    expected_head: str,
    launch_environment: Mapping[str, str],
    secrets: SecretProvider,
    reviewer_environment_builder: Callable[
        [Path, SecretProvider, Mapping[str, str]], ReviewerLaunchEnvironment
    ],
    reviewer_runner: Callable[
        [Path, ReviewerLaunchEnvironment, Mapping[str, object]], subprocess.CompletedProcess[str]
    ],
    credential_error: type[ReviewerCredentialUnavailable],
) -> int:
    try:
        target = _pr_target(pr_number, launch_environment)
    except (OSError, subprocess.TimeoutExpired):
        return _not_run("GITHUB_REVIEW_TARGET_UNAVAILABLE")
    if target is None:
        return _not_run("GITHUB_REVIEW_TARGET_UNAVAILABLE")
    if target["head_sha"] != expected_head:
        return _not_run("STALE_TARGET")
    try:
        diff = subprocess.run(
            (
                "git",
                "diff",
                "--no-ext-diff",
                "--unified=60",
                target["base_sha"],
                target["head_sha"],
            ),
            cwd=root,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return _not_run("REVIEW_DIFF_UNAVAILABLE")
    if diff.returncode != 0 or len(diff.stdout) > 200_000:
        return _not_run("REVIEW_DIFF_UNAVAILABLE")
    context = {
        "repository": "ktan514/ai-liver-yura",
        "pr_number": str(pr_number),
        **target,
        "diff": diff.stdout,
    }
    try:
        reviewer_environment = reviewer_environment_builder(root, secrets, os.environ)
    except credential_error:
        return _not_run("OPENAI_CREDENTIAL_UNAVAILABLE")
    except RuntimeError:
        return _not_run("OPENAI_REVIEWER_UNAVAILABLE")
    try:
        result = reviewer_runner(root, reviewer_environment, context)
        payload = json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return _not_run("OPENAI_REVIEWER_UNAVAILABLE")
    try:
        current = _pr_target(pr_number, launch_environment)
    except (OSError, subprocess.TimeoutExpired):
        return _not_run("GITHUB_REVIEW_TARGET_UNAVAILABLE")
    if current is None or current["head_sha"] != expected_head:
        return _not_run("STALE_TARGET")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


raise SystemExit(main())
