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
