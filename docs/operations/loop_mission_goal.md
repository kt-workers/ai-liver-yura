# Loop Engineering Mission Goal

version: 1.0
generation: 1

Complete Root #317 through Mission #450 and Parent #462 from GitHub live state.
Never embed a fixed PR or HEAD: obtain current state from #450 and GitHub live.

- Project #7 is V2 authority; never mutate Project #6.
- Pass a fresh Resume Gate before selecting work.
- Bind independent review to an exact HEAD and reject stale results.
- A review wait is not a Mission stop condition; continue independent work or yield without polling.

## Restore and verification

This file is the Repository source for Codex `/Goal`. On session start load it into `/Goal` and set
`CODEX_MISSION_GOAL_GENERATION=1` in the Codex launch environment. Preflight rejects a missing or
mismatched generation. To restore a lost `/Goal`, copy this file verbatim, then rerun Preflight.
