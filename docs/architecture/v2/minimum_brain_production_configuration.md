# V2 最小Brainの本番初期構成

所有者: #360（システム構成）、設計作業: #569、利用側: #561。
関連: #326 / #323 / #334 / #350 / #355 / #357 / #567。
状態: 設計正本案。#569の監査レビュー結果 `PASS_TO_DESIGN_AMENDMENT` を反映する。実装開始には、この設計差分に対するレビューと別途の実装指示が必要。

## 1. 責務と正本

本書は早期起動（Early Boot）#561が消費する初期データと構成境界を定める。通常会話の成功や#360のS2最終結合検証の完了は表さない。意味処理、状態の採用条件、役割識別子、要求・結果の構造識別子は既存所有者の正本を使う。

- [システム結合](system_integration_contracts.md): 段階的な結合と検証。
- [Brain結合実装](brain_integration_implementation.md): 4レーン、モジュール登録、所有者への採用判定の委譲。
- [入力意味解析](input_meaning_contracts.md): 意味の採用、受理方針、現在世代の読取。
- [LLM実行の数値契約](llm_execution_numeric_contracts.md): 実行方針の型・値域・式。
- [実行基盤の数値契約](runtime_operational_numeric_contracts.md)と[開始・終了契約](runtime_lifecycle_contracts.md): 実行調整と停止。
- [LLM提供サービス接続](llm_provider_adapter_contracts.md): #567を含む未構成・構成済みの分岐。
- [人物定義の配置](character_definition_resource_location_contract.md): 既存の人物データと読込責務。
- [複数所有者の状態読取](snapshot_consistency_contracts.md): 既存の整合した世代読取の手順。

本書は新しいドメインのDTOや意味アルゴリズムを導入しない。後述の `MinimumBrainProductionConfig` は構成層の不変な設定であり、ドメイン状態の正本ではない。

## 2. #561の起動成立に必要な集合

|必須のシステム構成|構成内容|
|---|---|
|静的な本番設定|検証済みの不変な設定と構成版|
|人物定義|既存YAMLを読み、既存の型と投影を使用|
|実行基盤|Runtime Kernelと4レーンの明示的な方針|
|開始・終了管理|RuntimeLifecycleと終了方針|
|Brain結合|BrainIntegrationRuntimeと既存BrainModulePort境界|
|本番LLM接続|#567の生成関数を通じたLLMRolePort|
|入力意味解析の本番方針|既存InputMeaningPolicyを初期データから構築|
|入力意味解析の論理役割登録|所有者のdescriptorから生成した登録|

BrainIntegrationRuntimeへ起動時に必須登録するモジュールは **`INPUT_MEANING` のみ**。これが最終的なBrain構成集合ではない。

次のモジュールは#561のREADY条件に含めず、#360の後続段階で有効化・結合する。

```text
APPRAISAL
ATTENTION
EXECUTIVE
GOAL_COMMITMENT
GOAL_PLANNING
ACTIVITY_EXECUTION
SPEECH_SEMANTICS
CHARACTER_LANGUAGE
SEMANTIC_VERIFICATION
SPEECH_PERFORMANCE
SPEECH_PRESENTATION
MEMORY
REFLECTION
```

S2で検証する境界に含まれることは、#561の起動前の必須登録を意味しない。#334の4レーンをすべて定義する要件は維持するが、全BrainIntegrationModuleの登録を要求しない。未登録モジュールへの要求は既存#334の拒否契約を使い、代替の意味処理を生成しない。

## 3. 起動時に証明する動作

