# Loop Engineering Design Completion Matrix

## Purpose

This matrix is the implementation authority for Loop Engineering under #462.
It deliberately separates development control-plane code in `tools/loop_engine/`
from the AI Liver product runtime in `app/`.

| Area | Canonical artifact | Owning work | Completion contract |
| --- | --- | --- | --- |
| A: environment | `docs/operations/loop_environment_preflight.md` | #463 / #469 | Capability checks and host launch are product-independent. |
| B: supervisor | `loop_mission_supervisor.md`, `loop_self_improvement.md` | #465 | Observe, reconcile, select, plan, and write-gate are deterministic. |
| C: canonical review | `loop_canonical_review_pipeline.md` | #472 | A trusted host broker binds a structured result to a live exact head. |
| D: operational memory | `loop_operational_store.md` | #470 | PostgreSQL retains execution evidence only; it never becomes GitHub authority. |
| E: runner | `loop_autonomous_runner.md` | #467 | One bounded transition connects Observe through Checkpoint. |
| F: integration and recovery | `loop_integration_recovery.md` | #471 | Recovery, wait, lease, and end-to-end acceptance are explicit. |

## Cross-cutting invariants

- GitHub live Issue, PR, branch, Actions, and Project #7 are current-state authority. Repository canonical blobs are design authority. Checkpoints and PostgreSQL are durable operational evidence, not replacements for either.
- Project #6 is a hard deny target. No Loop Engine command may read or mutate it.
- `app/**` never imports `tools.loop_engine`; Loop Engineering is not product runtime infrastructure.
- Credentials, provider payloads, request bodies, prompts, and diffs are not stored in the repository, checkpoints, or ordinary diagnostics.
- A normal run performs at most one mutation-capable transition. It does not busy-poll external work.

## Design completion verdict

The C/D/E/F contracts below cover all #462 completion responsibilities. Their implementation is independently owned by #467, #470, #472, and #471. A Work is not complete merely because no candidate is visible: Root #317 completion, required verification, and runtime lifecycle evidence remain mandatory.
