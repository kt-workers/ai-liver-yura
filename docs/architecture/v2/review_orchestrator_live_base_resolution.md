# Independent AI Review — Trusted Live Base Resolution

Status: 歴史参照。Issue #371の現行実装Authorityではない。
Effective: 2026-08-13
Depends on:
- `docs/architecture/v2/independent_ai_review_architecture.md`
- `docs/architecture/v2/review_orchestrator_implementation.md`

> 本書は旧`pull_request_target` workflow案の履歴補足である。現行#371の任意・非ブロッキング支援はworkflowを実装せず、`optional_review_support_contracts.md`を正本とする。

## 1. Problem

`pull_request_target` provides a trusted control-plane workflow from the default branch, but the Pull Request event/API `pull_request.base.sha` must not be assumed to equal the current HEAD of the protected V2 target branch for an older open PR.

PR #368 demonstrated this condition during #371 Live Verification preparation:

- event/API-visible PR base SHA candidate: `f4d6f98bd92f256cc30848f0804944b55654c9f9`
- live `refs/heads/rebuild/v2-foundation`: `a8ff310c2e0bb7be9ae8a2b28659e74deb2037b4`

The older SHA predates the merged Phase A Reviewer Runtime, so checking out `github.event.pull_request.base.sha` can execute a trusted but obsolete runtime or fail because the runtime does not exist there.

## 2. Authority

The Reviewer executable authority for #371 is the **live HEAD of the fixed trusted branch**:

`refs/heads/rebuild/v2-foundation`

The PR author cannot choose this branch. The control-plane workflow target filter is also fixed to `rebuild/v2-foundation`.

The PR head, merge ref, PR body, labels, diff, comments, and other PR-controlled content remain untrusted DATA and never choose executable code.

## 3. Resolution contract

Before checkout, the trusted workflow SHALL:

1. Query GitHub REST for `refs/heads/rebuild/v2-foundation` using the base repository `GITHUB_TOKEN`.
2. Extract the returned immutable commit SHA.
3. Reject empty or malformed SHA resolution.
4. Pass that resolved SHA as the explicit `actions/checkout` `ref`.
5. Execute Reviewer Runtime only from that resolved SHA.

The workflow SHALL NOT:

- checkout `pull_request.head.sha`;
- checkout a PR merge ref;
- execute code downloaded from the PR head;
- allow PR-controlled input to choose the executable ref;
- fall back from failed trusted-base resolution to PR code.

## 4. Security rationale

This preserves both required properties:

- **Freshness:** Reviewer Runtime follows the current trusted V2 trunk rather than an old PR base snapshot.
- **Immutability during execution:** after resolving the live branch, checkout occurs by immutable commit SHA, so a later branch movement cannot change the code executed by that run.

The secret-bearing Gemini step remains downstream of trusted SHA resolution and trusted-runtime checkout only.

## 5. Failure policy

If the trusted branch ref cannot be resolved, checkout fails, or the expected Reviewer Runtime files are missing, the workflow MUST fail closed. It must not invoke Gemini and must not publish a PASS.

## 6. Verification

For PR #368, Live Verification requires:

- resolved trusted runtime SHA equals the live `rebuild/v2-foundation` HEAD at resolution time;
- checked-out Reviewer Runtime exists at that SHA;
- PR head remains `58b1dcd9b33e43ca082c0287ec5d59c39d1ab619` unless independently changed;
- no PR head/merge code is executed;
- Gemini Review is emitted against the current PR head SHA;
- `yura/independent-ai-review` status is written to that same PR head SHA.
