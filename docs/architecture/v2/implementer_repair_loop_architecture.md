# Implementer Repair Loop Architecture

Status: Canonical design for Issue #372  
Parent: #369  
Depends on: #370, #371  
Root: #317  
Area: Development Tooling  
Effective: 2026-08-13

Related canonical:

- `docs/architecture/v2/independent_ai_review_architecture.md`
- `docs/architecture/v2/review_orchestrator_implementation.md`
- `docs/architecture/v2/review_orchestrator_runtime_race_guards.md`

## 1. Purpose

Issue #372 closes the automatic repair half of the Independent AI Review loop.

A trusted `ReviewDecision(CHANGES_REQUESTED)` for an exact PR head SHA is converted by the Orchestrator into a trusted, auditable `RepairRequest`. A local Codex Implementer Worker consumes that request, repairs the same implementation lineage, validates the result, commits and pushes a new head SHA, and thereby causes the existing Independent AI Review workflow to review the new SHA.

No human copies review findings from GitHub into the Implementer prompt between cycles.

```text
Implementation PR @ H0
        |
        v
Independent Gemini Review @ H0
        |
        +-- PASS ------------------------------> Merge Gate (#373)
        |
        +-- BLOCKED ---------------------------> stop / blocker resolution
        |
        `-- CHANGES_REQUESTED
                |
                v
        Trusted RepairRequest @ H0
                |
                v
        Local Codex Implementer Worker
                |
        preflight / repair / validation
                |
                v
        regular fast-forward push H0 -> H1
                |
                v
        existing `synchronize` trigger
                |
                v
        Independent Gemini Review @ H1
                |
                `-- repeat boundedly
```

GitHub remains the durable handoff/audit bus. Local worker memory is never the sole source of repair state.

## 2. Role separation

### 2.1 Implementer

Initial implementation backend:

`LocalCodexWorker`

Identity contract:

```text
role = IMPLEMENTER
provider = openai-codex
agent_id = yura-local-codex-implementer
session_id = repair:<repair_token>:<local_run_id>
credential_scope = IMPLEMENTATION_WRITE
```

The local Codex worker may edit the authorized implementation worktree. It does not create trusted ReviewDecision objects, write the Independent Review status, or approve/merge its own work.

### 2.2 Primary Reviewer

Existing #371 Gemini Reviewer remains the primary independent Reviewer.

```text
role = REVIEWER
provider = google-gemini
agent_id = yura-independent-reviewer-gemini
credential_scope = REVIEW_WRITE
```

It never receives the Implementer write credential.

### 2.3 Secondary Reviewer

GitHub Codex Review remains a secondary independent review lane. #372 does not make its GitHub UI behavior the trusted RepairRequest authority because its delivery/persistence contract is outside this repository's Orchestrator control.

#373 may require both review lanes at the final Merge Gate.

### 2.4 Orchestrator

The trusted GitHub-side review runtime owns:

- `ReviewDecision` validation;
- RepairRequest construction;
- repair token generation;
- duplicate/max-cycle policy;
- trusted request persistence.

The local worker owns deterministic execution of an already-authorized RepairRequest, not the authority to invent one.

## 3. Deployment architecture

### 3.1 Do not attach arbitrary PR workflows to the local machine

This repository is public. A persistent user machine must not act as a general-purpose self-hosted runner for arbitrary repository/PR workflow definitions.

The MVP therefore does **not** use `pull_request` jobs targeted at a local self-hosted runner.

Instead:

```text
GitHub trusted control plane
  Independent Review runtime
          |
          | CHANGES_REQUESTED only
          v
  PR Review COMMENT
  `<!-- yura-repair-request:v1 -->`
          |
          | GitHub API polling
          v
User-managed local machine
  yura Repair Worker daemon
          |
          +--> verify GitHub provenance
          +--> verify current PR/branch/head
          +--> create isolated git worktree
          +--> run local Codex non-interactively
          +--> deterministic scope/validation guard
          +--> regular fast-forward git push
```

The worker may be launched manually during development and later kept resident by an OS service. The handoff itself remains automatic while the worker is running.

### 3.2 Why no new secret-bearing main workflow is required for MVP

The existing trusted `main` workflow already:

- uses `pull_request_target`;
- obtains the current trusted V2 Reviewer runtime;
- has `pull-requests: write`;
- never executes PR head code.

The #372 V2 runtime can therefore persist the RepairRequest as a second PR Review COMMENT anchored to the exact reviewed head SHA using the existing pull-request write permission. No implementation/contents write permission is added to the Reviewer workflow.