1. `python -m app` が構成処理を呼び、静的設定を読み込む。
2. 既存の人物定義を読み、実行基盤と開始・終了管理を構成する。
3. BrainIntegrationRuntimeに入力意味解析を登録し、実行を開始する。
4. 所有者の論理役割を#567の本番生成関数へ渡してLLMRolePortを結合する。要求受付を開く前に登録と接続を確定する。
5. 提供サービス未構成時はUnavailableLLMRolePortを用いる。有効な入力意味解析要求に型付きの `PROVIDER_UNAVAILABLE` が返ることを確認する。
6. その役割の利用不可をプロセス終了へ変換せず、プロセスを継続する。
7. Ctrl+Cまたは外部取消で所定の順に停止し、所有する未完了タスクが0であることを確認する。

これは構築順と検証範囲であり、認知処理を直列に固定する規約ではない。BrainIntegrationRuntimeが所有するRuntimeCoordinatorを利用し、同一の実行基盤を重複生成・二重所有しない。

`Appraisal → Attention → Executive → Speech` による本番会話の成功は#360の後続結合責務である。#561に追加しない。実TTS・Avatar・Persistence再水和・Streaming・Game・GUI・Pluginの存在を起動条件にしない。

## 4. 静的設定の保存・読込境界

将来のデータ実体は `resources/config/v2/minimum_brain.yaml`、型付きの読込境界は `app/config/minimum_brain.py` とする。今回の設計工程では、いずれも作成しない。

```text
YAML
  ↓ strict typed validation
MinimumBrainProductionConfig
  ↓
Composition Root
```

上図の読込処理は厳密な型検証を意味する。YAMLの辞書をドメインへ直接渡さず、不変な構成設定から既存の型付きの方針を構築する。

|設定の項目|版1の内容・構造|
|---|---|
|schema_id|`yura.minimum-brain.production-config.v1`|
|config_id|`yura.minimum-brain.production`|
|config_revision|`1`|
|character_definition_path|`resources/character_definitions/v2/yura.yaml`|
|brain_module_registrations|`INPUT_MEANING`に対応する既存列挙値だけを含む配列|
|input_meaning|第6・7節のacceptanceとexecution|
|scheduler|第8節のscheduler方針|
|integration|第8節の方針識別・版とlane_policies|
|shutdown|第9節の終了方針|

`input_meaning`は `acceptance` と `execution` の2項目を持つ。`integration`は `policy_id`、`policy_revision`、`lane_policies` を持ち、lane_policiesは各既存RuntimeLanePolicyのfieldを持つ4要素の配列とする。schedulerとshutdownは、それぞれの既存型のfieldに対応する。型構築時には同じshutdown方針を結合方針・実行基盤・開始終了管理へ注入する。

表の大文字enum表記は既存列挙のメンバー名である。YAMLには各既存enumの `.value` を保存し、新しい別名・大小文字の暗黙変換を追加しない。方針のfield名も既存型へ対応させる。受理方針の意図別対応は、既存PrimaryIntentの値から必須項目の配列への対応表とし、空集合は空配列で表す。全意図を1回ずつ覆う。

役割識別・入出力schema・descriptorはYAMLで再定義しない。`INPUT_MEANING`の登録から所有者の生成処理へ明示的に接続する。人物定義の意味上の正本は既存の人物設定文書にあり、本設定は配置参照だけを所有する。

未知field、必須field欠落、重複YAML key、未知enum、不正数値、重複登録、4レーンの欠落・重複は起動設定失敗とする。数値は既存型の有限性・値域・bool拒否を維持する。不正値を補正・clampしたり試験値で埋めたりせず、要求受付を開かない。

このYAMLには秘密情報を保存しない。認証情報、秘密を含む指示文、提供サービスの生の応答、実行時の秘密情報を含めない。認証情報の取得責務は既存の環境設定境界にあり、一般的な最小Brain設定へ移さない。OpenAI固有の役割設定も別の境界に置く。

## 5. 設定世代

プロセス開始時にconfig_revision=1を読み、不変な設定をそのruntime_epochへ結び付ける。停止まで同じ世代を使用する。

#561では実行中の設定再読込（hot reload）を実装しない。YAMLを書き換えても進行中のプロセスの方針は変えず、新しいプロセス・runtime_epochで変更を読み込む。

