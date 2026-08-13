# Implementer Repair Loop Architecture

Status: Proposed canonical design for Issue #372  
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

A trusted `ReviewDecision(CHANGES_REQUESTED)` for an exact PR head SHA becomes a trusted, auditable `RepairRequest`. A user-managed local Codex worker consumes only a RepairRequest that is cryptographically content-addressed and **bound to the exact trusted Independent Review workflow run that produced it**. The worker repairs the same implementation lineage, performs fail-closed scope/stale validation, executes PR-controlled tests only inside a credentialless validation sandbox, and then performs one regular fast-forward push. The existing PR `synchronize` trigger starts review of the new head.

No human copies review findings from GitHub into the Implementer prompt between cycles.

```text
Implementation PR @ H0
        |
        v
Trusted Independent Gemini Review run R0 @ H0
        |
        +-- PASS ------------------------------> Merge Gate (#373)
        |
        +-- BLOCKED ---------------------------> stop / blocker resolution
        |
        `-- CHANGES_REQUESTED
                |
                v
        canonical RepairRequest bytes
        written by trusted reviewer runtime
                |
                +--> trusted run R0 artifact  <--- AUTHORITY
                |
                `--> PR Review index          <--- DISCOVERY ONLY
                         |
                         v
                Local Codex Worker
                         |
                  provenance preflight
                         |
                    repair worktree
                         |
                    scope guard
                         |
             credentialless validation sandbox
                         |
                  live stale re-check
                         |
                         v
              regular fast-forward H0 -> H1
                         |
                         v
               existing synchronize trigger
                         |
                         v
                Independent Review @ H1
```

GitHub is the durable handoff/audit bus. Local worker memory is never repair Authority.

## 2. Role and credential separation

### 2.1 Implementer

Initial backend: `LocalCodexWorker`.

```text
role = IMPLEMENTER
provider = openai-codex
agent_id = yura-local-codex-implementer
session_id = repair:<repair_token>:<local_run_id>
credential_scope = IMPLEMENTATION_WRITE
```

The worker may edit and fast-forward the authorized implementation branch. It cannot create trusted Review PASS, write the Independent Review status as success, approve, or merge.

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

GitHub Codex Review remains a secondary review lane. Its GitHub UI comments/reactions are not RepairRequest Authority because that persistence/provenance contract is outside the trusted Orchestrator implemented by this repository.

#373 owns the final rule for combining Gemini, Codex, ordinary CI, unresolved threads, and optional auto merge.

### 2.4 Orchestrator

The trusted GitHub-side runtime owns:

- trusted ReviewDecision validation;
- RepairRequest construction;
- scope snapshot construction;
- repair token/digest generation;
- bounded-attempt policy;
- writing canonical RepairRequest bytes to a known trusted-runtime output path;
- publishing a human-readable PR Review index only after normal ReviewDecision persistence succeeds.

The local worker executes an already-authorized request. It never invents repair Authority from model text or PR comments.

## 3. Ordered two-phase implementation lineage

The V2 Reviewer runtime and the secret-bearing/default-branch control plane are separate trust domains. #372 therefore uses the same **sequential two-stage lineage pattern** established by #371.

Never keep Phase A and Phase B as parallel active implementation lineages.

### 3.1 Phase A — V2 runtime and local worker

Base: `rebuild/v2-foundation`

Outputs:

- this design;
- provider-neutral RepairRequest models/token/scope logic;
- trusted review-side handoff generation;
- artifact payload file generation interface;
- PR Review discovery index persistence;
- local provenance verifier;
- local Codex adapter;
- isolated git worktree wrapper;
- validation sandbox abstraction and safe container backend;
- unit/fake E2E tests.

Phase A does not modify `main` workflow control-plane files.

After review/static/fake-E2E gates pass, Phase A is merged into `rebuild/v2-foundation`. A Resume Checkpoint records its final head/merge SHA before Phase B begins.

### 3.2 Phase B — trusted artifact publishing control plane

