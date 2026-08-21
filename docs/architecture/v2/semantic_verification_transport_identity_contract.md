# V2 Semantic Verification Transport Identity Contract

Owner Issue: #438
Parent capability: #363
Base implementation lineage: PR #428 / `feature/v2-semantic-verification`
Related:
- `semantic_verification_contracts.md`
- `semantic_verification_relation_edge_contract.md`
- `semantic_verification_self_disclosure_relation_contract.md`
- `app/domain/llm/contracts.py`
- `app/adapters/llm/openai_responses.py`

Status: Canonical Supplement / Design Gate

## 1. Purpose

#434 real-LLM Character Language validation exposed an intermittent Role B failure in #363 Semantic Verification.

Provider invocation itself succeeded, but the returned relation candidate contained a transport identity value that did not match the trusted request:

```text
schema_invalid
Semantic Verification candidate contract invalid:
relation request identityが一致しません
```

The runtime correctly failed closed. The failure is therefore not an unsafe acceptance bug. The problem is that #363 currently asks the semantic Provider to reproduce transport-owned identity fields which the Runtime already knows exactly.

This contract removes that unnecessary Provider responsibility while preserving the existing exact-pair, stale, cancellation, cross-request, proposition, blind-unit, and semantic acceptance gates.

The goal is not to tolerate an identity mismatch. The goal is to stop asking the LLM to generate identity in the first place.

---

## 2. Canonical precedence

For Role B (`semantic_verification_plan_relation`) only, this document supersedes the parts of `semantic_verification_contracts.md` that require the Provider output to exact-echo the following fields:

- `request_id`
- `semantic_plan_id`
- `utterance_id`
- `blind_observation_id`

The trusted request/snapshot still owns all four identities.

Role A (`semantic_verification_blind_inventory`) is not changed by #438. Its current identity contract remains as-is unless a separate Work Issue explicitly changes it.

`semantic_verification_relation_edge_contract.md` already establishes the governing principle used here:

> Runtimeで決定可能な派生値をLLMへ生成させない。

#438 applies the same principle to Role B transport/pair identity.

---

## 3. Responsibility split

### 3.1 Provider owns semantic payload only

Role B Provider decides only the semantic observations that require model judgement:

- proposition relation
- polarity relation
- certainty relation
- degree relation
- execution relation
- blind-unit accounting relation
- blind-unit -> proposition semantic support references
- budget observation
- self-disclosure relation

The Provider does not decide or regenerate which Runtime request, Plan, Utterance, or committed Blind Observation the response belongs to.

### 3.2 Runtime owns transport and pair identity

Runtime owns:

```text
relation request identity
exact SpeechSemanticPlan identity
exact CharacterUtterance identity
exact committed BlindUtteranceObservation identity
trace / revisions / lifecycle eligibility
```

These identities originate from the current `SemanticVerificationContextSnapshot`, the committed Role A observation, and the `LLMRoleRequest` created from them.

They are not semantic model output.

---

## 4. Provider raw output contract

The production Role B Provider JSON schema must not expose these top-level fields:

```text
request_id
semantic_plan_id
utterance_id
blind_observation_id
```

They are removed from both `required` and `properties` in the raw Provider schema.

`additionalProperties=false` remains enabled. A Provider response that nevertheless includes those fields is schema-invalid rather than silently trusted.

`candidate_id` remains a Provider candidate field in #438. It is not transport Authority and is outside the scope of this correction.

The logical Runtime `PlanRelationObservationCandidate` may continue to contain the four identity fields after canonical Runtime binding. The distinction is:

```text
Provider raw semantic payload
  !=
Runtime canonical relation candidate
```

This is the same canonicalization pattern already used by `canonical_relation.py` for Runtime-derived proposition support IDs and evidence refs.

---

## 5. Trusted identity envelope

After the Provider returns a successful raw Role B semantic payload, the canonical relation layer constructs the Runtime candidate envelope deterministically.

Conceptually:

```text
LLMRoleRequest / trusted relation input
  request_id -------------------------------┐
  pair.semantic_plan_id --------------------┤
  pair.utterance_id ------------------------┤
  blind_observation.observation_id ---------┤
                                             v
Provider raw semantic payload ----------> Runtime canonical candidate
```