config_revision、入力意味解析の実行方針版・受理方針版、実行基盤の方針版を途中で暗黙変更しない。設定内容の変更はconfig_revisionを進め、変更された方針もそのpolicy_revisionを進める。将来の動的再構成は、別の版付き契約で切替境界と進行中要求の扱いを定める。

SystemCompositionSnapshotには読み込んだ構成版とruntime_epoch、人物定義版、実際の登録を記録する。この記録をドメイン状態の所有者に置き換えない。

## 6. 入力意味解析の受理方針

既存の `InputMeaningAcceptancePolicy` を使用する。

|field|版1の値|
|---|---|
|policy_id|`yura.input-meaning.acceptance`|
|policy_revision|`1`|
|clarification_confidence_threshold|`0.70`|

|PrimaryIntent|必須の解決項目|
|---|---|
|PROVIDE_INFORMATION|information|
|REQUEST_INFORMATION|空集合|
|REQUEST_ACTION|target_ref|
|CONFIRM|references|
|DENY|references|
|START_ACTIVITY|target_ref|
|STOP_ACTIVITY|target_ref|
|ASK_INTERNAL_STATE|target_ref|
|SOCIAL|空集合|
|OTHER|空集合|

情報の提供は提供情報、行為の要求・開始・停止は対象、肯定・否定は参照先を要求する。一般的な問いかけや社交表現へ不要な対象必須化を追加しない。未解決参照の拒否は既存#326を維持する。閾値は初期調整値であり、変更時は方針版を進める。

これらは版付き本番データであり、InputMeaningInterpreter内部の暗黙定数にしない。#326は完了状態を維持し、descriptorや意味解析を構成層へ複製しない。

## 7. 入力意味解析の実行方針と登録

|LLMExecutionPolicyのfield|版1の値|
|---|---|
|policy_id|`yura.input-meaning.execution`|
|policy_revision|`1`|
|model_class|`BALANCED`|
|reasoning_effort|`MEDIUM`|
|timeout_seconds|`10.0`|
|max_attempts|`1`|
|max_output_tokens|`800`|
|temperature_normalized|`None`（YAMLではnull）|
|retry_policy.initial_backoff_seconds|`1.0`|
|retry_policy.backoff_multiplier|`1.0`|
|retry_policy.max_backoff_seconds|`1.0`|

LLMRequestRetryPolicyは型として必須である。総試行数1のため再試行せず、この3値は版1では待機時間として使用されない。将来max_attemptsを1より大きくする場合は実行方針版を進め、再試行時刻も同時に再設計する。これは本番初期値の決定であり、#323のドメイン契約変更ではない。

`app/domain/input_meaning/interpreter.py`の既存定義を取得する。

- ROLE_ID: `input_meaning`
- INPUT_SCHEMA: `yura.input-meaning.request.v1`
- OUTPUT_SCHEMA: `yura.input-meaning.result.v1`
- `descriptor(InputMeaningPolicy)`と既存の要求生成を使用する。

同じ構成の不変設定から構築したInputMeaningPolicyをdescriptor生成とInputMeaningInterpreterへ渡す。登録に使った方針と要求生成の方針を別々に生成・更新しない。試験補助関数のimport、試験値の流用、可変の大域辞書は禁止する。

## 8. 実行基盤と結合の初期方針

|方針|policy_id|policy_revision|追加値|
|---|---|---|---|
|RuntimeSchedulerPolicy|`yura.minimum-brain.scheduler`|1|max_priority_burst=8|
|BrainIntegrationRuntimePolicy|`yura.minimum-brain.integration`|1|次の4レーンと第9節の終了方針|