Begins **only after Phase A is merged**.

Base: current `main`.

Expected scope: `.github/workflows/independent-ai-review.yml` only, unless a separately reviewed trusted workflow helper is explicitly required.

The workflow adds a pinned artifact-upload action/step that:

- executes only in the trusted `pull_request_target` workflow;
- uploads only the known RepairRequest output file produced in the checked-out trusted Reviewer runtime;
- runs after the Reviewer step even when CHANGES_REQUESTED intentionally makes that step/job fail;
- never checks out or executes PR head/merge code;
- does not add `contents: write` or implementation-branch write permission;
- names the artifact using trusted run/head metadata;
- uses bounded retention appropriate for live repair pickup.

Phase B is reviewed/merged to `main`, then Live Verification starts with a controlled V2 test PR and a running local worker.

## 4. Public-repository local-machine boundary

This repository is public. A persistent user machine must not become a general-purpose GitHub self-hosted runner for arbitrary PR-controlled workflows.

MVP therefore does **not** use `pull_request` jobs targeted at the local machine.

The local worker is a separate user-managed process:

```text
python -m tools.repair_loop.worker --watch
```

It polls GitHub for candidate RepairRequest indexes, then independently verifies the authoritative workflow-run artifact before any local code mutation.

The local machine's GitHub/Codex credentials never enter GitHub Actions artifacts, PR comments, model prompts, or validation containers.

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
- request_digest
- repair_token
```

Only validated blocking findings from the trusted ReviewDecision enter an executable request.

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

Finding prose remains untrusted model-generated repair data. It cannot override repository/branch/head/scope/policy fields.

## 6. Canonical serialization, digest, and token

The Orchestrator serializes RepairRequest content as canonical UTF-8 JSON:

- sorted keys;
- stable separators;
- no NaN/Infinity;
- bounded field/list sizes;
- no secret material.

`request_digest` is SHA-256 of canonical request bytes before the digest/token fields are inserted, using a precisely specified serialization procedure.

`repair_token` is a deterministic idempotency/correlation value derived from trusted request identity and the digest. It is **not an authentication secret**.

At minimum the identity binds:

```text
repository
pr_number
issue_number
implementation_branch
reviewed_head_sha
review_run_id
review_run_attempt
review_cycle_key
repair_attempt
blocking finding IDs + fingerprints
canonical refs
scope digest
request_digest
```

Changing the reviewed SHA, finding set, scope, run identity, or request bytes changes the digest/token.

## 7. Trusted run artifact is the RepairRequest Authority

### 7.1 Why PR Review text is not sufficient Authority

Different GitHub Actions workflows can post as the same `github-actions[bot]` principal when granted pull-request write permission. Therefore:

- bot authorship alone is insufficient;
- a valid referenced run ID alone is insufficient;
- a recomputable token over comment-controlled bytes alone is insufficient.

A malicious or unrelated workflow must not be able to manufacture executable repair instructions merely by posting a look-alike marker.

### 7.2 Authority rule

The **canonical RepairRequest bytes uploaded as an artifact of the exact trusted Independent Review workflow run are the sole executable RepairRequest Authority**.

The trusted Reviewer runtime writes the request to a fixed relative output path, conceptually:

```text
reviewer-runtime/.yura/repair-request.json
```

Only a trusted CHANGES_REQUESTED decision creates this file. PASS/BLOCKED/internal-error paths must leave it absent.

The main trusted workflow uploads that exact path as an Actions artifact in Phase B.

A GitHub artifact belongs to its creating workflow run. Another workflow may create its own artifact but cannot retroactively attach bytes to an already-existing trusted Independent Review run. The local worker therefore binds executable request bytes to the actual trusted run that produced them.

### 7.3 Artifact identity

Artifact name is deterministic from trusted runtime metadata, conceptually:

```text
yura-repair-request-<run_id>-<reviewed_head_sha>
```

The worker requires:

- exact expected run ID;
- exact trusted workflow ID/path;
- trusted event type;
- expected repository;
- expected PR association;
- exact reviewed head SHA;
- exactly one acceptable RepairRequest artifact for the cycle;
- expected artifact name;
- not expired/deleted;
- bounded archive/file size;
- exactly one expected regular file after safe extraction;
- no symlink/hardlink/path traversal/archive bomb behavior;
- canonical JSON digest/token verification after extraction.

Missing/expired/ambiguous/malformed artifact means fail closed. There is no fallback to trusting the PR comment payload.

### 7.4 PR Review is discovery/index only

The Orchestrator also persists a PR Review COMMENT anchored to the reviewed commit:

```text
<!-- yura-repair-request:v1 -->
Repair-Token: `...`
Request-Digest: `sha256:...`
Reviewed-Head-SHA: `...`
Review-Run-ID: `...`
Review-Run-Attempt: `...`
Artifact-Name: `...`
Repair-Attempt: `N/M`
Blocking-Finding-IDs: `...`
```

This index:

- makes requests discoverable by a polling worker;
- is human-readable audit evidence;
- contains no executable request payload and no secrets;
- is never sufficient by itself to authorize repair.

The worker treats index fields as candidate lookup hints and checks them against the authoritative artifact bytes/live run metadata.

## 8. Trusted provenance verification

Before creating a worktree, the local worker verifies all of the following from GitHub live state:

1. candidate index marker/version is supported;
2. referenced `review_run_id` exists in the configured repository;
3. run workflow ID/path is the configured trusted Independent Review workflow;
4. run event is the configured trusted review event;
5. run attempt matches the request/index;
6. run is associated with the same PR and exact reviewed head SHA;
7. the authoritative artifact belongs to that exact run and passes Section 7 checks;
8. canonical artifact JSON recomputes the advertised digest/token;
9. artifact repository/PR/head/branch/Issue/run fields agree with live trusted metadata;
10. PR is still open, non-draft, same-repository, and V2-labeled;
11. current PR head equals `reviewed_head_sha`;
12. current implementation branch equals the request branch;
13. remote implementation branch ref equals `reviewed_head_sha`;
14. linked Work Issue/canonical refs still match live Issue scope;
15. `yura/independent-ai-review` for the exact SHA is the CHANGES_REQUESTED/failure state;
16. token is not superseded or already terminal locally/GitHub-side;
17. bounded-attempt policy still allows execution.

Any mismatch returns STALE/BLOCKED and performs no model/Git mutation.

## 9. Repair scope and protected paths

MVP scope is deterministic and fail-closed.

```text
RepairScope
- existing_pr_paths[]
- finding_paths[]
- canonical_paths[]
- allowed_new_test_prefixes[]
- protected_path_prefixes[]
```

The trusted Orchestrator computes the scope from GitHub/Issue/canonical data. Finding prose does not grant paths.

Default protected control-plane prefixes include:

- `.github/workflows/`
- `tools/independent_review/`
- Independent Review canonical documents
- credential/config paths
- worker security policy/configuration paths

A repair may touch a protected path only when the linked Work Issue explicitly owns that control-plane area and the computed scope authorizes it. Product-code findings cannot modify Reviewer logic to make review pass.

Path validation resolves normalized repository-relative paths and rejects:

- absolute paths;
- `..` traversal;
- symlink escape;
- nested repository/submodule escape;
- unexpected new files outside approved prefixes.

Scope is checked immediately after Codex and again immediately before commit.

## 10. Repair state machine and bounded cycles

```text
REVIEWING(Hn)
  |
  +-- PASS ------------------------------> PASS(Hn)
  +-- BLOCKED ---------------------------> BLOCKED(Hn)
  `-- CHANGES_REQUESTED
          |
          v
   REPAIR_REQUEST_CREATED(Rn,Hn)
          |
          v
   ARTIFACT_PUBLISHED(Rn,Hn)
          |
          +-- duplicate -----------------> same token owns execution
          +-- stale ---------------------> STALE / no repair
          +-- max exceeded -------------> ESCALATED
          |
          v
      REPAIRING(Hn)
          |
          v
      SCOPE_CHECKED
          |
          v
   REPAIR_VALIDATING_SANDBOXED
          |
          +-- sandbox unavailable -------> VALIDATION_BLOCKED
          +-- scope violation -----------> SCOPE_BLOCKED
          +-- validation failure --------> VALIDATION_FAILED
          +-- no diff -------------------> NO_CHANGE / ESCALATED
          |
          v
      LIVE_STALE_RECHECK
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

MVP default:

```text
max_repair_attempts = 3
```

Attempt history comes from trusted run/artifact/index history for the PR lineage, not from a resettable in-memory counter. Exceeding the maximum creates non-executable ESCALATED evidence.

## 11. Local Codex worker

### 11.1 Modes

```text
python -m tools.repair_loop.worker --once
python -m tools.repair_loop.worker --watch
```

`--watch` is a polling loop while the user-managed process is running. A later OS service may keep it resident, but repository design does not depend on ChatGPT/background execution.

### 11.2 Local prerequisites

- configured clone/repository root;
- `git` with push access to the authorized implementation branch;
- GitHub read access for PR/review/run/artifact/status provenance;
- optional GitHub comment/review write access for RepairOutcome audit only;
- local Codex CLI already authenticated by the user;
- supported container runtime for deterministic validation;
- trusted worker configuration stored outside PR-controlled files or otherwise pinned to a trusted local/base source.

Credentials remain on the host and are not copied into repair worktrees, artifacts, or validation sandboxes.

### 11.3 Isolated worktree

For each accepted token:

1. fetch remote;
2. verify remote implementation branch == reviewed SHA;
3. create temporary isolated worktree from exact SHA;
4. run Codex in that worktree;
5. inspect diff;
6. run first deterministic scope/protected-path guard;
7. snapshot the repaired tree into a validation input that excludes `.git` and credentials;
8. run deterministic validation in `ValidationSandbox`;
9. re-run scope/protected-path guard on the real worktree;
10. re-fetch PR/current remote head/token status;
11. if still exact, create one intentional repair commit;
12. regular fast-forward push to exact branch;
13. remove temporary worktree/sandbox data.

No amend/rebase/force push/history rewrite.

## 12. Codex invocation boundary

Codex runs non-interactively with an explicit bounded workspace-write sandbox. The adapter invokes a fixed argument vector without shell interpolation and a process timeout.

Conceptually:

```text
codex exec
  --sandbox workspace-write
  --json
  --output-schema <trusted local schema>
  <trusted wrapper prompt + untrusted repair data>