The canonical candidate receives:

- `request_id` from the current `LLMRoleRequest.request_id`
- `semantic_plan_id` from the trusted relation request pair
- `utterance_id` from the trusted relation request pair
- `blind_observation_id` from the committed Blind Observation carried by the trusted relation request

The canonicalizer must not recover these values from natural-language text, Provider prose, guessed IDs, previous requests, caches, or fallback state.

If the trusted relation input is structurally inconsistent, canonicalization must fail closed. It must not choose one conflicting identity and repair the request silently.

---

## 6. Transport correlation remains fail-closed

Removing identity echo from Provider JSON does not remove transport request correlation.

`OpenAIResponsesAdapter.invoke()` constructs `LLMRoleResult` identity from the active `LLMRoleRequest`, not from Provider-generated JSON:

- `result.request_id = request.request_id`
- `result.role_id = request.role_id`
- `result.revisions = request.revisions`
- `result.trace_id = request.trace_id`

`validate_role_exchange()` continues to reject:

- wrong Role
- wrong request/result identity
- wrong trace
- wrong revisions
- wrong input/output schema ID
- invalid result timing

Therefore a transport result associated with another `LLMRoleRequest` remains non-committable.

The Runtime must not replace these checks with the new envelope. `validate_role_exchange()` runs as an independent transport gate.

---

## 7. Exact pair and lifecycle safety remain unchanged

The following existing #363 safety gates remain mandatory:

### Snapshot pair gate

`SemanticVerificationContextSnapshot` still binds the exact:

- Plan
- CharacterUtterance
- decision
- intent
- source events
- RevisionVector

A mismatched Plan / Utterance pair is rejected before semantic verification proceeds.

### Role A -> Role B dependency

Role B still receives the immutable committed Blind Observation produced for the same actual Utterance.

### Authority identity checks

`SemanticVerificationAuthority.commit_relation()` may retain exact identity checks on the Runtime canonical candidate.

Those checks now verify that Runtime envelope construction is consistent with the active snapshot and committed blind observation. They are no longer checks of LLM self-reported transport identity.

### Live-state checks

The existing live eligibility checks remain before Provider invocation, after Role A, and after Role B:

- active
- stale
- superseded
- cancelled
- Plan ID
- Utterance ID
- revisions

No stale or superseded result becomes acceptable because of #438.

---

## 8. Semantic cross-request protection

Provider semantic payload remains closed against the exact current request through typed identifiers that are genuinely part of semantic accounting:

- Plan proposition IDs must match the current Plan proposition set exactly
- blind-unit accounting must cover the current committed Blind Observation exactly
- unknown proposition IDs are rejected
- unknown blind-unit IDs are rejected
- grounded proposition/accounting consistency remains fail-closed

A response containing semantic accounting for another request cannot be made valid by Runtime identity envelope injection when its proposition/blind-unit references do not belong to the active pair.

A lower-level transport implementation that returns a result for the wrong invocation is a transport-contract violation and must be detected by `LLMRoleResult` / `validate_role_exchange`, not by trusting an LLM-generated echo as transport Authority.

#438 does not claim that a model-generated identity echo is a semantic proof. A model could echo the current ID while still making an incorrect semantic judgement; therefore semantic correctness continues to depend on the existing closed relation/accounting checks and independent Observer design.

---

## 9. Canonical relation layer

`canonical_relation.py` is the appropriate boundary for this correction because it already converts a reduced raw Provider relation payload into the canonical Runtime candidate by deriving values that Runtime can determine safely.

The #438 implementation should extend that existing canonicalization rather than create a second parallel relation parser or Lab-only workaround.

Expected flow:

```text
Provider raw Role B payload
  - no top-level pair identity echo
  - no proposition support/evidence duplicate fields
        |
        v
canonical relation layer
  + trusted request/pair/blind identity envelope
  + Runtime-derived proposition support/evidence
        |
        v
existing parse_relation_candidate()
        |
        v
existing SemanticVerificationAuthority
        |
        v
existing closed SemanticAcceptance policy
```