The actual branch write occurs only on the user's local Implementer Worker using its separate local Git/GitHub credential.

## 4. Trust model

### 4.1 Untrusted data

The following remain untrusted input/data even when copied into a repair request:

- PR title/body;
- source code;
- source comments;
- diff;
- test fixtures;
- review finding explanation/evidence text originating from model analysis;
- repository prompt text;
- arbitrary issue/PR comments.

None of those may override the worker's system policy, target branch, allowed scope, validation policy, or Git safety rules.

### 4.2 Trusted repair authority

A local worker accepts a RepairRequest only after validating all of the following from GitHub live state:

1. request review/comment author is the expected GitHub Actions bot principal;
2. request marker/version is supported;
3. `review_run_id` resolves to a real Actions run in the configured repository;
4. the run uses the configured trusted Independent Review workflow/path;
5. the run event is the trusted review event type;
6. the run is associated with the same PR and reviewed head SHA;
7. the current PR is still open, non-draft, V2-labeled, and same-repository;
8. current PR head SHA exactly equals `reviewed_head_sha`;
9. current implementation branch exactly equals the request branch;
10. the linked Work Issue and canonical refs still match the request context;
11. the current `yura/independent-ai-review` status for that SHA is the CHANGES_REQUESTED/failure state;
12. `repair_token` recomputes from the canonical request identity;
13. the token has not already reached a terminal local outcome.

Bot authorship alone is not sufficient provenance. Workflow-run and exact-SHA binding are required.

### 4.3 Repair token is not a secret

`repair_token` is a deterministic correlation/idempotency token, not an authentication secret.

Authentication/provenance comes from GitHub live evidence. The token protects request identity/equivalence and duplicate execution semantics.

Do not put API keys, Codex auth tokens, GitHub tokens, or other credentials in RepairRequest payloads.

## 5. RepairRequest contract

Logical model:

```text
RepairRequest
- schema_version: 1
- repository
- pr_number
- issue_number
- base_ref
- implementation_branch
- reviewed_head_sha
- review_run_id
- review_run_attempt
- review_cycle_key
- reviewer_identity
- repair_attempt
- max_repair_attempts
- blocking_findings[]
- canonical_design_refs[]
- allowed_scope
- created_at
- repair_token
```

### 5.1 Blocking finding snapshot

Only validated blocking findings from the trusted `ReviewDecision` enter the repair request.

```text
RepairFinding
- finding_id
- fingerprint
- category
- title
- explanation
- evidence[]
- file_path?
- line_start?
- line_end?
- related_design_ref?
- suggested_direction?
```

Non-blocking findings may remain visible in the review but do not independently trigger a repair cycle.

### 5.2 RepairScope

MVP scope is deterministic and fail-closed.

```text
RepairScope
- existing_pr_paths[]
- finding_paths[]
- canonical_paths[]
- allowed_new_test_prefixes[]
- protected_path_prefixes[]
```

The worker computes/validates the effective allowed set from trusted repository/Issue/PR data. Request text does not grant arbitrary filesystem access.

Default protected control-plane paths include:

- `.github/workflows/`
- `tools/independent_review/`
- Independent Review canonical documents
- repository credential/config paths

A repair may modify such a path only when the linked Work Issue explicitly owns that control-plane area and its canonical/scope includes the path. Product-code repair findings cannot modify Reviewer implementation to make a review pass.

### 5.3 Canonical serialization

RepairRequest is serialized to canonical JSON with sorted keys and stable separators.

`repair_token` is derived from SHA-256 over the canonical request identity excluding the token itself. At minimum the digest binds:

```text
repository
pr_number
issue_number
implementation_branch
reviewed_head_sha
review_run_id
review_cycle_key
repair_attempt
blocking finding IDs + fingerprints
canonical design refs
scope digest
```

Duplicate delivery of the same trusted decision therefore produces the same token.

## 6. GitHub persistence

### 6.1 Review marker

RepairRequest is persisted as a PR Review COMMENT anchored to the reviewed commit.

Marker:

```text
<!-- yura-repair-request:v1 -->
```

Human-readable header:

```text
Repair-Token: `...`
Reviewed-Head-SHA: `...`
Review-Run-ID: `...`
Repair-Attempt: `N/M`
Blocking-Finding-IDs: `...`
```

Machine payload:

```text
Repair-Request-Data: `<base64url(canonical JSON)>`
```

The encoded payload contains no secrets. Encoding prevents Markdown/mention/control-character content inside finding text from becoming GitHub presentation instructions.

### 6.2 Idempotency

