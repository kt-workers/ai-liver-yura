# V2 Foundation Typed Contracts

Status: Implementation Contract / Issue #321
Parent architecture:
- `docs/architecture/v2/system_architecture.md`
- `docs/architecture/v2/concurrency_architecture.md`

Implementation package: `app/domain/contracts/`

## 1. Purpose

Issue #321 defines the smallest shared Domain contracts that later V2 modules can depend on without depending on a concrete Provider, SDK, renderer, game, TTS engine, or LLM implementation.

The Foundation transports identity, references, revisions, authority, preconditions, lifecycle facts, and capability availability. It does **not** decide natural-language meaning, goals, attention, character language, body motion, or game actions.

## 2. Dependency rule

```text
Domain contracts
    ↑
Application / Runtime coordination
    ↑
Ports
    ↑
Adapters / Providers / UI / External systems
```

The contracts must stay usable when OpenAI, FastAPI, VOICEVOX, Live2D, databases, game runtimes, and all plugins are absent.

## 3. EventEnvelope

`EventEnvelope` is the common transport envelope for external/internal facts entering typed runtime lanes.

Fields:

- `event_id`: unique event identity
- `event_type`: typed-name boundary; meaning remains owned by the producing/consuming Domain module
- `source`: logical source, not a concrete SDK object
- `occurred_at`: timezone-aware occurrence time
- `trace_id`: end-to-end trace identity
- `correlation_id?`: optional cross-event grouping
- `causation_event_id?`: direct causal event reference
- `revisions`: source/goal/attention consistency primitives
- `payload`: immutable JSON-like data only

The envelope must not contain provider objects or perform raw natural-language interpretation.

## 4. RevisionVector

`RevisionVector` carries only revision primitives needed to reject stale work.

```text
source_context_revision: required
goal_revision: optional
attention_revision: optional
```

A missing Goal/Attention revision means the work does not claim consistency against that owner. It does not mean revision zero.

Revision comparison is a consistency mechanism, not semantic authority.

## 5. AuthorityRef and PreconditionRef

`AuthorityRef` records which logical owner authorized a decision/command and its authority scope. It does not grant authority by itself; the owning module/runtime must validate the reference.

`PreconditionRef` is a transport expression:

- stable precondition id
- predicate name
- subject reference
- immutable expected JSON value

Foundation does not evaluate arbitrary predicates. Owning modules register/interpret predicates at their boundary.

## 6. IntentRef

`IntentRef` distinguishes high-level intent families without embedding realization-specific payloads.

Initial kinds:

- Speech
- Body
- Activity
- Plugin
- Attention
- Goal transition
- System

The referenced intent payload belongs to the owning Domain module. For example, Body-specific joint values do not enter `SystemCommand` merely because the command references a Body intent.

## 7. ExecutiveDecision

`ExecutiveDecision` is a high-level decision envelope, not an LLM response schema.

It carries:

- `decision_id`
- source event references
- zero or more typed intent references
- Executive authority reference
- consistency revisions
- creation time

The Foundation does not decide whether an intent should exist. Executive #328 owns conscious Goal/Action selection.

## 8. SystemCommand

`SystemCommand` requests execution of one previously selected intent.

It carries:

- command / decision identity
- one `IntentRef`
- authority reference
- issue time / optional deadline
- revisions
- precondition references
- required capability requirements

A command is a request/intent to execute. It is **not** evidence that execution started, became observable, or completed.

## 9. CapabilityDescriptor / CapabilityRequirement

`CapabilityDescriptor` is a provider-independent availability snapshot:

- capability identity/type
- supported operation names
- availability: available / degraded / unavailable / unknown
- monotonic/non-negative descriptor revision
- immutable JSON-like attributes

`CapabilityRequirement` expresses what a command needs without naming a provider. A degraded capability satisfies a requirement only when the requirement explicitly allows degraded operation.

Capability availability does not transfer Executive or Domain authority to the capability provider.

## 10. ExecutionResult lifecycle

Canonical execution statuses:

```text
requested
→ accepted
→ planned? / started
→ observable?
→ completed
```

Terminal alternatives:

```text
rejected
unsupported
failed
cancelled
timed_out
superseded
```

Not every successful execution requires `planned` or `observable`, but a request cannot jump directly from `requested` to `completed`. Actual execution facts must be represented by execution lifecycle evidence rather than by intent or generated language.

`ExecutionResult` is immutable. A transition creates a new snapshot and validates the lifecycle edge.

## 11. AsyncWorkResult

Long-running preparation work can finish after its assumptions are no longer current. `AsyncWorkResult` therefore distinguishes:

- succeeded
- failed
- cancelled
- timed_out
- stale
- superseded
- rejected

Only `succeeded` is inherently committable. Even a succeeded result is still subject to owning-module authority/precondition validation before an external/domain commit.

`stale` and `superseded` are not rewritten as success and must never become latest-context facts merely because a Provider returned a payload.

## 12. Serialization and immutability

Contracts expose `to_dict()` using JSON-compatible values.

Nested payload/attribute/precondition/result data is recursively frozen at construction time so caller mutation after construction cannot rewrite a recorded contract snapshot.

Timestamps are required to be timezone-aware.

## 13. Explicit non-goals

Issue #321 does not implement:

- Runtime queues/task groups/backpressure scheduling (#322)
- LLM role Provider contracts/structured output invocation (#323)
- Input Meaning (#326)
- Appraisal/Internal State (#327)
- Executive decision logic (#328)
- Activity runtime (#329)
- Attention state/scheduling (#333)
- Goal/Commitment state (#366)
- Speech/Body/Game realization payloads

Those modules depend on these primitives but retain their own Domain ownership.

## 14. Unit acceptance

Issue #321 Unit Gate requires:

- JSON serialization of all public envelopes/snapshots
- timezone-aware event/command/result timestamps
- non-negative revision validation
- immutable nested JSON-like payloads
- invalid execution lifecycle rejection
- stale/superseded async results are non-committable
- capability availability/operation matching
- no concrete Provider/SDK imports in `app/domain/contracts/`
