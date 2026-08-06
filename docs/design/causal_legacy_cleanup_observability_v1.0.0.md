# 因果経路の旧互換縮小・観測性設計 v1.0.0

## 1. 目的

Emotionを起点とした因果経路を導入した後も残る旧判断・互換API・旧表現を分類し、安全に縮小可能な箇所だけを移行する。

```text
Event / Input Meaning
  -> Affective Appraisal
  -> Emotion
  -> Desire
  -> Drive
  -> Motivation
  -> Interaction Intention
  -> Activity / Character / Body
```

Phase 6では一括削除を行わない。現在もActivity検証やAdapter互換に必要な経路は、役割を明示して残す。

## 2. 経路の分類

各経路を次の4種に分類する。

| lifecycle | 意味 |
|---|---|
| active | 現在の因果判断・事実判断を担う |
| compatibility | 旧呼出しや保守的移行のため残す |
| shadow | 採用結果へ影響せず比較だけ行う |
| deprecated | 主経路として使用せず削除可能 |

コード上の正本は`LegacyRouteInventory`とする。

## 3. 現在の台帳

### Active

- `interaction_intention_appraisal`
- `internal_directive_activity_selection`
- `autonomous_interaction_decider`
- `autonomous_topic_evaluate_completion`
- `deterministic_fact_validator`

Internal Directiveは新因果経路より古いが、Activity RegistryとActivity Plan Validationが依存しているため、現時点ではActiveである。一括削除しない。

### Compatibility

- `internal_directive_to_intention_projection`
- `drive_should_start_autonomous_talk`
- `autonomous_topic_should_complete_tuple`
- `legacy_expression_name`
- `legacy_gesture_name`
- `character_self_reported_claims`

Compatibility経路は事実決定権限を持たないか、新経路の拡張を抑止するためにだけ使う。

### Deprecated

- `user_body_command_as_primary_motion_driver`

ユーザー身体コマンドをBodyの主制御経路へ戻さない。Bodyの通常挙動はEmotion・Drive・Interaction Intentionから連続生成する。

## 4. 共通因果診断

`CausalDecisionSnapshot`は判断段階ごとに次を記録する。

- stage
- causal route
- legacy route
- outcome
- finite intention
- finite action
- accepted
- scalar metrics

判断段階:

- interaction intention
- autonomous start
- character claim
- autonomous continuation
- autonomous completion

共通Trace:

```text
causal_agent:decision_snapshot
```

Raw User Text、Prompt本文、Character本文、Memory本文は記録しない。

## 5. 自律開始

Phase 4の保守的ゲートを維持する。

```text
legacy=false, causal=false -> 開始しない
legacy=false, causal=true  -> expansion blocked
legacy=true,  causal=false -> causal veto
legacy=true,  causal=true  -> conservative allowed
```

`drive_should_start_autonomous_talk`はCompatibilityであり、単独では開始を決定しない。

## 6. 自律継続・終了

旧`should_complete()`はCompatibilityラッパーへ縮小し、内部判断は`evaluate_completion()`が型付きで行う。

```text
AutonomousContinuationEvaluation
  action: continue / complete
  reason
  continuation_strength
  turn_count
  waiting_for_user
  hard_limit_reached
```

終了条件:

1. 発話がユーザーへの質問で終わった
   - `user_response_expected_after_question`
   - 沈黙を継続要求として扱わず、即座に発話権を返す
2. 最大自律ターン数へ到達した
   - `maximum_autonomous_turns_reached`
   - デフォルト3ターン
3. 2ターン以上で継続強度が閾値以下になった
   - `topic_continuation_strength_exhausted`

それ以外だけ継続する。

これにより、質問後にユーザーが応答していないのに同じActivityが話し続ける経路を閉じる。

## 7. Character実行主張

Character JSONの自己申告ClaimはCompatibility入力であり、実行事実の正本ではない。

事実の正本:

- `ActivityExecutionResult`
- `ResponseContext.status`
- allowed claims
- forbidden claims
- 本文から独立抽出したClaim
- `DeterministicFactValidator`

### 身体動作完了

Interaction Intentionが`act`の場合、本文の身体動作完了形を独立抽出する。

検出例:

- 右手を挙げた
- 左腕を振った
- ジャンプした
- しゃがんだ
- 振り向いた
- うなずいた

次の条件を満たさなければ拒否する。

```text
activity_type != conversation
AND execution_status == succeeded
```

拒否理由:

```text
embodied_action_claim_without_execution_result
```

未来・意思表現は完了主張として扱わない。

- 右手を挙げてみるね
- ジャンプしてみるね

したがってBody実行結果がない状態で「右手を挙げたよ」と発話することはできない。

## 8. 維持する互換境界

### Internal Directive

Activity選択・Registry検証・Capability解決が依存している。Phase 6では削除しない。

### Drive開始閾値

自律開始を増やさない保守的ANDゲートとして残す。診断結果を蓄積する前に削除しない。

### Legacy expression / gesture

既存Character parserとAvatar Adapterが利用している。高レベル表現契約へのAdapter移行後に削除する。

### Character self-reported claims

旧JSON互換として受け取るが、独立抽出と実行結果に反する場合は拒否する。

## 9. 安全に縮小した箇所

- Agent内部の自律継続判断をtupleから型付き評価へ移行
- tuple APIを既存呼出し向けCompatibilityラッパーへ限定
- Character自己申告`conversation_only`が本文中の身体実行完了を隠せた経路を閉鎖
- 質問後の沈黙を自律継続理由として扱う経路を閉鎖
- 自律発話へ最大ターン境界を追加

## 10. 残作業

以下は後続の独立移行として扱う。

- Activity選択からInternal Directiveを外す
- Drive Compatibilityゲートを統計に基づいて縮小する
- Character JSONのlegacy expression / gestureを廃止する
- Avatar Adapterを高レベルBody契約だけへ移行する

これらは現在のPhase 1〜6 PR群を統合・実動作検証した後に行う。
