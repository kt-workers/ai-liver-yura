# Emotion起点のDesire・Drive更新設計

- Version: 1.0.0
- Status: Implemented in Phase 2 branch
- Parent design: `emotion_causal_agent_architecture_v1.0.0.md`
- Overall phase: 2 / 6

## 1. 目的

Event種別からDesireとDriveを直接変化させる現在の通常Runtime経路を、次の因果へ移行する。

```text
Event / Activity Result
        ↓
Emotion Appraisal
        ↓
Emotion State
        ↓
Desire State
        ↓
Drive State
```

Desireは「何を満たしたいか」を保持する。Driveは行動内容を決めず、現在の活性、関与、退屈、疲労を表す。

## 2. 更新順序

`AgentEventStateUpdater`の通常経路を次の順序へ変更する。

1. EventをEmotion Appraisalへ変換
2. Emotion Stateを確定
3. Affective Appraisalを観測
4. Emotion変化からDesireの方向を更新
5. Activity結果によるsatisfaction／frustrationを反映
6. Emotion、Desire、疲労、Activity有無からDriveを導出
7. RelationshipとMoralを更新

旧順序の`Drive → Desire → Emotion`は使用しない。

## 3. Desire更新

### 3.1 Emotion由来の方向

Affective Appraisalの次元とEmotion差分を、7種類のDesireへ投影する。

- joy、sadness、talkativeness、social relevance → connection
- surprise、novelty、activation → curiosity
- activation、valence変化、pressure、talkativeness → expression
- attention／recognition系causeとjoy → recognition
- anger、pressure → autonomy
- fear、discomfort、pressure、negative valence → security
- failureに伴うanger、discomfort、tension → achievement／frustration

係数は暫定値であり、Traceと実ログで調整する。

### 3.2 Activity Result

Activity Resultは、先に`CausalEmotionAppraiser`で感情へ戻す。

```text
completed → 小さい喜び・安心
partial   → 喜びと残念さの混合
failed    → 怒り・悲しみ・不快・圧力
canceled  → 小さい悲しみ・不快
```

その後、既存`ActivityDesireSatisfactionEvaluator`でActivity目的の充足・不満を反映する。

```text
Activity Result
  ├─ Emotionへの意味
  └─ Desire satisfaction / frustration
```

両者は別の意味を持つため維持する。

### 3.3 Outcome互換

次のEventは、感情由来更新後に既存の結果充足を重ねる。

- `SPEECH_FINISHED`
- `STREAM_COMMENT_RESPONSE`
- `STREAM_ENDED`

### 3.4 Raw Event直接更新の縮小

通常Runtimeは`update_from_affect()`を使用する。

旧`update_by_event()`は既存テスト、診断、段階移行の互換APIとして残すが、`AgentEventStateUpdater`からは呼ばない。

このため、`SILENCE_TIMEOUT`が発生しただけではDesireを増やさない。沈黙をどう感じたかがEmotion Appraisalに現れた場合だけDesireへ伝播する。

## 4. Drive導出

### 4.1 責務

Driveは次だけを表す。

- `curiosity`: Desire curiosityの互換投影
- `engagement`: Emotionと社会的関与から導出した現在の関与可能性
- `boredom`: activation、novelty、engagementの低さから導出
- `energy`: Activity・発話等による消費と、低活性時の回復

Driveから話題やActivity内容を直接作らない。

### 4.2 Curiosity互換

```text
drive.curiosity
  = desire.curiosity.effective_level
  + event noveltyによる短期補正
```

`drive.curiosity`は既存RuntimeとのCompatibility fieldである。長期的な「知りたい」はDesire、対象別の関心はTarget Interestへ移す。

### 4.3 時間経過

時間更新は次の順序で行う。

```text
Emotion decay
  → Desire baseline / satisfaction / frustration更新
  → Drive追従・疲労回復
  → Moral更新
```

Activity実行中はenergyを消費する。Activityがなく低arousalの場合は基準energyへ回復する。

## 5. Trace

```text
desire_state_updater:causal_update
drive_state_updater:causal_derivation
drive_state_updater:causal_elapsed_derivation
```

Traceには本文を含めず、Event ID、Event種別、Affective cause、更新元、有限の状態値だけを記録する。

## 6. 互換境界

Phase 2では次を残す。

- `DesireStateUpdater.update_by_event()`
- `DriveStateUpdater.update_by_event()`
- `DriveStateUpdater.update_by_elapsed_time()`
- `DriveState.should_start_autonomous_talk()`

これらは通常AgentState更新では使わない。`should_start_autonomous_talk()`はPhase 4でInteraction Intentionへ置き換える。

## 7. 変更しないもの

- Activity候補評価
- Internal Directive
- Conversation Response Mode
- 自律発話開始条件
- Character Response
- Body表現
- Safety、Authority、Capability、Constraint

## 8. テスト

- Emotion変化がない`SILENCE_TIMEOUT`ではDesireが直接増えない
- fear／discomfortがsecurity Desireへ伝播する
- 新規刺激がEmotionを経由してcuriosityへ伝播する
- Activity失敗がEmotionを更新してからDesire不満へ反映される
- `drive.curiosity`がDesire curiosityの互換投影になる
- 経過時間でEmotion、Desire、Driveの順に更新される
- 旧Updater APIの既存テストが維持される

## 9. 完了条件

- 通常Event経路が`Emotion → Desire → Drive`の順で動く
- Activity結果がEmotionへ戻る
- Raw Eventだけで通常Desireを直接増やさない
- DriveがEmotion・Desire・疲労から導出される
- Compatibility APIと既存境界を維持する
- 全体テストが成功する

## 10. 次工程

Phase 3では、Motivationから有限集合の`InteractionIntention`を生成し、既存`response_mode`と`activity_intent`とのShadow比較を追加する。
