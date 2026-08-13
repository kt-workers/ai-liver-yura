# Independent AI Reviewer — Trusted Review Target Context

Status: Canonical supplement for Issue #379
Parent: #369
Depends on: #370, #371
Effective: 2026-08-13

Related canonical:
- `docs/architecture/v2/independent_ai_review_architecture.md`
- `docs/architecture/v2/review_orchestrator_implementation.md`

## 1. Problem

The deterministic validator correctly requires a provider `echoed_head_sha` to match the trusted `ReviewTarget.head_sha`. However, the Reviewer prompt currently asks the provider to echo the reviewed head SHA without rendering the trusted ReviewTarget as an explicit trusted input section.

For a long-lived PR, untrusted PR text can contain previous head SHAs. PR #368 demonstrated this failure mode after new commits: Gemini echoed a different SHA and the validator correctly returned BLOCKED twice.

The validator must remain strict. The missing contract is explicit trusted target presentation to the Reviewer.

## 2. Authority

`ReviewContext.target` is constructed by the Orchestrator from live GitHub PR metadata and is trusted runtime context.

The following values are Review Target facts:

- repository
- PR number
- base ref
- base SHA reported for the PR relationship
- head ref
- **reviewed head SHA**

Only `ReviewContext.target.head_sha` is authoritative for provider `echoed_head_sha`.

A SHA appearing in any of the following is not Review Target authority:

- PR title/body
- source code
- tests
- diff
- comments/reviews
- historical review markers
- Issue prose

Those remain review data even when their text resembles a current SHA.

## 3. Reviewer input contract

Before Issue/Canonical/PR data, the rendered Reviewer input SHALL contain:

```text
[TRUSTED FACTS: REVIEW_TARGET]
Repository: <repository>
PR: <number>
Base-Ref: <base_ref>
Base-SHA: <base_sha>
Head-Ref: <head_ref>
Reviewed-Head-SHA: <head_sha>
```

The system instruction SHALL state that `echoed_head_sha` must exactly copy `Reviewed-Head-SHA` from this trusted section when present.

## 4. Validation contract

No validator relaxation is permitted.

- exact echo of `ReviewContext.target.head_sha` may proceed to normal deterministic verdict validation;
- a missing echo may follow the existing candidate schema/validator policy;
- an echoed value different from the trusted target remains BLOCKED;
- PR text, previous AI reviews, or GateEvidence must never override the trusted Review Target.

## 5. Prompt-injection boundary

Adding trusted target facts does not make PR metadata trusted. The input keeps authority labels distinct:

```text
[TRUSTED FACTS: REVIEW_TARGET]
[AUTHORITY: ISSUE_SCOPE]
[AUTHORITY: CANONICAL_REQUIREMENT]
[TRUSTED FACTS: GATE_EVIDENCE]
[UNTRUSTED: PR_METADATA]
[UNTRUSTED: PR_DIFF]
```

Instructions or SHA-like values under UNTRUSTED sections are review data only.

## 6. Verification

Unit acceptance:

- rendered input includes the exact current `ReviewTarget.head_sha` in `TRUSTED FACTS: REVIEW_TARGET`;
- a stale SHA embedded in PR body remains under `UNTRUSTED: PR_METADATA`;
- trusted target appears before untrusted PR metadata;
- system instruction tells the provider to echo the trusted `Reviewed-Head-SHA` exactly;
- existing validator still rejects mismatched echoed SHA.

Live acceptance:

- rerun PR #368 at current head;
- provider review is no longer BLOCKED because it had to infer the target SHA from untrusted text;
- persisted `Reviewed-Head-SHA` exactly equals the current PR head;
- normal PASS / CHANGES_REQUESTED / other valid review outcome is then determined by review findings, not target-SHA ambiguity.