|lane_id|queue_capacity|queue_policy|max_in_flight|cancellation_grace_seconds|error_isolation|
|---|---|---|---|---|---|
|foreground_interaction|64|REJECT_NEW|4|0.5|ISOLATE|
|cognitive_normal|64|REJECT_NEW|4|0.5|ISOLATE|
|speech_preparation|32|REJECT_NEW|2|0.5|ISOLATE|
|background_reflection|16|REJECT_NEW|1|0.5|ISOLATE|

REJECT_NEWを初期値とし、#334が所有者のpayloadの意味を解釈して破棄・併合する方針を追加しない。受付拒否と既存の取消・エラー隔離の契約をそのまま使う。レーンが存在するだけで、そのレーンのモジュールが有効化済みとは扱わない。

## 9. 終了方針と依存サービス

|RuntimeShutdownPolicyのfield|版1の値|
|---|---|
|policy_id|`yura.minimum-brain.shutdown`|
|policy_revision|`1`|
|in_flight_settle_grace_seconds|`2.0`|
|final_persistence_grace_seconds|`0.0`|
|resource_close_grace_seconds|`2.0`|
|owned_task_join_grace_seconds|`2.0`|

#561ではPersistence再水和と最終保存を有効化しないため、最終保存猶予を0.0とする。後続段階で永続化を有効化する際は方針版を再評価する。停止順序、猶予超過時の型付き失敗、タスクの取消後の回収は既存の実行基盤・開始終了管理の契約を維持する。時間超過を停止成功として隠さない。

版1では外部LLM提供サービスをRuntimeLifecycleの再試行対象の依存サービスとして必須登録しない。そのためLLM用DependencyRetryPolicyの初期値を新設しない。接続回復と再試行による復旧は#350/#360の後続段階で扱う。

## 10. 提供サービスの構成境界

#567の `create_openai_port_from_environment()` に所有者のdescriptorを渡す。

- 認証情報なし: UnavailableLLMRolePortを使用する。OpenAI固有設定を要求しない。
- 認証情報あり: 既存の構成済み提供サービス経路を使う。必要な役割設定が欠落・不整合なら既存生成関数の失敗を伝播する。

構成済みの不正設定を未構成として隠さない。#569/#561で全役割のOpenAI設定を補作せず、Character Language専用設定を入力意味解析へ流用しない。構成済み経路での会話成功は本書の検証完了条件にしない。

## 11. 入力意味解析の現在世代の境界

InputMeaningLiveContextPortと#326の採用契約を変更しない。

有効な交換契約を満たす提供サービスの非成功結果は、現在世代を読まず既存の型付き役割失敗として返す。したがって未構成経路のPROVIDER_UNAVAILABLE検証に、架空のsource_context_revisionを用意する必要はない。

将来成功結果が到着しても、権威ある現在の入力文脈世代と方針世代を取得できない限り意味を採用しない。接続側は取得不能を既存の読取失敗として明示し、InputMeaningInterpreterの既存経路でboundary_failure.code=REJECTEDへ閉じる。これは提供サービスの成功statusを捏造して上書きすることではない。外部CancelledErrorの伝播も維持する。

版1の受理方針の参照元は、第5節のruntime_epochへ結び付いた実際の不変設定である。現在の入力文脈世代の所有者が未結合なら、方針版だけ分かっていても有効なInputMeaningFreshnessStampを返せない。常にsource_context_revision=0を返す、要求開始時の版を現在版として返す、単に固定値1を返して方針の参照を省略する、といった偽の正本を作らない。

本番会話の成功に必要な入力文脈の状態の結合は#360のS2有効化時に再監査する。その時点でdescriptor・要求・採用直前の現在状態を同じ方針の不変設定に結び付け、既存snapshot_consistency_contracts.mdの読取手順を利用する。汎用の再試行・読取アルゴリズムを本書で再定義しない。

### 11.1 Brain登録用の接続アダプター

概念名 `InputMeaningBrainModulePort` は、#334のBrainModulePortと#326のInputMeaningInterpreterを接続するアプリケーション・構成層のアダプターである。新しいドメインの正本ではなく、意味解析、受理方針、現在世代に基づく採用、提供サービスの失敗分類を再実装しない。

