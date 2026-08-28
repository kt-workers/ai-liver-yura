# Loop Canonical Review Pipeline

## Boundary

`LoopCanonicalReviewGate` is an independent diagnostic reviewer for Loop Engineering changes. It is distinct from `OptionalReviewSupport`, but under the current Mission policy a review verdict alone is not a merge blocker. Functional completion is prioritized over review perfection.

The provider client and `OPENAI_API_KEY_REVIEWER` exist only in a trusted host control-plane process outside the target checkout. Codex and target checkout receive, at most, the non-secret `YURA_TRUSTED_REVIEWER_SOCKET`. The broker has no GitHub write or database credential and never imports or executes target checkout code.

## Identity and state machine

1. The caller supplies repository, PR number, and expected head only.
2. The broker read-only resolves the live PR, base ref/SHA, head SHA, and canonical blob set. Any mismatch is `NOT_RUN / STALE_TARGET`.
3. `ReviewTargetKey` hashes the repository, PR, live head, policy generation, model policy, canonical blob identity, and review-context identity.
4. The durable allocator reserves a monotonically increasing `ReviewAttemptKey` before one provider invocation. A used key is never sent again, including after a crash. Gaps are valid and never backfilled.
5. The broker writes a secret-safe provider outcome before terminal verdict normalization. Result is accepted only after a second live-head readback.

Terminal verdicts are `PASS`, `REQUEST_CHANGES`, or `ESCALATE`. Refusal, incomplete output, transport failure, invalid structure, timeout, stale target, and unavailable capability are typed `NOT_RUN`; they do not masquerade as a canonical verdict.

## Result contract and functional-blocker policy

The provider uses Structured Outputs with a strict bounded schema. The trusted broker, not the provider, attaches reviewed head/base, policy identity, request identity, and reviewer identity. Findings remain diagnostic evidence and raw provider output is never persisted.

A `REQUEST_CHANGES` verdict does not by itself stop completion. A finding becomes a functional blocker only when it is corroborated by deterministic tests, CI, an exact live-state readback, or a reproducible execution path showing that the Loop cannot start/progress, operates on the wrong exact target, loses a required effect, or otherwise fails its required runtime behavior. Such a blocker returns the same lineage to design/fix/test.

Non-functional hardening, additional auditability, stricter metadata validation, hypothetical race defense, or other findings that do not prevent required behavior are recorded and may be deferred. `NOT_RUN`, including provider failure, does not block a Work when machine gates and required functional evidence pass. Reviewer infrastructure is not hardened merely to obtain a cleaner verdict.

## Merge gate

Before Ready or merge, the Runner re-resolves PR/head/base, required exact-head machine gates, functional completion evidence, and Write Gate preconditions. Merge uses the normal GitHub merge path with expected head binding, then reads trunk and merge effect back.

A current review result may contribute diagnostic evidence but is not required to manufacture a PASS. Merge is prohibited when there is a known reproducible functional blocker, stale exact-target evidence, failed required machine gate, or failed Write Gate. An old review, API success response, or checkpoint alone is never effect truth.