The Domain candidate/Authority layer therefore stays strongly typed and fail-closed.

---

## 10. Prompt contract

Role B production instructions must stop asking the Provider to echo:

- request ID
- Plan ID
- Utterance ID
- Blind Observation ID

The Provider may see technical identifiers required for semantic mapping, such as proposition IDs and blind-unit IDs, but it must not be assigned transport binding responsibility.

Prompt wording must emphasize that the Provider returns semantic relation/accounting only.

No natural-language phrase matcher, regex, fixed sentence, identity recovery heuristic, or repair prompt is introduced.

---

## 11. Failure policy

### Provider/schema failure

- malformed raw semantic payload -> fail closed
- unexpected identity field in raw payload -> strict schema failure
- Provider unavailable/timeout -> no acceptance

### Transport exchange failure

- wrong `LLMRoleResult.request_id` / role / trace / revisions -> fail closed through `validate_role_exchange()`

### Runtime envelope failure

- missing trusted pair identity -> fail closed
- inconsistent trusted pair identity -> fail closed
- wrong envelope candidate presented to another snapshot/Blind Observation -> Authority rejects

### Semantic candidate failure

Existing proposition/accounting/grounding/facet/self-disclosure/budget rules remain unchanged.

No failure class is converted to `ACCEPTED` merely because identity is now Runtime-owned.

---

## 12. Required regression

Minimum automated coverage for #438:

1. Role B raw Provider schema does not contain the four transport/pair identity output fields.
2. Role B instructions do not request identity echo.
3. Raw Provider semantic payload without those fields is canonicalized into a complete `PlanRelationObservationCandidate` using trusted Runtime identity.
4. Normal exact pair still commits successfully.
5. `LLMRoleResult.request_id` mismatch remains fail-closed through role-exchange validation.
6. trace/revision mismatch remains fail-closed.
7. Runtime canonical candidate with wrong semantic Plan ID is still rejected by Authority.
8. Runtime canonical candidate with wrong Utterance ID is still rejected by Authority.
9. Runtime canonical candidate with wrong Blind Observation ID is still rejected by Authority.
10. concurrent relation requests receive their own deterministic envelope; cross-pair candidate reuse cannot commit against the other snapshot.
11. unknown proposition/blind-unit references remain rejected.
12. stale/superseded/cancelled regressions remain PASS.
13. existing relation-edge Runtime support/evidence derivation regressions remain PASS.
14. strict schema / Ruff / strict Mypy / full pytest / compileall / diff whitespace PASS.

---

## 13. Live verification

After automated gates pass, #434 should rerun the Gratitude real-LLM path that originally exposed #438.

Recommended minimum:

```text
Mode: Isolation
Scenario: Gratitude
Strict same-Plan
repetitions: 5
#363: ON
same model/reasoning policy used in prior evidence
```

Verify:

- Character generation succeeds independently
- Role B raw Provider output no longer contains transport identity fields
- all semantic runs either produce a normal semantic ACCEPTED/REJECTED result or a genuine non-identity infrastructure failure
- the old `relation request identityが一致しません` failure surface cannot recur from Provider JSON

One successful run is not the proof. The design proof is that the raw Provider schema no longer asks the model to emit the identity fields; the 5-run is live confirmation of the corrected path.

---

## 14. Non-goals

#438 does not:

- weaken identity mismatch acceptance
- remove exact Plan/Utterance pair binding
- remove stale/superseded/cancelled checks
- change semantic acceptance categories
- modify #330 Character Language quality or variation
- implement #348 retry/repair orchestration
- alter Role A identity ownership
- add retry merely to hide schema drift
- introduce lexical semantic heuristics

---

## 15. Implementation ownership

#438 implementation remains on the #363 stacked lineage and should modify only the Semantic Verification production boundary and its regressions/docs.

Expected primary files are limited to the existing #363 relation canonicalization/schema/prompt/tests unless implementation inspection proves an additional production boundary is required.

Any unrelated #434 Lab behavior or #330 Character behavior discovered during implementation must remain separate under Issue #207 rules.
