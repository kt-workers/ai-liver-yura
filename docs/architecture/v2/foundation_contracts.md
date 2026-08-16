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

Every present revision value is a non-negative **integer revision number** at the runtime boundary. Python `bool` is intentionally excluded even though `bool` subclasses `int`; `True` must not silently become revision `1`, and `False` must not become revision `0`. Floating-point, string, or other integer-like/untyped values are also rejected rather than coerced. This keeps serialized revisions numeric and prevents equality/order checks from conflating boolean state with a revision generation.

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
- Commitment transition
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

A command is a request/intent to execute. It is **not** evidence that execution started, became observable, was applied, or completed.

## 9. CapabilityDescriptor / CapabilityRequirement

`CapabilityDescriptor` is a provider-independent availability snapshot:

- capability identity/type
- supported operation names
- availability: available / degraded / unavailable / unknown
- monotonic/non-negative descriptor revision
- immutable JSON-like attributes

Descriptor `revision` follows the same strict runtime integer rule as `RevisionVector`: it must be a non-negative value whose concrete Python type is `int`; booleans, floats, strings, and implicit coercions are rejected.

`CapabilityRequirement` expresses what a command needs without naming a provider. A degraded capability satisfies a requirement only when the requirement explicitly allows degraded operation.

Capability availability does not transfer Executive or Domain authority to the capability provider.

## 10. ExecutionResult lifecycle

Canonical execution statuses:

```text
requested
→ accepted
→ planned? / started
→ observable? / applied?
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

Not every successful execution requires `planned`, `observable`, or `applied`, but a request cannot jump directly from `requested` to `completed`. `observable` and `applied` are alternative typed effect milestones; an operation chooses the milestone that represents its externally relevant execution fact before completion.

Actual execution facts must be represented by execution lifecycle evidence rather than by intent or generated language. `ExecutionResult` is immutable. A transition creates a new snapshot and validates the lifecycle edge. Transition timestamps cannot move backwards, and omitted fact payload/effect references inherit the previous snapshot so already-observed execution facts are not accidentally erased.

### 10.1 Construction authority

`ExecutionResult` creation itself is part of the lifecycle invariant. A caller must not be able to manufacture an `accepted`, `started`, `observable`, `applied`, `completed`, or terminal snapshot merely by choosing a `status` value in the public constructor.

- the public/root construction state is `requested`;
- every non-`requested` snapshot must be created by a validated transition from an existing snapshot;
- the implementation may use a module-private construction proof/token internally so `transition_to()` can construct the next immutable dataclass snapshot after validating the edge;
- callers outside that controlled transition path receive a validation error when attempting direct non-`requested` construction;
- if persistence rehydration is later required, it must use a separately defined trusted rehydration boundary that validates persisted lifecycle evidence rather than reopening unrestricted public construction.

This rule keeps `ExecutionResult` as evidence of lifecycle history instead of allowing a status enum alone to assert an Actual Execution Fact.

### 10.2 Monotonic Actual Effect references

`effect_refs` is part of the recorded Actual Execution Fact. It is not generic stage metadata and must be both immutable and monotonic across the lifecycle.

- construction defensively copies/coerces the supplied collection into the canonical immutable tuple representation before validation/storage;
- later mutation of an adapter-owned list or other mutable collection must not change an existing `ExecutionResult` snapshot;
- duplicate and empty effect references remain invalid after normalization;
- a `REQUESTED` snapshot must have no `effect_refs`; a request cannot claim an Actual Effect before execution;
- new effect references may first be introduced only when the successor status is `OBSERVABLE`, `APPLIED`, or `COMPLETED`;
- 実行継続中に追加の外部effectが後から判明する場合、`OBSERVABLE -> OBSERVABLE`または`APPLIED -> APPLIED`を追加effect snapshotとして許可する。この自己遷移は少なくとも1件の新しい`effect_refs`を必須とし、時刻前進とmonotonic ownershipを通常遷移と同様に検証する。stageを進めず同じ内容を複製するno-op自己遷移は拒否する;
- `COMPLETED` may introduce a first effect directly because `OBSERVABLE` / `APPLIED` are optional lifecycle milestones and `STARTED -> COMPLETED` is valid;
- once an effect reference has appeared, every later snapshot must retain it;
- explicitly supplied transition `effect_refs` are additive to the previously recorded set; supplying `()` or a subset must not erase historical effect facts;
- a transition may add new unique references while preserving the existing order and all previous references;
- terminal `FAILED`, `CANCELLED`, `TIMED_OUT`, or `SUPERSEDED` transitions may inherit prior effect references but must not introduce a brand-new effect reference. If an external effect actually occurred before terminal failure, the lifecycle must record `OBSERVABLE` or `APPLIED` before the terminal transition.

`details` has different semantics. When omitted it inherits the previous snapshot, but an explicitly supplied `details` mapping may replace stage-specific annotations. Only `effect_refs` carries the monotonic Actual Effect evidence contract.

## 11. AsyncWorkResult

Long-running preparation work can finish after its assumptions are no longer current. `AsyncWorkResult` therefore distinguishes:

- succeeded
- failed
- cancelled
- timed_out
- stale
- superseded
- rejected

It transports both `started_at` and `completed_at` timing facts required by the concurrency contract. `started_at` is optional for non-success results because rejected/cancelled/stale/superseded/timed-out/failed work may terminate before provider/execution start and must not invent a start fact. When present it must be timezone-aware and not later than `completed_at`.

A `succeeded` result necessarily represents work that started. Therefore `status == succeeded` requires a non-null, timezone-aware `started_at` no later than `completed_at`.

Only `succeeded` is inherently committable. Even a succeeded result is still subject to owning-module authority/precondition validation before an external/domain commit.

`stale` and `superseded` are not rewritten as success and must never become latest-context facts merely because a Provider returned a payload.

## 12. Serialization, temporal ordering, and immutability

Contracts expose `to_dict()` using JSON-compatible values.

Nested payload/attribute/precondition/result data is recursively frozen at construction time so caller mutation after construction cannot rewrite a recorded contract snapshot.

JSON object keys must be strings. A runtime/untyped mapping containing a non-string key is rejected during recursive freezing instead of being accepted into a snapshot that cannot be represented faithfully as a JSON object. The complete top-level mapping supplied to `EventEnvelope.payload`, `CapabilityDescriptor.attributes`, and `ExecutionResult.details` must pass through the same recursive key/value validation; validating only their nested values is insufficient.

JSON-compatible numeric values must be finite. IEEE-754 non-finite values (`NaN`, positive infinity, negative infinity) are rejected during recursive freezing rather than being allowed into an apparently valid Domain snapshot that strict JSON serialization cannot transport.

Collection-valued fact fields that are canonically immutable must take an owned immutable copy during construction. Static type annotations alone are not treated as a runtime immutability boundary. For the current Foundation contracts this includes at minimum:

- `CapabilityDescriptor.operations`
- `ExecutiveDecision.source_event_ids`
- `ExecutiveDecision.intent_refs`
- `SystemCommand.preconditions`
- `SystemCommand.required_capabilities`
- `ExecutionResult.effect_refs`

Caller-owned lists or other mutable sequences passed through an untyped/adapter boundary must therefore be normalized to tuples before validation and storage.

Revision/count-like fields that represent generations are not generic JSON numbers: they use strict integer validation at construction. In particular, `bool` must never pass revision validation merely because Python considers it an `int` subclass.

Timestamps are required to be timezone-aware. Whenever two aware timestamps are ordered against each other, the ordering is defined by their **absolute instant**, not by local wall-clock fields. Python's direct comparison of two datetimes sharing the same `tzinfo` object can ignore UTC-offset/fold differences during a daylight-saving fall-back, so Foundation ordering checks must normalize both operands to UTC before comparing. This applies to at least:

- `SystemCommand.issued_at` vs `deadline_at`;
- successive `ExecutionResult.occurred_at` values;
- `AsyncWorkResult.started_at` vs `completed_at`.

The original timezone-aware values may be retained and serialized with their offsets; UTC normalization is required for ordering semantics, not for replacing the recorded timestamp representation.

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
- timestamp ordering uses UTC absolute instants, including same-zone DST fall-back fold cases
- revision fields require concrete non-negative integers and reject `bool`, float, string, and negative values
- immutable nested JSON-like payloads
- non-string JSON object keys are rejected at both top-level and nested JSON-like mappings
- NaN/+Infinity/-Infinity are rejected from JSON-like payloads
- invalid execution lifecycle rejection
- direct non-`requested` `ExecutionResult` construction is rejected
- a `REQUESTED` `ExecutionResult` cannot contain effect references
- valid `ExecutionResult.transition_to()` paths continue to construct immutable successor snapshots
- previously recorded effect references cannot be erased by explicit or omitted successor input
- new effect references can be introduced only at `OBSERVABLE`, `APPLIED`, or `COMPLETED`
- 継続するobservable/applied effectは新規effect必須の同一milestone遷移で記録し、no-op自己遷移を拒否する
- terminal failure/cancellation/stale-style execution outcomes preserve prior effect refs but cannot invent new ones
- all canonical tuple-valued Foundation fact fields own immutable tuple copies
- stale/superseded async results are non-committable
- successful async work requires `started_at`
- non-success async work may omit `started_at` when it terminated before start
- async work timing preserves required completion ordering
- capability availability/operation matching
- no concrete Provider/SDK imports in `app/domain/contracts/`
