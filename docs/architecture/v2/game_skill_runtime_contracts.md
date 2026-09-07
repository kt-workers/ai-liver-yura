# V2 Game Skill Runtime Contracts

Owner Issue: #365
Parent: #345
Upstream: #328 / #366 / #333 / #361 / #329
Related: #344 / #347 / #352 / #360 / #445
Status: Canonical Supplement / Design Completion Gate

## 1. Purpose

#365は、Coreが選んだ高レベルGame Goal / Strategyと、ゲーム固有の高速認識・戦術・frame-level操作を分離する。

```text
Core Executive / Goal / Planner
→ typed GameSessionIntent / StrategyUpdate
→ Game Skill Runtime
   perception
   tactical state
   frame-level action selection
   controller timing
→ game environment
→ bounded GameObservationEvent / GameExecutionReport
→ Core Appraisal / Attention / Executive / #329
```

Core Executive LLMを毎frame呼ばない。

---

## 2. Authority boundary

### Core owns

- gameを始める/続ける/やめる
- session参加/離脱
- participant/target high-level choice
- high-level Goal / Commitment
- high-level Strategy adoption/change
- Streamingと同時に行うか
- game resultをどう評価するか
- game eventについて話すか

### Game Skill owns

- game-specific state perception
- fast opponent/environment estimate
- tactical planning subordinate to current high-level strategy
- frame/tick-level action selection
- controller/output timing
- pathfinding/search/RL/VLM/deterministic skill processing
- game-specific telemetry compression
- bounded salient observation/result generation

### Game Skill does not own

- Executive Goal Authority
- Goal/Commitment State mutation
- Attention State mutation
- raw user conversation meaning
- Character final speech
- stream lifecycle decision

---

## 3. Session identity

```text
GameSessionIntent
- session_request_id
- decision_id
- activity_id
- game_capability_id
- participant_refs[]
- goal_id
- goal_revision
- strategy_revision
- high_level_goal_ref
- high_level_strategy
- stream_context_ref?
- source_context_revision
- priority
- interruptibility
- created_at
```

`high_level_strategy` is committed typed/Core-provided strategy semantics, not raw user text.

Game Skill must not invent a different high-level Goal.

---

## 4. Session lifecycle

```text
REQUESTED
ADMITTED
INITIALIZING
ACTIVE
PAUSED
ENDING
ENDED
FAILED
CANCELLED
```

Game external environment connection/readiness may have its own adapter lifecycle and must not be conflated with Core Goal lifecycle.

Session start intent is not proof the game/session actually started.

---

## 5. Strategy updates

Core may send asynchronous strategy update:

```text
GameStrategyUpdate
- update_id
- session_id
- goal_id
- expected_goal_revision
- strategy_revision
- strategy_payload
- source_decision_id
- created_at
```

Rules:
- strategy revision monotonic.
- stale `goal_revision` update rejected/revalidated.
- older strategy revision cannot overwrite newer.
- frame loop need not pause while new strategy is being prepared; current accepted strategy remains active until atomic swap.
- update cannot silently change session participants/game capability/Goal identity.

---

## 6. Realtime state

Game-specific large state remains inside Skill Runtime.

```text
GameSkillState
- session_id
- game_state_revision
- strategy_revision
- local tactical state
- last_action_ref?
- observed_at
```

Do not copy full frame/world state into Core Event stream.

Core receives bounded summaries/events only.

---

## 7. Perception boundary

Game adapter may consume:
- game API/state
- screen/video frames
- controller telemetry
- game-specific events

Perception models may be deterministic/VLM/etc.

Outputs remain game-internal until projected to bounded typed observations.

No raw user conversation enters frame-level agent to decide Core intent.

---

## 8. Frame-level action contract

Logical action:

```text
GameFrameAction
- action_id
- session_id
- game_state_revision
- strategy_revision
- action_kind
- parameters
- intended_at
- deadline?
```

Action kind/parameters are game-adapter-specific behind Game Skill boundary; they are not Foundation Executive intents.

Core does not need to understand joystick/key/frame action details.

---

## 9. Action execution truth

Selected frame action ≠ applied action.

Adapter returns:

```text
GameActionReport
- action_id
- status
- effect_state
- applied_at?
- game_state_revision_after?
- sanitized_diagnostics[]
```

Actual game Activity/Skill execution evidence can be aggregated and returned to #329.

Timeout/cancel after an external input may have been applied must preserve ambiguous/applied effect state.

`select()` のawait完了後からcontroller適用直前まで、およびcontroller応答後には、live sessionの
`ACTIVE` lifecycle、strategy revision、game state revisionを再照合する。pause、end、cancel、
strategy更新でselection世代が変わったactionを新たに適用してはならない。

controllerがすでに `APPLIED` と確認したactionは、strategy/lifecycleがそのawait中に変化していても、
確認済み `game_state_revision_after` をlive stateへ単調に反映する。一方、selection世代が古くなった
reportは `STALE` として返す。`STALE` のeffect truthは `APPLIED` または `AMBIGUOUS` に限定し、
元の `NOT_APPLIED` / `FAILED` をcontract不正な組合せのまま置換しない。

---

## 10. Salient event projection

Game Skill does not send every frame to Appraisal/Attention.

