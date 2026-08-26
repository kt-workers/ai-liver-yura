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
    assert 'test "$base_sha" = "$EVENT_BASE_SHA"' in workflow
    assert "needs.resolve-pr-identity.outputs.head_sha" in workflow
    assert "needs.resolve-pr-identity.outputs.base_sha" in workflow
    assert "github.event.pull_request.number || inputs.pr_number || github.run_id" in workflow
