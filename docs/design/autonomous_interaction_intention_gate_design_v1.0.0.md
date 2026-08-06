# 自律開始Interaction Intentionゲート設計

- Version: 1.0.0
- Status: Implemented in Phase 4 branch
- Parent roadmap: Issue #167
- Phase issue: #171
- Overall phase: 4 / 6

## 1. 目的

自律発話の開始をDriveの単純閾値だけで決めず、Emotion、Desire、Motivation、Relationship、話題継続状態から「今、会話ターンを取る心理的理由があるか」を判断する。

```text
Emotion / Desire / Drive / Motivation
Relationship / Topic Continuation / Conversation State
        ↓
Autonomous Interaction Decision
        ↓
start / wait / observe
        ↓
既存Drive閾値との比較
        ↓
保守的ゲート
```

Phase 4では、新判断だけで自律発話を増やさない。旧Drive閾値と新判断の両方が開始を認めた場合だけ、既存の自律Eventを生成する。

## 2. 型付き契約

### 2.1 AutonomousInteractionAction

- `start`: 自律的に対人Activityを開始する
- `wait`: 状態が落ち着くまで待つ
- `observe`: 発話せず状況や内的変化を観察する

### 2.2 AutonomousInteractionDecision

- action
- Interaction Intention
- confidence
- reason
- legacy drive readiness
- conversation resume reason
- topic continuation decision

### 2.3 AutonomousInteractionComparison

- `legacy_drive_ready`
- `causal_should_start`
- `matched`
- `conservative_start_allowed`
- `expansion_blocked`
- `causal_vetoed_legacy_start`

## 3. 保守的移行

```text
legacy=false, causal=false → 開始しない
legacy=false, causal=true  → 開始しない（expansion blocked）
legacy=true,  causal=false → 開始しない（causal veto）
legacy=true,  causal=true  → 開始を許可
```

新判断は、旧閾値が開始しなかった場面を新たに開始させない。比較ログを蓄積した後、Phase 6で旧閾値を削除できるか判断する。

## 4. Interaction Intentionの導出

### 4.1 既存ActivityのLookahead

準備済み自律Activityの次ターンは`share`として継続する。これは新規の会話占有ではなく、進行中Activityの継続である。

### 4.2 中断話題の継続

Topic Continuationがresume／branch／start new topicを選び、対象話題が存在する場合は`share`として開始可能にする。

### 4.3 Security・緊張

次の場合は`pause`／`wait`とする。

- primary desireがsecurity
- securityを含むDesire conflict
- fear、discomfort、emotional pressure、angerの最大値が高い
- energyまたはtalkativenessが低い

### 4.4 Expression・Autonomy

表出強度が十分な場合は`share`を選ぶ。弱い場合は`observe`とする。

### 4.5 Connection

Relationshipが存在し、engagementとexpression strengthが十分な場合だけ`invite`を選ぶ。それ以外は`listen`／`observe`とする。

### 4.6 Curiosity

Global Curiosityだけでは質問を生成しない。

- curiosityが高い
- expression strengthが十分
- Motivationに`explore_related_topic`がある

この場合は`ask`ではなく`share`として、自分の観察・知識・関連話題を共有する。条件不足では`observe`する。

### 4.7 Achievement・Recognition

非発話Activityの動機として`act`を保持するが、自律発話は開始しない。PluginやActivity選択は既存Activity境界に委ねる。

### 4.8 Boredom

boredomだけでは会話ターンを取る理由にしない。旧閾値がboredomで開始可能でも、新判断は`observe`として拒否できる。

## 5. Interaction Intentionの昇格

Phase 3ではすべてのInteraction Intentionが`observation_only=true`だった。

Phase 4では契約へ`observation_only`を明示し、次を区別する。

- 通常Internal DirectiveとのShadow比較: `true`
- 自律開始の保守的ゲートに採用する意図: `false`

採用されるのは開始／待機の有限判断だけであり、発話本文、Activity実行可否、Capability、Authority、Safetyは決定しない。

## 6. Runtime統合

`AutonomousEventPlanner`は従来の安全・会話・Activity境界を先に維持する。

1. Pending confirmation
2. Active／Pending／Ongoing Activity
3. Awakening settle
4. Conversation idle timeout
5. Topic continuation
6. Emotionによる発話抑制
7. Motivation構築
8. Autonomous Interaction Decision
9. 旧Drive閾値との保守的比較
10. Speech pause／User handoff／Retry／Talk interval
11. 自律Event生成

既存境界をInteraction Intentionが迂回することはない。

## 7. Event Payload

開始を許可したEventへ次を追加する。

- `interaction_intention`
- `autonomous_start_decision`
- `autonomous_start_comparison`

既存の次は維持する。

- `reason=internal_drive`
- `drive`
- `motivation`
- `memory.response_content_plan`
- topic continuation情報
- interaction environment

## 8. Skip理由

- 旧Drive閾値が弱い: `drive_too_weak`
- 旧閾値は強いが心理的開始理由がない: `interaction_intention_wait`

どちらも比較情報をdetailsへ含める。

## 9. Trace

```text
autonomous_interaction:decision_compared
```

記録項目:

- action／intention／reason／confidence
- primary desire
- legacy／causal比較
- resume／continuation状態
- topic有無
- emotion・driveの有限値

Raw User Text、話題本文、Prompt、Character Response本文は記録しない。

## 10. 変更しないもの

- Pending confirmation
- Activity競合
- Conversation idle timeout
- Topic continuationのWAIT／SUSPEND／ABANDON
- Emotion Activity Policy
- Speech handoff interval
- Retry backoff
- Activity Registry／Capability／Authority／Safety／Constraint
- Character Response本文
- Body表現

## 11. テスト

- 強いCuriosityは質問ではなくshareとして開始する
- boredomだけでは会話ターンを取らない
- 新判断だけが開始でも旧閾値が弱ければ開始しない
- security動機は旧閾値を拒否する
- 許可Eventへ採用済みInteraction Intentionと比較結果を含める
- Phase 3のShadow意図は観測専用のまま
- 既存AutonomousEventPlanner回帰を維持する

## 12. 完了条件

- 型付き開始判断が存在する
- Emotion／Motivation／Conversation状態から決定論的に導出する
- 旧Drive閾値と比較できる
- 保守的ゲートとして通常Runtimeへ接続する
- 新判断だけで発話を増やさない
- boredomだけの開始を抑制できる
- 全体pytestが成功する

## 13. 次工程

Phase 5では、採用されたInteraction IntentionをCharacter ResponseとBodyへ共通上流契約として接続する。