```text
BrainIntegrationWork
  ↓
InputMeaningBrainWorkPayload
  ↓
InputMeaningInterpreter.interpret()
  ↓
InputMeaningInterpretationResult
  ↓
BrainIntegrationWorkOutcome.result
```

上図の最初の接続で、運ぶ入力の構造と識別子の自己整合を確認する。InputMeaningInterpreterはBrainModulePortと直接互換ではないため、構成処理はこのアダプターを `INPUT_MEANING` として登録する。Input Gatewayを新たな起動必須モジュールへ追加せず、既存の型付き入力を運ぶ境界だけを定める。

### 11.2 運搬する入力と識別子の整合

概念型 `InputMeaningBrainWorkPayload` は、BrainIntegrationWork.payloadに載せる不変な構成層の入力である。意味のドメインDTOを追加するものではない。

|項目|型・制約|
|---|---|
|event|既存NormalizedInputEvent|
|reference_context|既存ReferenceContext|
|request_id|空でない要求識別子|

trace_idとcreated_atはpayloadへ重複保存せず、それぞれwork.envelope.trace_idとwork.envelope.created_atを使う。アダプターは型とrequest_idに加え、次の全条件を検証する。

```text
work.module == INPUT_MEANING
work.lane == FOREGROUND_INTERACTION
work.envelope.source_event_ids == (payload.event.envelope.event_id,)
work.envelope.source_context_revision
    == payload.event.envelope.revisions.source_context_revision
    == payload.reference_context.source_context_revision
work.envelope.trace_id == payload.event.envelope.trace_id
```

これらは運搬中の不変な入力同士の整合であり、現在の入力文脈世代を証明する条件ではない。不正な型や不一致を補正・再解釈しない。構成・プログラム上の誤りとしてValueErrorで拒否し、意味や提供サービス失敗を捏造しない。Runtimeの検査・実行経路内でこの誤りが発生した場合は、既存の例外隔離によりFAILEDとなる。例外本文や入力の生データを公開結果へ持ち込まない。

### 11.3 executeの委譲

`execute(work, cancellation)`は第11.2節の整合を確認し、次の呼出しをawaitする。

```python
await interpreter.interpret(
    payload.event,
    payload.reference_context,
    request_id=payload.request_id,
    trace_id=work.envelope.trace_id,
    created_at=work.envelope.created_at,
)
```

戻り値のInputMeaningInterpretationResultをそのまま返す。生のLLMRoleResultをBrainの公開結果にせず、所有者が返した型付き非成功をPython例外へ変換しない。

アダプターが正常に所有者の結果を返した場合、取消・期限切れ等の既存Runtime条件がなければBrainIntegrationWorkOutcome.statusはCOMPLETEDとなる。その内側の役割結果がFAILEDであることとは別の状態である。

### 11.4 is_freshと意味採用の順序

このアダプターの `is_fresh(work)` は、第11.2節の固定済み入力・世代・識別子の自己整合だけを確認する。有効な不変入力ならTrueを返す。不正な構成入力は第11.2節の誤りとして拒否し、現在世代を読んだ結果のSTALEと取り違えない。提供サービスが未構成であることや、その結果が非成功であることをFalseの理由にしない。

`InputMeaningLiveContextPort.current_freshness_stamp()`をここから呼ばない。Runtimeの実行前後の検査が、#326の意味採用の検査を先取りしてはならない。

- 有効な提供サービスの非成功結果: 現在世代を読まず、型付きの役割失敗を返す。
- 提供サービスの成功結果: InputMeaningInterpreter内部の既存のawait後の検査で現在世代を読み、採用を判断する。

