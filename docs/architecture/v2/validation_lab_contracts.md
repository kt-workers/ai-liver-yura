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

## 21. 検証実行の開始・終了と結果保持

検証基盤の起動失敗は本体の本番実行を停止させない。各検証実行は、生成した子タスクと資源の取消・回収を所有する。

取消・終了時は、新しい段階の受付を止め、取消可能な模擬提供先・実提供先の処理を取り消し、終了状態を回収する。終了後の所有する未完了タスクは0とし、反復実行で接続資源を残さない。

`ValidationRunner.run()`の呼出し側タスクが取り消された場合も、内部実行の終了結果を捨てない。内部実行へ取消を通知して回収し、返された`ValidationRunResult`を実行識別子で保持してから、呼出し側へ`CancelledError`を伝播する。結果と実測時系列は`result()`／`take_result()`から取得できる。終了処理中に呼出し側が再度取り消されても、内部実行の回収・結果保持を中断しない。

既に内部実行が完了していた場合は、その実際の終了結果を保持し、取消結果へ付け替えない。内部実行自体が結果を返さずに取り消された場合や例外終了した場合は、結果を捏造しない。保持件数の上限と取得済み結果の回収規則を維持する。

---

## 22. 検証基盤の必須試験

検証基盤の試験ディレクトリはPythonのパッケージとして明示し、PostgreSQLなど隣接領域の同名試験ファイルと同時に収集できるようにする。リポジトリ全体の試験実行で収集の衝突がないことを確認する。

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


## 24. 永続化・別プロセス再起動・停止の検証（#619）

`persistence_target`は共通`ValidationRunner`へ登録するINTEGRATED接続とする。既存の`build_persistent_core`、`CoreGoalPersistenceBinding`、本番Memory接続、`PostgresPersistenceRuntime`を使用し、保存形式・復元可能なOwner・復元失敗後の書込保護を追加・変更しない。

信頼済みの起動コードが`PersistenceLabSettings`と`PersistenceLabCase`を登録する。外部入力から関数・コマンド・接続先を解決しない。設定には本番起動構成、接続上限、Memory順位付け方針、保存再試行・依存再接続方針と受付上限を明示する。Goalへの確定済み判断、Memory書込・検索要求、シナリオをfixtureの型付き入力と照合する。構成の識別子・リビジョン・検証済み公開設定のdigestを保持し、記録した条件と異なれば実行を拒否する。

各反復は新規生成した専用DBだけを所有する。管理接続先の既存DBやテーブルへ障害を注入しない。接続拒否は専用DBの新規接続設定、復元失敗・最終保存猶予は既知の製品テーブルへの別接続のロックで実現する。Ownerの返却値を差し替えて障害を作らない。開始済みのDB操作と子プロセス生成は取消・再取消でも完了を回収し、登録失敗時にも生成済み資源を閉じる。終了時は本番停止、子プロセス・ロックの回収、専用DB削除を行う。

| シナリオ | 保持する証拠 |
| --- | --- |
| `restart` | Goalのdurability receiptとMemory保存結果、親の停止、別PIDの本番入口でのGoal・入力文脈・Memory復元、子の停止 |
| `database_unavailable` | 保存後のDB接続拒否、復元失敗保護、停止後の別プロセス復元 |
| `reconnect` | 依存再接続方針による復旧、同一Goal Owner、復元失敗後のGoal書込拒否とMemory結果、別プロセス復元 |
| `restore_failure` | 実DBのロックによる復元失敗、接続復旧後も維持されるGoal書込保護、別プロセス復元 |
| `final_save_timeout` | 未完了の実Memory書込、設定した最終保存猶予の失敗段階、停止後の資源回収 |
| `stop_cancelled` | 未完了の実Memory書込、本番停止への取消・再取消、取消の結果と資源回収 |

公開設定は対象登録時にimmutableな値へ固定し、run開始時にはfixtureとも照合する。各本番起動の直前と起動完了後、子プロセス生成直前、最終証拠確定直前に現在の設定を固定値と照合する。子へのpacketにはlive再読込値ではなく固定値を渡し、子もその値に対して起動前の設定を再照合する。途中変更・読取不能を検出した場合は証拠を確定せず、生成済み資源を回収する。親の設定不一致は`BLOCKED_UPSTREAM`、子の起動拒否で正常な通信結果が得られない場合は`HARNESS_FAILED`とし、COMPLETEDへ変換しない。

親と子はrun ID・反復番号・製品HEAD・branchを照合する。正式CIのdetached HEADではbranchを`HEAD`と明示し、架空のbranch名を補わず実SHAで照合する。親は実行前後、子は復元前に製品ソースの来歴を再取得し、子は起動構成も再照合する。子への接続設定は専用pipeだけで渡し、環境変数を継承しない。認証情報・接続先・設定パス・提供元の生例外を結果やstderrへ出さない。公開結果は既存の有限なJSON/Markdown書出しを使い、入力・出力・実測区間を同じrunへ対応付ける。

意図した障害でも、型付き失敗・利用不可・Ownerの拒否は`PRODUCT_FAILED`、取消は`CANCELLED`として保持する。Harnessの構成・投影・子プロセス通信の失敗は`HARNESS_FAILED`と区別する。手順完走を製品の成功へ読み替えず、機械判定は`NOT_RUN`を維持する。INTEGRATEDの主張は本番永続化・起動停止経路に限り、実LLM・音声・外部サービス・人間による会話品質や#586の性能受入へ拡張しない。
