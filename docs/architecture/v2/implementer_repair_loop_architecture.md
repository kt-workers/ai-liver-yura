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

A trusted `ReviewDecision(CHANGES_REQUESTED)` for an exact PR head SHA becomes a trusted, auditable `RepairRequest`. A user-managed local Codex worker consumes only a RepairRequest that is content-addressed and bound to the exact trusted Independent Review workflow run that produced it.

The local worker must keep three security domains separate:

```text
A. Trusted host control plane
   Git / GitHub credentials, request provenance, commit/push authority
   NEVER executes PR-controlled code or model-generated shell commands

B. CodexRepairSandbox
   model-generated reads/writes/commands
   sanitized repair source copy only
   NO host Git/GitHub/SSH/Codex credential visibility
   NO direct access to the real git worktree

C. ValidationSandbox
   PR-controlled tests/build/static-analysis code
   disposable repaired source copy only
   credentialless + networkless
```

After Codex repairs the sanitized source copy, the trusted wrapper transfers only a deterministically validated patch into the real isolated git worktree, validates a second disposable copy, performs a live stale check, creates one commit, and regular-fast-forwards the implementation branch. The existing PR `synchronize` trigger starts review of the new head.

No human copies findings from GitHub into the Implementer prompt between cycles.

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
                |
                +--> trusted run R0 artifact  <--- AUTHORITY
                `--> PR Review index          <--- DISCOVERY ONLY
                         |
                         v
                Trusted Local Worker Host
                         |
                  provenance preflight
                         |
                real isolated git worktree H0
                   (Codex cannot access)
                         |
                sanitized repair source copy
                         |
                         v
                   CodexRepairSandbox
                         |
                    repaired copy
                         |
                    scope/safety diff
                         |
              deterministic patch transfer
                         |
                real isolated git worktree
                         |
                 scope guard again
                         |
                disposable validation copy
                         |
                         v
                 ValidationSandbox
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

The trusted wrapper owns implementation Git mutation. Codex is an editing backend inside `CodexRepairSandbox`; it is not given Git push authority.

The Implementer side cannot create trusted Review PASS, write the Independent Review status as success, approve, or merge.

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

GitHub Codex Review remains a secondary review lane. Its UI comments/reactions are not RepairRequest Authority because that persistence/provenance contract is outside the trusted Orchestrator implemented by this repository.

#373 owns the final rule for combining Gemini, GitHub Codex, ordinary CI, unresolved threads, and optional auto merge.

### 2.4 Orchestrator

The trusted GitHub-side runtime owns:

- trusted `ReviewDecision` validation;
- RepairRequest construction;
- scope snapshot construction;
- repair token/digest generation;
- bounded-attempt policy;
- writing canonical RepairRequest bytes to a known trusted-runtime output path;
- publishing a human-readable PR Review index only after ReviewDecision persistence succeeds.

The local worker executes an already-authorized request. It never invents repair Authority from model text or PR comments.

## 3. Ordered two-phase implementation lineage

The V2 Reviewer runtime and the secret-bearing/default-branch control plane are separate trust domains. #372 therefore uses the same sequential two-stage lineage pattern established by #371.

Never keep Phase A and Phase B as parallel active implementation lineages.

### 3.1 Phase A — V2 runtime and local worker

Base: `rebuild/v2-foundation`

Outputs:

- this design;
- provider-neutral RepairRequest models/token/scope logic;
- trusted review-side handoff generation;
- artifact payload file generation interface;
- PR Review discovery-index persistence;
- local run/artifact provenance verifier;
- `CodexRepairSandbox` abstraction and Codex permission-profile capability preflight;
- sanitized repair-copy / deterministic patch-transfer logic;
- isolated git worktree wrapper;
- `ValidationSandbox` abstraction and safe container backend;
- local Codex adapter;
- unit/fake E2E tests.

Phase A does not modify `main` workflow control-plane files.

After review/static/fake-E2E gates pass, Phase A is merged into `rebuild/v2-foundation`. A Resume Checkpoint records its final head/merge SHA before Phase B begins.

### 3.2 Phase B — trusted artifact publishing control plane

Begins only after Phase A is merged.

Base: current `main`.

Expected scope: `.github/workflows/independent-ai-review.yml` only, unless a separately reviewed trusted workflow helper is explicitly required.

The workflow adds a pinned artifact-upload action/step that:

- executes only in the trusted `pull_request_target` workflow;
- uploads only the known RepairRequest output file produced in the checked-out trusted Reviewer runtime;
- runs after the Reviewer step even when `CHANGES_REQUESTED` intentionally makes that step/job fail;
- never checks out or executes PR head/merge code;
- does not add `contents: write` or implementation-branch write permission;
- names the artifact using trusted run/head metadata;
- uses bounded retention appropriate for live repair pickup.

Phase B is reviewed/merged to `main`, then Live Verification starts with a controlled V2 test PR and a running local worker.

## 4. Public-repository local-machine boundary

This repository is public. A persistent user machine must not become a general-purpose GitHub self-hosted runner for arbitrary PR-controlled workflows.

MVP therefore does not use `pull_request` jobs targeted at the local machine.

The local worker is a separate user-managed process:

```text
python -m tools.repair_loop.worker --watch
```

It polls GitHub for candidate RepairRequest indexes, then independently verifies the authoritative workflow-run artifact before any local code mutation.

The host's GitHub/Git/SSH/Codex credentials remain in the trusted host domain and are excluded from both model-generated tool execution and PR-controlled validation execution.

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

Finding prose remains untrusted model-generated repair data. It cannot override repository/branch/head/scope/sandbox/push-policy fields.

## 6. Canonical serialization, digest, and token

The Orchestrator serializes RepairRequest content as canonical UTF-8 JSON:

- sorted keys;
- stable separators;
- no NaN/Infinity;
- bounded field/list sizes;
- no secret material.

`request_digest` is SHA-256 of canonical request bytes before digest/token fields are inserted, using a precisely specified serialization procedure.

`repair_token` is a deterministic idempotency/correlation value derived from trusted request identity and the digest. It is not an authentication secret.

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

### 7.1 PR Review text is not sufficient Authority

Different GitHub Actions workflows can post as the same `github-actions[bot]` principal when granted pull-request write permission. Therefore:

- bot authorship alone is insufficient;
- a valid referenced run ID alone is insufficient;
- a recomputable token over comment-controlled bytes alone is insufficient.

A malicious or unrelated workflow must not manufacture executable repair instructions merely by posting a look-alike marker.

### 7.2 Authority rule

The canonical RepairRequest bytes uploaded as an artifact of the exact trusted Independent Review workflow run are the sole executable RepairRequest Authority.

The trusted Reviewer runtime writes the request to a fixed relative output path, conceptually:

```text
reviewer-runtime/.yura/repair-request.json
```

Only a trusted CHANGES_REQUESTED decision creates this file. PASS/BLOCKED/internal-error paths leave it absent.

The main trusted workflow uploads that exact path as an Actions artifact in Phase B.

A GitHub artifact belongs to its creating workflow run. Another workflow may create its own artifact but cannot attach bytes retroactively to an already-existing trusted Independent Review run. The worker therefore binds executable request bytes to the actual trusted run that produced them.

### 7.3 Artifact identity

Artifact name is deterministic from trusted runtime metadata, conceptually:

```text
yura-repair-request-<run_id>-<reviewed_head_sha>
```

The worker requires:

- exact expected run ID and attempt;
- exact trusted workflow ID/path;
- trusted event type;
- expected repository/PR association;
- exact reviewed head SHA;
- exactly one acceptable RepairRequest artifact for the cycle;
- expected artifact name;
- not expired/deleted;
- bounded archive/file size;
- exactly one expected regular file after safe extraction;
- no symlink/hardlink/path traversal/archive-bomb behavior;
- canonical JSON digest/token verification after extraction.

Missing/expired/ambiguous/malformed artifact means fail closed. There is no fallback to trusting PR comment payload bytes.

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

The worker treats index fields as candidate lookup hints and checks them against authoritative artifact bytes and live run metadata.

## 8. Trusted provenance verification

Before preparing repair content, the worker verifies all of the following from GitHub live state:

1. candidate index marker/version is supported;
2. referenced run exists in the configured repository;
3. run workflow ID/path is the configured trusted Independent Review workflow;
4. run event is the configured trusted review event;
5. run attempt matches request/index;
6. run is associated with the same PR and exact reviewed head SHA;
7. authoritative artifact belongs to that exact run and passes Section 7 checks;
8. canonical artifact JSON recomputes advertised digest/token;
9. artifact repository/PR/head/branch/Issue/run fields agree with trusted live metadata;
10. PR is still open, non-draft, same-repository, and V2-labeled;
11. current PR head equals `reviewed_head_sha`;
12. current implementation branch equals request branch;
13. remote implementation branch ref equals reviewed SHA;
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

The trusted Orchestrator computes scope from GitHub/Issue/canonical data. Finding prose does not grant paths.

Default protected control-plane prefixes include:

- `.github/workflows/`
- `tools/independent_review/`
- Independent Review canonical documents
- credential/config paths
- repair worker security/sandbox policy paths.

A repair may touch a protected path only when the linked Work Issue explicitly owns that control-plane area and computed scope authorizes it. Product-code findings cannot modify Reviewer logic to make review pass.

Path validation resolves normalized repository-relative paths and rejects:

- absolute paths;
- `..` traversal;
- symlink escape;
- nested repository/submodule escape;
- unexpected new files outside approved prefixes.

Scope is checked on the Codex-produced repair-copy diff and again after patch transfer to the real worktree.

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
   IMPLEMENTER_SANDBOX_PREFLIGHT
          |
          +-- unsafe/unavailable --------> IMPLEMENTER_SANDBOX_BLOCKED
          |
          v
      REPAIRING_COPY(Hn)
          |
          v
      REPAIR_DIFF_SCOPE_CHECKED
          |
          v
      PATCH_TRANSFERRED_TO_REAL_WORKTREE
          |
          v
      REAL_WORKTREE_SCOPE_CHECKED
          |
          v
   REPAIR_VALIDATING_SANDBOXED
          |
          +-- sandbox unavailable -------> VALIDATION_BLOCKED
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

## 11. Local worker host and filesystem domains

### 11.1 Modes

```text
python -m tools.repair_loop.worker --once
python -m tools.repair_loop.worker --watch
```

`--watch` is a polling loop only while the user-managed process is running. A later OS service may keep it resident, but repository design does not depend on ChatGPT/background execution.

### 11.2 Local prerequisites

- configured clone/repository root;
- `git` with push access to the authorized implementation branch;
- GitHub read access for PR/review/run/artifact/status provenance;
- optional GitHub comment/review write access for RepairOutcome audit only;
- local Codex CLI already authenticated by the user;
- a Codex/runtime/platform combination that can enforce the required read/write/deny filesystem policy for model-generated tool execution;
- supported container runtime for deterministic ValidationSandbox;
- trusted worker configuration stored outside PR-controlled files or pinned to a trusted local/base source.

Credentials remain on the trusted host. They are never copied into GitHub artifacts, repair copies, Codex tool-readable roots, model prompts, or validation sandboxes.

### 11.3 Real isolated git worktree

For each accepted request, the trusted wrapper:

1. fetches remote;
2. verifies remote implementation branch == reviewed SHA;
3. creates a temporary isolated git worktree from exact SHA;
4. verifies its parent/head and repository identity;
5. keeps this real worktree inaccessible to Codex tool execution;
6. uses it later only as trusted patch target, deterministic validation source, commit parent, and push source.

The real worktree contains `.git` linkage/metadata needed by the trusted wrapper, so it is not the Codex editing workspace.

### 11.4 Sanitized Codex repair copy

The wrapper creates a separate disposable repair source copy from the exact reviewed tree.

The copy:

- contains only repository source content required for the authorized repair;
- excludes `.git`, `.git` pointer files, worker state, host config, credentials, sockets, and unrelated repository siblings;
- materializes symlinks/path metadata according to deterministic safety rules and rejects escaping links;
- is owned by the repair token/local run;
- is disposable after patch extraction;
- is the only project tree Codex may read/write.

Codex never receives the path of the real git worktree.

## 12. CodexRepairSandbox

### 12.1 Threat model

Repository instructions, source code, tests, and finding prose are untrusted. Prompt labels reduce instruction confusion but are not a filesystem confidentiality boundary.

A model-generated shell command must not be able to read host GitHub credentials, SSH keys, Codex authentication storage, shell histories, unrelated repositories, cloud credentials, or other user files and copy those bytes into an otherwise allowed source file.

Therefore legacy/broad-read `workspace-write` behavior alone is **not accepted for unattended automatic repair**.

### 12.2 Interface

```text
CodexRepairSandbox
- probe_capabilities(trusted_config) -> CapabilityReport
- self_test(canary, trusted_config) -> SandboxSelfTestResult
- run(repair_copy, trusted_prompt, trusted_config) -> CodexRepairResult
- dispose()
```

The backend is provider-neutral. MVP uses local Codex only when installed Codex + OS sandbox capabilities can prove the required read isolation.

### 12.3 Filesystem permission profile

The worker generates Codex filesystem/sandbox policy from trusted local configuration, not repository/PR content.

Required effective policy:

- repair source copy: read + write;
- only minimal platform/runtime/tool roots needed for Codex command execution: read-only;
- real git worktree: not readable;
- repository siblings: not readable;
- host home except explicitly necessary non-secret runtime roots: not readable;
- GitHub/Git credential stores: deny read;
- SSH keys/config/agent sockets: deny read/not exposed;
- Codex auth/config storage used by the core process: deny read to model-generated tool commands;
- cloud credential directories and common secret files: deny read;
- worker state/config: deny read;
- arbitrary temporary/shared roots: deny unless explicitly required and isolated.

The exact Codex configuration syntax is a runtime-adapter detail because supported permission-profile syntax/platform backends may change. The adapter compiles a desired abstract `RepairFilesystemPolicy` into the installed Codex/runtime representation and fails closed when it cannot express/enforce it.

### 12.4 Codex authentication vs tool-process access

The trusted Codex process may need its own user authentication to contact the Codex service. That does not authorize model-generated subprocesses/tools to read authentication storage or inherit authentication environment variables.

The worker therefore requires both:

- filesystem read-deny/read-allow enforcement around model-generated tool execution; and
- shell/tool environment filtering.

The adapter must never solve Codex authentication by placing API keys/tokens into the repair prompt or into a shell environment visible to model-generated commands.

### 12.5 Shell/tool environment policy

Model-generated command environment starts from a trusted minimal allowlist, not the full worker environment.

At minimum it must not expose values or sockets associated with:

- GitHub/GH tokens;
- OpenAI/Codex/API credentials;
- SSH agent/auth sockets;
- AWS/Azure/GCP/cloud credentials;
- password/secret/token/key environment variables;
- container-engine sockets;
- user-specific credential helpers.

The adapter uses installed Codex environment-policy capabilities when available, and additionally performs an effective-behavior self-test. Configuration presence without behavioral proof is insufficient.

Login-shell/profile behavior must not be allowed to reintroduce excluded host secrets. If the installed runtime/platform cannot guarantee the effective minimal environment, automatic repair is blocked.

### 12.6 Network policy

Model-generated command network access is disabled by default.

The Codex product/core process may have the network capability required for its own model interaction, but repository shell/tool commands do not receive general network access merely because the core process can communicate with the service.

A future repair mode requiring command network access needs a separately reviewed design. It is not part of #372 MVP.

### 12.7 Mandatory capability and canary self-test

Before `--watch` automatic mode can execute the first repair, and again after relevant Codex/runtime/config changes, the worker performs a fail-closed sandbox self-test using a synthetic local canary.

The self-test proves at least:

- repair copy can be read/written;
- a canary file outside all readable roots cannot be read;
- configured host credential paths cannot be read;
- real git worktree cannot be read;
- excluded secret environment variables are absent from model-generated command environment;
- command network is unavailable;
- no unexpected host socket is visible.

Self-test failure or unsupported permission-profile enforcement returns:

```text
IMPLEMENTER_SANDBOX_BLOCKED
```

and no Codex repair starts.

There is no automatic fallback to legacy/broad-read `workspace-write`, danger/full access, direct host shell execution, or direct real-worktree editing.

### 12.8 Codex invocation contract

Codex runs non-interactively with:

- trusted adapter-generated restrictive permission profile;
- approval policy suitable for unattended operation only **inside that proven sandbox**;
- fixed argument vector without shell-string interpolation;
- bounded process timeout;
- repair copy as working/project root;
- trusted output schema for repair summary;
- command network disabled;
- model-command environment allowlisted/filtered;
- no direct Git mutation responsibility.

Conceptually:

```text
codex exec
  <trusted restrictive permission-profile selection>
  <never-ask approval policy inside proven sandbox>
  --json
  --output-schema <trusted local schema>
  <trusted wrapper prompt + untrusted repair data>
