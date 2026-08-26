# Loop Environment & Capability Preflight

Issue #463 implements the bootstrap gate for Loop Engineering (#462).  It
checks the execution environment before a work lineage is selected; it does
not mutate GitHub Projects or start an OpenAI request.

## Authority and boundaries

- GitHub Issue, PR, and Project #7 are live-state authorities.  Cached field
  identifiers are never an input to this command.
- Project #7 is the only Project this command may inspect.  It never invokes a
  Project mutation command and never addresses Project #6.
- A missing reviewer credential, Docker, or PostgreSQL capability is reported
  as work-scoped unavailable.  It is not a Mission-wide stop condition.
- Command output is reduced to a boolean capability result and a stable,
  secret-safe diagnostic code.  It must not expose command output, token
  values, database URLs, or environment values.

## Contract

`python -m app.operations.preflight` emits one JSON object:

```json
{
  "status": "PASS",
  "capabilities": {"github_repo_read": true},
  "blocking_for_loop_bootstrap": [],
  "work_scoped_unavailable": [],
  "diagnostics": []
}
```

`status` is `BLOCKED` when a bootstrap capability is unavailable, `DEGRADED`
when only work-scoped capabilities are unavailable, otherwise `PASS`.

## Checks

| Capability | Evidence command | Classification on failure |
| --- | --- | --- |
| GitHub repository read | `gh repo view` | bootstrap blocking |
| GitHub repository write | `git push --dry-run` | bootstrap blocking |
| Project #7 read | `gh project view`, `field-list`, `item-list` | bootstrap blocking |
| Project #7 write | supplied, independently verified live evidence | bootstrap blocking |
| OpenAI reviewer | `OPENAI_API_KEY` presence only | work scoped |
| Docker / PostgreSQL tooling | `docker version` / `pg_isready --version` | work scoped |

The Project write result is deliberately an injected evidence flag.  A normal
preflight must not alter Project data merely to prove a permission; the
controlled #462/#463 Project #7 mutation and readback is the initial evidence.