```

The adapter preflights installed capability/version. The default worker does not use dangerous bypass flags or unrestricted sandbox modes.

Prompt authority is separated:

```text
[SYSTEM POLICY: IMPLEMENTER_REPAIR]
[AUTHORITY: WORK_ISSUE]
[AUTHORITY: CANONICAL]
[TRUSTED FACTS: REPAIR_TARGET]
[TRUSTED FACTS: ALLOWED_SCOPE]
[UNTRUSTED: REVIEW_FINDINGS]
[UNTRUSTED: PR_METADATA]
```

Codex is instructed to edit only; it must not commit, push, merge, write review status, broaden scope, or modify protected review infrastructure outside authorized Issue ownership.

Codex-run tests are implementation hints only. They are never the deterministic automatic-push Authority.

## 13. Credentialless ValidationSandbox

### 13.1 Threat model

Tests, build scripts, compiler plugins, package hooks, and static-analysis extensions at the repaired PR head are PR-controlled executable code. Running them directly in the credential-bearing local worker process would expose host files, Git/Codex credentials, network, sockets, or other local capabilities.

Therefore **no PR-controlled validation command executes directly in the worker host process**.

### 13.2 Interface

```text
ValidationSandbox
- prepare(snapshot, trusted_config)
- run(argv[]) -> ValidationResult
- dispose()
```

The backend is provider-neutral. MVP provides a container backend suitable for the user's trusted local environment.

### 13.3 Trusted validation image/config

Validation image, image digest, resource limits, command argv, timeouts, and sandbox policy come only from trusted local worker configuration or another trusted base source. They are not selected by:

- PR Dockerfiles;
- PR compose files;
- PR body;
- finding text;
- repair artifact model prose;
- repository scripts that attempt to change sandbox configuration.

Production/live automatic mode requires the configured image to be pinned by immutable digest. Missing/unavailable safe backend means `VALIDATION_BLOCKED`; the worker never falls back to host execution.

### 13.4 Validation input

The worker copies/snapshots the repaired repository content into disposable sandbox input.

Do not mount the credential-bearing worktree's `.git` directory into the container. Do not expose host credentials, agent sockets, Docker/container-engine sockets, or arbitrary host directories.

Validation may modify only the disposable sandbox copy. The actual repair worktree remains outside the validation container.

### 13.5 Minimum container isolation

The default safe profile requires at least:

- no GitHub token/environment credential;
- no Codex auth / `CODEX_HOME`;
- no SSH agent/socket;
- no Docker/container-engine socket;
- no host home mount;
- no `.git` metadata from the host worktree;
- network disabled;
- read-only container root filesystem;
- explicit disposable writable workspace/tmpfs only where required;
- dropped Linux capabilities;
- `no-new-privileges`;
- bounded CPU/memory/process/time limits;
- fixed working directory;
- fixed argv execution without host shell interpolation.

The sandbox must not be able to push Git, call GitHub, invoke the host Codex credential, or mutate the host worktree.

### 13.6 Dependencies and offline validation

Because network is disabled, required validation dependencies must already exist in the trusted validation image or trusted prebuilt cache/image. The automatic repair loop does not dynamically `pip install`, `npm install`, or fetch untrusted dependencies from the Internet during the privileged local repair transaction.

Dependency/image refresh is a separate trusted maintenance action, not something PR data can request.

### 13.7 Validation result authority

Only deterministic worker-configured commands executed inside the safe ValidationSandbox authorize an automatic push.

Examples include trusted-configured test, lint, type, compile, and repository invariant commands. #373 owns which exact checks are final Merge Gate requirements.

## 14. Deterministic post-Codex / pre-push guards

The wrapper checks, in order:

1. authoritative artifact provenance and digest/token;
2. worktree parent == exact reviewed SHA;
3. non-empty repair diff;
4. first scope/protected-path guard;
5. no remote/submodule/credential-policy mutation;
6. ValidationSandbox available and safe-profile preflight passes;
7. all configured sandbox validation commands pass;
8. second scope/protected-path guard on actual worktree;
9. PR still open/non-draft/same-repo/V2;
10. live PR head == reviewed SHA;
11. remote implementation branch == reviewed SHA;
12. token remains current/not superseded;
13. no conflicting active local execution;
14. commit parent still equals reviewed SHA.

Any failure prevents commit/push.

## 15. Git commit and push policy

The deterministic wrapper, not Codex, owns Git mutation after repair.

Successful automatic repair creates exactly one commit:

- parent == reviewed head SHA;
- message references Work Issue and short repair token;
- configured Implementer author/committer identity;
- exact authorized implementation branch;
- no amend/rebase/merge/force push;
- regular fast-forward push only.

If remote head moved, normal push fails and outcome is STALE. Worker does not retry by rebasing its generated patch onto the newer head automatically.

The resulting GitHub PR `synchronize` event starts the next Independent Review automatically.

## 16. Persistence and idempotency

### 16.1 Request discovery index

Before publishing a new index, the Orchestrator checks trusted request history for the same token.

- same trusted token/run/digest already indexed -> no duplicate;
- same reviewed SHA with conflicting executable request identities -> BLOCKED/ESCALATED;
- PASS/BLOCKED -> no request artifact/index.

### 16.2 Local state

Local state is an execution cache only, e.g.:

```text
repair-state/<repair_token>.json
```

It may record first-seen time, local run ID, provenance result, outcome, old/new SHA, validation summary, and temporary paths.

Loss of local state does not create new Authority; GitHub trusted run/artifact/current branch state determines whether a request is executable.

### 16.3 Repair outcome

The worker may publish implementation-side audit evidence:

```text
<!-- yura-repair-outcome:v1 -->
Repair-Token: `...`
Outcome: PUSHED | STALE | NO_CHANGE | SCOPE_BLOCKED | VALIDATION_BLOCKED |
         VALIDATION_FAILED | FAILED | ESCALATED