Before publishing, the Orchestrator scans existing PR reviews for the same `Repair-Token`.

- same token already persisted -> do not publish a duplicate;
- same reviewed SHA with a different token -> BLOCKED/ESCALATED unless explained by a newer trusted review cycle;
- PASS/BLOCKED decision -> no RepairRequest.

### 6.3 Repair outcome marker

The local worker may persist a separate implementation-side audit comment/review after deterministic completion:

```text
<!-- yura-repair-outcome:v1 -->
Repair-Token: `...`
Outcome: PUSHED | STALE | NO_CHANGE | SCOPE_BLOCKED | VALIDATION_FAILED | FAILED
Old-Head-SHA: `...`
New-Head-SHA: `...`?
Commit-SHA: `...`?
```

This outcome is implementation evidence only. It never grants Review PASS.

## 7. Repair cycle state machine

```text
REVIEWING(Hn)
  |
  +-- PASS ------------------------------> PASS(Hn)
  |
  +-- BLOCKED ---------------------------> BLOCKED(Hn)
  |
  `-- CHANGES_REQUESTED
          |
          v
   REPAIR_REQUESTED(Hn, token N)
          |
          +-- duplicate -----------------> existing token owns execution
          +-- stale ---------------------> STALE / no repair
          +-- max exceeded -------------> ESCALATED
          |
          v
      REPAIRING(Hn)
          |
          v
   REPAIR_VALIDATING(Hn)
          |
          +-- scope violation -----------> ESCALATED/SCOPE_BLOCKED
          +-- validation failure --------> repair failure evidence
          +-- no diff -------------------> NO_CHANGE -> ESCALATED
          |
          v
      REPAIR_PUSHED(Hn -> Hn+1)
          |
          v
  existing synchronize trigger
          |
          v
   REVIEW_PENDING(Hn+1)
```

A repair cycle is not complete until a distinct new head SHA exists.

## 8. Bounded cycle / recurrence policy

MVP defaults:

```text
max_repair_attempts = 3
```

Configuration may lower the value but may not make the loop unbounded.

Attempt calculation is based on trusted RepairRequest history for the PR lineage, not worker-local counters.

For each new CHANGES_REQUESTED decision:

- collect blocking finding fingerprints;
- compare with prior repair requests;
- preserve recurring fingerprint history in audit metadata;
- if the next repair attempt exceeds the configured maximum -> do not mint a new executable request; persist ESCALATED evidence instead.

Repeated findings are diagnostic evidence. The hard automatic stop is the bounded cycle limit; #373 may add an earlier recurrence threshold after E2E data.

## 9. Local Codex Worker

### 9.1 Process model

Repository-side command:

```text
python -m tools.repair_loop.worker --watch
```

Modes:

- `--once`: perform one poll/execution iteration;
- `--watch`: continue polling with a configured interval while the process is running.

The worker is intended for a user-managed trusted machine, not GitHub-hosted untrusted PR execution.

### 9.2 Local prerequisites

- clone of the repository or configured repository root;
- `git` with push access to authorized implementation branches;
- GitHub API read access sufficient to verify PR/review/workflow/status evidence;
- local Codex CLI already authenticated by the user;
- Python runtime for the worker.

Credentials remain on the local machine and are never embedded in the GitHub repair request.

### 9.3 Isolated worktree

The worker never edits the user's arbitrary current checkout in place.

For each token:

1. fetch the configured remote;
2. verify remote implementation branch == `reviewed_head_sha`;
3. create a temporary isolated worktree from that exact commit;
4. run Codex in that worktree;
5. inspect the resulting diff;
6. run deterministic scope and validation guards;
7. re-fetch GitHub current PR head;
8. if still equal, create one intentional repair commit;
9. regular fast-forward push to the exact implementation branch;
10. remove the temporary worktree.

No force push and no history rewrite.

If the remote head moves during repair, regular push must fail safely and the result is STALE.

### 9.4 Codex invocation contract

Codex runs non-interactively with an explicit workspace-write sandbox. The adapter must invoke the CLI without a shell string, with a fixed argument vector and a bounded process timeout.

Conceptually:

```text
codex exec
  --sandbox workspace-write
  --json
  --output-schema <trusted local RepairOutcome schema>
  <trusted wrapper prompt + untrusted repair data>