したがって、このBrainModulePort.is_freshは意味採用の現在世代の正本ではない。Runtimeの前後検査を通しても、入力意味解析の意味採用条件を通過したことにはならない。未構成経路の現在世代の読取は0回を維持する。

### 11.5 現在世代を取得できない接続

早期起動では権威ある入力文脈の状態所有者をまだ本番結合しない。InputMeaningInterpreterのconstructorが要求する接続には、概念名 `UnavailableInputMeaningLiveContextPort` を明示的に渡す。

これは読取専用であり、current_freshness_stamp()が呼ばれた場合は、現在の権威ある世代を提供できないことを明示的な取得失敗として通知する。既存Interpreterが扱うException系の取得失敗を使い、新しいLLMFailureCodeやドメイン失敗enumを追加しない。偽のInputMeaningFreshnessStampは返さない。

固定のsource_context_revision=0、方針版1だけの捏造、要求時の版、最後に観測した版を現在版として返すことは禁止する。第5節の実際の不変設定を方針の参照元とすることと、入力文脈の現在世代を取得できることは別である。

非成功結果ではこの読取メソッドは呼ばれず、型付きの役割失敗が保持される。成功結果では既存Interpreterが読取を試み、取得失敗をboundary_failure.code=REJECTEDへ閉じ、meaning=Noneとする。生の内部例外は公開結果へ出さない。

### 11.6 取消と公開結果

InputMeaningBrainModulePortはPythonのCancelledErrorを捕捉して通常結果へ変換しない。#322が割込み可能な処理を取り消した場合はタスク取消を伝播し、既存RuntimeのCANCELLEDへ閉じる。取消用トークンとタスクの所有・回収は既存Runtime契約に従う。提供サービス呼出しの取消をPROVIDER_UNAVAILABLE、REJECTED、成功へ読み替えない。

|条件|BrainIntegrationWorkOutcome.status|resultの意味|
|---|---|---|
|有効な要求、提供サービス未構成|COMPLETED|InputMeaningInterpretationResult。role_status=FAILED、role_failure.code=PROVIDER_UNAVAILABLE、meaning=None。現在世代読取0回|
|提供サービス成功、現在世代の接続が利用不可|COMPLETED|InputMeaningInterpretationResult。boundary_failure.code=REJECTED、meaning=None。提供サービスのrole_status=SUCCEEDEDは保持|
|Runtimeによる取消|CANCELLED|通常の意味結果を捏造しない。既存Runtimeの結果保持契約を変更しない|
|不正な構成入力・不変条件違反|既存Runtime経路ではFAILED|第11.2節の構成誤り。意味・型付き提供サービス失敗を捏造しない|

上表のCOMPLETEDは、取消・期限切れなど別のRuntime終了条件がない場合の正常な委譲結果を示す。外側の処理終了状態と内側の役割・意味採用の状態を混同しない。

第10節の構成済み提供サービス境界は維持する。認証情報があるのに入力意味解析用の設定が欠落・不整合なら、構築失敗を起動設定失敗として伝播する。未構成接続への代替で隠さず、本WorkでOpenAI固有設定を補作しない。

## 12. 後続段階へ残す構成

第2節で必須から外したModuleの具体的な調整値を版1へ含めない。特に次は、そのモジュールを本番で有効化する段階で既存所有者に従って確定する。

- #327のDecayPolicyと初期InternalStateSnapshot。
- #332のMemoryRetrievalRankingPolicy。
- #361の計画、#362の発話意味、#330の言語化、#363の意味検証の実行方針。
- #328等の他の論理役割の実行方針と、#364の背景処理の方針。

試験用データや過去の暗黙値を本番の初期値へコピーしない。この保留は#561の阻害要因ではなく、各後続段階の有効化条件である。通常会話やS2最終検証を完了扱いしない。

## 13. 監査不足の最終分類

