# AI Liver ゆら V2 Design Reconciliation Checkpoint

Checkpoint date: 2026-08-12
Root: #317
Branch: `rebuild/v2-foundation`
Product code status: **FROZEN — no V2 product implementation yet**

## 1. Purpose

V1の責務分離・failure knowledgeを維持しつつ、V2を「自由意志をもったゆら」という最終目標へ再設計した現在地点を固定する。

このCheckpointはResume候補発見用のsummaryではなく、Resume GateでGitHub live canonicalと照合するためのV2 Design checkpointである。

## 2. Canonical Set

- `system_architecture.md`
- `brain_architecture.md`
- `cognitive_llm_architecture.md`
- `goal_commitment_architecture.md`
- `concurrency_architecture.md`
- `speech_pipeline_architecture.md`
- `body_architecture.md`
- `plugin_architecture.md`
- `subsystem_architecture.md`
- `legacy_migration_matrix.md`
- `project_sync_manifest.md`
- `project_sync_runbook.md`

## 3. Final Goal

ゆらはUser Messageへの返信器ではない。

- userとの会話
- YouTube等のVTuber配信
- userとのgame対戦
- 配信中game実況/対戦
- 観察 / 探索 / 沈黙 / 休止
- future Activities / Capabilities

を、Internal State・Memory・Relationship・Goal/Commitment・Attention/Focus・Activity/Execution Factから自ら選択する継続主体を目指す。

## 4. Authority Certificate

```text
External NL Meaning                  #326 Input Meaning
Subjective Appraisal / State         #327
Conscious Goal / Action selection    #328 Executive ONLY
Current Goal / Commitment            #366
Attention / Focus / Turn scheduling  #333
Complex Goal Planning                #361
Activity / Actual Execution Facts    #329
What to say                          #362
How to say                           #330
Semantic Observation                 #363
Speech Runtime                       #331 / #348
Body                                 #335 - #341
Memory Store / Retrieval             #332
Reflection / Memory Candidate        #364
Game realtime skill                  #365 (subordinate to Core Goal)
```

## 5. LLM Design Certificate

- system-wide fixed 4 LLM rule: **withdrawn**
- fixed Role numbering: **withdrawn**
- Role count is not an architecture invariant
- responsibility separation remains required
- `Logical Role count != API call count`
- `Responsibility graph != Runtime invocation graph`
- simple paths may skip/non-LLM specialized roles
- complex paths may invoke dedicated roles
- independent work may fan-out / run concurrently
- LLM free text does not directly own Domain State / Actual Fact
- Semantic Verifier remains an independent Observer where required

## 6. Non-blocking Runtime Certificate

Causal cognition is not one global blocking cycle.

Required:

- slow LLM does not block unrelated lanes
- Speech playback does not block next generation
- TTS does not block cognition
- Body realtime does not wait for Motion LLM / Character / TTS
- Reflection does not block foreground interaction
- Goal/Attention mutation is not a Core-global lock
- Game frame loop is independent from Executive LLM latency
- Streaming burst is bounded/aggregated
- foreground interaction cannot be starved by background cognition
- stale context / goal / attention revisions are not blindly committed

## 7. Persistent Goal / Commitment Certificate — #366

Executive decisions are not stored only inside an LLM context.

```text
Executive Decision
→ validated Goal / Commitment transition
→ persistent typed Goal State #366
→ later Attention / Executive / Planner
```

- survives turns/context truncation
- Goal != Activity
- Goal != Memory
- Commitment != Character utterance
- stale `goal_revision` Plan rejected

## 8. Attention / Focus Certificate — #333

Simultaneous game/stream/conversation events are not all sent directly to Executive.

```text
Appraisal salience
+ Executive attention intent
+ user/turn priority
→ bounded AttentionFocusState / scheduling #333
→ eligible Executive triggers
```

Example:
- foreground: game match
- secondary: Streaming aggregated comments
- high-priority interrupt: direct user interaction
- background: Reflection

#333 does not decide NL meaning, Goal, Speech content, or Internal State.
Body gaze is a projection of Focus, not cognitive Attention authority.

## 9. Body Certificate

- Body is Core, not Plugin
- Canonical model is renderer-independent and 3D-capable
- current pose / velocity / continuity
- no preset-only main path
- no forced Home/Neutral reset
- generative Motion Planning, LLM only when appropriate
- deterministic Solver/Controller owns physical constraints
- gaze/blink/breath/viseme/subtle realtime layers
- Motion Planner delay does not freeze Body realtime
- Character and Body are sibling realizers from Executive

## 10. Plugin / Subsystem Certificate

Plugin:
- structural extension contract, not merely optional capability
- does not own Core-native State / Authority
- Providers/Adapters are not Plugins merely because external

Subsystem / Skill AI:
- Streaming, Game Skill, Avatar, GUI, Labs, Tooling are outside Core
- Game Skill may use LLM/VLM/RL/search/deterministic/hybrid AI
- Skill AI executes selected Activity; it does not become Yura's Goal Authority

## 11. V1 Migration Certificate

`legacy_migration_matrix.md` retains initial:
- 44 Legacy Open Issue mappings
- 23 initial Open PR mappings

and additionally records:
- non-serial LLM latency failure class
- persistent Goal/context-loss failure class
- bounded Attention/high-frequency event overload failure class
- V1 semantic realization/verifier lessons
- Body free-motion lessons
- shutdown/degradation/validation lessons

No old product code is to be merged/cherry-picked into V2.

## 12. Project Management State

#319 Manifest/Runbook are current through #366/#333.

Actual Projects v2 field mutation / formal Parent-Subissue sync is still Blocked because this ChatGPT environment currently has:
- no Projects v2 mutation connector action
- no formal Sub-issue mutation connector action
- no authenticated `gh` CLI/token

Do not guess old field IDs.
Run `project_sync_runbook.md` in a `gh`-authenticated environment.

## 13. Design Reconciliation Status

Completed:
- [x] V1 requirement/failure reconciliation
- [x] System / Brain / Cognitive / Goal / Concurrency design
- [x] Speech / Body / Plugin / Subsystem design
- [x] variable LLM roles / Single Executive
- [x] non-serial runtime
- [x] persistent Goal #366
- [x] Attention/Focus #333
- [x] Game Skill #365
- [x] current V2 Issue terminology/Authority audit
- [x] #207 V2 canonical authority checkpoint
- [x] Project sync Manifest / Runbook

Pending:
- [ ] **user confirmation of V2 canonical architecture**
- [ ] #319 actual Projects v2 / formal Parent-Subissue mutation in capable environment

## 14. Freeze Gate

**Do not start V2 product code implementation before user confirmation of the final canonical architecture.**

After user confirmation, re-fetch GitHub live and pass the normal Resume/Implementation Gate before creating any implementation lineage.
