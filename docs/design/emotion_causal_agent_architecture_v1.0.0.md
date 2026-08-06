# 感情を起点とするエージェント因果アーキテクチャ

- Version: 1.0.0
- Status: Proposed / Authoritative causal model
- Scope: Core cognition, motivation, Activity, conversation, Body expression

## 1. 文書の目的

本書は、AI VTuber「ゆら」における心理状態・行動・表現の因果関係を一本化する。

既存実装では、安全に段階導入するため、Emotion、Drive、Desire、Motivation、Activity、会話応答モード、Body Contextを独立した入力として追加してきた。その結果、コード上の責務分離が、心理的にも互いに独立した原因であるように見える状態が生じている。

本書では次を正本とする。

> ゆらの人格的な行動と表現は、外界・記憶・時間経過をどう受け止めたかという感情評価を心理的起点とする。

Desire、Motivation、Activity、発話、声、表情、視線、Body動作は、感情と並列の行動原因ではない。感情から段階的に派生する持続状態、判断、実行単位、表現チャネルである。

ただし、呼吸、瞬き、姿勢安定化、低遅延の視線追従など、人格判断を伴わない生体維持・反射・センサーモーター処理はこの原則の例外とする。

## 2. 設計原則

### 2.1 心理的な因果は一方向に流す

```text
Perception / Event / Memory / Time
                ↓
         Meaning Appraisal
                ↓
        Affective Appraisal
                ↓
           Emotion State
                ↓
    Desire / Moral State / Drive
                ↓
       Motivation Appraisal
                ↓
       Interaction Intention
                ↓
            Activity
                ↓
       Expression Intention
        ┌───────┼────────┐
        ↓       ↓        ↓
      Speech   Voice    Body
                ↓
         Activity Result
                ↓
        次のAppraisalへ戻る
```

後段の状態を前段へ逆流させない。

- Response Content PlanをActivity選択の事実ソースにしない
- Bodyの現在姿勢をEmotionの原因として直接扱わない
- Activity候補順をEmotionそのものとみなさない
- Driveの数値だけで自律発話を開始しない
- タイマー満了だけで話し始めない

### 2.2 「状態を分ける」と「原因を分ける」を混同しない

Emotion、Desire、Drive、Moral、Relationshipは別のDomain Stateとして保持してよい。

しかし、別オブジェクトであることは、互いに無関係な原因であることを意味しない。

```text
別責務として保持する
    !=
独立した人格主体として判断する
```

### 2.3 Safety、Authority、Capabilityは動機ではない

Safety、Authority、Capability、Existence Boundary、Conversation Flowは、行動理由を作る状態ではなく、採用可能な行動の境界である。

```text
感情・動機
    ↓ 行いたいことを作る
候補Activity
    ↓
Safety / Authority / Capability / Constraint
    ↓ 実行可能性を検証する
Validated Activity
```

境界が行動を拒否した場合、その拒否結果は次の感情評価へ戻り得るが、境界自体が人格的欲望を生成しない。

### 2.4 「発話しない」も表現結果である

沈黙は処理欠落ではない。

- 話したい感情が弱い
- 聞くことを優先したい
- 警戒している
- 疲れている
- 言葉にする前に観察したい
- 感情が落ち着いた

といった状態から、`listen`、`observe`、`rest`、`wait`を選べるようにする。

## 3. 各概念の責務

### 3.1 Trait

長期的に変化しにくい感じ方の傾向を表す。

TraitはActivityを直接選ばない。Affective Appraisalの感度や、感情の立ち上がり方、持続時間、表出しやすさを調整する。

例:

- 社交性が高いほど、相手からの反応を喜びとして評価しやすい
- 警戒心が高いほど、曖昧な接触を不安として評価しやすい
- 表出性が高いほど、同じEmotionでもExpression Intentが強くなる

### 3.2 Relationship

相手との関係に基づき、出来事の意味と感情強度を調整する。

```text
同じ発言
  + familiarity / trust / affinity / recent history
        ↓
異なるAffective Appraisal
```

Relationshipは発話文体だけを変える後処理ではない。感情が生じる前段と、感情をどこまで表へ出すかの両方へ影響する。

### 3.3 Emotion

出来事がゆらにとってどのような意味を持ったかを表す現在状態である。

主な離散感情:

- joy
- amusement
- anger
- sadness
- fear
- surprise
- discomfort
- emotional_pressure

