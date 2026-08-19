# V2 Character Language Bounded Variation Contracts

Owner Issue: #330
Validation: #434
Parent canonical: `character_language_contracts.md`
Status: Canonical Supplement / Design Gate

## Canonical precedence

本書は`character_language_contracts.md`の既存Role identity記載のうち、**input schema IDだけ**を次のようにsupersedeする。

```text
character.language.context.v1
  -> character.language.context.v2
```

Role ID、output schema、Character/semantic Authority境界その他の親正本契約は変更しない。
`character_language_provider_contracts.md`も本書のinput schema v2を使用する。

## 1. Purpose

#434 real-LLM Isolation検証で、意味内容・Character Profile・constraint条件を同一にした10回生成が、実質2表現へ収束した。

- `今日は少し涼しいね。` x 8
- `今日は少し涼しいよ。` x 2
- #363 semantic acceptance: 10/10

意味保持は安定している一方、#330が期待する語彙・語順・rhythm・phrase segmentationの自然なvariationは十分に観測できなかった。

現行Promptはvariationを要求するが、各Character Language requestは他の生成variantを知らない。したがって「何を避けるべきか」というboundedなHow-to-say情報が存在せず、Provider samplingだけにvariationを依存している。

本契約は、同一`SpeechSemanticPlan`の再生成時に限って、直近の少数variantを**style-only negative reference**として入力へ追加する。

---

## 2. Authority invariants

以下は変更しない。

- `SpeechSemanticPlan`が唯一のWhat-to-say Authority。
- `CharacterLanguageProfile`はHow-to-say Style Authority。
- prior realizationはFact / Goal / Relationship / Execution / semantic propositionのAuthorityにならない。
- prior realizationを根拠に新しいmaterial claim、質問、自己開示、話題展開を追加しない。
- #363がactual `CharacterUtterance`の意味保持を独立検証する。
- fixed phrase / sentence-ending dictionary / regex / finite synonym tableをvariation生成Authorityにしない。
- generic fallbackを作らない。

variationはsemantic preservationとnaturalnessより優先しない。
「違う表現にするためだけ」の不自然な言い換えを要求しない。

---

## 3. Scope

### 3.1 対象

本契約のbounded repetition-awarenessは、**同一Plan identityのregeneration / repeated variant generation**だけを対象とする。

例:

```text
SpeechSemanticPlan P
  -> Character variant A
  -> verifier / quality policyにより別variantが必要
  -> Character variant B
```

又は#434 Labで同じPlanを5〜10回生成してvariationを評価する場合。

### 3.2 対象外

異なるturn、異なるPlan identity、unbounded conversation history全体の「口癖回避」は本契約へ入れない。

それらは将来のbounded discourse/history projection設計で扱う。

#330が会話履歴Storeを所有したり、過去発話全文を検索したりしない。

---

## 4. Bounded prior realization view

新しいtyped read-only viewを追加する。

```text
CharacterLanguagePriorRealizationView
- source_utterance_id
- semantic_plan_id
- character_id
- character_schema_version
- character_definition_revision
- constraint_revisions[]
- text
- committed_at

CharacterLanguagePriorConstraintRevision
- constraint_id
- source_revision
```

production callerは任意文字列からpriorを組み立てるのではなく、commit済み`CharacterUtterance`から`prior_realization_from_utterance()`で投影する。

### 4.1 boundedness

1 requestへ渡せるprior realizationは最大3件とする。

```text
MAX_PRIOR_REALIZATIONS = 3
```

理由:

- unbounded history再導入を防ぐ
- Prompt token増加を抑える
- 直近の表現収束だけを避ける
- 過去variantをCharacter Authority化しない

### 4.2 eligibility

prior realizationはcurrent snapshotと次が全て一致するときだけ利用できる。

- `semantic_plan_id`
- `character_id`
- `character_schema_version`
- `character_definition_revision`
- current relationship/discourse constraintの`constraint_id + source_revision`集合

さらに:

- source utterance IDは一意
- exact textは一意
- `semantic_plan.committed_at <= prior.committed_at <= snapshot.captured_at`
- committed sourceだけを使う

不一致はProvider呼出前にrejectする。

### 4.3 LLM projection

Providerへ見せるのは、Domainでeligibility確認済みのbounded style viewだけとする。

