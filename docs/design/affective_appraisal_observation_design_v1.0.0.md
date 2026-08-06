# Affective Appraisal観測実装設計

- Version: 1.0.0
- Status: Implemented in Phase 1 branch
- Parent design: `emotion_causal_agent_architecture_v1.0.0.md`
- Overall phase: 1 / 6

## 1. 目的

感情を人格的行動の心理的起点とする因果モデルへ移行するため、現在のEmotion更新を変更せずに、次を型付きで観測する。

- Event
- 利用可能なStructuredInputMeaning
- Relationship
- 直近Emotion History
- 出来事をどう受け止めたかを表す評価次元
- Emotion Stateへの投影
- 現行Emotion更新結果との差分

Phase 1はShadow観測だけを行う。Desire、Drive、Motivation、Activity、自律発話、Character Response、Bodyの選択結果を変更しない。

## 2. 現行実装との関係

現在の`EmotionAppraiser`と`EmotionStateUpdater`は、すでに次の責務を持つ。

```text
AgentEvent
  -> EmotionAppraiser
  -> EmotionAppraisal（Emotion差分）
  -> EmotionStateUpdater
  -> EmotionState
```

Phase 1では、この経路を実更新の正として維持する。

```text
現行EmotionAppraisal
        ├─ 現行Emotion State更新
        └─ AffectiveAppraisalObserver
             ├─ 意味・関係・記憶の証拠要約
             ├─ Affective評価次元
             ├─ Shadow Emotion投影
             └─ 現行更新との比較Trace
```

`projection_source`は`legacy_emotion_appraiser_shadow`と明示する。これは最終的なAffective Appraiserが完成したという意味ではない。

## 3. 型付き契約

### 3.1 AffectiveInputMeaning

Affective Appraisalが参照できた入力意味の安全な要約を保持する。

- `available`
- `source`
- `input_speech_act`
- `primary_intent`
- `expected_response`
- `target_type`
- `target_id`
- `confidence`

Raw User Text、entities全文、information_provided全文は保持しない。

### 3.2 AffectiveAppraisalDimensions

- `pleasantness`: -1.0..1.0
- `activation`: 0.0..1.0
- `novelty`: 0.0..1.0
- `social_relevance`: 0.0..1.0
- `relationship_significance`: 0.0..1.0
- `certainty`: 0.0..1.0
- `controllability`: 0.0..1.0
- `approach`: -1.0..1.0
- `tension`: 0.0..1.0

Phase 1では、現行投影後Emotion、Event種別、Relationship、意味解析Confidenceから決定論的に導出する。係数は観測用の暫定値であり、Activity判断には使用しない。

### 3.3 AffectiveEmotionProjection

現行`EmotionAppraisal`の各差分を、将来差し替え可能な投影契約として保持する。

### 3.4 AffectiveAppraisal

- Event識別子とEvent種別
- 入力意味の要約
- 評価次元
- Emotion投影
- 投影元
- 原因カテゴリ
- Confidence
- Relationship識別子とRole
- Emotion History件数
- 同じ原因カテゴリの履歴件数

`observation_only=true`として外部化する。

### 3.5 AffectiveAppraisalComparison

Shadow投影後Emotionと、現行Runtimeが確定したEmotionを比較する。

- `matched`
- `max_abs_difference`
- `mismatched_fields`
- `projected`
- `actual`

比較対象はmood、arousal、valence、talkativeness、8種類のReactive Emotionとする。

## 4. StructuredInputMeaningの取得

Phase 1は、Event Payload内の次の既存互換位置を読み取る。

1. `structured_input_meaning`
2. `input_meaning`
3. `_internal_directive.structured_input_meaning`
4. `validated_action_plan.structured_input_meaning`

意味がまだ生成されていないEventでは、Raw User Textを再解釈しない。

```text
meaning.available = false
meaning.source = unavailable
```

として観測する。

これは入力意味解析の責務をEmotion Runtimeへ混入させないためである。通常USER_TEXTの初回AgentState更新時点では意味解析前の場合があるため、意味利用率もPhase 1の観測対象となる。

## 5. RelationshipとMemory

Relationshipは現在対象の次だけを評価へ使用する。

- familiarity
- trust
- affinity
- counterpart ID
- role

`relationship_significance`は次の暫定合成値である。

```text
familiarity * 0.30
+ trust * 0.35
+ normalized_affinity * 0.35
```

Emotion Historyは本文を参照せず、次だけを観測する。

- 保持件数
- 現在のcause categoryと一致する件数

## 6. Runtime統合

```text
AgentEventStateUpdater.update()
  ├─ Drive更新（既存）
  ├─ Desire更新（既存）
  ├─ EmotionAppraiser（既存）
  ├─ EmotionStateUpdater（既存・確定結果）
  ├─ AffectiveAppraisalObserver（新規・観測専用）
  ├─ Relationship更新（既存）
  └─ Moral更新（既存）
```

`AgentEventStateUpdateResult`へ次を追加する。

- `affective_appraisal`
- `affective_comparison`

AgentStateには保存しない。Affective AppraisalはEvent、Relationship、Memory、Emotionから再構築できる観測値であり、Phase 1では永続化しない。

## 7. Trace

Trace label:

```text
affective_appraisal:shadow_compared
```

記録項目:

- Event識別子と種別
- projection source
- cause category
- confidence
- StructuredInputMeaningの有無と有限項目
- Relationshipの有無とcounterpart ID
- History件数
- 評価次元
- 比較一致結果と最大差

記録しないもの:

- Raw User Text
- Prompt
- Character Response本文
- entities全文
- information_provided全文
- Memory本文
- Secret

## 8. Phase 1で変更しないもの

- 現行Emotionの更新結果
- DesireのEvent直接更新
- DriveのEvent直接更新
- Moral更新
- Motivation Appraisal
- Activity候補順
- Internal Directive
- 自律発話開始条件
- Response Content Plan
- Character LLM Prompt
- Body表現
- Safety、Authority、Capability、Constraint

## 9. テスト

- StructuredInputMeaningを型付き証拠へ変換できる
- 内部指令互換位置から意味を取得できる
- Raw User TextをTraceへ複製しない
- RelationshipとHistoryの要約を保持する
- 評価次元を契約範囲へClampする
- Shadow投影と現行更新が一致する
- 差がある場合に対象Fieldを列挙できる
- `AgentEventStateUpdater`の確定Emotionが従来と同じである

## 10. 完了条件

Phase 1は次を満たした時点で完了とする。

- 型付きAffective Appraisal契約が存在する
- 通常Event更新経路で毎回Shadow観測される
- 現行Emotion更新との比較Traceが出る
- Raw User Textを新規Traceへ複製しない
- 既存Runtimeの判断結果を変更しない
- 全体テストが成功する

## 11. 次工程

Phase 2では、Phase 1の観測値を基礎に次を行う。

- Desireのraw Event直接更新を互換経路へ縮小
- EmotionとActivity Result AppraisalからDesireを更新
- DriveをEmotion、疲労、直近Activityから導出
- `drive.curiosity`をCompatibility fieldへ移行
