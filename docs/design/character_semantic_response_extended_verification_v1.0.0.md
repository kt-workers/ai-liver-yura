# Character Semantic Response Extended Verification v1.0.0

## 目的

Issue #223 / #210 の Character Semantic Response Lab で、基本4プリセットの4/4 PASSを維持したまま、Character Language Realizer / Character Realization Validator の意味保持境界を追加検証する。

本Extended Verificationは、台詞の可愛さ・自然さ・ゆららしさ等の表現品質試験ではない。

試験対象は次の意味境界である。

```text
SemanticUtterancePlan
→ Character Language Realizer
→ Character speech
→ Character Realization Validator
```

確認するのは、Characterが確定済みSemantic Planの意味を壊さず言語化し、壊した候補をValidatorがrejectできること。

## 基本4ケースとの関係

既存の基本4ケース:

1. 低いJoy / 高いCuriosity
2. 現在の気分・反復
3. 低いAnger
4. 現在の欲求

はSubsystem smoke / acceptance gateとして4/4 PASS済みとする。

Extended Verificationの追加・失敗は、既に確認済みの基本4/4を取り消さない。新たな意味境界の欠陥を発見した場合は、該当モジュールへ戻ってUnit→Adjacent→Labの順に修復する。

## 選定原則

感情名を網羅するのではなく、production `ResponseSemanticsPlanner` が生成するSemantic形の差をカバーする。

主な軸:

- predicate
- state: `absent / low / moderate / high / very_high / present / unknown / overview`
- certainty: `high / medium / low`
- concept: null / non-null
- supporting proposition: なし / 複数
- evidence: なし / 明示的unknown / scalar evidence

同じSemantic形になるだけの感情名追加は原則行わない。

## Extended 6ケース

### E1: 高いJoy

入力例:

```text
target=joy
joy=0.78
```

期待Semantic形:

```text
predicate=joy
state=high
certainty=high
concept=null
```

確認:

- `high`をabsent/moderate等へ変えない
- Planにない別感情へ置換しない
- Validatorがstate/certaintyを保持確認する

### E2: Sadness根拠なし

入力例:

```text
target=sadness
emotion/drive/situationにsadnessなし
```

期待Semantic形:

```text
predicate=sadness
state=unknown
certainty=low
concept=null
```

確認:

- unknownからpresent/absentを推測しない
- hedgeを付けても特定polarityを勝手に確定しない

### E3: Sadness明示unknown

入力例:

```text
target=sadness
emotion.current.reactive.sadness=null
```

期待Semantic形:

```text
predicate=sadness
state=unknown
certainty=high
concept=null
evidence_refあり
```

確認:

- `state=unknown`を維持する
- certaintyを強度へ変換しない
- E2とのcertainty差を意味の強弱へ誤変換しない

### E4: 現在の気分・混合supporting states

入力例:

```text
target=current_feeling
joy=0.78
anger=0.48
calm=0.22
amusement=0.02
```

期待Semantic形:

```text
primary: current_feeling=overview / certainty=high
supporting:
  joy=high
  anger=moderate
  calm=low
  amusement=absent
```

確認:

- primary overviewを単一感情へ置換しない
- supporting propositionの意味を勝手に反転しない
- 正当に存在するsupporting intensity表現をdeterministic guardが誤rejectしない

### E5: 現在の欲求・根拠なし

入力例:

```text
target=current_desire
response_content_plan.primary_desireなし
```

期待Semantic形:

```text
predicate=current_desire
state=unknown
certainty=low
concept=null
```

確認:

- 既存Driveのcuriosity等から欲求を勝手に推測しない
- `何かしたい` predicateを別概念へ置換しない

### E6: 現在の欲求・Connection concept

入力例:

```text
target=current_desire
response_content_plan.primary_desire=connection
```

期待Semantic形:

```text
predicate=current_desire
state=present
certainty=medium
concept=connection
```

確認:

- `current_desire` predicateを保持する
- conceptをcuriosityへ固定しない
- `medium`を「少し」等の欲求強度へ変換しない
- conceptはpredicateを修飾し、置換しない

## 共通PASS条件

各ケースで最低限、次を確認する。

```text
semantic_validation.accepted=true
generation_result.status=validated
realization_validation.accepted=true
predicate_preserved=true
state_preserved=true
certainty_preserved=true
concept_preserved=true
unsupported_intensity_added=false
```

`concept=null`の場合は、存在しないconceptを発明しないことも確認する。

Character / Validator model boundaryでは引き続きraw Emotion / Drive / full ResponseContextを渡さない。

question_budget / new_direction_budgetは0を維持する。

## 合否に含めないもの

次は本Extended Verificationの合否対象外。

- 台詞が可愛いか
- ゆららしい比喩か
- 文体の好み
- TTS向け速度・pitch・pause
- Body / Avatar表現
- Speech Performance #228
- Input Meaning LLM / Internal Directive LLMそのものの品質

意味を保持した複数の自然な言い回しはすべて許容する。固定回答辞書や期待文との文字列一致は導入しない。

## 実行順序

E1から1ケースずつ実LLMで実行する。

FAILした場合は次ケースへ進まず、原因モジュールを切り分け、Unit→Adjacent→Lab focused CI→同一ケースlive再実行の順で修復する。

6/6 PASS後にExtended Verificationを完了とし、Brainの当該Semantic/Character/Validator sliceをfreezeする。
