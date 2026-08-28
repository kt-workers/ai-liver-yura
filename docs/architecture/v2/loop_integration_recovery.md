# Loop Integration and Recovery

## Field-specific source of truth

| Field | Authority |
| --- | --- |
| Issue state | GitHub live Issue |
| PR/head/base | GitHub live PR and branch |
| CI | exact-head GitHub Actions evidence |
| Project Status/Priority/Area/Issue level/Start/Target | Project #7 live |
| Canonical design | repository canonical blob identity |
| Work checkpoint | transition, TaskPacket, health, durable narrative |
| Mission checkpoint | current-work narrative and next action |

Checkpoint data never overwrites Project #7-owned fields. A conflict with a live authority is repaired from live state or fails closed.

## Recovery ordering

Every mutation-capable transition is `fresh observe → WriteIntent → fresh precondition → effect → effect readback → checkpoint → fresh observe`. On timeout or crash, the effect is unknown until the remote target is read back.

One trusted host holds the mutation lease in v1. Concurrent external waits are allowed, but only one actionable mutation transition runs at a time. Multi-host active-active is outside v1.

## Actual host target resolution

The normal Loop CLI uses the **latest** `Mission Checkpoint` comment on #450 as a discovery record and never searches backward for an older apparently-parseable target. A mutation-capable checkpoint must explicitly identify at least `current Work`; when a PR exists it also records `current PR` and the observed exact HEAD.

The checkpoint target is not execution authority. After parsing it, the host fresh-reads the Work Issue and PR/branch HEAD from GitHub before CI interpretation, Codex dispatch, Ready, merge, Issue close, or checkpoint publication. A checkpoint HEAD that differs from the live PR HEAD is stale and blocks mutation until reconciliation.

If the latest Mission Checkpoint is missing an explicit current target, has an invalid target identity, or cannot be reconciled with live GitHub state, the host returns a fail-closed typed result. It must not silently fall back to an older Mission Checkpoint because doing so could execute a previously completed Work.

Planning-only Codex output that selects the next Work must therefore write a new Mission Checkpoint with the explicit current Work/PR/HEAD identity needed by the next host invocation.

## Merge conflict reconciliation

PR mergeability is GitHub live authority and is checked again immediately before any Ready or merge mutation. A PR reported as `mergeable=false` or `mergeable_state=dirty` must not be marked Ready and must not be sent directly to the merge command even when exact-head CI is successful.

A merge conflict is an actionable product-lineage state, not a Human intervention by itself. The host dispatches one bounded Codex functional reconciliation transition. Codex must fresh-read the latest Mission Checkpoint, current Work/PR, current trunk, canonical design, dependency state, and the Work-specific Resume Gate requirements before choosing the repair:

- reconcile the existing lineage by normally merging current trunk into the feature branch and resolving conflicts, or
- when the canonical Resume Gate says the preserved lineage is obsolete, create a new lineage from current trunk and record that identity instead.

Force push and rebase remain prohibited. Codex does not merge the product PR in the reconciliation transition. It updates design/code/tests as required, runs the applicable machine gates, performs a normal push, fresh-reads the new exact HEAD, and records one explicit Mission Checkpoint. The next host invocation re-observes that new state and handles CI/merge normally.

If the expected-head merge command fails for a reason that fresh GitHub readback does **not** identify as a merge conflict, the host keeps the typed `EXPECTED_HEAD_MERGE_FAILED` intervention rather than treating credential, permission, or transport failures as source conflicts.

## Codex host execution contract

The trusted host invokes Codex with an **explicit current CLI contract** instead of depending on the deprecated/compatibility `--full-auto` shortcut.

The default Codex child must be equivalent to:

```text
codex -a never exec --sandbox workspace-write \
  -c sandbox_workspace_write.network_access=true <instruction>
```

This is required because Loop Engineering needs both:

- workspace writes for design/code/test/branch work inside the target checkout
- outbound network access for `gh` read/write operations against GitHub live state

`codex --version` alone is not sufficient evidence that this execution contract is usable. The actual pilot must prove that the child can execute the required bounded transition. A CLI syntax incompatibility, effective read-only sandbox, or unavailable network that prevents the child from performing the assigned transition is a functional blocker, not a review-hardening concern.

