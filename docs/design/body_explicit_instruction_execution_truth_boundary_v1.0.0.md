# Body明示指示 実行事実境界 v1.0.0

## 1. 目的

Issue #184「身体動作を実行していないのに完了・進行中として発話する」を、既存の因果設計とBody責務分離を崩さずに修正する。

本設計は、ユーザーの明示的な身体指示をBodyの主動機へ昇格させるものではない。Emotion / Desire / Drive / Motivation / Interaction Intentionから生じる連続Body状態を主状態として維持し、その上に短時間の外部制約をOverlayする。

## 2. 非目標

- Raw User TextをBody Controllerへ渡さない。
- `right_look`、`raise_right_hand`のような固定モーション名をCore契約にしない。
- 明示Body指示をEmotion、Desire、Drive、Motivationへ逆流させない。
- Body ControllerにCharacterの発話内容や発話事実性を判断させない。
- `APPLIED`をブラウザ描画完了・ユーザー視認完了の意味にしない。

## 3. 入力意味契約

入力意味解析LLMは、明示的な身体指示をモデル非依存の意味へ正規化する。

```text
StructuredInputMeaning
  body_instruction:
    effector
    direction
    side
    magnitude
```

この段階ではPose軸、角度、速度、Live2D Parameter、モーション名、再生時刻を決めない。Body Runtimeが実行可能か、実行に成功したかも判断しない。

信頼できるauthorityの `command` / `request` かつ `expected_response=action` の場合だけ、明示Body指示を実行候補へ持ち上げる。

## 4. 一時Body制約への解決

```text
BodyInstruction
  -> BodyInstructionConstraintResolver
  -> BodyExternalConstraint
  -> BodySubsystemPort.apply_external_constraint()
```

`BodyExternalConstraint` は既存のEmotion / Drive由来Poseを置き換えず、期限付きOverlayとしてControllerへ適用する。

ResolverはRaw User Textを参照しない。意味上のeffector / direction / side / magnitudeだけから、BodyPoseAxis上の安全な正規化制約へ変換する。

## 5. 公開Body実行結果契約

`BodySubsystemPort` は次の型付き境界を公開する。

```text
apply_external_constraint(
    BodyExternalConstraint
) -> BodyConstraintExecutionResult
```

`BodyConstraintExecutionStatus` は次の4状態を持つ。

### ACCEPTED

Body Subsystemが要求を受理したが、まだControllerの権威状態へ適用済みとは確認できない状態。

- 成功発話の根拠にしてはならない。
- `execution_performed=true` にしてはならない。
- 現在進行・完了の身体実行主張を許可してはならない。

### APPLIED

正規化済み制約がBody RuntimeによってControllerの権威状態へコミットされた状態。

- Body実行事実として成功扱いできる唯一の状態。
- `ActivityExecutionStatus.SUCCEEDED` および `execution_performed=true` の根拠にできる。
- 次回以降のBody tickでPose Frameへ投影される。
- ブラウザが既に描画したこと、ユーザーが視認したことまでは意味しない。

### REJECTED

Body Subsystemは存在するが、要求を適用できなかった状態。例外、契約違反、不正な戻り値もここへfail-closedする。

### UNSUPPORTED

Body Subsystem未接続、または意味上の指示を現在のBody契約で表現できない状態。

## 6. fail-closed規則

Speech成功やConversation fallbackをBody成功へ読み替えない。

次の場合はBody実行成功にしない。

- Body Subsystemが未接続。
- Resolverが制約へ解決できない。
- Body Subsystemが `BodyConstraintExecutionResult` 以外を返す。
- Body適用中に例外が発生する。
- statusが `ACCEPTED` / `REJECTED` / `UNSUPPORTED`。

特に、型付き結果が返らなかった場合に暗黙で `APPLIED` を生成してはならない。

## 7. Activity実行境界

明示Body指示はActivity RegistryのPlugin Activityではなく、Runtime内部の `body_expression_loop` 実行経路で扱う。

```text
trusted body_instruction
  -> BodyAwareBehaviorPlanner
  -> runtime/body_expression_loop
  -> BodyInstructionExecutor
  -> BodyConstraintExecutionResult
  -> ActivityExecutionResult
```

`activity_types=[]` でも、信頼済みBody指示がある場合は通常Conversation fallbackより先にこの経路を通す。

変換規則は次の通り。

- `APPLIED` -> `ActivityExecutionStatus.SUCCEEDED`
- `ACCEPTED` -> 非成功状態
- `REJECTED` -> `ActivityExecutionStatus.REJECTED`
- `UNSUPPORTED` -> `ActivityExecutionStatus.REJECTED`

## 8. Character Claim検証

Characterが自己申告するclaimだけを信頼しない。

通常のResponse Validationでは、Response Validation LLMが発話本文から抽出したobjective claimと、決定論的なIndependent Claim Extractorの結果を統合し、確定済み `ResponseContext` / `ActivityExecutionResult` とDeterministic Fact Validatorで照合する。

日本語の身体状態表現について、決定論側でも少なくとも次を補助検出する。

- 見ている / 見てる
- 向いている / 向いてる
- 挙げている / 挙げてる
- 上げている / 上げてる
- 動かしている / 動かしてる
- `〜してる感じでいる` のように曖昧化した現在状態表現

正規表現はLLM claim抽出を置き換えるものではなく、LLM未使用時や取りこぼし時のfail-safe補助である。

現在進行・完了の身体実行主張を許可できるのは、対応するBody実行結果が `APPLIED` でActivity側も成功事実を持つ場合だけとする。

## 9. HTTP / SSE境界検証

単体テストだけでは `APPLIED -> Pose Frame -> HTTP/SSE -> Body Pose Lab` の投影を保証できない。

既存のBody Pose Lab実HTTPハーネスを利用し、少なくとも次を回帰テストする。

1. `右見て`相当の正規化BodyInstructionを実行する。
2. Body Runtimeが `APPLIED` を返す。
3. Body tick後のPose FrameでHEAD_YAW / GAZE_Xが右方向へ変化する。
4. 実HTTP/SSE境界を経由して同じ変化を観測できる。
5. `右手挙げて`相当でRIGHT_ARM_RAISEが変化する。
6. Body未接続、未対応、契約違反時は成功事実を生成しない。

HTTP/SSEでの観測は画面までの伝播検証であり、`APPLIED`そのものの定義には含めない。

## 10. 完了・マージ条件

- 公開 `BodySubsystemPort` に型付き外部制約契約がある。
- Body Runtime実装がその契約を満たす。
- Executorが型不一致をfail-closedする。
- `APPLIED` 以外を成功発話の根拠にしない。
- 現在進行・曖昧化した日本語身体主張の回帰テストがある。
- 実HTTP/SSE境界の回帰テストがある。
- 全体pytestが成功する。
- 実画面で右向き・右手上げを確認する。
- ユーザーの明示確認まではDraft・未マージを維持する。