```

The design intentionally does not hardcode a legacy preset flag such as `--sandbox workspace-write` as the security boundary.

### 12.9 Prompt authority

Prompt sections remain explicit:

```text
[SYSTEM POLICY: IMPLEMENTER_REPAIR]
[AUTHORITY: WORK_ISSUE]
[AUTHORITY: CANONICAL]
[TRUSTED FACTS: REPAIR_TARGET]
[TRUSTED FACTS: ALLOWED_SCOPE]
[UNTRUSTED: REVIEW_FINDINGS]
[UNTRUSTED: PR_METADATA]
```

Codex is instructed to edit only the repair copy. It must not commit, push, merge, write review status, broaden scope, modify worker policy, or modify protected review infrastructure outside authorized Issue ownership.

Prompt policy is defense in depth; filesystem/environment sandboxing remains authoritative for host-secret protection.

## 13. Deterministic repair-copy diff and patch transfer

Codex never writes directly to the real git worktree.

After Codex exits, the trusted wrapper compares the original sanitized copy with the repaired copy and creates an internal normalized patch/change set.

Before applying to the real worktree it rejects:

- out-of-scope/protected paths;
- unexpected file types;
- symlinks/hardlinks/device/special files not explicitly supported;
- path traversal/case-normalization escape;
- submodule/nested-repository metadata;
- unexpected executable-bit/mode changes outside policy;
- per-file/total size limits;
- generated `.git`/credential/config artifacts;
- binary changes when the current Issue/scope does not explicitly permit them.

Only the trusted wrapper applies the approved normalized change set to the real isolated worktree.

After application it recomputes the real worktree diff and repeats the scope/protected-path guard. The wrapper does not trust Codex's structured summary as proof of what changed.

## 14. Credentialless ValidationSandbox

### 14.1 Threat model

Tests, build scripts, compiler plugins, package hooks, and static-analysis extensions at the repaired PR head are PR-controlled executable code. Running them directly in the credential-bearing local worker process would expose host files, Git/Codex credentials, network, sockets, or other local capabilities.

Therefore no PR-controlled validation command executes directly in the worker host process.

### 14.2 Interface

```text
ValidationSandbox
- prepare(snapshot, trusted_config)
- run(argv[]) -> ValidationResult
- dispose()
```

The backend is provider-neutral. MVP provides a container backend suitable for the trusted local environment.

### 14.3 Trusted validation image/config

Validation image, image digest, resource limits, command argv, timeouts, and sandbox policy come only from trusted local worker configuration or another trusted base source. They are not selected by:

- PR Dockerfiles;
- PR compose files;
- PR body;
- finding text;
- RepairRequest model prose;
- repository scripts that attempt to change sandbox configuration.

Production/live automatic mode requires the configured image to be pinned by immutable digest. Missing/unavailable safe backend means `VALIDATION_BLOCKED`; the worker never falls back to host execution.

### 14.4 Validation input

The worker snapshots repaired repository content into a second disposable sandbox input.

Do not mount the real worktree `.git` metadata. Do not expose host credentials, agent sockets, container-engine sockets, or arbitrary host directories.

Validation may modify only the disposable sandbox copy. The actual repair worktree remains outside the validation container.

### 14.5 Minimum container isolation

Default safe profile requires at least:

- no GitHub token/environment credential;
- no Codex auth / `CODEX_HOME`;
- no SSH agent/socket;
- no Docker/container-engine socket;
- no host home mount;
- no `.git` metadata from host worktree;
- network disabled;
- read-only container root filesystem;
- explicit disposable writable workspace/tmpfs only where required;
- dropped Linux capabilities;
- `no-new-privileges`;
- bounded CPU/memory/process/time limits;
- fixed working directory;
- fixed argv execution without host shell interpolation.

The sandbox must not push Git, call GitHub, invoke host Codex credentials, or mutate the real worktree.

### 14.6 Dependencies and offline validation

Because validation network is disabled, required validation dependencies already exist in the trusted validation image or trusted prebuilt cache/image. The automatic repair loop does not dynamically `pip install`, `npm install`, or fetch untrusted dependencies from the Internet during the privileged repair transaction.

Dependency/image refresh is a separate trusted maintenance action, not something PR data can request.

### 14.7 Validation result authority

Only deterministic worker-configured commands executed inside safe ValidationSandbox authorize an automatic push.

Codex-run tests are implementation hints only and never the deterministic automatic-push Authority. #373 owns which exact checks are final Merge Gate requirements.

## 15. Deterministic post-Codex / pre-push guards

The trusted wrapper checks, in order:

1. authoritative artifact provenance and digest/token;
2. CodexRepairSandbox capability/canary self-test is current and passing;
3. real worktree parent == exact reviewed SHA;
4. Codex operated only on sanitized repair copy;
5. non-empty repair-copy diff;
6. repair-copy diff scope/protected-path/special-file guard;
7. deterministic patch transfer to real worktree;
8. recomputed real-worktree scope/protected-path guard;
9. no remote/submodule/credential-policy mutation;
10. ValidationSandbox available and safe-profile preflight passes;
11. all configured sandbox validation commands pass;
12. final real-worktree diff/scope guard passes;
13. PR still open/non-draft/same-repo/V2;
14. live PR head == reviewed SHA;
15. remote implementation branch == reviewed SHA;
16. token remains current/not superseded;
17. no conflicting active local execution;
18. commit parent still equals reviewed SHA.

Any failure prevents commit/push.

## 16. Git commit and push policy

The trusted wrapper, not Codex, owns Git mutation after repair.

Successful automatic repair creates exactly one commit:

- parent == reviewed head SHA;
- message references Work Issue and short repair token;
- configured Implementer author/committer identity;
- exact authorized implementation branch;
- no amend/rebase/merge/force push;
- regular fast-forward push only.

If remote head moved, normal push fails and outcome is STALE. The worker does not automatically rebase/transplant the generated patch onto a newer head.

The resulting PR `synchronize` event starts the next Independent Review automatically.

## 17. Persistence and idempotency

### 17.1 Request discovery index

Before publishing a new index, the Orchestrator checks trusted request history for the same token.

- same trusted token/run/digest already indexed -> no duplicate;
- same reviewed SHA with conflicting executable request identities -> BLOCKED/ESCALATED;
- PASS/BLOCKED -> no request artifact/index.

### 17.2 Local state

Local state is an execution cache only, for example:

```text
repair-state/<repair_token>.json
```

It may record first-seen time, local run ID, provenance result, CodexRepairSandbox self-test version/result, outcome, old/new SHA, validation summary, and temporary paths.

Loss of local state does not create new Authority; GitHub trusted run/artifact/current branch state determines whether a request is executable.

### 17.3 Repair outcome

The worker may publish implementation-side audit evidence:

```text
<!-- yura-repair-outcome:v1 -->
Repair-Token: `...`
Outcome: PUSHED | STALE | NO_CHANGE | SCOPE_BLOCKED |
         IMPLEMENTER_SANDBOX_BLOCKED | VALIDATION_BLOCKED |
         VALIDATION_FAILED | FAILED | ESCALATED
