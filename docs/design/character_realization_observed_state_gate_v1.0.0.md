# Character Realization Observed State Gate v1.0.0

## 対象

Issue #229 / PR #233。

Character Realization ValidatorがSemanticUtterancePlanの意味保持を検証する際、open-ended自然言語の強度・state・certaintyを有限語彙・regex・substringで判定しないための契約を定義する。

## 背景

2回目Live Verificationで、Planが `energy=low` なのにCharacter speechが「元気はある」とbare presenceへ弱まったケースを、Plan-aware Validator modelが `state_fidelity=exact` と誤判定した。

その後Runtimeへ `_EXPLICIT_INTENSITY_MARKERS` が追加され、speech/evidence span内の有限日本語degree表現を検索するguardが導入された。しかしこの方式は未列挙paraphraseを必ず生み、自然言語意味判定をraw text matcherへ戻すため採用しない。

## 正規フロー

```text
SemanticUtterancePlan ------------------------------┐
                                                    │
Character speech                                    │
      │                                             │
      v                                             │
Independent Character Realization Observer          │
      │  ※ expected state/certainty/conceptを見ない │
      v                                             │
RealizedSemanticObservation                         │
      │                                             │
      ├─ typed state/certaintyをRuntimeでPlanと比較 ┤
      │                                             │
      v                                             v
Plan-aware Character Realization Validator -------- compare
      │
      v
accept / reject
```

### 1. Independent Character Realization Observer

ObserverはCharacter speechが**実際に何を表しているか**を観測する。

Observerへ渡してよいもの:

- Character speech
- 観測結果をpropositionへ対応付けるcanonical `realization_id / kind / predicate`
- primary predicateの自然語意味枠を補助するbounded User Wording Hint

Observerへ渡してはいけないもの:

- expected `state`
- expected `certainty`
- expected `concept`
- expected intensity
- Planとの一致/不一致判定
- Character自身のsemantic realization自己申告を意味の根拠として扱う情報
- raw Emotion / Desire / Drive

Observerは次のtyped observationを返す。

```text
realization_id
predicate_realized
observed_state
observed_certainty
predicate_evidence_spans
state_evidence_spans
certainty_evidence_spans
```

`observed_state` は `absent / low / moderate / high / very_high / present / overview / unknown / omitted` のtyped vocabularyを使う。

`low/moderate/high/very_high` は単なるpresenceとは異なる。speechが存在だけを表し強度を意味的に識別できない場合は `present` とする。

強度の表現方法は副詞・構文・対比・反復・婉曲・強調など自由であり、特定の自然語リストへ対応付けない。

### 2. Runtime typed comparison

Runtimeは自然言語理解をしない。Observerによる自然言語理解が完了した後のtyped構造だけを比較する。

Runtimeが決定論的に検証してよいもの:

- observationのschema / enum / ID
- observation IDがrealized propositionと一致するか
- `predicate_realized` がtrueか
- `observed_state == planned.state` か
- `observed_certainty == planned.certainty` か
- required evidence spanが存在するか
- evidence spanがCharacter speechの実在部分文字列か
- required primary realizationの存在
- unplanned realizationの不存在

Runtimeが行ってはいけないもの:

- speech内の単語・phrase・regexからstate/intensity/certaintyを再推定する
- evidence span内の語をsemantic categoryへ分類する
- finite degree dictionaryをguard/fallback/safety net等の別名で再導入する

例:

```text
Plan: energy=low
Observer: observed_state=present
Runtime typed comparison: present != low
=> reject
```

未列挙の自然なparaphraseでもObserverがspeechの意味として `low` を観測できれば、Runtimeはその日本語表現を知らなくても比較できる。

### 3. Plan-aware Character Realization Validator

独立Observerを通過した後、既存のPlan-aware Validatorが次を引き続き検証する。

- predicate
- state / polarity
- certainty
- concept
- required semantic content
- forbidden addition
- supporting proposition
- unknown非commit
- state_fidelity
- regeneration後の意味保持
- question/new-direction budget等の既存semantic contract

このValidatorはPlanを見てよいが、独立Observerによるstate/certainty観測を置き換えない。

## Prompt / Dependency boundary

RuntimeはConcrete Prompt Builderをimportしない。

`CharacterRealizationValidationPromptBuilder` Portを介し、Adapter側が次の2種類のPromptを構築する。

- `build_observation(...)`: expected state/certainty/conceptを含まないObserver Prompt
- `build(...)`: Plan-aware Realization Validator Prompt

同じ `ResponseValidationModel` Portを異なる `llm_role` で再利用してよい。

- `character_realization_observer`
- `character_realization_validator`

Model providerが同じであることと、意味上の役割・Prompt authorityが同じであることは別である。

## Fail closed

次ではsemantic validation済みと扱わない。

- model unavailable
- Observer invocation failure
- Observer JSON/schema invalid
- required observation欠落
- duplicate/unexpected observation
- evidence spanがspeech外
- typed observed state/certaintyがPlanと不一致

失敗時にfinite lexical fallbackへ戻らない。

## Evidence span

Runtimeはevidence spanについて次だけを確認する。

- required facetで必要なspanが非空か
- spanがCharacter speechに実在するか

spanの単語自体から「これはlowを意味する」「これはcertainty=mediumを意味する」と推論しない。

## #229の終了条件との関係

本gateは今回侵入したfinite intensity dictionaryを置換するだけでなく、#229の基盤契約を壊さず補強する。

本工程で固める:

- predicate
- state / polarity
- certainty
- concept
- required content
- forbidden addition
- supporting proposition
- unknownを勝手にyes/noへ確定しない
- intensityを勝手に弱めたり強めたりしない
- regeneration後も上記を保持
- Desire / Drive / Memory・Knowledgeの代表入力で同じ契約
- Character Profileによる言い回し差を許容しつつ意味変更をreject

本工程で完成させない:

- Character Bible由来の語尾・語彙・冗談・照れ方 (#236/#237)
- Relationshipの本格的距離感
- Discourse/話題転換/acknowledgement (#193)
- 音響的な間・抑揚・話速 (#228)
- Voice/Body統合

Memory/Knowledgeについては#229の意味保持contractをSemantic Plan fixtureで検証してよいが、#226側のproduction projectionを本Issueで先行実装しない。

## Verification

最低限次を確認する。

1. E8型: Plan `low` / bare presence → Observer `present` → typed comparisonでreject。
2. E4型: realized supporting intensityのbare presenceも同じ仕組みでreject。
3. 未知paraphrase: finite dictionaryに存在しない表現でもObserver `low`ならaccept可能。
4. Observer Promptにexpected state/certainty/conceptが入っていない。
5. Observer evidence spanがspeech外ならreject。
6. model unavailable/schema invalid/observation欠落はfail closed。
7. EmotionだけでなくDesire / Driveの代表Planで同一contractを確認。
8. Memory/KnowledgeはSemantic Plan fixtureで同じ意味保持contractを確認する。
9. Character Profile差はsemantic meaningが同じなら表面差だけでrejectしない。
10. Unit → Adjacent → #223 Labの順で検証する。

## 再発防止

- `_EXPLICIT_INTENSITY_MARKERS` 型の有限自然語semantic authorityを追加しない。
- test speechをProduction既知語へ変更してPASSさせない。
- unseen paraphraseを回帰ケースとして残す。
- チャット切替時は本設計書と#229/#233の責務を再読してから実装を再開する。
- 他Issueで発見した同種問題を本Issueから横断修正せず、各Issueを実施する時にその責務内で是正する。
