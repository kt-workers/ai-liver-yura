# Loop Autonomous Runner

## One-transition command

`python -m tools.loop_engine` performs one bounded control-plane transition:

`Preflight → Observe → Reconcile → Resume Gate → Select → Plan/Execute/Wait/Integrate → Readback → Checkpoint`

It is neither a product runtime service nor a polling daemon. Pending CI, human verification, credential, Project, or provider work produces a typed `YIELD_EXTERNAL`; the next explicit run re-observes GitHub live state.

## Ports and execution boundary

The deterministic Core keeps `MissionSupervisor`, typed snapshots, Resume/Write gates, and injected executor/verifier/checkpoint ports. The repository also provides an ai-liver-yura host composition that binds these control-plane concepts to `gh`, Codex, and the repository root without moving Loop Engineering into `app/**`.

The host composition treats the latest #450 Mission Checkpoint as a discovery candidate only. Before any Codex start, CI interpretation, Ready transition, merge, Issue close, or checkpoint, it fresh-reads the live Issue/PR/branch/HEAD and rejects a stale checkpoint target. It never treats chat memory as execution authority.

`CodexExecutor` uses a fixed argv and sanitized child environment. It passes no reviewer or database credential, does not shell-interpolate TaskPacket or Mission instruction text, runs from the repository root, and checks the live PR head after child exit. One run may start only one Codex child.

A successful implementer process exit is not execution identity evidence by itself. After the child exits successfully, the trusted host must fresh-read the live PR/branch head and attach that SHA to execution evidence. Verification evidence is accepted only when its exact head is present and matches the execution readback SHA. Missing or mismatched identity is fail-closed and must not advance to integration.

## Host stage routing

For the current Work discovered from #450 and then fresh-resolved:

- no current implementation PR / implementation or CI repair required → invoke Codex once with the bounded Mission/Work target, then fresh-read GitHub and checkpoint the observed result;
- exact current-head CI absent or `queued` / `in_progress` → `YIELD_EXTERNAL` without starting another Codex child;
- exact current-head CI failed → invoke Codex once for the same-lineage functional repair;
- exact current-head CI passed and no known reproducible functional blocker → Ready if needed, normal expected-head merge, merge/trunk readback, Work completion checkpoint;
- stale CI/head/checkpoint identity → fail closed for reconciliation;
- review `REQUEST_CHANGES` / `NOT_RUN` alone → record diagnostic evidence but do not block the functional path under the current Mission policy.

After a Work merge, the host may invoke Codex once in a **planning-only** transition to fresh-read #207/#317/#450/#462 and Project #7, select the next dependency-ready Work, and write the next Mission Checkpoint. That planning transition must not modify product/control-plane code or perform a merge.

## Transition rules

- Resume conflicts generate no implementation TaskPacket and no mutation.
- CI evidence is bound to the expected live head before pending/success/failure classification. Pending/running current-head CI yields; failure returns the same lineage to a repair transition.
- Independent review is diagnostic. Only a deterministic/reproducible functional blocker forces repair; review-provider failure or non-functional hardening does not stop merge.
- Mutation follows fresh precondition → effect → effect readback → checkpoint. Direct implementation write to canonical trunk and Project #6 target are hard rejects.
- Implementer completion → live-head readback → exact-head verification is one identity chain. A process exit code, an old CI result, or a verification result for another SHA cannot advance the transition.
- SIGINT stops accepting new mutation, bounds child termination, and leaves GitHub state sufficient for next-run reconciliation.

## CLI exit semantics

`0` means a completed safe transition, `2` means `YIELD_EXTERNAL`, and `3` means fail-closed intervention/reconciliation. Exit status never upgrades an external API response into effect truth.
