# AI Liver ゆら V2 Autonomous Completion Loop Mission

version: 4
generation: 5

## Mission

Complete Root #317 through Mission #450 and Parent #462. GitHub live Issue,
PR, branch, exact HEAD, CI, and Project #7 state are current-state authority.
Never embed a fixed PR number or HEAD in this Goal; obtain them from the latest
#450 checkpoint and fresh live readback.

## Authority and safety

- Project #7 is the V2 planning authority. Project #6 is never mutated.
- Repository canonical design and the selected Work Issue define design intent.
- Codex is implementer; independent review is diagnostic and never receives GitHub write credentials or rewrites an implementation branch.
- The trusted reviewer boundary is defined in
  `docs/architecture/v2/trusted_host_reviewer_boundary.md`. Reviewer credentials
  are never available to Codex or a reviewed checkout.
- Secrets, tokens, request headers, database URLs, and raw provider failures do
  not enter repository files, Issues, PRs, checkpoints, or ordinary logs.

## GitHub human communication language

Write all human-facing GitHub communication in Japanese: Issue bodies, Issue
comments and checkpoints, PR bodies, PR comments/review explanations, Mission
Checkpoints, and Resume Certificates. Keep only machine-like or proper technical
terms in English: status values such as `ACTIVE`, `PASS`, `NOT_RUN`, and
`REQUEST_CHANGES`; branch names; commands; file paths; SHAs; API/class/function/
field names; machine-readable JSON keys and values; and verbatim external API
output when quoting it is necessary. Use those terms within Japanese prose.

Apply this rule to newly created communication only. Do not rewrite historical
GitHub posts solely to translate them.

## Resume Gate and Task Packet

Before branch creation, implementation, push, merge, or a new PR: read GitHub
live state; read the latest Mission and Work checkpoints; identify canonical
design; audit active lineages; and produce a Resume Certificate containing
Issue, design, branch, base/head SHAs, verification, next action, and conflicts.
Do not infer live state from chat memory. A conflict, unknown lineage, or
unexplained SHA change requires reconciliation before implementation.

The selected Task Packet states authority, scope/non-goals, exact target,
dependencies, acceptance checks, risk boundary, and the one active lineage.

## Loop

OBSERVE → RECONCILE → RESUME GATE → SELECT → PLAN → DESIGN → IMPLEMENT →
VERIFY → REVIEW/DIAGNOSE → FIX/INTEGRATE → CHECKPOINT → REPEAT/YIELD/ESCALATE.

Every external probe is bounded and returns a secret-safe typed diagnostic.
Preflight distinguishes bootstrap blockers from work-scoped unavailable
capabilities. Project write evidence is read-only; a normal preflight does not
mutate a Project.

## Review and functional repair policy

Independent review is diagnostic. Bind a review to an exact HEAD when it is run,
request no duplicate attempt for the same ReviewAttempt identity, and reject a
stale result after a HEAD change. However `REQUEST_CHANGES` or `NOT_RUN` alone is
not a Mission or merge blocker.

Repair is mandatory only when deterministic tests, exact-head CI, live readback,
or a reproducible execution path demonstrates a functional blocker: the Loop
cannot start/progress, acts on the wrong exact target, loses a required effect,
or otherwise fails required runtime behavior. Non-functional hardening,
additional auditability, hypothetical race defense, and reviewer-provider
availability issues are recorded and may be deferred. Do not harden the reviewer
runtime merely to obtain a cleaner verdict.

Review pending is not a Mission stop condition. Do not poll or repeatedly sleep
for it. Select another dependency-ready Work only through a fresh Resume Gate;
do not mix changes into the review-pending lineage.

## Mission state and checkpoint

Mission is ACTIVE while useful independent work exists. YIELD_EXTERNAL is a
safe run disposition when only external results are pending; it is not Human
Intervention. PAUSED_FOR_INTERVENTION is reserved for an actual user decision
or authority that cannot be safely inferred. Each material transition records
Mission/Work, branch/PR, exact HEAD, completed work, verification, blocker,
and first resume action in GitHub.

## Restore and identity verification

This file is the Repository source for Codex `/Goal`. The launcher loads it
verbatim and injects all three non-secret values: `CODEX_MISSION_GOAL_VERSION`,
`CODEX_MISSION_GOAL_GENERATION`, and the SHA-256 of this exact UTF-8 file in
`CODEX_MISSION_GOAL_SHA256`. Preflight verifies version, generation, and
content identity. It cannot read Codex UI state directly; the launcher hash
attests the loaded canonical source, not an unverifiable UI transcript.

To restore a lost `/Goal`, load this file verbatim through the launcher and
reinject its version/generation/hash. Never reconstruct it from an old summary.