連続軸:

- valence
- arousal
- tension
- approach / avoidance
- social warmth
- certainty

Emotionは単なる表情パラメータではない。Desire、Moral State、Drive、Motivationの更新根拠である。

### 3.4 Desire

Emotionが「何をしたいか」という方向を持って持続した状態である。

```text
寂しい・親しさを感じる
    ↓
connection

面白い・驚いた・分からないことが気になる
    ↓
curiosity

うれしい・興奮した・引っかかった
    ↓
expression

認められてうれしい・役に立ちたい
    ↓
recognition

窮屈・自分で決めたい
    ↓
autonomy

不安・不快・過負荷
    ↓
security

達成感・悔しさ・再挑戦したい
    ↓
achievement
```

Desireは一瞬のEmotionより長く残り得る。Activity結果により満たされたり、不満として蓄積したりする。

Desireのbaselineは独立した命令源ではなく、Traitから導出される「その感情方向へ傾きやすい長期傾向」として扱う。

### 3.5 Drive

Driveは行動内容ではなく、現在どれだけ動けるか、どれだけ外へ関われるかという活性・準備状態である。

主な導出元:

- Emotionのarousal
- 疲労と経過時間
- 直近Activity負荷
- 発話中かどうか
- 睡眠・休止相当の状態

```text
Emotion + fatigue + recent activity
        ↓
energy / engagement / talkativeness / movement_energy
```

DriveだけでActivityを選ばない。

`curiosity`はDriveから段階的に廃止する。長期の探索傾向はTrait、現在の対象への注意はTarget Interest、未知を埋めたい欲求はDesireとして表現する。互換期間中の`drive.curiosity`は導出値または旧入力の読み替えに限定する。

### 3.6 Target Interest

現在どの対象へ意識が向いているかを表す。Emotionそのものではなく、Affective Appraisalの対象と注意状態を保持する。

Target Interestは次から更新する。

- 対象に対して生じたEmotion
- novelty
- relevance
- knowledge gap
- satiation
- relationship
- attention continuity

全体的な好奇心だけで質問を続けず、対象別Interestと未解決Knowledge Gapが揃う場合にのみ、curiosity Desireへ寄与する。

### 3.7 Moral State

Moral Profileは長期的な価値判断傾向、Moral StateはEmotionやActivity結果から変化する一時状態である。

例:

- angerがaggressive_impulseを上げる
- fearやdiscomfortがrestraintを上げる
- Activity失敗がguiltを上げる
- joyや安心が攻撃衝動を下げる

MoralはSafetyの代わりではない。許可済み候補の中で、どの方法を好むか、どのように表現するかを調整する。

### 3.8 Motivation

Motivationは、現在のEmotion、Desire、Relationship、Moral、Target Interest、記憶を統合し、「なぜ今それをしたいか」を表す派生値である。

```text
Motivation
  = emotion fit
  + desire gain
  + target relevance
  + relationship fit
  + moral fit
  - emotional cost
```

MotivationはActivity名を直接生成しない。まずInteraction Intentionを作る。

### 3.9 Interaction Intention

Interaction Intentionは、心理状態から実行管理上のActivityへ移る中間契約である。

初期の有限集合:

- `observe`
- `approach`
- `ask`
- `request_permission`
- `tell`
- `listen`
- `respond`
- `continue`
- `withdraw`
- `rest`
- `express_nonverbally`

例:

```text
うれしい + expression高 + connection高
    ↓
tell

話したい + 相手が別作業中 + respect高
    ↓
request_permission

好奇心 + 対象Interest高 + Knowledge Gapあり
    ↓
ask

不快 + security高
    ↓
withdraw / set_boundary
```

### 3.10 Activity

Activityは継続目的、現在の文脈、TurnごとのAction、Lifecycleを束ねる実行管理単位である。

Activityは感情ではない。Interaction Intentionを、利用可能な機能と実行境界の中で実現する手段である。

```text
Interaction Intention
        ↓
Activity candidate selection
        ↓
Authority / Capability / Safety / Constraint
        ↓
Activity Plan
```

### 3.11 Expression Intention

選択済みActivityと現在Emotionから、何をどの程度外へ表すかを決める。

```text
Expression Intention
- communicative_goal
- affect
- intensity
- openness
- warmth
- approach
- tension
- assertiveness
- attention_target
- speech_permission
```

