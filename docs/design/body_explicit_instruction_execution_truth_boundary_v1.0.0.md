# Body明示指示 実行事実境界 v1.0.0

## 1. 目的

Issue #184「身体動作を実行していないのに完了・進行中として発話する」を、既存の因果設計とBody責務分離を崩さずに修正する。

本設計は、ユーザーの明示的な身体指示をBodyの主動機へ昇格させるものではない。Emotion / Desire / Drive / Motivation / Interaction Intentionから生じる連続Body状態を主状態として維持し、その上に短時間の外部制約をOverlayする。

## 2. 非目標

- Raw User TextをBody Controllerへ渡さない。
- `right_look`、`raise_right_hand`のような固定モーション名をCore契約にしない。
- 明示Body指示をEmotion、Desire、Drive、Motivationへ逆流させない。
- Body ControllerにCharacterの発話内容や発話事実性を判断させない。
- LLM待ち時間を見込んでConstraint時間を固定的に延長しない。
- `ACCEPTED`やPlanning完了を、身体動作成功の意味にしない。

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

## 5. Planningと実行を分離する

明示Body指示はCharacter生成より前に実行しない。

従来はBehavior Routing中にConstraintを適用していたため、1.5〜1.9秒の短時間ConstraintがCharacter LLM・Response Validation待ちの間に終了し、ユーザーへ返答が見える時点では動作が終わる可能性があった。

現在の正規経路は次とする。

```text
StructuredInputMeaning
  -> BodyInstruction
  -> BodyInstructionExecutor.preflight()
  -> ACCEPTED / REJECTED / UNSUPPORTED
  -> Character生成・Response Validation
  -> ActionPlan生成
  -> synchronized MOVE
  -> BodyInstructionExecutor.execute()
  -> BodyExternalConstraint
  -> BodyPoseFrame
  -> SPEAK
```

`preflight()` は次だけを確認する。

- 指示を現在の正規化Pose軸へ解決できる。
- Body Subsystemが接続されている。

この段階ではControllerへConstraintを登録しない。

## 6. 公開Body実行結果契約

`BodySubsystemPort` は次の型付き境界を公開する。

```text
apply_external_constraint(
    BodyExternalConstraint
) -> BodyConstraintExecutionResult
```

### ACCEPTED

実行前の事前確認が通った、またはBody Subsystemが要求を受理した状態。

- 身体動作成功ではない。
- `execution_performed=true` にしてはならない。
- 現在進行・完了の身体実行主張を許可してはならない。
- Outputの`MOVE` Actionへ進める根拠にはできる。

### APPLIED

出力段階で、正規化済みConstraintが現在のBody Controllerへコミットされた状態。

- Body側の適用成功を示す。
- Speech成功とは独立した結果である。
- 次回以降のBody tickでPose Frameへ投影される。
- ブラウザ描画済み・ユーザー視認済みまでは保証しない。

### REJECTED

Body Subsystemは存在するが、要求を適用できなかった状態。例外、契約違反、不正な戻り値もここへfail-closedする。

### UNSUPPORTED

Body Subsystem未接続、または意味上の指示を現在のBody契約で表現できない状態。

## 7. Activity実行境界

Behavior Planningでは実行可能性だけを判定する。

```text
trusted body_instruction
  -> BodyAwareBehaviorPlanner
  -> runtime/body_expression_loop
  -> BodyInstructionExecutor.preflight
  -> ActivityExecutionStatus.WAITING_INPUT
```

事前確認成功時も、次を維持する。

```text
execution_performed = false
body_instruction_execution_ready = true
```

Body未接続・未対応なら`REJECTED`として通常の成功発話へ進めない。

## 8. 出力同期境界

事前確認済みBodyInstructionは`AvatarPerformanceActionPlanner`が最初のReaction Segmentへ1件だけ`ActionType.MOVE`として載せる。

既存`ActionScheduler`の同期順序をそのまま利用する。

```text
UPDATE_SUBTITLE
  -> CHANGE_EXPRESSION
  -> MOVE              # BodyExternalConstraintをここで適用
  -> SPEAK
```

これにより、Character生成時間とは無関係に、ユーザーへ返答を提示する直前にBody動作を開始できる。

固定時間をLLM待ち時間分だけ延ばす対症療法は行わない。

明示Body指示が存在するSegmentではCharacter由来gestureの`MOVE`を重複生成せず、同じBody Resourceへ別経路の命令を同時投入しない。

## 9. Action実行事実

`BodyAwareExecuteActionUsecase`は、明示Body指示としてマークされた`MOVE`だけを`BodyInstructionExecutor.execute()`へ接続する。

- `APPLIED`ならMOVE Actionは成功する。
- `REJECTED` / `UNSUPPORTED` / 不正結果なら例外化し、ActionSchedulerがMOVEをFAILEDとして記録する。
- SPEAK Actionとは別の`ActionExecutionResult`になる。

したがってSpeech再生や字幕成功をBody成功へ読み替えない。

## 10. Character Claim検証

Character生成は実Body MOVEより前なので、生成時点では現在進行・完了の身体成功主張を許可しない。

少なくとも次を独立Claimとして検出する。

- 見ている / 見てる
- 向いている / 向いてる
- 挙げている / 挙げてる
- 上げている / 上げてる
- 動かしている / 動かしてる
- `〜してる感じでいる` のような曖昧化表現

事前確認`ACCEPTED`だけではこれらを正当化しない。

Characterは「うん」「右を見るね」のような、未実行事実と矛盾しない応答を生成できる。実Body MOVEはその直後、SPEAKより前に実行される。

## 11. HTTP / SSE境界検証

単体テストだけではOutput時の`MOVE -> APPLIED -> Pose Frame -> HTTP/SSE -> Body Pose Lab`を保証できない。

実HTTPハーネスでは`BodyInstructionExecutor`を直接呼ばず、本番と同じ`BodyAwareExecuteActionUsecase`の`MOVE` Actionを通す。

最低限次を検証する。

1. `右見て`相当のMOVEを実行する。
2. Body RuntimeへConstraintが適用される。
3. Body tick後のPose FrameでHEAD_YAW / GAZE_Xが右方向へ変化する。
4. 実HTTP/SSE境界を経由して同じ変化を観測できる。
5. `右手挙げて`相当でRIGHT_ARM_RAISEが変化する。
6. Body未接続、未対応、契約違反時はMOVE成功にしない。

## 12. 完了・マージ条件

- Body基盤は#178 / PR #180〜#182で統合済みの正本を使用する。
- Planning時にConstraintを実適用しない。
- preflight成功は`ACCEPTED`であり実行成功ではない。
- 明示Body指示は同期`MOVE`としてSPEAK直前に実行される。
- MOVEとSPEAKの実行結果が分離される。
- 実HTTP/SSE境界の回帰テストが同期MOVE経路を通る。
- 現在進行・完了の未実行身体主張をResponse Validationで拒否する。
- 全体pytestが成功する。
- 実画面で`右見て`・`右手挙げて`の動作を返答付近で確認する。
- ユーザーの明示確認まではDraft・未マージを維持する。
