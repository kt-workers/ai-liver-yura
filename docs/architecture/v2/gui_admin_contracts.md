# V2 GUI / Administration Contracts

Owner Issue: #351
Parent: #345
Upstream: #334 / #341 / #344
Related: #350 / #352 / #445
Status: Canonical Supplement / Design Completion Gate

## 1. Purpose

#351は、Core / Body / Plugin / Subsystemの状態・設定・診断を、**typed Read Modelと明示されたAdmin Command APIだけ**を通して可視化・操作するGUI/Admin Subsystemを定義する。

```text
Core / Subsystem owners
→ typed Read Model publication
→ GUI/Admin

GUI/Admin
→ typed Admin Command
→ owning command boundary
→ owner validation / mutation
→ new Read Model
```

GUIはDomain Authorityではない。

---

## 2. Authority boundary

GUI may:
- display current read models
- request allowed configuration changes
- request lifecycle/admin operations
- display sanitized diagnostics/health
- export safe diagnostic/validation data where explicitly supported

GUI may not:
- directly mutate Internal State
- directly set Emotion/Desire/Drive
- decide Executive Goal/Action
- directly mutate Goal/Commitment
- directly set Attention/Focus
- directly create Activity execution fact
- directly write BodyState/joint pose
- alter Character Definition by editing Runtime Profile
- infer provider success from button press

Button click is a request, not a successful state transition.

---

## 3. Read Model boundary

Every screen reads purpose-specific immutable DTOs, not live Domain object references.

Common envelope:

```text
AdminReadModelEnvelope
- model_kind
- schema_version
- source_owner
- source_revision
- generated_at
- payload
- availability
- degraded_reasons[]
```

Rules:
- payload is bounded for screen purpose.
- no writable alias to owner state.
- source revision visible for stale detection.
- raw provider SDK objects excluded.
- secrets excluded.
- prompts/raw private payload included only if a dedicated safe debugging contract explicitly permits it; default is exclude.

---

## 4. Read Model categories

Initial categories may include:

```text
SYSTEM_HEALTH
RUNTIME_LIFECYCLE
INTERNAL_STATE_SUMMARY
GOAL_COMMITMENT_SUMMARY
ATTENTION_FOCUS_SUMMARY
ACTIVITY_SUMMARY
SPEECH_RUNTIME_SUMMARY
BODY_SUMMARY
PLUGIN_CAPABILITY_SUMMARY
SUBSYSTEM_HEALTH_SUMMARY
PROVIDER_DIAGNOSTIC_SUMMARY
CONFIGURATION_SUMMARY
```

The Read Model schema must reflect owner semantics; GUI must not flatten all state into arbitrary generic key/value JSON and then infer meaning client-side.

---

## 5. Admin command boundary

GUI writes only through typed commands.

```text
AdminCommandRequest
- command_id
- command_kind
- target_owner
- target_ref?
- expected_revision?
- payload
- requested_at
- actor_context
```

```text
AdminCommandResult
- command_id
- status
- owner_revision_before?
- owner_revision_after?
- applied_at?
- failure_code?
- sanitized_message?
```

The concrete command schemas are owned by the target module, not by the GUI.

GUI may not invent a generic `set_state(path, value)` API across Core.

---

## 6. Allowed command classes

Examples of admin-level requests:
- runtime start/stop/reconnect where owner exposes it
- configuration update through versioned config owner
- validation trigger in Lab subsystem
- safe plugin enable/disable request through Plugin lifecycle boundary
- diagnostic refresh

Not allowed as generic GUI commands:
- `set_emotion(joy=1)`
- `set_goal(...)` bypassing Executive/#366
- `move_joint(...)` bypassing Body authority
- `mark_activity_completed` without execution evidence
- `set_stream_live=true`

Development-only simulators may inject fixtures through separate Validation/Test contracts, clearly not production Admin authority.

---

## 7. Optimistic concurrency / stale UI

State-changing Admin commands use owner revision where applicable.

```text
screen reads revision R
→ user requests change expected_revision=R
→ owner currently R+1
→ STALE_ADMIN_VIEW
→ GUI refreshes
```

Do not silently overwrite a newer canonical state from an old browser tab.

Idempotent lifecycle/admin commands should carry command identity for duplicate delivery handling.

---

