# V2 Validation Labs Contracts

Owner Issue: #352
Parent: #345
Related: #323 / #326 / #327 / #328 / #333 / #361 / #362 / #330 / #363 / #338 / #348 / #364 / #347 / #365 / #434 / #445
Status: Canonical Supplement / Design Completion Gate

## 1. Purpose

#352は、各production Module/Subsystemをwhole-appから切り離しつつ、**production contract / production role / production provider pathのまま**独立検証するための共通Lab/Harness境界を定義する。

Labは品質・latency・concurrency・failureを観測するが、production decision logicを再実装しない。

```text
production DTO / Port / Role / Authority
        ↓
Validation Harness
  fixture/source adapter
  run orchestration
  delay/failure injection
  timeline/metrics capture
  Human evaluation context
        ↓
Export / evidence
```

---

## 2. Lab is not production Authority

Lab may:
- construct typed test fixtures
- call production entrypoints
- inject fake provider/delay/failure
- select production configuration/model policy where explicitly supported
- observe exact input/output/provenance/timing
- collect Human ratings

Lab may not:
- create Lab-only Prompt as production substitute
- create Lab-only semantic matcher as production substitute
- change production DTO semantics
- accept/reject candidate with its own hidden semantic rules
- write current Internal State/Goal/Attention/Memory/Body as production truth
- treat a fixture string as literal production trigger specification

---

## 3. LabRunSpec

Every run is reproducible from an explicit spec.

```text
LabRunSpec
- run_id
- lab_kind
- mode
- target_module
- target_contract_revision
- scenario_id
- fixture_revision
- provider_policy_refs[]
- repeat_count
- delay_injections[]
- failure_injections[]
- seed?
- requested_at
```

Modes:

```text
ISOLATION
ADJACENT
INTEGRATED
SYSTEM_SLICE
```

Mode must be recorded in Export. Isolation evidence cannot be relabeled Integrated.

---

## 4. Fixture authority boundary

Fixtures are test inputs, not production semantic rules.

```text
ValidationFixture
- fixture_id
- fixture_revision
- scenario_category
- typed_inputs
- human_context?
- expected_structural_invariants[]
- source_notes?
```

Natural-language examples:
- may test semantic categories
- must have paraphrase variants where semantic generalization matters
- must not become keyword/regex/allowlist implementation

Deleting/changing one literal example should not destroy production semantic capability if equivalent paraphrases remain.

---

## 5. Production provenance

Each run records exact production origin:

```text
ProductionTargetProvenance
- git_head
- branch
- module_contract_ids[]
- character_definition_revision?
- role_schema_ids[]
- provider_config_revision?
- runtime_policy_revision?
```

Required for Integrated evidence:
- actual production DTO
- actual production Authority/entrypoint
- actual production Prompt/schema for LLM roles
- no shadow implementation inside Lab

If provenance cannot be established, evidence is diagnostic-only.

---

## 6. Common execution envelope

```text
ValidationRunResult
- run_id
- status
- target_provenance
- stage_results[]
- timeline
- metrics
- machine_gate
- human_evaluation?
- blockers[]
- completed_at
```

status examples:

```text
COMPLETED
BLOCKED_UPSTREAM
PROVIDER_FAILED
TIMED_OUT
CANCELLED
HARNESS_FAILED
```

Harness failure and product failure are distinct.

---

## 7. Timeline contract

Shared timeline event:

```text
ValidationTimelineEvent
- event_id
- run_id
- stage
- event_kind
- logical_work_id?
- source_context_revision?
- goal_revision?
- attention_revision?
- priority?
- timestamp
- status_metadata
```

Common event kinds include:
- received
- queued
- started
- completed
- cancelled
- stale
- superseded
- committed
- presented
- external_observation

Provider latency and queue wait are separate metrics.

---

## 8. Delay / failure injection

Harness may wrap Ports with deterministic fake delay/failure adapters.

```text
DelayInjection
- target_stage
- duration
- activation_count/rule

FailureInjection
- target_stage
- closed_failure_kind
- activation_count/rule
```

Injection must not modify production Domain logic.

Use cases:
- Meaning 10s while Body/playback continues
- Reflection 20s while foreground conversation continues
- Verifier delay while safe Performance/TTS prep runs
- Body Planner delay while realtime Body continues
- Streaming API delay while Core continues

---

## 9. Concurrency evidence

A run that claims non-blocking behavior records overlap, not only total duration.

```text
WorkInterval
- work_id
- lane
- started_at
- completed_at
- status
```

Required assertions can state:
- B started before A completed
- playback duration increase did not shift next generation start by same duration
- foreground work completed while background role remained pending

Avoid deriving concurrency PASS from log message ordering alone when timestamped interval evidence is available.

---

## 10. Machine Gate boundary

Machine gates use production/closed deterministic acceptance criteria.

Examples:
- schema validity
- revision freshness
- #363 semantic acceptance
- queue bound
- no pending tasks
- timing overlap

