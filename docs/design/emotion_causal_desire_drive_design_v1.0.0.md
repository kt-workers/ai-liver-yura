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

- `curiosity`: Desire curiosityと短期探索圧の互換投影
- `engagement`: Emotionと社会的関与から導出した現在の関与可能性
- `boredom`: activation、novelty、social relevance、engagementの低さから導出
- `energy`: Activity・発話等による消費と、低活性時の回復

Driveから話題やActivity内容を直接作らない。

### 4.2 Curiosity互換

Event更新時は次の大きい方を使用する。

```text
desire curiosity + event novelty
previous drive curiosity × 0.96
```

`CURIOSITY_PEAK`は現在の内的状態をActivity計画へ渡す通知であり、新しい刺激ではない。そのため、このEventでは短期慣性を減衰させない。

時間経過時は、Activityがない時間にだけ有限の探索圧を加える。

```text
drive.curiosity target
  = desire.curiosity.effective_level
  + min(0.40, 0.06 × idle elapsed minutes)
```

これにより次を区別する。

- Desire curiosity: 長期的な「知りたい」
- Event novelty: 新しい刺激への短期反応
- Drive inertia: 直前の探索意欲が急に消えないための短期慣性
- Idle exploration pressure: 何もしていない時間から生じる一時的な探索準備
- Target Interest: 特定対象への関心

`drive.curiosity`は既存RuntimeとのCompatibility fieldであり、これらを行動開始判定へ渡す短期活性値である。

### 4.3 時間経過

時間更新は次の順序で行う。

```text
Emotion decay
  → Desire baseline / satisfaction / frustration更新
  → Drive追従・疲労回復
  → Moral更新
```

Activity実行中はenergyを消費する。Activityがなく低arousalの場合は基準energyへ回復する。

経過時間が内部時計より前の場合、DriveとDesireの結果値は変化させないが、負の経過秒数は診断値として`ElapsedStateUpdateResult`へ保持する。各内部時計は`max(previous, now)`で更新し、巻き戻さない。

`record_event()`はEmotion、Desire、Moralの基準時刻をEvent時刻へ進める。Driveの無活動時間はEventを挟んでも連続計測し、自律的な探索圧を失わない。

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
- `drive.curiosity`がDesire curiosityと短期補正の互換投影になる
- 高い探索Driveが次のEventで急に消えず、徐々に減衰する
- 無活動時の探索圧が上限付きで加わる
- 経過時間でEmotion、Desire、Driveの順に更新される
- 負の経過時間を観測しても内部時計が巻き戻らない
- 旧Updater APIの既存テストが維持される

## 9. 完了条件

- 通常Event経路が`Emotion → Desire → Drive`の順で動く
- Activity結果がEmotionへ戻る
- Raw Eventだけで通常Desireを直接増やさない
- DriveがEmotion・Desire・疲労・短期探索圧から導出される
- Compatibility APIと既存境界を維持する
- 全体テストが成功する

## 10. 次工程

Phase 3では、Motivationから有限集合の`InteractionIntention`を生成し、既存`response_mode`と`activity_intent`とのShadow比較を追加する。