## 8. Configuration ownership

Configuration UI edits configuration through typed/versioned schemas.

```text
ConfigReadModel
- config_owner
- schema_version
- config_revision
- editable_fields[]
- effective_values
- provenance
```

Rules:
- Character Bible content is not a generic Runtime config form unless the Character authoring workflow explicitly exposes it.
- provider credentials are never returned as current plaintext values.
- secret fields expose configured/not-configured status and replacement action only.
- changes requiring restart/reload report that requirement explicitly.
- invalid field/value fails before owner mutation.

---

## 9. Secret handling

Browser never receives:
- OpenAI API key
- YouTube OAuth token
- GitHub token
- DB password
- Authorization headers
- raw credential files

Secret write flow:

```text
browser secret replacement input
→ TLS/authenticated Admin endpoint
→ secret backend/composition storage
→ sanitized result
```

The secret value is not echoed into Read Model, logs, Export or client state longer than needed.

---

## 10. Authentication / authorization

Production Admin surfaces require explicit access policy.

Initial contract distinguishes:
- public/read-only visualization if intentionally exposed
- operator read access
- operator mutation access
- development/validation-only access

Mutation endpoints are never enabled merely because a UI element exists.

Render/local deployments may use Basic Auth or future auth adapter, but authentication mechanism stays outside Core Domain.

---

## 11. Subscription / realtime updates

GUI can subscribe to Read Model updates via WebSocket/SSE/polling adapters.

Requirements:
- slow/disconnected client does not block owner publication.
- per-client bounded queue/latest-state coalescing for state snapshots.
- event history that must not be lost uses separate bounded history/query contract.
- reconnect fetches latest authoritative snapshot; client cache is not authority.
- schema version mismatch is explicit.

---

## 12. Diagnostics boundary

Safe diagnostics may expose:
- IDs/revisions/status
- timestamps/latencies
- closed failure categories
- provider safe request IDs where allowed
- queue depth/counts
- degradation states

Default exclude:
- raw prompts
- API credentials
- raw provider response bodies
- unbounded conversation text
- unnecessary Memory content
- arbitrary stack traces containing sensitive paths/data

Detailed development diagnostics belong to explicit development tooling contracts, not every production GUI.

---

## 13. GUI screen inventory lifecycle

Existing `gui/*` screens are classified:

```text
PRODUCTION_ADMIN
PRODUCTION_VISUALIZER
VALIDATION_LAB
DEVELOPMENT_TOOL
DEPRECATED
```

Each screen must declare:
- owner Issue
- purpose
- input Read Models
- allowed commands
- deployment mode
- auth requirement
- V2 replacement/supersession if any

Do not update every old screen merely to preserve it. Screens without V2 purpose may be deprecated.

---

## 14. Render / local deployment

UI deployment is a Subsystem concern.

- Core does not know Render URLs/ports.
- environment-specific server configuration stays outside Domain.
- frontend does not embed server credentials/tokens.
- health endpoint may be intentionally unauthenticated only if it reveals no sensitive state.
- admin/data endpoints follow access policy.

---

## 15. Failure / degradation

GUI unavailable:
- Core and other Subsystems continue.

Core/subsystem read model unavailable:
- screen shows typed unavailable/degraded state.
- do not substitute stale cached value without age/provenance indicator.

Command failure:
- display owner failure result.
- button state does not pretend command applied.

---

## 16. Observability

GUI/Admin metrics:
- active connections
- read model publication lag
- dropped/coalesced client updates
- command request/result latency
- stale command rejects
- auth failures (rate-limited/sanitized)
- schema mismatch

Do not log secret payload or full sensitive command body.

---

## 17. Required tests

- immutable Read Model projection
- GUI cannot mutate owner object by alias
- typed command owner validation
- stale revision rejection
- duplicate idempotent command handling
- secret not returned/logged/exported
- disconnected/slow client nonblocking
- reconnect latest snapshot
- schema mismatch handling
- unavailable Core/subsystem screen degradation
- no generic `set_state` authority bypass
- screen classification inventory completeness
- GUI absent Core normal operation

Browser usability/visual correctness remains Human Verification after contract tests.

---

## 18. #445 Gate

GUI/Admin production implementation remains frozen until #445 D1-D9 and final user confirmation PASS.