Expression Intentionを各出力チャネルへ分配する。

- Speech: 何を言うか
- Voice: どのように話すか
- Face: 感情を顔へどう出すか
- Gaze: 何へどの程度注意を向けるか
- Body: 姿勢と身振りへどう出すか
- Silence: 言葉を出さずどう存在するか

## 4. 正規データフロー

### 4.1 通常のユーザー入力

```text
Observed Input
    ↓
Input Meaning Interpreter
    ↓ StructuredInputMeaning
Affective Appraiser
    ↓ AffectiveAppraisal
Emotion State Updater
    ↓ Emotion State
Desire / Moral / Drive Updater
    ↓
Motivation Appraiser
    ↓
Internal Directive Planner
    ↓ Interaction Intention + response obligation
Core Validator
    ↓
Activity Planner
    ↓
Expression Intent Planner
    ↓
Character / Voice / Body
```

Internal Directive Plannerは、構造化入力と内部状態からActivity候補を提案できるが、Emotionを迂回して独立した人格的意図を作らない。

ユーザーの直接質問、明示的命令、終了要求などは`response obligation`または`external constraint`として保持する。これは現在Emotionを消去せず、行動候補の優先条件として作用する。

### 4.2 Activity結果

```text
Activity Result
    ↓
Result Meaning Appraisal
    ├─ 達成できた
    ├─ 失敗した
    ├─ 途中で止まった
    ├─ 相手に受け入れられた
    └─ 拒否された
    ↓
Emotion State Update
    ↓
Desire satisfaction / frustration Update
    ↓
次のMotivation
```

Activity結果からDesireへ直接係数を加える現在実装は互換経路とする。最終形では、結果の意味評価とEmotion更新を先に行い、その結果からDesire充足を導出する。

### 4.3 時間経過

タイマーや沈黙は発話命令ではなくEventである。

```text
Elapsed Time / Silence
    ↓
Meaning Appraisal
    ├─ 相手が忙しそう
    ├─ 反応がなく寂しい
    ├─ 落ち着いた
    ├─ 退屈してきた
    └─ 休みたい
    ↓
Emotion
    ↓
Motivation
    ↓
話す / 観察する / 待つ / 別Activityへ移る
```

`SILENCE_TIMEOUT`だけで自律発話を開始しない。

## 5. 自律発話

### 5.1 発話条件

自律発話は固定インターバルの出力ではない。

次が揃った場合に候補化する。

- 表現したい、関わりたい、尋ねたい等のEmotion由来Motivationがある
- Conversation Flow上、発話権がある
- 直前の相手入力への返答待ちではない
- 同じ感情・話題を繰り返していない
- Activityとして実行可能
- Safety、Authority、Capabilityを満たす

### 5.2 発話終了

一定時間、一定文数、一定話題数だけで機械的に止めない。

Activity Resultにより、次を再評価する。

- expression Desireが満たされた
- connection Desireが満たされた
- 感情の強度が下がった
- 相手の反応を待ちたい
- 別のEmotionが残っている

話す理由が弱くなれば自然に静かになる。別のEmotionが十分に強ければ、関連する次のActivityへ移る。

### 5.3 許可を求める発話

話したいが、相手の状態やRelationshipから一方的に始めない方がよい場合は`request_permission`を選ぶ。

```text
何かを共有したいEmotion
        ↓
expression / connection Desire
        ↓
相手が別作業中、または慎重に関わりたい
        ↓
request_permission
        ↓
「ちょっと聞いてほしいな」
        ↓
wait
```

ユーザーが承諾した場合:

```text
承諾
  ↓
安心・喜び
  ↓
permission granted
  ↓
tell Activity
  ↓
話し終える
  ↓
充足・落ち着き
  ↓
wait / listen / next emotion
```

## 6. 起動時と常駐時の振る舞い

### 6.1 起動

`application_started`を固定挨拶命令として扱わない。

```text
起動した
  ↓
環境、時間、直前記憶、ユーザー在席を認識
  ↓
Emotion Appraisal
  ↓
安心・期待・好奇心・警戒など
  ↓
Interaction Intention
```

結果は、短い挨拶、視線だけを向ける、周囲を観察する、何も言わない、のいずれもあり得る。

### 6.2 PC操作を観察した場合

