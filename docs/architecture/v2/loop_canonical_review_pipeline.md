# Loop Canonical Review Pipeline

## Boundary

`LoopCanonicalReviewGate` is mandatory for a merge that requires canonical review. It is distinct from `OptionalReviewSupport`, which remains advisory and cannot produce a merge PASS.

The provider client and `OPENAI_API_KEY_REVIEWER` exist only in a trusted host control-plane process outside the target checkout. Codex and target checkout receive, at most, the non-secret `YURA_TRUSTED_REVIEWER_SOCKET`. The broker has no GitHub write or database credential and never imports or executes target checkout code.

## Identity and state machine

1. The caller supplies repository, PR number, and expected head only.
2. The broker read-only resolves the live PR, base ref/SHA, head SHA, and canonical blob set. Any mismatch is `NOT_RUN / STALE_TARGET`.
3. `ReviewTargetKey` hashes the repository, PR, live head, policy generation, model policy, canonical blob identity, and review-context identity.
4. The durable allocator reserves a monotonically increasing `ReviewAttemptKey` before one provider invocation. A used key is never sent again, including after a crash. Gaps are valid and never backfilled.
5. The broker writes a secret-safe provider outcome before terminal verdict normalization. Result is accepted only after a second live-head readback.

Terminal verdicts are `PASS`, `REQUEST_CHANGES`, or `ESCALATE`. Refusal, incomplete output, transport failure, invalid structure, timeout, stale target, and unavailable capability are typed `NOT_RUN`; they do not masquerade as a canonical verdict.

## Result contract

The provider must use Structured Outputs with a strict bounded schema. The trusted broker, not the provider, attaches reviewed head/base, policy identity, request identity, and reviewer identity. Findings are bounded by count, string length, nesting, enum, path, and line validators. Raw provider output is never persisted.

`PASS` requires zero blocking findings and exact live head identity both before and after invocation. `REQUEST_CHANGES` returns a same-lineage fix TaskPacket. `ESCALATE` routes to the configured escalation policy. `NOT_RUN` yields or blocks only the affected Work; independent dependency-ready Work may continue.

## Merge gate

Before Ready or merge, the Runner re-resolves PR/head/base, exact-head CI, reviewed head, and Write Gate preconditions. Merge uses the normal GitHub merge path with expected head binding, then reads trunk and merge effect back. An old review, advisory result, API success response, or checkpoint alone is never merge evidence.
