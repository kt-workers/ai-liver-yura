# 「プロジェクトゆらv2」#7 Sync Manifest

Status: **Synchronized / PASS**
Effective: 2026-08-13
Last synchronization: 2026-08-13
Project: `ktan514 / 7 / プロジェクトゆらv2`
Repository: `ktan514/ai-liver-yura`
Root: #317
Management migration: #367 — **completed / closed**
Management spec: `docs/architecture/v2/project_v2_management_spec.md`
Runbook: `docs/architecture/v2/project_v2_sync_runbook.md`

## 1. Current authority

Project #7 is the current GitHub Projects v2 authority for V2 work.

Project #6 is historical transition state and must not be used to determine current V2 Project status.

Membership authority:

- repository label `v2` present → Project #7 management target
- repository label `v2` absent → not a Project #7 management target

Issue / PR titles, branch names, old Project membership, or the string `v2` appearing in historical names are not sufficient to establish V2 membership.

Auto-add was user-verified in the GitHub UI on 2026-08-13:

- enabled
- repository = `ktan514/ai-liver-yura`
- filter = `label:v2`

The filter/repository were not API-readable, so this remains explicitly **human UI verified**, not API verified.

## 2. Synchronized Issue scope

51 V2 Issues:

`#317 #318 #319 #320 #321 #322 #323 #324 #325 #326 #327 #328 #329 #330 #331 #332 #333 #334 #335 #336 #337 #338 #339 #340 #341 #342 #343 #344 #345 #346 #347 #348 #349 #350 #351 #352 #353 #354 #355 #356 #357 #358 #359 #360 #361 #362 #363 #364 #365 #366 #367`

Confirmed current V2 Pull Requests at synchronization: **0**.

## 3. Final Project #7 synchronization result

Phase B mutation and full re-audit completed on 2026-08-13.

- initial Project items: 118
- initial V2-labeled items: 13
- missing V2 labels added: 38 (`#329`–`#366`)
- final V2 Issue labels: 51/51
- scope-out labels added: 0
- non-`v2` Project items removed from Project #7: 67
- Issue / PR objects deleted or closed by membership cleanup: 0
- final Project membership: 51
- final unlabeled Project items: 0
- final scope-out Project items: 0
- duplicate Project items: 0
- archived Project items: 0
- confirmed V2 PR: 0
- formal hierarchy: 50/50 PASS including `#367 → #317`
- Project #6 mutations: 0
- V1 lineage mutations: 0
- product implementation started during migration: NO

## 4. Project field schema

### Status

`Backlog`, `Ready`, `In progress`, `Review`, `Verification`, `Blocked`, `Done`

### 担当ロール

`AI作業`, `人間確認`, `共同判断`

### Priority

`P0`, `P1`, `P2`

### Issue level

`Parent`, `Work`, `Integration`, `Management`

### Area

Issue body `Area:` exact value is canonical.

Management special cases:

- #317 = `Management`
- #318 = `Management`
- #319 = `Management`
- #367 = `Management`

`Management` Area option was added non-destructively during synchronization. Existing Area options were not removed, renamed, or assigned new IDs.

### Schedule / estimates

- Start date = explicit Issue body value
- Target date = explicit Issue body value
- Iteration = unset unless separately canonicalized
- Size = unset unless separately canonicalized
- Estimate = unset unless separately canonicalized

## 5. Final synchronized fields

For all 51 Issues:

- Status: 51/51 PASS
- 担当ロール: 51/51 PASS
- Priority: 51/51 PASS
- Issue level: 51/51 PASS
- Area: 51/51 PASS
- Start date: 51/51 PASS
- Target date: 51/51 PASS
- Iteration: canonical-unset maintained
- Size: canonical-unset maintained
- Estimate: canonical-unset maintained

Total synchronized required field values: 357.

Priority distribution at sync:

- P0: 36
- P1: 14
- P2: 1

Issue-level distribution:

- Management: 4
- Parent: 7
- Work: 36
- Integration: 4

## 6. Status at migration completion

- #317: `In progress` / `AI作業`
- #318: `Blocked` / `AI作業`
- #319: `Done` / `AI作業`
- #367: `Done` / `AI作業`
- remaining V2 Product Parent / Work / Integration Issues: `Blocked` / `AI作業`

#367 was automatically closed by the enabled Project `Auto-close issue` workflow immediately after its Project Status changed to Done. The temporary execution guard that expected #367 to remain open was not a canonical requirement. The final `Done + completed/closed` state was reconciled and accepted; #367 is not reopened.

## 7. Explicit non-mutations during Project migration

- no source/product code changes
- no implementation branch or implementation PR creation
- no old Project #6 mutation
- no V1 lineage mutation
- no scope-out `v2` label additions
- no Assignee or Milestone changes
- no legacy Issue/PR close as part of Project membership cleanup

## 8. Completion state

Project #7 migration gate: **PASS / COMPLETE**.

V2 architecture Design Gate: **APPROVED** by user.

V2 product implementation: **not started yet**.

The next management gate is #318 legacy implementation-lineage cleanup. After #318 completes, #321 Typed Contracts must pass its own Resume/Start Gate before any implementation branch/PR is created.
