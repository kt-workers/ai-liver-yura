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

## 15. 所有者の世代と最終確定の共通契約（#632）

本節は#321・#322の完了済み成果を再定義せず、後発Work #632として追加する設計である。具体的な並行動作・取得順序・所有者への適用条件の正本は[並行動作設計第20節](concurrency_architecture.md#20-所有者の世代更新と最終確定を直列化する632)とする。本節の型と機構は`app/domain/contracts/finalization.py`へ実装し、設計採用だけを製品完成と扱わない。

| 公開契約 | 所有する情報と動作 |
| --- | --- |
| `AuthorityGenerationToken` | 正規所有者の識別子、起動インスタンスの識別子、参加者の識別子、不変な世代番号。正規の参加者が発行したことを検査できる起動中の参照を持つ |
| `AuthorityFinalizationParticipant` | 既存所有者の状態更新と同じ同期境界、現在の世代、利用可能状態、固定した取得順序キーを所有する。読取値とトークンを同一区間で返し、更新・失効を同一区間で公開する |
| `AuthorityReadPublication[T]` | 所有者が返した不変な読取値と、その値の取得時に保護した全参加者のトークン群。複合値の由来を単一の独自リビジョンへ置き換えない |
| `AuthorityFinalizationRequest` | 出典の期待トークン群、確定先の参加者、登録済みの同期確定操作を識別する参照、確定先が検査する入力。参加者の集合を取得前に固定する |
| `AuthorityFinalizationFence` | 固定順序で必要な参加者を取得し、全期待世代を検査して、確定先の短い同期操作を一度だけ実行する。逆順に解放し、確定結果を返す |
| `FinalizationFailure` | 不一致、利用不能、未対応、不正な参加者、取得設定不正、競合中、取消、確定済み、確定拒否、予期しない確定障害を区別する型付き失敗 |

世代トークンは`AuthorityRef`や承認を代用しない。所有者を名乗る文字列、任意の整数、別プロセスから復元したトークンだけで正規出典へ昇格できない。登録された参加者との対応と発行インスタンスを検査し、再登録・再起動後の同じ番号を別世代として扱う。トークンの直列化は診断用であり、永続化したトークンを実行権限として復元しない。

当初の粒度は一つの所有者インスタンスにつき一参加者とする。リソース別ロックを新設しない。必要な計画・命令の識別子は所有者の読取値に残し、その所有者の世代と組にする。`RevisionVector`、計画や実行記録の既存リビジョン、必須要件の方針リビジョンとは別の機械的な世代であり、いずれの意味も置き換えない。

Foundationは具体的なExecutive・Goal Planning・Plan Execution・Activity Executionの型をimportせず、能力・必要条件・計画の意味を判断しない。参加者と型付き結果を提供し、各所有者がそれに依存する。確定操作の入力・出力の意味、権限、合法な状態遷移、重複判定は従来の確定先所有者が保持する。

### 15.1. #632の実装入口と検証境界

`AuthorityFinalizationParticipant`自身を各所有者の同期境界として使用する。`authority_mutation`は更新可能メソッド全体の入口で失効し、ロック取得前だった入力検査の失敗も保守的失効に含める。元の製品リビジョン・記録・意味判断は変更しない。通常読取は世代を進めない。

`current_plan_publication`、`snapshot_publication`、計画進行の`scope_publication / observation_publication`は値と全出典トークンを同一区間で返す。計画進行の出典は進行・現在計画・目標・活動の四参加者であり、一部を省略した確定要求は拒否する。既存の汎用`GoalSnapshotPort`は通常経路で保持するが、監査済み`GoalCommitmentStore`以外からの最終確定参加は`PARTICIPANT_UNSUPPORTED`とする。

実行判断所有者は`ExecutiveFinalizationInput`と`finalization_operation`を提供する。構成時に登録した所有者の同期メソッド参照だけをFenceから呼ぶ。#630の意図別要件・方針・由来をこの入口で生成しない。確定時刻は全取得・世代検査後の共通UTC時計を用いる。