```json
"prior_realizations": [
  {
    "source_utterance_id": "...",
    "text": "...",
    "committed_at": "..."
  }
]
```

plan/profile/constraintの照合用provenanceをLLMへsemantic contentとして再提示しない。

---

## 5. Input contract version

`CharacterLanguageContextSnapshot`へ`prior_realizations`を追加するため、logical input schemaを更新する。

```text
character.language.context.v1
  -> character.language.context.v2
```

output schemaは変更しない。

```text
character.language.candidate.v1
```

Provider output formatも変更しない。

```text
character_language_candidate_v1
```

これは入力contextの拡張であり、`CharacterUtteranceCandidate`のsemantic/structural Authorityを変更しないためである。

---

## 6. Prompt behavior

production Character Language instructionsへ次を明示する。

- `prior_realizations`は同一Plan/Profile/constraintから生成済みの直近表現である。
- これは**避けたいHow-to-say例**であり、Fact sourceではない。
- current `semantic_plan`だけから意味を決める。
- equally naturalな代替がある場合は、priorとexact/near-exactな語彙・語順・rhythm・締め方への収束を避ける。
- priorとの差を作るために意味を追加・削除・弱化・強化しない。
- priorとの差を作るために不自然な同義語置換や過剰なCharacter演技をしない。
- 自然で意味安全な代替がほぼ1つしかない場合は、重複自体をfailureにしない。

Variationはquality objectiveであり、semantic hard constraintではない。

---

## 7. Ownership

### #330 owns

- prior realization typed contract
- committed utterance -> prior view production projector
- snapshot eligibility validation
- bounded max count
- input schema v2
- production Prompt interpretation
- current Plan/Profile/constraintとのprovenance gate

### #330 does not own

- global Character history Store
- unbounded conversation history retrieval
- prior variant ranking across unrelated Plans
- semantic verification
- automatic quality score / uniqueness threshold

### caller / orchestration owns

regeneration時に、利用可能なsame-context committed utteranceから最大3件を選択し、production projectorを使ってSnapshotへ渡す。

#330はStoreを検索しない。

---

## 8. #434 Lab correction

#434のsame-Plan repeated variant試験では、batch開始時にproduction `SpeechSemanticPlan`を**1回だけcommit**し、全repetitionで同じPlan object / plan_idを再利用する。

現在の「repetitionごとに新plan_idをcommitする」挙動は、意味内容は同一でもstrict same-Plan試験ではないため修正する。

batch内では:

1. repetition 1: `prior_realizations=[]`
2. successful CharacterUtteranceを収集
3. repetition 2以降: 直近のunique variantを最大3件Snapshotへ追加
4. #363には各actual utteranceを通常どおり独立投入

Isolation結果は引き続きIntegrated evidenceへ昇格しない。

---

## 9. Regression requirements

### Domain

- 0件priorは従来互換
- 最大3件を受理
- 4件以上reject
- duplicate utterance ID reject
- duplicate exact text reject
- different plan ID reject
- different character ID/schema/definition revision reject
- current constraint ID/revision不一致reject
- Plan commitより古いprior reject
- future committed_at reject
- committed `CharacterUtterance`からproduction projectorでpriorを構築
- request payloadへCONFIRMED Profile + bounded priorだけを投影
- raw history fieldなし

### Provider

- input schema ID = `character.language.context.v2`
- production instructionsがpriorをstyle-only negative referenceとして扱う
- output schema / provider formatはv1維持

### Live / #434

same Plan / same Profile / same constraintsで5〜10回。

評価:

- semantic acceptance
- exact duplicate率
- unique表現数
- 語彙 / 語順 / rhythm / phrase segmentation
- naturalness
- latency / token cost増加

固定の「unique率X%以上」をCore hard gateにはしない。
Human quality evaluationと実測比較で判断する。

---

## 10. Explicit non-goals

本修正で次は行わない。

- temperatureを固定で上げる
- random seedをvariation Authorityにする
- `ね / よ / かな`等の有限語尾ローテーション
- synonym辞書
- previous utteranceと文字列距離が近ければ強制reject
- #363へvariation品質判定を追加
- unrelated conversation historyを#330へ注入

これらは意味品質低下、テンプレート化、責務混在を招くため採用しない。
