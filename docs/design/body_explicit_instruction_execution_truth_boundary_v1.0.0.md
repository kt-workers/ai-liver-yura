# 意識的Body行動・実行事実境界 v1.1.0

## 1. 目的

Issue #184「Character/Body出力が内部指示器の意識的行動決定と一致しない」を、既存の因果設計とBody責務分離を崩さずに修正する。

本設計の正本は、Character発話でもBody実行結果でもユーザー入力そのものでもない。**Internal Directive LLMが決定した「ゆらは何をする／しないか」という意識的行動決定**である。

```text
Perception / Input / Memory / Internal State
→ Input Meaning / Appraisal
→ Internal Directive LLM
   conscious action decision
      ├─ CharacterLLM → Speech realization
      ├─ Body Realizer → Body motion realization
      └─ Other Realizer → Voice / Face / Gaze / etc.
```

CharacterとBodyは兄弟Realizerであり、片方の出力を見てもう片方の意思を決めない。それぞれが同じValidated Internal Directiveに従う。

## 2. 非目標

- Raw User TextをBody Controllerへ渡さない。
- `StructuredInputMeaning.body_instruction`をそのままBody実行命令にしない。
- Character発話を見てBody動作を決めない。
- Body実行結果を見てCharacterの意思そのものを決めない。
- `right_look`、`raise_right_hand`のような固定Motion名を意識的行動の正本にしない。
- `MOVE → SPEAK`の順序を人格の意思決定ルールにしない。
- `WAITING_INPUT`やpreflight結果を「ゆらはできない」という自己認識へ変換しない。
- 実行失敗をInternal Directiveより先回りして仮定しない。
- Characterに身体動作の実況・完了報告を強制しない。

## 3. Input Meaningの責務

入力意味解析LLMは、ユーザーが何を要求・質問・報告したかを構造化する。

明示的な身体要求は次のモデル非依存意味として保持できる。

```text
StructuredInputMeaning
  body_instruction:
    effector
    direction
    side
    magnitude
```

ここでの`body_instruction`は**ユーザーが望んだ身体行動の意味**であり、ゆら自身が実行すると決めた事実ではない。

この段階では以下を決めない。

- ゆらが要求に応じるかどうか
- Activityを開始するかどうか
- Pose軸 / 関節角 / 軌道
- 固定Motion / Preset
- Body Runtimeの実行成否
- Characterが何を発言するか

したがって正規経路で次を行ってはならない。

```text
StructuredInputMeaning.body_instruction
→ Body Runtime
```

## 4. Internal Directiveが意識的行動を決める

Internal Directive LLMは、Input Meaning、内部状態、Appraisal、Character Profile、利用可能Activity等を踏まえ、ゆら自身が何をするかを決める。

明示Body要求に応じて身体を動かすと判断した場合は、既存の`InternalDirective.activity_intent`を正本として用いる。

```text
InternalDirective.activity_intent
  activity_type = body_expression_loop
  operation = start
  constraints:
    body_action_intent:
      effector
      direction
      side
      magnitude
```

`body_action_intent`はInput Meaningの要求を単純コピーする必須契約ではない。Internal Directiveが実際に行うと決めた高レベル身体意図を表す。

Internal Directiveが身体行動を選ばなければ、Input Meaningに`body_instruction`が存在してもBodyを実行してはならない。

### Core-owned Body Activity

`body_expression_loop`はCoreが所有する意識的Body Activityとして、明示Body要求を評価するTurnではInternal Directiveが選択可能である。

Plugin Activity Registryが空でも、Core-owned Activityであることを理由にInternal Directive Validatorが正規に検証できる。

後段がInput MeaningからActivityを復元して、この意思決定をバイパスしてはならない。

## 5. Validated Internal Directiveを共通正本にする

Internal DirectiveはCore Validatorを通して`ValidatedActionPlan`となる。

```text
StructuredInputMeaning
→ InternalDirective
→ Core Validator
→ ValidatedActionPlan
```