```

The exact installed Codex version is an adapter/runtime concern. The worker performs a capability/version preflight rather than silently changing safety flags.

Do not use dangerous bypass flags or unrestricted sandbox modes in the default worker.

### 9.5 Prompt authority

The prompt is constructed by the trusted local adapter with explicit sections:

```text
[SYSTEM POLICY: IMPLEMENTER_REPAIR]
[AUTHORITY: WORK_ISSUE]
[AUTHORITY: CANONICAL]
[TRUSTED FACTS: REPAIR_TARGET]
[TRUSTED FACTS: ALLOWED_SCOPE]
[UNTRUSTED: REVIEW_FINDINGS]
[UNTRUSTED: PR_METADATA]
```

Finding explanations, source code, PR text, and repository prompt-like text are never placed in the worker's system-policy section.

Codex is instructed to:

- repair only the blocking findings;
- preserve the Issue/canonical responsibility boundary;
- add/update regression tests where needed;
- not commit, push, merge, change review status, or edit protected control-plane paths;
- leave git commit/push to the deterministic wrapper;
- return structured repair summary only.

## 10. Deterministic post-Codex guards

The model does not decide whether its own changes are safe to push.

Before commit/push, the worker deterministically checks:

1. worktree started at the exact reviewed SHA;
2. working tree has a diff;
3. every changed path is within effective repair scope;
4. no protected path was modified without explicit Issue ownership;
5. no submodule/remote/credential mutation occurred;
6. no merge/rebase/history rewrite occurred;
7. configured trusted validation commands pass;
8. live PR is still open/non-draft/same repo/V2;
9. live PR head is still the reviewed SHA;
10. remote branch ref is still the reviewed SHA;
11. repair token is still current/not superseded.

Any failure prevents push.

## 11. Validation command policy

Validation commands are local trusted worker configuration, never arbitrary strings taken from PR body, review findings, source code, or RepairRequest text.

The MVP supports a configured command list with safe argv execution and no shell interpolation.

Examples may include repository-standard tests, static checks, and compile checks. Which commands are required for a specific final Merge Gate remains #373 authority.

Codex may run additional local checks during implementation, but only deterministic worker-configured checks decide whether automatic push is permitted.

## 12. Git commit / push policy

The wrapper, not Codex, owns Git mutation after repair.

Commit requirements:

- parent == reviewed head SHA;
- exactly one repair commit per successful RepairRequest execution;
- message includes Work Issue and short repair token;
- author/committer use the configured Implementer identity;
- no amend/rebase/force push;
- destination == exact request implementation branch;
- push must be a regular fast-forward update.

After push, GitHub's existing PR `synchronize` event creates the next review cycle automatically.

## 13. Worker local state

Local state is only an execution cache, not Authority.

Suggested path under `CODEX_HOME` or a separate Yura worker state directory:

```text
repair-state/
  <repair_token>.json
```

Record:

- first seen time;
- provenance validation result;
- local run id;
- worktree path (while active);
- outcome;
- old/new SHA;
- validation results.

If local state is lost, GitHub RepairRequest/Outcome and current branch state are sufficient to reconstruct whether a token is still executable.

## 14. Concurrency and stale guards

### 14.1 Per-PR single-flight

Only one RepairRequest for a PR may be actively executed by a worker at a time.

Local worker uses a per-repository/per-PR lock. A second process seeing the same token defers or exits without mutation.

### 14.2 New review supersedes old repair

If a new PR head or newer trusted RepairRequest exists before push, the old repair becomes stale.

Old worktree changes may be retained locally for diagnostics but are never pushed automatically onto the newer branch state.

### 14.3 Worker crash

A crash does not implicitly retry a push. On restart, the worker revalidates GitHub provenance/current head before resuming or discarding the request.

## 15. GitHub client extensions

Trusted review-side client needs only additional review/read operations required to:

- count/find existing RepairRequest markers;
- persist a RepairRequest review comment.

It must **not** gain contents/branch write APIs.

Local worker uses a separate GitHub adapter/credential for:

- PR/read review/status/workflow provenance;
- remote branch/head validation;
- optional RepairOutcome persistence.

Review-side and implementation-side credentials are never reused across adapters.

## 16. Code layout

Planned MVP layout:

```text
tools/
├── independent_review/
│   ├── orchestrator.py          # invokes handoff after trusted decision
│   ├── github_client.py         # review-side read/review-write only
│   └── ...
└── repair_loop/
    ├── __init__.py
    ├── models.py                # RepairRequest / scope / outcome
    ├── token.py                 # canonical serialization + token
    ├── handoff.py               # ReviewDecision -> RepairRequest
    ├── persistence.py           # repair request marker/idempotency
    ├── provenance.py            # local GitHub live verification
    ├── scope.py                 # deterministic changed-path guard
    ├── codex_adapter.py         # non-interactive local Codex
    ├── git_workspace.py         # isolated worktree/commit/push guard
    ├── worker.py                # --once / --watch entrypoint
    └── schemas/
        └── repair_outcome.schema.json

