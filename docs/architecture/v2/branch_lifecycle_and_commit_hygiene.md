# V2 Branch Lifecycle and Commit Hygiene

Status: Proposed canonical supplement
Effective: 2026-08-13
Parent: #317
Management Issue: #384
Related canonical: `docs/architecture/v2/project_v2_management_spec.md`

## 1. Purpose

V2 development history must remain readable from Git Graph and GitHub state without guessing whether a branch is active, paused, abandoned, merged, or test-only.

This policy also prevents accidental history-only commits such as placeholder files, empty trigger commits, and temporary `NOOP` / `nonexistent` files from entering shared branch history.

## 2. Branch states

Every non-trunk V2 branch must have exactly one operational state that can be inferred from its linked Issue and PR.

### ACTIVE

- linked V2 Issue is `In progress` or `Review`;
- one Open PR exists for the active lineage;
- PR is Draft while implementation/design is incomplete, Ready only when review is intentionally requested;
- Resume Checkpoint records branch, base SHA, head SHA, current status, and next action.

### BLOCKED

- linked Issue records the blocker;
- PR remains Open Draft unless there is a specific reason to close it;
- no implementation commit is added until the blocker is resolved;
- Resume Checkpoint records the exact blocking condition.

### MERGED

- PR is merged;
- normal V2 merge method is `merge` so source ancestry visibly joins the target branch;
- merge target contains the source head in ancestry;
- final source head and merge commit SHA are recorded;
- source branch is frozen and must not receive later commits;
- branch ref is deleted after merge verification.

### ABANDONED

- PR is closed unmerged;
- Issue/PR records why the lineage was rejected, replaced, or cancelled;
- useful design/test/failure knowledge is preserved in Issue/canonical history before cleanup;
- branch ref is deleted after the disposition is recorded.

### TEST_ONLY

- used only for temporary CI / validation execution;
- PR states explicitly that it must not be merged;
- result and final head SHA are copied to the owning Issue/PR;
- PR is closed unmerged;
- branch ref is deleted immediately after evidence capture.

## 3. Merge policy

Normal V2 Pull Requests use GitHub merge method `merge`.

Do not normally use:

- squash merge;
- rebase merge.

Reason: the project intentionally values visible branch ancestry. A completed work branch must visibly converge into its target branch in Git Graph.

Before merge:

1. re-fetch live PR head SHA;
2. re-fetch live target branch SHA;
3. confirm required review/test gates;
4. merge with the exact expected head SHA;
5. verify the returned merge commit;
6. verify source ancestry is present in the target branch;
7. record completion checkpoint;
8. delete the source branch ref.

If a branch has undesirable local commit history, clean it before review/merge rather than hiding it with squash merge. Never rewrite a shared branch that another active lineage depends on without explicit reconciliation.

## 4. Follow-up after merge

A merged branch is finished forever.

If additional changes are required after merge:

- do not append commits to the merged source branch;
- start from the latest target branch HEAD;
- create a new `fix/*`, `feature/*`, `docs/*`, `management/*`, or other purpose-specific branch;
- link it to the same Issue only when it is truly a follow-up within the same responsibility;
- otherwise create a new Work/Bug/Management Issue.

This rule prevents a branch from being simultaneously "merged" and "still in progress".

## 5. Prohibited history-only commits

Shared V2 history must not contain commits whose primary purpose is only to trigger automation, move a branch pointer, or test whether GitHub reacts.

Prohibited examples include:

- creating `NOOP`, `nonexistent`, `.trigger`, `dummy`, or equivalent placeholder files;
- commit messages such as only `x`, `noop`, `trigger`, or equivalent when no real repository change is intended;
- empty commits used only to retrigger CI/review;
- adding a temporary file and then deleting it in the next commit only to create activity;
- artificial whitespace/comment changes made solely to produce a new SHA.

Automation must be retriggered by a mechanism that does not pollute repository history, such as:

- Draft -> Ready transition when that event is the intended review trigger;
- explicit `workflow_dispatch` where supported;
- GitHub Actions re-run;
- a dedicated trusted control-plane action;
- an explicit reviewer command/comment when supported and safe.

## 6. Pre-commit / pre-push verification contract

Before any shared V2 branch mutation, the operator/automation must verify all of the following:

### Before commit

- current branch is the intended work branch;
- the branch is not a protected trunk (`main`, `develop`, `rebuild/v2-foundation`, or other protected aggregation branch);
- the linked Issue/PR is the intended active lineage;
- staged paths are expected for the current task;
- no placeholder/sentinel file is staged;
- the diff contains a real design/code/test/ops change.

### After commit, before push

- inspect the new commit message;
- inspect the new commit's changed paths and stats;
- inspect its parent SHA;
- confirm the commit contains only intended changes;
- confirm no `NOOP`, `nonexistent`, placeholder, accidental generated file, credential, or temporary artifact was introduced;
- if any check fails, do not push.

### After push

- re-fetch remote branch HEAD;
- confirm remote HEAD equals the intended local/shared commit;
- confirm the linked PR follows that same exact SHA;
- record the new head in the working checkpoint when the change is material.

## 7. Automated commit-hygiene guard

V2 should have an automated guard that inspects commits introduced by a Pull Request and fails closed on obvious history-only accidents.

The guard must detect at least:

- empty commits in the PR range when they exist only as automation triggers;
- commits whose complete change set consists only of known placeholder/sentinel paths;
- introduction of known placeholder paths such as root-level `NOOP` or `nonexistent`;
- add-then-delete placeholder pairs within the same PR lineage;
- explicitly forbidden trigger-only patterns configured by this policy.

The guard must not reject legitimate small commits merely because they touch one line. Decision must be based on change intent signals and deterministic path/content rules, not arbitrary minimum diff size.

The guard reports the offending commit SHA and reason. It never automatically rewrites shared history.

## 8. Accidental commit recovery

If an accidental commit is found before push:

- repair local history before sharing;
- do not create a second "undo" commit just to preserve the accident.

If it has been pushed to a branch that has not been merged and no other active lineage depends on it:

- stop the branch;
- record the accidental SHA in the Issue/PR for audit if relevant;
- prefer recreating a clean branch from the correct trusted base over stacking add/remove cleanup commits;
- close superseded PRs as appropriate;
- delete the dirty branch after recovery.

If the accidental commit has already entered a protected/shared target branch:

- do not silently rewrite protected history;
- create an explicit corrective commit or a separately approved history-rewrite plan depending on impact;
- document the event and remediation.

## 9. Existing V2 cleanup rule

For V2 branches created before this policy:

1. classify each as ACTIVE / BLOCKED / MERGED / ABANDONED / TEST_ONLY;
2. preserve authoritative evidence in Issue/PR/canonical docs;
3. never merge accident-only commits merely to make graphs converge;
4. do not rewrite already-published trunk history just to make old squash merges look connected;
5. delete obsolete branch refs after verification;
6. retain only trunk branches and currently active/blocked work branches with explicit ownership.

Known accidental commits from the Independent AI Review build-out include:

- `40dcdefd1dc5378f35780a49a405547988eccb8b` (`x`, added `nonexistent`);
- `f08e3bc6066210865eb4c9dfa3330ba02d44f65f` (removed that accidental file);
- `a703f8be7bf74c189d4302e1327cfe62ea65ec92` (`noop`, added `NOOP`).

These commits are not valid V2 product/design history and must not be propagated into trunk to preserve them.

## 10. Completion criteria for #384

- this policy is merged with a normal merge commit;
- an automated commit-hygiene guard is implemented and verified;
- current V2 branches are classified;
- obsolete merged/test/abandoned branch refs are cleaned up where tooling permits;
- active/blocked branches remain explicit and linked to live Issues/PRs;
- future V2 merges use merge commits by default;
- merged source branches are not reused.