Character RealizerとBody Realizerは**同じValidatedActionPlan / Internal Directive revision**を参照する。

```text
Validated Internal Directive
   ├─ CharacterLLM
   └─ Body Realizer
```

Activityへ射影した後も`_internal_directive` envelopeを失ってはならない。Conversation以外のBody Activityでも、CharacterとBodyが同じ意思を追跡できるよう保持する。

## 6. Character Realizerの責務

CharacterLLMはInternal Directiveの`response_mode`、`response_goal`、`content_requirements`、`activity_intent`等を受け、自然な発言を生成する。

Internal Directiveが「右手を上げる」と決めた場合でも、Characterに以下を強制しない。

- 「右手を上げたよ」と報告する
- 身体動作を実況する
- 完了を説明する

次のような出力もDirectiveと矛盾しなければ正しい。

- `うん`
- 指示内容への自然な短い反応
- 別の自然な発話
- 発話しない方針

一方、Internal Directiveが身体行動を選び、実行失敗が確定していない状態で次のような自己否定を生成するのはバグである。

- `体は動かせない`
- `身体を動かすことはできない`
- `その動作はできない`
- アバターBody能力を存在境界と混同した能力否定

Response Validationは、Character出力をBody出力と比較するのではなく、Validated Internal Directiveと既知のExecution Factに対して検証する。

## 7. Body Realizerの責務

Body RealizerはInternal Directiveの`body_action_intent`を高レベル身体意図として受け取り、Body側の身体知識と現在状態から実現する。

現PR #202では既存Body実行境界との互換のため、Validated Directive由来`body_action_intent`を移行用`_body_instruction`へ射影している。

重要なのは、その値の出所が必ず次であること。

```text
Validated Internal Directive
→ body_action_intent
→ runtime compatibility projection (_body_instruction)
→ Body execution
```

次は禁止する。

```text
StructuredInputMeaning.body_instruction
→ _body_instruction
→ Body execution
```

`_body_instruction`は認知上の正本ではなく、既存#202実行機構へ接続するための移行用Adapter値である。

### Generative Body Motionとの関係

Bodyが高レベル身体意図をどう関節運動へ変換するかはIssue #211が所有する。

最終形は次を目標とする。

```text
Internal Directive body_action_intent
→ Body Motion Planner / BodyLLM
  + current pose / velocity
  + Skeleton Profile
  + Joint hierarchy / DOF / limits
  + kinematic chain
  + continuous Emotion / Activity expression
→ multi-joint motion / trajectory / IK
→ BodyPoseFrame
```

#202の目的は#211を完了させることではなく、**Bodyが実現する意思の正本をInternal Directiveへ戻すこと**である。

## 8. 意思と実行事実を分離する

Internal Directiveは「何をするか」を決める。Body Runtimeは「実際にどうなったか」を返す。

```text
Directive intent
→ Body realization
→ Runtime execution
→ Execution Result
```

少なくとも次を概念上分離する。

- intended / selected
- accepted / planned
- started
- observable / applied
- completed
- rejected / unsupported / failed

`preflight=ACCEPTED`は「意識的に行動を選んだ」ことそのものではない。また「実行成功」でも「実行不能」でもない。

Body実行に失敗した場合はExecution Factとして記録し、必要であれば次の認知サイクルへ戻す。

```text
Body Runtime FAILED
→ Event / Appraisal
→ next Internal Directive
```

Characterが同一ターンで「実行済み」「完了した」という事実を明示する場合だけ、その主張には対応するExecution Resultが必要である。

## 9. preflight / MOVE / SPEAKはRuntime detail

PR #202で導入したpreflightと同期`MOVE`は、短時間Body動作がLLM待ち時間中に消費される問題を避け、Body実行結果をSpeech結果と分離するためのRuntime機構として残す。

例:

