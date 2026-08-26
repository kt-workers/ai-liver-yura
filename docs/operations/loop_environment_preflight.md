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
| OpenAI reviewer | configured-model lookup + bounded Responses API health request | work scoped |
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

Run `python scripts/launch-codex-v2.py` from the repository host. It reads the
`yura-codex-github` Keychain item only into VS Code's child environment, derives
Goal version/generation/SHA-256 from the canonical file, retains PATH for
Homebrew tooling, and launches VS Code. It neither writes a token to disk nor
prints one. After VS Code creates a fresh Codex process, run normal Preflight;
no manual `export`, `gh auth login`, or `gh auth refresh` is part of the flow.

## One-shot independent reviewer

The optional canonical review is deliberately separate from normal Preflight.
Run it only after live PR/CI identity has been verified:

```text
python scripts/launch-codex-v2.py \
  --canonical-review-pr 464 \
  --expected-head <exact-current-head-sha>
```

For this mode only, the launcher reads the distinct Keychain service
`yura-openai-reviewer`. The key is passed solely to the reviewer subprocess.
That subprocess receives an explicit environment containing only `PATH`,
`OPENAI_API_KEY`, the repository-owned reviewer model/config, and non-secret
review context on stdin. It receives neither `GH_TOKEN`/`GITHUB_TOKEN`, any
GitHub write credential, database credential, nor inherited parent secrets.

Before starting, the launcher reads the live PR and rejects an expected/head
mismatch as `NOT_RUN` / `STALE_TARGET`. The reviewer performs configured-model
lookup plus a bounded Responses API health request before the bounded review
request. A missing Keychain item returns `NOT_RUN` /
`OPENAI_CREDENTIAL_UNAVAILABLE`; it does not consume a review attempt. After
the subprocess returns, the launcher rereads the live PR head and discards any
result as `STALE_TARGET` if it changed. The only emitted result is bounded
JSON with `review_status`, target SHA, verdict, and sanitized findings; no
credential, raw provider response, request header, or command stderr is
printed or persisted.