```text
操作対象を認識
  ↓
novelty / relevance / Target Interest
  ↓
面白い・気になる
  ↓
curiosity Desire
  ↓
ask または observe
```

「それなーに？」は固定反応ではなく、Interest、Knowledge Gap、関係性、相手の集中状態を評価した結果として出る。

### 6.3 反応がない場合

```text
一定時間反応がない
  ↓
寂しさ・退屈・安心・無関心・休息欲求のいずれか
  ↓
connection / expression / security等
  ↓
ask / observe / rest / 別Activity
```

無反応を「続きを求めている」と解釈しない。罪悪感を与える発話へつなげない。

## 7. 会話応答モードの再配置

既存の`answer / ask / listen / react / speak / observe`は、独立した心理判断器ではなく、Interaction IntentionとExpression IntentionをCharacter境界へ投影する互換表現とする。

```text
Interaction Intention
        ↓
Conversation Response Mode
        ↓
Effective Response Content Plan
        ↓
Character LLM
```

Mode選択はDriveとBudgetの直接スコアだけで決めない。

- Emotion
- Emotionの対象
- Motivation
- response obligation
- current Activity
- Conversation Flow

を確定した後、その結果をModeへ射影する。

## 8. Bodyの位置づけ

### 8.1 Bodyは感情表現チャネルである

BodyはEmotionを決定しない。

```text
Emotion
    ↓
Expression Intention
    ↓
Body Expression Context
    ↓
Body Runtime
    ↓
BodyPoseFrame
```

Body Runtimeは意味軸から顔、視線、頭、胴体、腕、呼吸、瞬き、口形を連続生成する。

### 8.2 Bodyの合成

```text
Final Body Pose
  = affect-driven baseline expression
  + Activity posture tendency
  + attention orientation
  + speech-coupled expression
  + temporary external constraint
  + autonomous physiological motion
```

Activity、Attention、Speech、明示的身体指示を、Emotionと並列の人格的原因として扱わない。それらは、感情表現を実現する文脈、対象、時間同期、外部制約である。

### 8.3 低遅延経路の例外

次はAffective Appraisalを毎フレーム通さずBodyへ直接入力してよい。

- 対象位置の微小変化
- 音源方向
- 視線のデッドゾーン追従
- 姿勢安定化
- 呼吸
- 瞬き
- 音素・Viseme

ただし、誰を見るか、見続けるか、避けるかという人格的判断はEmotion、Target Interest、Activity側で決める。

### 8.4 明示的な身体指示

「右手を上げて」「ジャンプして」等は、Bodyの主入力ではない。

```text
感情から生まれる基礎Body表現
              +
短時間のexternal body constraint
              ↓
同一BodyPoseFrame
```

外部制約が終了したらneutralへ戻すのではなく、現在の感情表現へ連続的に戻る。

## 9. 既存設計書との関係

### 9.1 正本として維持するもの

`character_motivation_morality_design_report.md`の次の考えを正本として維持する。

```text
Emotion Appraisal
    ↓
Emotion State
    ↓
Desire State Update
    ↓
Moral State Update
    ↓
Motivation Appraisal
    ↓
Activity
```

本書はこの因果をCore、会話、自律発話、Bodyまで拡張して確定する。

### 9.2 段階実装仕様として扱うもの

次の資料は、当時の安全な段階導入と現在実装を説明する資料として有効である。ただし、心理的な因果が本書と衝突する場合は本書を優先する。

- `character_desire_state_implementation_design_v1.0.0.md`
- `character_activity_result_desire_satisfaction_design_v1.0.0.md`
- `character_motivation_appraisal_observation_design_v1.0.1.md`
- `character_motivation_activity_candidate_preference_design_v1.0.0.md`
- `character_response_content_plan_and_conversation_evaluation_design_v1.0.0.md`
- `state_driven_conversation_response_mode_design_v1.0.0.md`
- `body_subsystem_architecture_v1.0.0.md`
- `body_runtime_mvp_v1.0.0.md`

### 9.3 維持する実装境界

次は変更しない。

- Input Meaning InterpreterとInternal Directive Plannerの責務分離
- ActivityのLifecycleとActionPlanGroup
- Safety、Authority、Capability、Constraint検証
- Character LLMとValidatorの契約共有
- Bodyの30〜60fps非LLM Tick
- Avatar Adapterが表示・モデル変換だけを担当する境界
- Streaming、Game等のSubsystem分離