|不足|分類|本設計での扱い|
|---|---|---|
|G1|CONTRACT_GAP|解消。第2節で起動必須集合を確定|
|G2|PRODUCTION_CONFIGURATION_GAP|再分類して解消。第7節で再試行の構築値を明示|
|G3|CONTRACT_GAP|解消。第4・5節で場所・形式・型付き境界・構成版を確定|
|G4|SYSTEM_COMPOSITION_AUTHORITY_GAP|#561範囲で解消。実際の不変設定を方針の参照元とし、入力文脈世代の取得不能なら拒否。会話成功の接続は後続S2へ限定|
|G5|PRODUCTION_CONFIGURATION_GAP|#561必須値を解消。第7〜9節。LLM依存再試行は有効化しない|
|G6|後続Moduleの有効化時の構成課題|第12節へ保留し、#561を阻害しない|

設計HEAD `d9660901e9dfb0b82176ed1169730a06b93e05cb` のレビューはREQUEST_CHANGESで、入力意味解析をBrainへ登録する接続契約の不足が阻害指摘となった。第11.1〜11.6節で運搬入力、委譲、検査順序、取得不能の接続、公開結果を明示し、このCONTRACT_GAPを設計上解消する。

本書の範囲で残存DESIGN_BUG・CONTRACT_GAPはないという設計案である。実装・検証の完了宣言ではなく、この新設計HEADのレビュー判定を別途受ける。

## 14. 後続実装工程で必要な検証

- 正規配置の設定から既存の型付きの方針と不変な構成を生成できる。
- 未知・欠落・重複・不正enum・不正数値を起動時に拒否し、暗黙の既定値を使わない。
- INPUT_MEANINGだけを登録し、他モジュールなしで起動成立する。4レーンの方針は全件検証する。
- 人物定義の既存loader・投影と、所有者のdescriptor・schemaを再利用する。
- descriptorと要求の方針が同じ不変設定に対応する。実行中のファイル変更で世代が変わらない。
- 未構成の生成関数経由の有効な入力意味解析要求がPROVIDER_UNAVAILABLEを返し、現在世代の読取回数は0。プロセスは継続する。
- 成功結果で権威ある入力文脈世代を取得できなければREJECTEDとして意味採用0。偽の版を返さず、外部取消は伝播する。
- 総試行1回で要求単位の再試行待機がない。LLM依存の復旧再試行も開始しない。
- `python -m app`の子プロセス試験で継続とCtrl+C相当の停止を検証する。
- 取消と停止後に所有タスクを回収し、未完了タスクが0。猶予超過時は失敗を隠さない。
- 構成済み接続の不正設定を未構成として隠さず、秘密情報をログ・設定・確認記録へ出さない。

### Brain接続に追加する検証

1. InputMeaningBrainModulePortはINPUT_MEANING / FOREGROUND_INTERACTIONの組だけを受理する。
2. event・reference_context・workの入力文脈版の不一致を拒否する。
3. event識別子・trace識別子の不一致、不正なpayload型・空request_idを拒否する。
4. 提供サービス未構成でBrain処理はCOMPLETED、所有者の結果はFAILED / PROVIDER_UNAVAILABLE、meaningなし、現在世代読取0回となる。
5. 成功結果を返す試験用提供サービスとUnavailableInputMeaningLiveContextPortを結合すると、Brain処理はCOMPLETED、boundary_failureはREJECTED、meaningなしとなり、偽の版を返さない。
6. 外部CancelledErrorを握り潰さず、Runtimeによる取消はCANCELLEDとなる。
7. 生のLLMRoleResultをBrainの公開resultへ返さない。
8. 実際のRuntimeの実行前後のis_fresh検査が現在世代を先読みしない。
9. 提供サービス未構成をBrainのFAILED / STALEへ誤変換しない。
10. 入力文脈の状態所有者が未接続でも、提供サービスなしの早期起動が成立する。Input Gatewayを起動必須集合へ追加しない。

この工程では上記試験・コード・設定実体を作らず、設計文書だけを変更する。
