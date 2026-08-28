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

## Wait and completion

`CI_PENDING`, `REVIEW_PENDING`, `HUMAN_VERIFICATION_PENDING`, credential, provider, Project, and database outages are typed waits. Independent actionable Work may proceed; otherwise the runner yields without busy retry.

`MISSION_COMPLETE` requires explicit Root #317, required Work/Integration, human/system verification, runtime boot/continuous/restart/graceful-shutdown, and zero blocking conflicts. Zero candidates or one merged Work is insufficient.

## E2E acceptance

The integration suite covers new Work to normal merge, review and CI repair, pending yield/resume, stale review rejection, crash recovery after push/review/merge, DB degradation, Project #7 outage, Project #6 reject, self-improvement dedupe, SIGINT, competing lineage stop, and false-completion prevention.
