# Loop Autonomous Runner

## One-transition command

`python -m tools.loop_engine` performs one bounded control-plane transition:

`Preflight → Observe → Reconcile → Resume Gate → Select → Plan → Execute → Readback → Checkpoint`

It is neither a product runtime service nor a polling daemon. Pending CI, review, human verification, credential, Project, or provider work produces a typed `YIELD_EXTERNAL`; the next explicit run re-observes GitHub live state.

## Ports and execution boundary

The Runner composes `Observer`, `MissionSupervisor`, `CodexExecutor`, `CIGate`, `ReviewGate`, `IntegrationPort`, checkpoint publisher, and optional operational store ports. Ports accept typed snapshots and return typed evidence. Failures to observe an authority are conflicts, never empty lists.

`CodexExecutor` uses a fixed argv and sanitized child environment. It passes no reviewer, database, or unnecessary GitHub credential, does not shell-interpolate TaskPacket text, and checks worktree/remote live head after child exit. One run may start only one Codex child under the trusted-host execution lease.

A successful implementer process exit is not execution identity evidence by itself. After the child exits successfully, the trusted host must fresh-read the live PR/branch head and attach that SHA to `ExecutionEvidence`. Verification evidence is accepted only when its `exact_head_sha` is present and exactly matches the execution readback SHA. Missing or mismatched identity is a fail-closed `VERIFICATION_HEAD_MISMATCH`; it must not be checkpointed as `VERIFIED` and must not advance to review/merge.

## Transition rules

- Resume conflicts generate no implementation TaskPacket and no mutation.
- CI evidence is exact live PR head/base evidence. Pending/running CI yields; failure returns the same lineage to a fix transition.
- Review is requested once per exact `ReviewTargetKey`; `REQUEST_CHANGES` is a same-lineage fix transition, and only fresh `PASS` reaches merge.
- Mutation follows fresh precondition → effect → effect readback → checkpoint. Direct implementation write to canonical trunk and Project #6 target are hard rejects.
- Implementer completion → live-head readback → exact-head verification is one identity chain. A process exit code, an old CI result, or a verification result for another SHA cannot advance the transition.
- SIGINT stops accepting new mutation, bounds child termination, releases the local lease, and records enough state for next-run reconciliation.

## CLI exit semantics

`0` means a completed safe transition, `2` means `YIELD_EXTERNAL`, and `3` means fail-closed intervention/reconciliation. Exit status never upgrades an external API response into effect truth.