Machine gate may not auto-claim:
- naturalness
- Character fidelity
- subjective animation quality
- visual usability

Those require Human Verification where specified.

---

## 11. Human Evaluation Context

When Human evaluation depends on context, Lab must present enough **source-grounded context** to judge the output.

The #434 finding generalizes to:

> an isolated output without its actual situation/inputs is insufficient for context-fit judgment.

Human context may include:

```text
HumanEvaluationContext
- scenario summary
- recent relevant interaction / event summary
- available facts/evidence
- target intent / response role
- required/forbidden constraints
- actual generated output
- observable runtime result
```

Rules:
- context comes from fixture/production inputs; do not invent after generation.
- Human-only explanatory text does not silently become extra LLM input.
- machine PASS result should be collapsible/blinded where it could bias subjective rating.
- exact production provenance remains available.

---

## 12. Human rating contract

Common rating states:

```text
UNRATED
PASS
FAIL
NOT_APPLICABLE
```

Possible dimensions vary by Lab.

Character Language example:
- naturalness
- Yura fidelity
- natural self/restraint
- context adaptation
- variation (only when repeat_count sufficient)

Body example:
- continuity
- full-body coordination
- natural motion
- no Home reset
- gaze/blink/breath quality

Human score never overrides semantic/physical truth Authority.

---

## 13. Blind comparison

For model/policy comparison, Lab may hide labels during Human evaluation.

Requirements:
- stable randomization/assignment ID
- model identity revealed only after rating where appropriate
- all candidate provenance retained in Export
- no hidden candidate editing

---

## 14. Export contract

Export supports JSON and human-readable Markdown projection.

Must include where applicable:
- run spec
- git/provenance/revisions
- exact typed inputs
- exact typed outputs
- provider-safe metrics
- machine gates
- Human ratings/comments
- timeline
- degradation/failures

Must not include:
- API keys
- Authorization headers
- raw provider SDK objects
- unsafe raw exception/body
- unrelated private conversation history

Export is evidence artifact, not production state.

---

## 15. Provider diagnostics

Labs consume safe operational diagnostics from Infrastructure contracts (#437 etc.).

Provider failure category, status, attempts and safe request ID can be shown where permitted.

Lab must not duplicate provider exception mapping.

Provider health and product semantic/quality result are separate axes.

---

## 16. Character Language Lab policy (#434)

#434 remains a specialized implementation of this framework.

Formal Human Character quality is deferred until at least the real speech path exists:

```text
#362 SpeechSemanticPlan
→ #330 CharacterUtterance
→ #363 semantic observation
→ #331 SpeechPerformancePlan
→ #348 Speech Runtime
→ #358 actual TTS
→ actual Presentation
```

Isolation generation remains useful for diagnosis but is not final Human conversational quality evidence.

Human view must show actual conversation/situation context before rating context adaptation.

---

## 17. Streaming semantic harness

For #347/#396:
- prepare/start/end request semantic categories
- state report categories
- multiple paraphrases per category
- word order / politeness / colloquial / ellipsis / contextual reference
- provider observation vs user report provenance
- no Actual Fact before execution/observation
- no finite matcher outside #326

The Lab invokes production #326 path; it does not implement Streaming keywords.

---

## 18. Body validation harness

Uses production Body DTOs and fake/real providers.

May provide:
- typed BodyIntent fixture
- fake slow Motion Planner
- Stick renderer adapter
- actual BodyPoseFrame visualization

Must not implement a second body motion decision engine in JavaScript/UI.

Stick model is a renderer/visualizer of production Body output.

---

## 19. Game realtime harness

Must verify:
- Game frame loop survives slow Executive/Character/TTS
- bounded salient event publication
- strategy revision update
- quit/cancel latency
- telemetry burst non-starvation

Fake game environment is allowed if it exercises production Game Skill runtime interface.

---

## 20. Lab security

- credentials server-side
- Basic Auth/future auth as deployment concern
- public health endpoint exposes no sensitive state
- `/api/run`/exports protect secrets
- uploaded fixture/data treated as untrusted
- Lab cannot execute arbitrary shell/code from fixture

---

## 21. Lab lifecycle

Lab startup failure does not affect Core production runtime.

Each run owns/cancels all spawned tasks.

Run cancel/shutdown:
- stop new stage admission
- cancel interruptible fake/provider work
- collect terminal statuses
- pending task 0

Repeated runs do not leak provider clients/tasks.

---

## 22. Required framework tests

- production provenance captured
- Isolation cannot claim Integrated
- fixture does not become trigger rule
- exact production entrypoint used
- injected delay preserves Domain behavior
- timeline ordering/overlap correct
- machine vs Human gate separation
- Human context sourced before generation
- secret-safe Export
- provider diagnostic safe projection
- run cancellation pending task 0
- schema/version mismatch blocker
- blind comparison identity integrity

---

## 23. #445 Gate

Validation Lab implementation/extensions remain frozen until #445 D1-D9 and final user confirmation PASS.