Old-Head-SHA: `...`
New-Head-SHA: `...`?
Commit-SHA: `...`?
```

This is not Reviewer Authority and can never create PASS.

## 18. Concurrency and stale guards

- per-repository/per-PR local lock: one active repair execution;
- duplicate delivery of same token: one mutation at most;
- newer PR head/request supersedes older request;
- current-head checks occur before repair preparation and immediately before commit/push;
- worker restart revalidates GitHub artifact/current state and sandbox capability before resuming;
- old repair-copy patches may be retained only for diagnostics and are never automatically transplanted onto a newer head.

## 19. Code layout

Phase A planned layout:

```text
tools/
├── independent_review/
│   ├── orchestrator.py          # handoff after trusted decision
│   ├── persistence.py           # review + discovery index
│   ├── main.py                  # fixed request output lifecycle
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
    ├── repair_copy.py
    ├── codex_sandbox.py
    ├── codex_adapter.py
    ├── patch_transfer.py
    ├── validation.py
    ├── container_validation.py
    ├── git_workspace.py
    └── worker.py

tests/tools/repair_loop/
    ...
```

Network, process, sandbox, container, and Git operations remain behind narrow adapters so state-machine/security behavior can be unit-tested with fakes.

## 20. Integration order with Independent Review

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

If ReviewDecision persistence fails, no RepairRequest is produced.

If request construction/index persistence/artifact publication fails, review remains CHANGES_REQUESTED but automatic repair infrastructure is BLOCKED. It must never be reported as a successful closed repair loop.

PASS/BLOCKED do not create executable RepairRequest bytes.

## 21. Unit and fake-E2E acceptance

At minimum Phase A tests cover:

### Request / provenance

- CHANGES_REQUESTED + validated blocking findings -> canonical RepairRequest;
- PASS/BLOCKED -> no request;
- same trusted cycle -> deterministic bytes/digest/token;
- changed head/finding/scope/run -> changed digest/token;
- request output absent on non-repair paths;
- duplicate token -> one index;
- max cycle -> ESCALATED/no executable request;
- untrusted finding text cannot alter trusted target/scope fields;
- artifact archive traversal/symlink/size/ambiguity rejection;
- artifact run/workflow/PR/head mismatch rejection;
- forged PR Review index with no matching trusted artifact rejection;
- alternate-workflow look-alike artifact rejection;
- valid index but artifact digest/token mismatch rejection;
- stale current PR/remote head rejection.

### CodexRepairSandbox / repair copy

- automatic mode rejects legacy/broad-read workspace-write as the sole security boundary;
- repair copy excludes `.git`, worker state, and configured credential paths;
- Codex cannot access real git worktree path;
- effective filesystem policy exposes repair copy read/write and only approved minimal roots;
- deny-read canary outside allowed roots fails to read;
- configured GitHub/SSH/Codex/cloud credential paths fail to read;
- secret environment variables/socket paths are absent from model-generated command environment;
- command network self-test fails as expected;
- unsupported/unenforceable permission profile -> `IMPLEMENTER_SANDBOX_BLOCKED` / no Codex invocation;
- Codex-produced traversal/symlink/special-file/oversize/out-of-scope change rejected;
- deterministic patch transfer is the only route from repair copy into real worktree;
- Codex no-diff -> no push.

### Validation / Git

- protected/out-of-scope real-worktree change -> no push;
- ValidationSandbox unavailable -> no host fallback/no push;
- validation command failure -> no push;
- validation container builder excludes host credentials/network/sockets/`.git`;
- remote head movement after repair/validation -> no push;
- two workers on same token -> at most one mutation;
- successful repair -> one regular fast-forward commit/push;
- RepairOutcome never creates Review PASS.

Fake adjacent E2E:

```text
H0 review -> CHANGES_REQUESTED
-> trusted run artifact request(token1)
-> provenance PASS
-> CodexRepairSandbox self-test PASS
-> Codex repairs sanitized copy
-> deterministic scope/safety diff PASS
-> wrapper transfers patch to real worktree
-> ValidationSandbox PASS
-> live stale check PASS
-> H1 fast-forward push
-> simulated synchronize
-> PASS(H1)
```

Also cover stale H0, forged index, malicious alternate-workflow index, host-secret read attempt by Codex, protected-path edit, validation sandbox unavailable, duplicate worker, and bounded repeated-finding escalation.

## 22. Live Verification

Live Verification begins only after Phase A and Phase B are merged.

Use a deliberately controlled V2 test PR with a known repairable defect.

1. user starts local worker in trusted environment;
2. worker CodexRepairSandbox capability/canary self-test passes;
3. Gemini produces CHANGES_REQUESTED on exact H0;
4. trusted workflow run produces authoritative RepairRequest artifact + discovery index;
5. local worker verifies run/artifact/digest/token/current head;
6. wrapper creates real H0 worktree and separate sanitized repair copy;
7. local Codex repairs only sanitized copy inside proven read-isolated sandbox;
8. negative canary confirms host credential paths/real worktree are unreadable to model tools;
9. deterministic repair diff/scope guard passes;
10. wrapper transfers allowed patch into real worktree;
11. credentialless/networkless ValidationSandbox passes configured checks;
12. live head still H0;
13. wrapper pushes one fast-forward H1 commit;
14. existing Independent Review automatically starts on H1;
15. loop reaches PASS or another bounded RepairRequest;
16. GitHub audit evidence reconstructs H0 -> run -> artifact digest/token -> H1 -> next review.

Negative Live Verification also proves:

- look-alike comment without matching trusted artifact is rejected;
- unsafe/unavailable Codex read-isolation capability blocks repair before model execution;
- an attempted Codex read of a local canary secret outside repair roots fails;
- safe ValidationSandbox unavailable prevents push.

## 23. Failure and escalation policy

Automatic repair stops without push on:

- invalid/missing/expired/ambiguous trusted artifact;
- artifact/index/run digest or identity mismatch;
- stale PR/remote head/branch mismatch;
- Issue/canonical mismatch;
- Codex unavailable/timeout;
- Codex read-isolation capability missing or self-test failing;
- no repair diff;
- repair-copy or real-worktree out-of-scope/protected/special-file change;
- safe ValidationSandbox unavailable;
- validation failure;
- remote head movement/non-fast-forward push rejection;
- duplicate/conflicting active repair;
- max repair attempts exceeded.

Never recover by:

- trusting comment bytes instead of artifact Authority;
- giving Codex direct access to the real git worktree;
- relying only on broad-read workspace-write for unattended repair;
- exposing host credentials/CODEX_HOME/SSH agent to model-generated commands;
- running PR-controlled tests on credential-bearing host;
- enabling validation command network as an automatic fallback;
- mounting host credentials or container-engine socket;
- force push/rebase;
- widening Codex sandbox bypass/full-access flags;
- modifying Reviewer logic to make a finding disappear;
- merging automatically inside #372.

## 24. Done boundary

### Phase A complete

- RepairRequest models/digest/token/scope implemented;
- trusted Reviewer side writes exact canonical request output for CHANGES_REQUESTED;
- PR discovery index is explicitly non-authoritative;
- local worker verifies run-artifact provenance and exact current head;
- real git worktree is separated from Codex repair copy;
- CodexRepairSandbox abstraction and installed-Codex permission capability preflight/self-test implemented;
- unattended mode fails closed unless host-secret reads are denied to model-generated tools;
- Codex-produced changes enter real worktree only through deterministic patch transfer;
- credentialless ValidationSandbox + safe container backend implemented;
- successful fake repair produces one fast-forward new head;
- unit/fake E2E security cases pass;
- Phase A merged to `rebuild/v2-foundation` with Resume Checkpoint.

### Phase B complete

- `main` trusted workflow uploads only trusted request output as a run-owned artifact using pinned action code;
- no PR head code execution or implementation write permission is introduced;
- workflow behavior for PASS/BLOCKED/no-request is fail-closed;
- Phase B merged to `main` with Resume Checkpoint.

### Issue #372 complete

- controlled live PR demonstrates CHANGES_REQUESTED -> trusted run artifact -> read-isolated local Codex repair-copy edit -> deterministic patch transfer -> credentialless sandbox validation -> fast-forward push -> automatic new-head review;
- forged index without matching trusted artifact is rejected;
- Codex cannot read host canary/credential paths or real worktree through model-generated tools;
- unsafe/unavailable Codex sandbox or ValidationSandbox prevents push;
- stale/duplicate/max-cycle paths fail closed;
- Reviewer and Implementer credentials/identities remain separate.

After these gates, #373 owns Required Checks, combined Gemini/Codex/CI Merge Gate, unresolved-review-thread policy, and optional Auto Merge.