Old-Head-SHA: `...`
New-Head-SHA: `...`?
Commit-SHA: `...`?
```

This is not Reviewer Authority and can never create PASS.

## 17. Concurrency and stale guards

- per-repository/per-PR local lock: one active repair execution;
- duplicate delivery of same token: one mutation at most;
- newer PR head/request supersedes older request;
- current-head checks occur before worktree creation and again immediately before commit/push;
- worker restart revalidates GitHub artifact/current state; it does not blindly resume a pending push;
- old local patches may be retained only for diagnostics, never automatically transplanted onto a newer head.

## 18. Code layout

Phase A planned layout:

```text
tools/
├── independent_review/
│   ├── orchestrator.py          # invokes handoff after trusted decision
│   ├── persistence.py           # normal review + request discovery index
│   ├── main.py                  # trusted request output path lifecycle
│   └── ...
└── repair_loop/
    ├── __init__.py
    ├── models.py
    ├── token.py
    ├── handoff.py
    ├── persistence.py
    ├── artifact.py
    ├── provenance.py
    ├── scope.py
    ├── codex_adapter.py
    ├── validation.py
    ├── container_validation.py
    ├── git_workspace.py
    └── worker.py

tests/tools/repair_loop/
    ...
```

Network, process, container, and Git operations remain behind narrow adapters so state-machine and security behavior can be tested with fakes.

## 19. Integration order with Independent Review

Review-side order:

```text
Provider candidate
  -> deterministic ReviewDecision validation
  -> final head-stale validation
  -> persist ReviewDecision
  -> if CHANGES_REQUESTED:
       build deterministic RepairRequest
       enforce max-cycle/idempotency policy
       write canonical request bytes to fixed trusted output path
       persist discovery/index Review
  -> workflow uploads fixed output path as run artifact (Phase B)