```text
Validated Directive
→ Activity projection
→ preflight
→ Character realization
→ ActionPlan
→ MOVE
→ SPEAK
```

ただし、この順序は次を決める根拠ではない。

- ゆらが身体を動かすか
- ゆらが何を言いたいか
- CharacterとBodyの人格上の整合性

それらの正本はすでにValidated Internal Directiveで決まっている。

## 10. 存在境界

Character Profileの「物理的な身体を持たない」は、人間と同じ生物学的肉体や現実空間での身体経験を創作しないための存在境界である。

これは次を意味しない。

```text
アバターBodyを動かせない
```

ゆらにはAvatar Bodyを表現・操作する能力があり、Internal Directiveはその能力を意識的行動として選択できる。

したがって、身体行動を選んだDirectiveに対し「物理的身体がないから動けない」とCharacterが自己否定するのは存在境界の誤適用である。

## 11. 独立した整合性検証

検証対象は`Speech ↔ Body`ではない。

```text
Character output ↔ Validated Internal Directive
Body output      ↔ Validated Internal Directive
Other output     ↔ Validated Internal Directive
```

### Character側

- Directiveが身体行動を選んだのに、能力不可を虚偽に主張しない。
- Directiveと矛盾しない自然な発言・無言を許容する。
- 実行完了を主張する場合だけExecution Factを要求する。

### Body側

- Directiveが身体行動を選ばなければ、Input Meaningの要求だけで動かない。
- Directiveが身体行動を選べば、そのBody intentionを実行系へ渡す。
- 実行不能ならtyped failureを返す。
- #211導入後は高レベル意図を関節・IK等で実現する。

## 12. Trace / Verification

実HTTP/SSE環境では、最低限次を同一Turnで追跡できること。

```text
StructuredInputMeaning
→ Internal Directive
→ ValidatedActionPlan
→ Character realization
→ Body realization
→ Body execution result
→ BodyPoseFrame / HTTP / SSE
```

手動Verificationでは単に「発話とBodyが同じことを言っているか」を見るのではなく、次を確認する。

1. `右見て` / `右手挙げて`等のInput Meaningがユーザー要求として解析される。
2. Internal Directive自身が`body_expression_loop`と`body_action_intent`を選択する。
3. Directiveが選択しなければ、Input Meaningだけを理由にBodyは動かない。
4. Directiveが選択した場合、Body実行系へ同じbody intentionが渡る。
5. Characterが同じDirectiveと矛盾する`体は動かせない`等を生成しない。
6. Characterに身体動作の実況を強制しない。
7. Body未接続/unsupportedの場合はtyped failureとなる。
8. 実Body Pose変化をHTTP/SSEで観測できる。

## 13. 完了・マージ条件

- [ ] Input Meaningの身体要求からBody Runtimeへの直接実行経路がない。
- [ ] Internal Directiveが意識的Body Activityを選択できる。
- [ ] Core-owned `body_expression_loop`がPlugin Registry空でも正規に検証できる。
- [ ] Body Activity化後も同じValidated Internal Directive envelopeが保持される。
- [ ] CharacterとBodyが同じDirectiveを参照する。
- [ ] Directive未選択時はBody要求だけで動かない。
- [ ] Directive選択時はBody intentionが実行系へ渡る。
- [ ] Directive選択＋未失敗時にCharacterがAvatar Body能力を虚偽に否定しない。
- [ ] Characterの身体動作実況・完了報告を必須にしない。
- [ ] 実行完了主張にはExecution Factを要求する。
- [ ] preflight / MOVE / SPEAKを意思決定の正本として使わない。
- [ ] Body実行失敗を次の認知サイクルへ戻せる設計を維持する。
- [ ] #211のGenerative Motionと責務が分離されている。
- [ ] 全体pytestが成功する。
- [ ] 実HTTP/SSE環境でDirective・Character・Bodyを同一Traceとして確認する。
- [ ] ユーザーの実画面確認まではDraft・未マージを維持する。
