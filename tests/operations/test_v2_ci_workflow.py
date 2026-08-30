from pathlib import Path


def test_workflow_dispatch_resolves_and_validates_live_pr_identity() -> None:
    workflow = Path(".github/workflows/v2-ci.yml").read_text(encoding="utf-8")

    assert "pr_number:" in workflow
    assert "expected_head_sha:" in workflow
    assert 'gh api "repos/$GITHUB_REPOSITORY/pulls/$PR_NUMBER"' in workflow
    assert 'EXPECTED_DISPATCH_HEAD_SHA: ${{ inputs.expected_head_sha }}' in workflow
    assert 'test "$head_sha" = "$EXPECTED_DISPATCH_HEAD_SHA"' in workflow
    assert "DISPATCH_SHA" not in workflow
    assert 'test "$base_ref" = "rebuild/v2-foundation"' in workflow
    assert 'test "$head_sha" = "$EVENT_HEAD_SHA"' in workflow
    assert 'git/ref/heads/$base_ref' in workflow
    assert "needs.resolve-pr-identity.outputs.live_base_sha" in workflow
    assert "needs.resolve-pr-identity.outputs.head_sha" in workflow
    assert "github.event.pull_request.number || inputs.pr_number || github.run_id" in workflow


def test_workflow_rejects_stale_base_and_dependency_source_regressions() -> None:
    workflow = Path(".github/workflows/v2-ci.yml").read_text(encoding="utf-8")

    assert 'git merge-base --is-ancestor "$LIVE_BASE_SHA" "$EXPECTED_HEAD_SHA"' in workflow
    assert 'test "$fetched_base_sha" = "$LIVE_BASE_SHA"' in workflow
    assert 'test "$current_base_sha" = "$LIVE_BASE_SHA"' in workflow
    assert "cache-dependency-path: Pipfile.lock" in workflow
    assert 'PIPENV_VERSION: "2026.8.0"' in workflow
    assert "test -f Pipfile" in workflow
    assert "test -f Pipfile.lock" in workflow
    assert "test ! -e requirements.txt" in workflow
    assert "test ! -e requirements-dev.txt" in workflow
    assert 'python -m pip install "pipenv==$PIPENV_VERSION"' in workflow
    assert "python -m pipenv install --system --deploy --dev" in workflow
    assert 'git diff --check "$LIVE_BASE_SHA...$HEAD_SHA"' in workflow

    assert not Path("requirements.txt").exists()
    assert not Path("requirements-dev.txt").exists()


def test_workflow_keeps_full_product_quality_gates() -> None:
    workflow = Path(".github/workflows/v2-ci.yml").read_text(encoding="utf-8")

    assert "python -m ruff check app tests" in workflow
    assert "python -m mypy --strict app tests" in workflow
    assert "python -m pytest -q" in workflow
    assert "python -m compileall -q app tests" in workflow