```

If normal ReviewDecision persistence fails, no RepairRequest is produced.

If request construction/index persistence/artifact publication fails, review remains CHANGES_REQUESTED but the automatic repair infrastructure is BLOCKED. It must never be reported as a successful closed repair loop.

PASS/BLOCKED do not create executable RepairRequest bytes.

## 20. Unit and fake-E2E acceptance

At minimum Phase A tests cover:

- CHANGES_REQUESTED + validated blocking findings -> canonical RepairRequest;
- PASS/BLOCKED -> no request;
- same trusted cycle -> deterministic bytes/digest/token;
- changed head/finding/scope/run -> changed digest/token;
- request output absent on non-repair paths;
- duplicate token -> one index;
- max cycle -> ESCALATED/no executable request;
- untrusted finding text cannot alter trusted target/scope fields;
- artifact archive path traversal/symlink/size/ambiguity rejection;
- artifact run/workflow/PR/head mismatch rejection;
- forged PR Review index with no matching trusted artifact rejection;
- valid index but artifact digest/token mismatch rejection;
- stale current PR/remote head rejection;
- protected/out-of-scope path rejection;
- two workers on same token -> at most one mutation;
- Codex no-diff -> no push;
- ValidationSandbox unavailable -> no host fallback/no push;
- sandbox command failure -> no push;
- container command builder excludes host credentials/network/sockets;
- validation snapshot excludes `.git` and host credential paths;
- remote head movement after validation -> no push;
- successful repair -> one regular fast-forward commit/push;
- RepairOutcome never creates Review PASS.

Fake adjacent E2E:

```text
H0 review -> CHANGES_REQUESTED
-> trusted run artifact request(token1)
-> worker provenance PASS
-> Codex repair
-> scope PASS
-> sandbox validation PASS
-> H1 fast-forward push
-> simulated synchronize
-> PASS(H1)
```

Also cover stale H0, forged index, malicious alternate-workflow index, protected-path edit, validation sandbox escape configuration rejection, duplicate worker, and bounded repeated finding escalation.

## 21. Live Verification

Live Verification begins only after Phase A and Phase B are merged.

Use a deliberately controlled V2 test PR with a known repairable defect.

1. user starts the local worker in the trusted local environment;
2. Gemini produces CHANGES_REQUESTED on exact H0;
3. trusted workflow run produces authoritative RepairRequest artifact and PR discovery index;
4. local worker verifies run/artifact/digest/token/current head;
5. local Codex changes only allowed files in isolated worktree;
6. scope guard passes;
7. credentialless/networkless validation container passes configured checks;
8. live stale guard still sees H0;
9. wrapper pushes one fast-forward H1 commit;
10. existing Independent Review runs automatically on H1;
11. loop reaches PASS or another bounded RepairRequest;
12. GitHub audit evidence can reconstruct H0 -> run -> artifact digest/token -> H1 -> next review.

Also perform a negative Live Verification where a look-alike PR marker without the trusted run artifact is rejected, and where the validation backend is unavailable and automatic push fails closed.

## 22. Failure and escalation policy

Automatic repair stops without push on:

- invalid/missing/expired/ambiguous trusted artifact;
- artifact/index/run digest or identity mismatch;
- stale PR/remote head/branch mismatch;
- Issue/canonical mismatch;
- local Codex unavailable/timeout;
- no diff;
- out-of-scope/protected-path changes;
- safe ValidationSandbox unavailable;
- validation failure;
- remote head movement/non-fast-forward push rejection;
- duplicate/conflicting active repair;
- max repair attempts exceeded.

Never recover by:

- trusting comment bytes instead of artifact Authority;
- running PR-controlled tests on the credential-bearing host;
- enabling validation network access as an automatic fallback;
- mounting host credentials or container-engine socket;
- force push/rebase;
- widening Codex sandbox bypass flags;
- modifying Reviewer logic to make the finding disappear;
- merging automatically inside #372.

## 23. Done boundary

### Phase A complete

- RepairRequest models/digest/token/scope implemented;
- trusted Reviewer side writes exact canonical request output for CHANGES_REQUESTED;
- PR discovery index is explicitly non-authoritative;
- local worker verifies run-artifact provenance and exact current head;
- Codex adapter/worktree/scope guards implemented;
- credentialless ValidationSandbox + safe container backend implemented;
- successful fake repair produces one fast-forward new head;
- unit/fake E2E security cases pass;
- Phase A merged to `rebuild/v2-foundation` with Resume Checkpoint.

### Phase B complete

- `main` trusted workflow uploads only the trusted request output as a run-owned artifact using pinned action code;
- no PR head code execution or implementation write permission is introduced;
- workflow behavior for PASS/BLOCKED/no-request is fail-closed;
- Phase B merged to `main` with Resume Checkpoint.

### Issue #372 complete

- controlled live PR demonstrates CHANGES_REQUESTED -> trusted run artifact -> local Codex repair -> credentialless sandbox validation -> fast-forward push -> automatic new-head review;
- forged index without matching trusted artifact is rejected;
- unsafe/unavailable validation sandbox prevents push;
- stale/duplicate/max-cycle paths fail closed;
- Reviewer and Implementer credentials/identities remain separate.

After these gates, #373 owns Required Checks, combined Gemini/Codex/CI Merge Gate, unresolved-review-thread policy, and optional Auto Merge.