`LOOP_CODEX_COMMAND_JSON` may override the default command for a trusted host, but the override is responsible for preserving the same minimum capabilities and secret boundary. Reviewer credentials remain excluded from the Codex child.

## Runtime observability contract

The normal CLI must never appear silently hung during a bounded transition, but default terminal output must remain readable. Human-visible progress, detailed diagnostics, and machine-readable completion output use separate channels:

- default stderr shows only concise lifecycle events: startup, log path, major stage entry, Codex dispatch/completion, failures, and final result
- repetitive successful GitHub/API child command start/done events and raw Codex output are written to the persistent run log but are hidden from the default terminal
- `--verbose` enables the detailed child-command and raw Codex stream on stderr for live diagnosis
- stdout remains reserved for the final `HostTransitionResult` JSON so scripts can parse the terminal result deterministically
- every run persists the full safe child output under `logs/loop_engine/`, regardless of terminal verbosity
- logs must not print secret values, `.env` content, reviewer credentials, database credentials, full sanitized environments, or full argv containing prompt/secret-like values

A failure must identify the stage and exit/result code on the default terminal and point to the persistent log for full evidence. Observability is part of actual-host operability, but observability must not flood the operator console with routine low-level traffic.

## #471 bootstrap and pilot completion

PR #477 is the bootstrap implementation that makes the actual host Loop executable. Merging PR #477 is **not** #471 completion evidence by itself. After #477 reaches trunk, #471 remains open and the host selects an actual dependency-ready V2 product Work as the pilot.

The post-bootstrap planning transition treats #471 and #462 as orchestration/integration state, not pilot candidates. It must select a **V2 product Work/Integration** that is dependency-ready under GitHub live state and Project #7. Issues whose work identity is Loop Engineering infrastructure (`loop-engineering` responsibility) are excluded from the actual product pilot. The planner must not select #471 itself merely because #471 remains open while pilot evidence is pending.

If no dependency-ready V2 product Work exists, the planner records a typed external/dependency wait instead of fabricating a pilot or closing #471.

#471 may be completed only after the installed trunk Loop has driven at least one actual V2 product Work through the applicable bounded stages without a human copying TaskPackets/review findings, with exact-head CI/merge identity and restart-safe GitHub checkpoints. The pilot Work's own completion and #471 integration completion are distinct records.

Therefore the host completion path special-cases #471 bootstrap: merge/readback #477, keep #471 open, and perform a planning-only selection of the actual V2 product pilot Work. Ordinary Work issues may be closed after their own successful expected-head merge/readback.

## Exact-head CI ordering

CI evidence is first bound to the expected current head, then interpreted by lifecycle status. If an observed workflow run belongs to another head, the result is `STALE` even when that old run is still `queued` or `in_progress`. An old-head pending run must never yield the current Work as if its CI were legitimately pending.

Only after `evidence.head_sha == expected_head_sha` is established may `queued` / `in_progress` become `YIELD_EXTERNAL`, `success` become `PASS`, or another terminal conclusion become `FAILED`.

## Wait and completion

`CI_PENDING`, `REVIEW_PENDING`, `HUMAN_VERIFICATION_PENDING`, credential, provider, Project, and database outages are typed waits. Independent actionable Work may proceed; otherwise the runner yields without busy retry.

A review wait or provider-side `NOT_RUN` is not a completion blocker by itself. Review findings are blocking only when deterministic or reproducible evidence establishes a functional failure under the current Mission policy.

`MISSION_COMPLETE` requires explicit Root #317, required Work/Integration, human/system verification, runtime boot/continuous/restart/graceful-shutdown, and zero functional blocking conflicts. Zero candidates or one merged Work is insufficient.

## E2E acceptance

The integration suite covers new Work to normal merge, functional repair, pending yield/resume, stale CI/review rejection, crash recovery after push/review/merge, DB degradation, Project #7 outage, Project #6 reject, self-improvement dedupe, SIGINT, competing lineage stop, and false-completion prevention.

Controlled fake-port integration is necessary but not sufficient for #471 completion. The repository must also provide a host composition reachable from the normal Loop CLI so that the real Preflight/Observe/Supervisor/Implementer/Verify/Checkpoint boundaries can execute one bounded transition without a human copying a TaskPacket or review finding between agents.