取得後の未宣言読取や出典書込みは`INVALID_LOCK_CONFIGURATION`で拒否する。確定操作へ入った後に発見した取得設定違反は、状態未更新と決めつけず対象を利用不能・失効へ移す。その他の予期しない確定例外は`TARGET_COMMIT_FAULT`とし、どちらも公開済み状態を巻き戻さない。

責務内の試験は`tests/domain/contracts/test_finalization.py`で管理する。設計時の競合再現記録と、実装後のTest/Fix・CI・独立レビューの証拠を区別し、後者の現在値は#632の最終Checkpointで照合する。

## 条件の実測source bindingと公開境界（#644）

`app/domain/contracts/preconditions.py`は、条件と正規所有者の明示的な接続形式を提供する。Foundationはidentity・routing・publication形式だけを所有し、predicateを評価しない。条件の意味、current state、actualの導出は各Domain Ownerに残す。`precondition_id`から所有者を推測せず、predicate文字列を任意処理として実行しない。

- `PreconditionSourceRef(owner_id, contract_id)`は実測公開元を識別する。
- `PreconditionSourceBinding(precondition_id, subject_ref, predicate, source)`は条件のidentityとsourceを固定する。問い合わせにexpectedを持たせず、既存`PreconditionRef`の期待値と分離する。
- `PreconditionObservation(binding, actual)`は同じidentity・sourceと実測値を保持する。actualは厳密なJSONで、不正型・非有限数・非文字列キーを拒否し、配列・mappingを深く不変化する。JSON深さは32を上限とする。
- `PreconditionSourceReader.read_current(binding)`は`AuthorityReadPublication[PreconditionObservation]`を返す。所有者は実測値と全出典tokenを同じ同期読取で生成する。Foundationが状態から実測値を代作することはない。

`PreconditionSourceRegistration`はsource、信頼済みreader、正規の`AuthorityFinalizationParticipant`を構成時に固定する。`PreconditionSourceRouter`は登録済みの完全一致するowner/contractだけへ配送する。重複登録、所有者identity不一致、未登録source、不正な公開、条件ID・対象・述語・sourceの戻り値不一致、token欠落を拒否する。既定の登録上限は128、公開JSONのUTF-8上限は65,536 bytesで、構成時に正の整数として明示変更できる。容量超過を切り詰めない。

返されたtoken集合は、登録済みparticipantとその宣言済み依存の閉包に完全一致しなければならない。16を超える参加者は拒否する。公開取得後、既存`authority_read_set`の順序で同期取得し、同じFoundationの#632検査で世代・instance・seal・利用可能性を照合する。世代不一致は`STALE_PUBLICATION`、読取不能は`SOURCE_UNAVAILABLE`等の`PreconditionReadError`へ閉じる。供給元の例外本文を外へ搬送しない。

この読取成功は最終確定を意味しない。呼出し側は実際に使用した公開のtokenを保持し、最終確定時に既存`AuthorityFinalizationFence`へ渡す。読取後の更新を新しいtokenで救済してはならない。Routerはtokenを発行し直さず、返された公開をそのまま保持する。新しい世代機構・Fence・意味Authorityは追加しない。

Routerの登録はimmutableで、同じsource名でも別Owner instanceへ自動追従しない。restart後のOwnerには新しい信頼済み構成が必要であり、旧instanceの公開は新しい構成の登録participantと一致しない。旧Ownerを停止する側は既存契約でparticipantをretireし、旧経路も利用不能にする。旧tokenや期待値を現在のactualとして代用しない。

非同期読取はRouterが子taskを所有し、取消時に取消を伝え、再取消中も完了まで回収する。readerが取消を捕捉して値を返してもRouterは取消を成功へ変換しない。所有者側も自分が生成した子taskや資源を回収する。await中はparticipantを取得しない。

#610のExecutive供給と#329の実行前再検証は、この共通公開から各境界の型へ機械投影できる。具体的なDomain条件・Owner実装・両経路のwiringは本Workで追加していない。試験用の明示的Ownerで境界を検証することと、製品のpredicateを新設することを区別する。`GoalFacts`の移植、expectedからactualへのコピー、未登録時の空factによる成功は行わない。