tests/tools/repair_loop/
    ...
```

Network/process/Git operations remain behind narrow adapters so state-machine and safety behavior can be unit-tested with fakes.

## 17. Integration with ReviewOrchestrator

The handoff executes only **after** a trusted `ReviewDecision` is constructed and final head-stale validation has succeeded.

Order:

```text
Provider candidate
  -> deterministic review validation
  -> final current-head validation
  -> persist ReviewDecision
  -> if CHANGES_REQUESTED:
       build deterministic RepairRequest
       apply bounded-cycle/idempotency checks
       persist RepairRequest PR Review
```

If ReviewDecision persistence fails, no repair request is published.

If RepairRequest persistence fails, the review remains CHANGES_REQUESTED but automatic repair is considered BLOCKED infrastructure state; it must not be reported as a successful closed loop.

PASS/BLOCKED decisions never invoke the Implementer.

## 18. Tests

### 18.1 Unit

At minimum:

- CHANGES_REQUESTED + blocking findings -> RepairRequest;
- PASS -> no request;
- BLOCKED -> no request;
- token deterministic for same cycle;
- changed finding/head -> different token;
- duplicate token -> one persisted request;
- max cycle -> ESCALATED/no executable request;
- exact branch/head/Issue/canonical binding;
- untrusted finding text cannot change trusted request fields;
- request base64 payload round-trip;
- unsafe/protected path rejected;
- list alias/path traversal/symlink-style scope attacks rejected;
- stale PR head prevents worker execution;
- workflow-run provenance mismatch prevents worker execution;
- duplicate local process/token does not double push;
- Codex no-diff -> no push;
- validation failure -> no push;
- remote head movement -> no push;
- successful repair -> one commit and regular fast-forward push;
- repair outcome does not create Review PASS.

### 18.2 Fake adjacent E2E

Using Fake GitHub + Fake Codex + Fake Git:

```text
H0 review -> CHANGES_REQUESTED
-> RepairRequest(token1)
-> worker repair
-> H1 push
-> simulated synchronize
-> PASS(H1)
```

Also verify:

- H0 changes while worker is repairing -> stale/no push;
- same finding repeats until configured maximum -> ESCALATED;
- protected path edit -> SCOPE_BLOCKED;
- two workers receive same token -> one mutation only.

### 18.3 Live Verification

Live Verification requires a deliberately controlled V2 test PR with a known repairable blocking defect.

1. local worker is started on the user's machine;
2. Gemini returns CHANGES_REQUESTED on exact H0;
3. trusted RepairRequest appears automatically;
4. local worker accepts provenance/token/current-head checks;
5. local Codex changes only authorized files;
6. deterministic local validation passes;
7. wrapper pushes H1 without force;
8. existing Independent AI Review automatically runs on H1;
9. defect is fixed and review reaches PASS, or another bounded repair request is produced;
10. full H0 -> finding -> token -> H1 -> review evidence remains inspectable in GitHub.

Actual local-machine/Codex execution is a Verification-stage gate. Repository-side implementation can be unit/fake-E2E complete before that manual environment prerequisite is available.

## 19. Failure / escalation policy

Automatic repair stops and records an explicit outcome on:

- untrusted/invalid request provenance;
- stale PR head/branch mismatch;
- linked Issue/canonical mismatch;
- worker/Codex unavailable;
- Codex timeout;
- no repair diff;
- protected/out-of-scope changed files;
- deterministic validation failure;
- push rejection/non-fast-forward;
- duplicate/conflicting active repair;
- max repair attempts exceeded.

The worker never resolves those cases with force push, widened sandbox, ignored tests, Reviewer modification, or merge.

## 20. Done boundary

Issue #372 implementation is complete when:

- trusted CHANGES_REQUESTED automatically persists a deterministic RepairRequest;
- local worker can discover and provenance-validate requests without human copy/paste;
- local Codex adapter can perform bounded workspace-write repair in an isolated worktree;
- deterministic scope/stale/validation guards gate commit/push;
- successful repair creates a new fast-forward implementation head;
- existing `synchronize` review automatically starts on the new head;
- duplicate/stale/max-cycle cases fail closed;
- reviewer and implementer identities/credentials stay separate;
- Fake E2E covers the full repair loop.

Live local-Codex E2E is then moved through Project Verification. #373 owns final Required Checks / multi-review Merge Gate / optional Auto Merge integration.
