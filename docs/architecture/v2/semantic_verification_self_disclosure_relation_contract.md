# V2 Semantic Verification Self-Disclosure Relation Contract

Owner Issue: #363
Live Validation: #427 / #434
Upstream Authority: #362 Speech Semantics
Parent canonical:
- `semantic_verification_contracts.md`
- `semantic_verification_observer_strategy.md`

Status: Canonical Supplement / Live Validation feedback

## 1. Background

#434 `Unknown / uncertainty` live run exposed a false-reject risk.

Committed Plan:
- required proposition content: `まだ分からない`
- polarity: `UNKNOWN`
- certainty: `UNKNOWN`
- self-disclosure policy: `FORBIDDEN`

Actual Character utterance:
- `まだ分からないんだ。`

#363 Role B observed at the same time:
- proposition relation = `ENTAILED`
- polarity = `PRESERVED`
- certainty = `PRESERVED`
- corresponding blind unit = `SUPPORTED_BY_PLAN`
- self-disclosure relation = `EXCEEDED`

Runtime therefore produced `SELF_DISCLOSURE_EXCEEDED` despite the actual material content already being fully accounted to the required Plan proposition.

This is a contradictory observation surface: one Provider output simultaneously says that the utterance means exactly what the Plan requires and that the same material meaning independently exceeds the Plan's self-disclosure boundary.

## 2. Upstream authority boundary

Self-disclosure policy is owned by #362 Speech Semantics, not by #363.

#362 `SpeechSemanticAuthority` already validates self-disclosure against bounded `SpeechSemanticFactKind.SELF` provenance before a Plan can be committed.

For a committed Plan whose `self_disclosure = FORBIDDEN`:
- no non-FORBIDDEN proposition may be grounded in a SELF fact;
- therefore a non-FORBIDDEN proposition that exists in the committed Plan is already authoritative What-to-say content and must not be reclassified by #363 into an independently forbidden SELF claim solely from its natural-language surface.

#363 observes whether the actual utterance preserves or adds meaning relative to that committed Plan. It must not replace the upstream typed provenance decision with a lexical, grammatical, first-person, epistemic, or pragmatic reinterpretation.

## 3. Canonical rule

`self_disclosure_relation` is an **additional-content boundary**, not a second semantic interpretation of Plan-supported material content.

A material blind unit that is fully accounted as `SUPPORTED_BY_PLAN` and supports an `ENTAILED` Plan proposition cannot, by itself, be the sole basis for `self_disclosure_relation = EXCEEDED`.

If the actual utterance contains additional self-disclosure beyond the Plan-supported proposition, Role A / Role B must expose that additional meaning through the ordinary material-content accounting path:

- separate atomic blind unit when separable; or
- `UNSUPPORTED_EXTRA` when the extra meaning is material and not represented by any Plan proposition; or
- `AMBIGUOUS` when Plan-supported and extra meaning cannot be safely separated.

The Provider must not hide the extra meaning inside a `SUPPORTED_BY_PLAN` unit and then use `self_disclosure_relation` as an independent free-form rejection channel.

## 4. Surface-form non-authority

The following are not self-disclosure proof by themselves:

- first-person grammar or omitted Japanese subject;
- `分からない`, `思う`, `感じる`, `気がする` or similar surface phrases;
- epistemic or conversational stance wording;
- sentence endings, fillers, hedges, pronouns, or fixed phrases.

No finite phrase list, regex, keyword, pronoun detector, synonym list, or sentence pattern may become self-disclosure Authority.

Example:

```text
Plan proposition:
  topic-schedule / availability / {content: "まだ分からない"}
  polarity = UNKNOWN
  certainty = UNKNOWN

Actual:
  "まだ分からないんだ。"
```

If Role B observes this utterance as fully `ENTAILED` by that proposition with no extra material blind unit, the phrase must not be rejected solely because it can be read conversationally as the speaker saying they do not know.

The committed Plan already owns that meaning boundary.

## 5. Additional self-disclosure example

```text
Plan:
  p1 REQUIRED: schedule availability is still unknown

Actual:
  "まだ分からないんだ。私、予定を忘れがちでさ。"
```

Expected observation shape:
- unit U1 = `まだ分からないんだ。` -> `SUPPORTED_BY_PLAN [p1]`
- unit U2 = `私、予定を忘れがちでさ。` -> `UNSUPPORTED_EXTRA` (or `AMBIGUOUS` if safe separation is impossible)

Runtime rejects because of the Plan-extra material claim.

`self_disclosure_relation` may add diagnostic classification for U2, but it must not be the only mechanism that reveals the extra material meaning.

## 6. Acceptance consistency

For current v1 relation schema compatibility:

1. If every `MATERIAL_SEMANTIC_CONTENT` blind unit is safely `SUPPORTED_BY_PLAN`, no material unit is `AMBIGUOUS`, and all corresponding proposition relations are semantically safe, then `EXCEEDED` cannot independently create `SELF_DISCLOSURE_EXCEEDED`.
2. If Role B believes self-disclosure exceeds the Plan, the excess must be represented by a Plan-extra or ambiguous material unit/accounting path.
3. Unsupported/ambiguous material content remains fail-closed under existing #363 policy.
4. This rule does not allow Character Language to invent new personal facts when `self_disclosure = ALLOWED`; all material content still requires Plan support.
5. Character `realization_refs` remain hints only and are not used to prove compliance.

This is a structural consistency rule, not a natural-language whitelist.

## 7. Role B instruction requirement

Production Role B instructions must explicitly state:

- self-disclosure policy does not override proposition/accounting semantics;
- Plan-supported material content is not an independent self-disclosure excess merely because of first-person or epistemic surface realization;
- `EXCEEDED` requires additional material meaning beyond what the Plan propositions support;
- that additional meaning must appear in blind-unit accounting as `UNSUPPORTED_EXTRA` or `AMBIGUOUS` rather than being hidden in a `SUPPORTED_BY_PLAN` unit.

## 8. Required regression

Automated:

- committed Plan `self_disclosure=FORBIDDEN` + required GENERAL unknown proposition `まだ分からない` + actual `まだ分からないんだ。`
  - proposition `ENTAILED`
  - polarity `PRESERVED`
  - certainty `PRESERVED`
  - material unit `SUPPORTED_BY_PLAN`
  - must not reject solely as `SELF_DISCLOSURE_EXCEEDED`
- same Plan + explicit Plan-extra personal fact
  - extra material unit must be `UNSUPPORTED_EXTRA` or `AMBIGUOUS`
  - acceptance remains reject
- Provider candidate that returns `EXCEEDED` while every material unit is fully Plan-supported is normalized/rejected as internally inconsistent according to implementation strategy; it must not become a semantic false reject of the utterance
- no lexical/regex self-disclosure matcher
- existing required/forbidden/polarity/certainty/degree/execution/accounting gates remain unchanged

Live #434:

1. rerun `Unknown / uncertainty` after #363 correction;
2. first one-run smoke must no longer reject `まだ分からないんだ。` solely as self-disclosure;
3. then run the planned same-Plan 5-run characterization;
4. continue Negation / Gratitude / Apology / Degree only after this gate clears.

## 9. Non-goals

- weakening #362 self-disclosure policy;
- allowing ungrounded personal facts;
- adding first-person word lists;
- changing #330 Character style authority;
- making #363 a self-disclosure content generator;
- using self-disclosure relation to bypass unsupported-extra accounting.
