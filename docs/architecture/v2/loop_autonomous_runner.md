# Loop Autonomous Runner

## Continuous host command

`python -m tools.loop_engine` is the trusted-host **continuous Mission runtime**. Each internal control-plane transition remains bounded:

`Preflight → Observe → Reconcile → Resume Gate → Select → Plan/Execute/Wait/Integrate → Readback → Checkpoint`

The process does not stop merely because one safe transition completed. After `COMPLETED`, it fresh-observes GitHub and starts the next bounded transition automatically. This preserves one-transition mutation safety while removing the requirement for a human to repeatedly re-run the command.

`python -m tools.loop_engine --once` retains the diagnostic one-transition behavior.

The continuous runtime may wait and automatically re-observe **machine-resolvable current-head CI pending state** at a coarse bounded interval. This is not permission to busy-poll review, Human Verification, credential, provider, or other external conditions. Those conditions continue to produce typed `YIELD_EXTERNAL` and terminate the current runtime when no independent actionable Work is available.

Codex execution has **no fixed wall-clock kill timeout**. A long but live Codex child remains attached to the current bounded transition and emits heartbeat progress while running. The old fixed 30-minute kill boundary is prohibited because task duration is not failure evidence and would convert legitimate long-running implementation into an operator-monitoring requirement. Explicit process failure, launch failure, SIGINT, or other deterministic failure remains fail-closed.

`python -m tools.loop_engine --validate-installation` is the non-mutating installation smoke path. The CLI prints secret-safe transition progress to stderr and structured transition results to stdout.

## Ports and execution boundary

The deterministic Core keeps `MissionSupervisor`, typed snapshots, Resume/Write gates, and injected executor/verifier/checkpoint ports. The repository also provides an ai-liver-yura host composition that binds these control-plane concepts to `gh`, Codex, and the repository root without moving Loop Engineering into `app/**`.

The host composition treats the latest #450 Mission Checkpoint as a discovery candidate only. It does not search backward for an older parseable checkpoint. The latest checkpoint must explicitly state `current Work`; a PR-backed Work also states `current PR` and exact HEAD. Missing or invalid current target identity is fail-closed and cannot dispatch Codex or mutate GitHub.

Planning-only Codex output is part of this machine-readable contract. Every selected next Work checkpoint must contain the literal field `- current Work: #<issue>`. When an active PR exists, it must also contain `- current PR: #<pr>` and `- exact HEAD: <40-hex-sha>`. Narrative aliases such as `選択した次Work:` do not replace these fields. A Work with no active PR omits PR/HEAD rather than inventing them.

Known safe observation failures are surfaced with their typed cause instead of being collapsed into an opaque status. In particular, an invalid latest checkpoint is reported as `GITHUB_OBSERVE_FAILED:MISSION_CHECKPOINT_TARGET_UNRESOLVED`; credentials, transport, invalid JSON, and incompatible GitHub response shape remain separately classifiable safe diagnostics without exposing secrets.

Before any Codex start, CI interpretation, Ready transition, merge, Issue close, or checkpoint, the host fresh-reads the live Issue/PR/branch/HEAD and rejects a stale checkpoint target. It never treats chat memory as execution authority.

`CodexExecutor` uses a fixed argv and sanitized child environment. It passes no reviewer or database credential, does not shell-interpolate TaskPacket or Mission instruction text, runs from the repository root, and checks the live PR head after child exit. One bounded transition may start only one Codex child.

A successful implementer process exit is not execution identity evidence by itself. After the child exits successfully, the trusted host must fresh-read the live PR/branch head and attach that SHA to execution evidence. Verification evidence is accepted only when its exact head is present and matches the execution readback SHA. Missing or mismatched identity is fail-closed and must not advance to integration.

## Host stage routing

For the current Work discovered from #450 and then fresh-resolved:

- no current implementation PR / implementation or CI repair required → invoke Codex once with the bounded Mission/Work target, then fresh-read GitHub and checkpoint the observed result;
- exact current-head CI absent or `queued` / `in_progress` → `YIELD_EXTERNAL` from that bounded transition; continuous CLI may wait and fresh-reobserve current-head CI without operator intervention;
- exact current-head CI failed → invoke Codex once for the same-lineage functional repair;
- exact current-head CI passed and no known reproducible functional blocker → Ready if needed, normal expected-head merge, merge/trunk readback, Work completion checkpoint;
- stale CI/head/checkpoint identity → fail closed for reconciliation;
- review `REQUEST_CHANGES` / `NOT_RUN` alone → record diagnostic evidence but do not block the functional path under the current Mission policy.

After a Work merge, the next bounded transition may invoke Codex once in a **planning-only** transition to fresh-read #207/#317/#450/#462 and Project #7, select the next dependency-ready Work, and write the next Mission Checkpoint. That planning transition must not modify product/control-plane code or perform a merge, and its checkpoint must explicitly identify the next current Work/PR/HEAD for the following transition.

## Continuous runtime rules

- `COMPLETED` → immediately fresh-observe and continue to the next bounded transition.
- `YIELD_EXTERNAL / CI_PENDING` → in continuous mode, wait at a coarse interval and fresh-observe again; no mutation occurs during the wait.
- other `YIELD_EXTERNAL` → stop the process cleanly unless a separate dependency-ready Work was already selected by the scheduler.
- `INTERVENTION_REQUIRED` → stop fail-closed with the typed reason and log path.
- Mission completion → terminate normally only when Root #317 completion evidence satisfies the canonical completion contract.
- `--once` → return after exactly one bounded transition regardless of the above continuation rules.

A continuous host runtime is not permission for same-head review polling. Review pending, Human Verification, credentials, provider recovery, and equivalent external waits retain their explicit no-busy-poll rules.

## Transition rules

- Resume conflicts generate no implementation TaskPacket and no mutation.
- CI evidence is bound to the expected live head before pending/success/failure classification. Pending/running current-head CI yields; failure returns the same lineage to a repair transition.
- Independent review is diagnostic. Only a deterministic/reproducible functional blocker forces repair; review-provider failure or non-functional hardening does not stop merge.
- Mutation follows fresh precondition → effect → effect readback → checkpoint. Direct implementation write to canonical trunk and Project #6 target are hard rejects.
- Implementer completion → live-head readback → exact-head verification is one identity chain. A process exit code, an old CI result, or a verification result for another SHA cannot advance the transition.
- SIGINT stops accepting new mutation, terminates the current child under the existing graceful-shutdown boundary, and leaves GitHub state sufficient for next-run reconciliation.

## CLI exit semantics

For `--once`, `0` means a completed safe transition, `2` means `YIELD_EXTERNAL`, and `3` means fail-closed intervention/reconciliation.

For the default continuous runtime, intermediate completed transitions do not cause process exit. Final exit uses the same typed semantics when the runtime reaches a non-auto-resumable yield, intervention, or Mission completion. Exit status never upgrades an external API response into effect truth.