## 10. 移行方針

一度に全Runtimeを置き換えない。次の順で移行する。

### Phase 1: 観測

- Affective Appraisalの型付き契約を追加
- Event、StructuredInputMeaning、Memory、RelationshipからAppraisalを生成
- 現在Emotion更新との比較Traceを追加
- 既存Activity結果を変更しない

### Phase 2: DesireとDriveの因果修正

- Desireのraw Event直接更新を互換経路へ縮小
- EmotionとActivity Result AppraisalからDesireを更新
- DriveをEmotion・疲労・直近Activityから導出
- `drive.curiosity`をCompatibility fieldへ移行

### Phase 3: Interaction Intention

- Motivationから有限集合のInteraction Intentionを生成
- Internal DirectiveへInteraction Intentionを追加
- 既存`response_mode`と`activity_intent`は射影として維持
- Shadow比較で現在Activity選択との差を観測

### Phase 4: 自律発話

- タイマーを発話TriggerからAppraisal Eventへ変更
- Emotion由来MotivationとConversation Flowが揃う場合のみ発話
- permission request、wait、resumeをActivity Lifecycleへ追加
- Activity結果から感情を再評価して自然終了する

### Phase 5: Expression Intention

- Speech、Voice、Face、Gaze、Bodyで共有する高レベル表現契約を追加
- Response Content PlanとBodyExpressionRequestを同じExpression Intentionから導出
- Character LLMとBodyが別々の感情解釈をしないようにする

### Phase 6: Body統合

- affect-driven baseline expressionをBody Runtimeの基礎Layerにする
- Activity姿勢、Attention、Speech、外部身体制約を補助Layerへ再配置
- 低遅延反射経路と人格判断経路をテストで分離

## 11. 非対象

本書だけでは次を決めない。

- Emotion AppraisalをLLM、決定論、Hybridのどれで実装するかの最終選定
- 各Emotionの更新係数
- Desireの確定baseline
- Moral Profileの確定値
- 自律発話の具体的なしきい値
- Live2D Parameter名
- 3D Skeleton名
- 音素解析方式
- DB永続化形式

これらは本書の因果関係を守る個別実装設計で定義する。

## 12. 受け入れ条件

- raw EventだけでDesireが人格的行動を開始しない
- Driveの高値だけで自律発話を開始しない
- SILENCE_TIMEOUTだけで話し始めない
- 同じ外界入力でもRelationship、Memory、TraitによりEmotionが変わり得る
- Activity結果がEmotionを更新し、その後Desire充足へ反映される
- 自律発話がEmotion由来の理由を持つ
- 話す理由が満たされたとき自然に静かになる
- 沈黙、観察、待機を正規の表現結果として選べる
- Speech、Voice、Face、Gaze、Bodyが同じExpression Intentionを共有する
- Bodyの意味ある動きが感情表現として説明できる
- 呼吸、瞬き、姿勢安定化、低遅延追従は非人格的例外として独立して動く
- 明示的身体指示は短時間制約として感情表現へ重なる
- Safety、Authority、CapabilityがMotivationと混同されない

## 13. 代表シナリオ

### 13.1 人間さんがPCを操作している

```text
操作対象を観察
  ↓
対象へのnovelty / relevance
  ↓
面白い・気になる
  ↓
Target Interest + curiosity Desire
  ↓
observe または ask
  ↓
視線を向ける / 「それなーに？」
```

### 13.2 人間さんがしばらく操作していない

```text
反応がない
  ↓
寂しい / 退屈 / 安心 / 休みたい
  ↓
connection / expression / security
  ↓
ask / observe / rest
  ↓
「今何してるの？」または静かに待つ
```

### 13.3 ゆらが話を聞いてほしい

```text
共有したいEmotion
  ↓
expression + connection
  ↓
request_permission
  ↓
「ちょっと聞いてほしいな」
  ↓
承諾を待つ
  ↓
承諾で安心・喜び
  ↓
tell
  ↓
充足して静かになる
```

### 13.4 拒否された

```text
「今は無理」
  ↓
残念 / 理解 / 少し寂しい
  ↓
security・relationship・restraintを考慮
  ↓
withdraw / wait
  ↓
短く受け止め、Bodyも現在の感情へ移る
```

拒否を実行エラーだけとして処理せず、次の感情状態へ反映する。
