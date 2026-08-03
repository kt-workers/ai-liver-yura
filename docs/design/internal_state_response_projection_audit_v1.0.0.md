# 内的状態からCharacter発話への投影監査 v1.0.1

## 1. 目的

チャットへのリアクション品質を、次の二つへ分離して評価する。

1. 内的状態モデルがCharacter生成まで正しく届いているか
2. 届いた状態を使って自然なセリフを生成できているか

本資料は前者だけを対象とする。セリフの言い回し、反復、質問頻度、話題展開、接触リアクションの改善は対象外とする。

## 2. 調査対象

- Base: `fix/runtime-character-evaluation-blockers`
- Branch: `fix/internal-state-response-projection`
- 起点SHA: `8db777e90b51b6b54d9d1a11f4a05f6e0e6b05f4`

確認した主な経路は次のとおり。

```text
AgentState
  ├─ DriveState
  ├─ EmotionState
  ├─ DesireState
  ├─ MoralProfile / MoralState
  ├─ RelationshipState
  ├─ SituationState
  └─ AgentMemoryState
        ↓
BehaviorPlanningContextBuilder
        ↓
MotivationAppraiser
        ↓
ResponseContentPlanner
        ↓
AgentEvent.payload
        ↓
ActivityManager
        ↓
ResponseContextBuilder
        ↓
CharacterPromptBuilder
        ↓
Character LLM
```

## 3. 監査結果

### 3.1 Desire／Motivation／Moral

欲望は`MotivationAppraiser`で順位付けされ、会話戦略、表現強度、競合へ変換される。

その後`ResponseContentPlanner`が次の有限な発話方針へ変換する。

- `primary_desire`
- `conversation_strategies`
- `value_emphases`
- `interpersonal_stance`
- `expression_mode`
- `self_disclosure_level`
- `conflict_mode`
- `question_budget`
- `new_direction_budget`

この`ResponseContentPlan`はイベントのMemoryへ格納され、Character Promptへ投影される。したがって、欲望・Motivation・Moralの基本経路は存在する。

### 3.2 Relationship／Situation／Memory

これらは通常会話でも`event_payload`を経由してResponse Contextへ到達する。

### 3.3 Emotion／Driveの欠落

`BehaviorPlanningContextBuilder`は通常会話イベントへ次を格納している。

```text
event_payload.emotion
event_payload.drive
```

しかし従来の`ResponseContextBuilder`は次だけを参照していた。

```text
emotion = activity.context.emotion
drive = autonomous_situation_context.drive_state
```

通常会話Activityでは状態は`activity.context.event_payload`内に保持されるため、Character用Response ContextでEmotion／Driveが空になる。

## 4. 修正契約

状態取得元の優先順位を全Activityで統一する。

### Emotion

```text
1. event_payload.emotion
2. activity.context.emotion
3. autonomous_situation_context.emotion_state
```

### Drive

```text
1. event_payload.drive
2. activity.context.drive
3. autonomous_situation_context.drive_state
```

最新のイベントスナップショットを優先し、既存Activityおよび自律発話形式は互換フォールバックとして維持する。

DriveはCharacter Response Contextの型契約に合わせ、真偽値を除く数値項目だけを投影する。

## 5. Trace

次のTraceを追加する。

```text
response_context_builder:internal_state_projected
```

記録内容：

- `emotion_source`
- `drive_source`
- `emotion_available`
- `drive_available`
- `emotion_keys`
- `drive_keys`

これにより、セリフ内容を読む前に状態がCharacter境界へ届いたかを確認できる。

## 6. 回帰テスト

次を固定する。

1. 通常会話のイベントEmotion／DriveがResponse Contextへ届く
2. イベントの最新状態が古いActivity snapshotより優先される
3. 自律発話のSituation状態が引き続き使われる
4. 接触など既存Activity context形式が互換維持される

## 7. 対象外

- Emotion、Drive、Desireの更新式
- セリフの自然さ
- 意味的反復
- 質問頻度
- 話題展開
- 接触対象・部位・ドラッグ区間

これらは状態投影の正しさを確定した後、別ブランチで評価する。
