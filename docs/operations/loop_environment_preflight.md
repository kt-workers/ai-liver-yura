# Loop Environment & Capability Preflight

Issue #463 implements the bootstrap gate for Loop Engineering (#462).  It
checks the execution environment before a work lineage is selected; it does
not mutate GitHub Projects or start an OpenAI request.

## Authority and boundaries

- GitHub Issue, PR, and Project #7 are live-state authorities.  Cached field
  identifiers are never an input to this command.
- Project #7 is the only Project this command may inspect.  It never invokes a
  Project mutation command and never addresses Project #6.
- Every invocation performs all three Project #7 read probes (`view`,
  `field-list`, and `item-list`), including after a Codex/VS Code restart.
  They are not cached from a previous successful run.
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
| Project #7 write | GraphQL `viewerCanUpdate` read-only query | bootstrap blocking |
| OpenAI reviewer | trusted host brokerへのbounded health request | work scoped |
| PostgreSQL client | `psql --version` | work scoped |
| PostgreSQL server / database | `pg_isready`, then `SELECT 1` using secret-only process environment | work scoped |
| PostgreSQL migration | `alembic current` only when `alembic.ini` exists | work scoped |
| Toolchain | project Python/venv, pytest, Ruff, Mypy, compileall, Codex CLI | bootstrap blocking |

The Project write result is a fresh, side-effect-free GitHub permission query.
It is not an injected test flag, cached field ID, or mutation. The controlled
#462/#463 Project #7 mutation remains independent historical evidence.

`LOOP_DATABASE_URL` is used only to derive `PG*` variables for child probes;
it is never included in a command argument, result, or diagnostic. #463
verifies migration *capability* when a migration configuration exists. It does
not create the Loop Operational Store schema or apply a migration: those belong
to the later operational-store implementation under #462.

## Restart verification

Before #463 can be completed, start a fresh minimal process with only the
credential injection supplied by the Codex environment and run the GitHub and
Project #7 read probes.  It must succeed without `gh auth login`,
`gh auth refresh`, or any interactive action.  This verifies credential
injection into a new process; it does not mutate a Project.

## macOS host launcher

Run `python scripts/launch-codex-v2.py` from the repository host. The launcher
never reads `.env` directly. An approved host-side environment loader injects
`GH_TOKEN` before launch; the launcher passes it only to the GitHub/VS Code
child environment, derives Goal version/generation/SHA-256 from the canonical
file, retains PATH for Homebrew tooling, and launches VS Code. It neither
prints nor persists a credential. After VS Code creates a fresh Codex process,
run normal Preflight; no manual `export`, `gh auth login`, or `gh auth refresh`
is part of the flow.

## Trusted host independent reviewer

The optional canonical review is deliberately separate from normal Preflight.
Its complete authority boundary is [Trusted Host Reviewer Boundary](../architecture/v2/trusted_host_reviewer_boundary.md).

The target checkout never imports a reviewer client or receives
`OPENAI_API_KEY_REVIEWER`. It may receive only the non-secret
`YURA_TRUSTED_REVIEWER_SOCKET`, and Preflight uses that path for a bounded
health request. The trusted host broker, outside every target checkout, owns
credential validation, model lookup, bounded Responses API health check, live
PR identity/diff retrieval, review invocation, and result validation. It must
independently bind and recheck the exact HEAD, return `NOT_RUN` for a stale
target, and never pass GitHub write or database credentials to the reviewer.

The launcher uses only the host-injected `GH_TOKEN` for GitHub/VS Code. It
does not read `.env`, retrieve reviewer credentials, or start reviewer code.