```text
GameObservationEvent
- event_id
- session_id
- category
- salience_hint
- subject_refs[]
- game_state_revision
- observed_at
- bounded_payload
```

Possible structural categories may include:
- session state change
- score/result milestone
- opponent significant action
- danger/opportunity signal
- objective change
- match completed

Category is game event structure, not natural-language trigger.

#327/#333 decide subjective salience/attention from typed evidence.

---

## 11. Aggregation / backpressure

High-frequency events use:
- coalescing
- periodic summary
- thresholded salient event
- bounded queue
- latest-state snapshot

Do not queue every frame indefinitely.

When Core is busy, Game frame loop continues independently; lower-value telemetry may coalesce/drop according to policy.

---

## 12. Attention integration

Game Skill emits bounded observation/salience hints only.

```text
Game observations
→ Appraisal
→ #333 Attention
→ optional Executive trigger
```

Game Skill cannot mark itself foreground directly.

When Game is foreground and Streaming secondary:
- direct user interaction can become high-priority Core interrupt
- Game frame loop continues while Core handles user interaction
- Core may later send pause/strategy/quit intent

---

## 13. Streaming integration

Game Skill and Streaming are peer Subsystems.

```text
Game Skill → bounded game events → Core
Streaming → bounded comment/stream events → Core
Core Attention / Executive / Speech coordinates both
```

Forbidden direct shortcut:

```text
Game Skill → Character final speech → Streaming output
```

Game event narration goes through Core Speech path.

Streaming/TTS/comment delays do not stall game frame loop.

---

## 14. Skill AI policy

Game-specific AI may use:
- RL
- search/planning
- VLM
- small/large LLM where latency permits
- deterministic heuristics
- hybrids

Choice is Skill implementation concern.

No requirement that one global cognitive LLM decide every action.

Long-running tactical AI result uses state/strategy revision; stale result discarded.

---

## 15. Capability / Plugin relation

Game session external capability may be discovered through generic Capability mechanisms, but the persistent realtime Skill Runtime is not reduced to a single Plugin invoke call.

#344 Plugin architecture may expose lightweight game operations/capability discovery.

#344は#365 Game Skill Runtimeそのもののdirect dependencyではない。Plugin 0件でもGame Skill contractは成立する。

#365 owns dedicated realtime session processing where needed.

Provider/SDK specifics remain Game Subsystem adapters.

---

## 16. Pause / quit / cancel

Core high-level request:
- PAUSE
- RESUME
- END/QUIT

Game Skill applies with bounded latency according to game capability.

Rules:
- new quit intent supersedes future tactical work.
- already-applied controller action is not erased.
- pending long-running tactical/model tasks cancel when safe.
- session end reports external result/effect state.
- Core Goal complete/abandon still requires owner transition, not automatic Skill mutation.

---

## 17. Failure / degraded

Possible failure states:
- game unavailable
- perception degraded
- controller unavailable
- strategy unsupported
- reconnecting
- realtime deadline miss

Skill reports typed availability/result to Core.

Do not:
- make up successful actions
- continue unsafe stale controls
- shut down Core because game failed

Executive can choose next behavior from failure facts.

---

## 18. Concurrency requirements

- Executive LLM 5s/20s delay: frame loop continues.
- Character/TTS/Verifier delay: frame loop continues.
- Reflection delay: frame loop continues.
- Streaming comment burst: frame loop continues.
- direct user interaction: frame loop continues unless Core sends pause/quit.
- strategy update asynchronously swaps without blocking frames unnecessarily.
- telemetry publication cannot starve controller loop.
- shutdown/cancel leaves no Skill-owned pending tasks.

---

## 19. Realtime scheduling

Game frame loop uses game-specific cadence/deadline rather than Core event-loop turn cadence.

Requirements:
- monotonic clock
- bounded work per frame/tick
- deadline miss metrics
- no catch-up explosion
- slow optional inference skipped/deferred when it cannot meet realtime deadline
- safe fallback strategy is game-specific and must remain subordinate to accepted high-level Goal; fallback cannot invent new Core Goal.

---

## 20. Observability

Metrics/events:

```text
game_session_requested/started/ended
game_frame_heartbeat
game_state_revision_changed
strategy_update_received/applied/stale
tactical_work_started/completed/cancelled/stale
action_selected/applied/failed
observation_published/coalesced/dropped
```

Metrics:
- frame interval/jitter
- deadline miss rate
- perception latency
- action latency
- strategy swap latency
- observation rate/aggregation ratio
- queue depth/drop count

No credentials/raw giant game state in Core trace.

---

## 21. Required tests

- session lifecycle
- stale goal revision reject
- strategy revision monotonic
- atomic strategy swap
- fake realtime frame loop
- frame action selected vs applied distinction
- timeout after possible effect
- event aggregation/bounded queue
- slow Executive/Character/TTS independence
- Streaming concurrent operation
- direct user Attention interrupt without frame stop
- quit/cancel bounded latency
- unavailable/degraded game Core continuation
- no raw user conversation semantic bypass
- no direct Character speech generation
- shutdown pending tasks 0

Real game/device operation remains Human/Integration Verification.

---

## 22. #445 Gate

#445 Design Completion Gate / D10は完了済み。Game Skill implementationの設計freezeは解除されている。現在の残Gateは#365自身の実ゲーム/実操作Human Verificationである。
