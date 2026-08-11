# Character Realization Observed State Gate v1.0.0

## 対象

Issue #229 / PR #233。

Character Realization ValidatorがSemanticUtterancePlanの意味保持を検証する際、open-ended自然言語の強度を有限語彙・regex・substringで判定しないための契約を定義する。

## 背景

2回目Live Verificationで、Planが `energy=low` なのにCharacter speechが「元気はある」とbare presenceへ弱まったケースを、Validator modelが `state_fidelity=exact` と誤判定した。

その後Runtimeへ `_EXPLICIT_INTENSITY_MARKERS` が追加され、speech/evidence span内の有限日本語degree表現を検索するguardが導入された。しかしこの方式は未列挙paraphraseを必ず生み、自然言語意味判定をraw text matcherへ戻すため採用しない。

## 原則

- Runtimeは自然言語中の単語・phrase・regexからstate/intensityを推定しない。
- evidence spanは「非空」「speech原文に実在する」ことだけをRuntimeで検証する。
- Character Realization Validator modelは、Planとの一致判定とは別に、speechが実際に表している `observed_state` をtyped enumで返す。
- explicit intensity Planでは `observed_state` を必須とし、RuntimeはPlan stateとtyped値を比較する。
- `observed_state` は期待Plan stateをコピーせず、speechの意味から決める。bare presenceしか表していない場合は `present` とする。
- degreeの表現方法は副詞・構文・対比・反復・婉曲等を含め自由であり、特定語彙を必須にしない。
- model/schema failure、必須observed_state欠落はfail closed。
- modelが利用できない場合、semantic validation済みとは扱わない。

## Runtimeが決定論的に検証してよいもの

自然言語理解後のtyped contractに限る。

- realization IDがPlan内に存在するか
- required primary realizationが存在するか
- `observed_state` が許可enumか
- explicit intensity Planで `observed_state == planned.state` か
- state_fidelity enumが `exact` か
- predicate/certainty/concept/intensity evidence spanがspeech内に実在するか
- required schema fieldの型と存在

Runtimeはspan内の語を見て意味カテゴリへ分類しない。

## Realization Validator model contract

explicit intensity state (`low/moderate/high/very_high`) をrealizeしたpropositionでは、各checkに次を追加する。

```json
{
  "realization_id": "proposition:0:energy",
  "observed_state": "present",
  "state_fidelity": "weakened"
}
```

`observed_state` の候補はSemanticUtterancePlanのstate vocabularyと `omitted`。期待stateと一致しない場合、top-level `accepted=true` でもRuntimeはrejectする。

例:

```text
Plan: energy=low
speech: energyの存在だけを表現
observed_state: present
=> reject
```

一方、未列挙の自然なparaphraseでもmodelが意味として `low` を観測できれば、Runtimeは語彙を知らなくてもaccept可能である。

## Concept / required / forbidden content

本gateは今回侵入したfinite intensity dictionaryを置換するhard gateであり、#229の他facetを別責務へ移さない。

- predicate / certainty / concept
- required content
- forbidden addition
- supporting proposition
- unknown非commit
- Character Profile表現差

は既存Realization Validator semantic checkとevidence contractを維持する。

Conceptの自然語意味同値をRuntime文字列比較へ落とさない。canonical concept contractが存在しない箇所ではmodel semantic validationを利用する。

## Verification

最低限次を確認する。

1. E8型: Plan `low` / bare presence → `observed_state=present` でreject。
2. 未知paraphrase: finite dictionaryに存在しない表現でも `observed_state=low` ならaccept。
3. supporting intensityでも同じgateを適用。
4. evidence spanがspeech外ならreject。
5. model unavailable/schema invalid/observed_state欠落はfail closed。
6. EmotionだけでなくDesire / Driveの代表Planで同一contractを確認。
7. Memory/KnowledgeはSemantic Plan fixtureで同じtyped comparison contractを確認し、production projectionを先行実装しない。
8. Character Profile差はsemantic stateが同じなら表面差だけでrejectしない。

## 非目標

- 有限degree辞書を別名で再導入すること
- test speechをProduction既知語へ変更してPASSさせること
- #193 Discourse Appraisal
- #228 Speech Performance
- #236/#237 Character Bible / Personality完成
- Memory/Knowledgeのproduction Semantic Plan projectionを本Issueで先行実装すること
