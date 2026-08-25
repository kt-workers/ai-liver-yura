# V2 Character Language Bounded Variation Contracts

Owner Issue: #330
Validation: #434
Parent canonical: `character_language_contracts.md`
Related canonical: `character_language_semantic_repair_contracts.md`
Status: Canonical Supplement / Design Gate

## Canonical precedence

本書は`character_language_contracts.md`の既存Role identity記載のうち、**input schema IDだけ**を次のようにsupersedeする。

```text
character.language.context.v1
  -> character.language.context.v2
```

Role ID、output schema、Character/semantic Authority境界その他の親正本契約は変更しない。
`character_language_provider_contracts.md`も本書のinput schema v2を使用する。

semantic `REJECTED`後の再生成は`character_language_semantic_repair_contracts.md`を正本とする。

---

## 1. Purpose

#434 real-LLM検証では、同一意味・Profile条件の旧10-runが実質2表現へ収束した。

- `今日は少し涼しいね。` x 8
- `今日は少し涼しいよ。` x 2
- #363 semantic acceptance: 10/10

その後same-Plan bounded prior awarenessを有効化したstrict 10-runでは:

- exact-text unique: 10/10
- #363 semantic acceptance: 8/10
- `certainty_changed`: 2/10

となった。

つまり、prior awarenessは表現収束を弱める効果を持つ一方、強すぎるvariation pressureはsemantic driftを誘発し得る。

本契約の目的は**unique率最大化ではない**。
同一Planで過度に同じ表現へ収束する傾向を弱く抑えつつ、semantic preservation / naturalnessを最優先する。

---

## 2. Production generation policy

production Character Languageは候補探索器ではない。
通常のpresentation opportunityでは**1回生成を原則**とする。

```text
SpeechSemanticPlan
  -> Character Language generation x1
  -> actual CharacterUtterance
```

prior realizationが存在しても:

- 自然で意味安全な別表現があれば参考にしてよい
- 同じ表現が最も自然・安全なら再使用してよい
- exact duplicateをfailureにしない
- unique率をruntime hard gateにしない

semantic `REJECTED`時の追加生成だけは`character_language_semantic_repair_contracts.md`のbounded repair policyに従う。

---

## 3. Authority invariants

以下は変更しない。

- `SpeechSemanticPlan`が唯一のWhat-to-say Authority。
- `CharacterLanguageProfile`はHow-to-say Style Authority。
- prior realizationはFact / Goal / Relationship / Execution / semantic propositionのAuthorityにならない。
- prior realizationを根拠に新しいmaterial claim、質問、自己開示、話題展開を追加しない。
- #363がactual `CharacterUtterance`の意味保持を独立検証する。
- fixed phrase / sentence-ending dictionary / regex / finite synonym tableをvariation生成Authorityにしない。
- generic fallbackを作らない。

優先順位は明示的に:

```text
semantic preservation
> naturalness
> Character fidelity
> repetition avoidance / variation
```

とする。

---

## 4. Scope

### 4.1 対象

bounded repetition-awarenessは、**同一Plan identityに対する複数回のrealizationが実際に発生する場合**だけを対象とする。

例:

- semantic repair前の既存same-Plan realizationがある
- Labで同一Planの表現分布を複数回測定する
- 将来、同一Planを再提示する明示的orchestrationがある

priorが存在すること自体は「必ず別variantを作れ」という指示ではない。

### 4.2 対象外

異なるturn、異なるPlan identity、unbounded conversation history全体の口癖回避は本契約へ入れない。

#330が会話履歴Storeを所有したり、過去発話全文を検索したりしない。

---

## 5. Bounded prior realization view

既存typed read-only viewを使用する。

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

production callerは任意文字列からpriorを組み立てず、commit済み`CharacterUtterance`から`prior_realization_from_utterance()`で投影する。

### 5.1 boundedness

1 requestへ渡せるprior realizationは最大3件。

```text
MAX_PRIOR_REALIZATIONS = 3
```

理由:

- unbounded history再導入を防ぐ
- Prompt token増加を抑える
- 直近の表現傾向だけを参考にする
- 過去variantをCharacter Authority化しない

### 5.2 Domain eligibility

prior realizationはcurrent snapshotと次が全て一致するときだけDomain上利用できる。

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

### 5.3 Semantic acceptance selection

#363が適用されるproduction orchestrationでは、prior候補へ選べるのは**semantic `ACCEPTED`済みutteranceだけ**とする。

`REJECTED` utteranceをfuture priorへ追加してはならない。

ただし#330 Domainは#363型/Storeをimport・検索しない。
accepted-only selectionはcaller/orchestration ownershipであり、詳細は`character_language_semantic_repair_contracts.md`を参照する。

### 5.4 LLM projection

Providerへ見せるのはDomainでeligibility確認済みのbounded style viewだけ。

```json
"prior_realizations": [
  {
    "source_utterance_id": "...",
    "text": "...",
    "committed_at": "..."
  }
]
```

Plan/Profile/constraint照合用provenanceをLLMへsemantic contentとして再提示しない。

---

## 6. Input contract version

`CharacterLanguageContextSnapshot`のlogical input schemaは:

```text
character.language.context.v2
```

を使用する。

output schemaは変更しない。

```text
character.language.candidate.v1
```

Provider output formatも変更しない。

```text
character_language_candidate_v1
```

---

## 7. Prompt behavior

production instructionsではpriorを**weak repetition-awareness reference**として扱う。

- `prior_realizations`は同一Plan/Profile/constraintから生成済みの直近表現。
- Fact source / conversation history / additional propositionではない。
- actual meaningはcurrent `semantic_plan`だけから決める。
- equally natural **かつ意味安全**な代替が明らかにある場合だけ、priorとの過度なexact/near-exact収束を避けてもよい。
- priorと同じ表現を使う方が自然・意味安全なら、そのまま再使用してよい。
- priorとの差を作るために意味を追加・削除・弱化・強化しない。
- 不自然な同義語置換、certaintyを弱める婉曲表現、過剰なCharacter演技で差分を作らない。
- unique outputを生成すること自体を目標にしない。

Variation/repetition avoidanceはquality objectiveでありsemantic hard constraintではない。

---

## 8. Ownership

### #330 owns

- prior realization typed contract
- committed utterance -> prior view production projector
- snapshot Domain eligibility validation
- bounded max count
- input schema v2
- production Prompt interpretation
- current Plan/Profile/constraintとのprovenance gate

### #330 does not own

- global Character history Store
- unbounded conversation history retrieval
- prior variant ranking across unrelated Plans
- semantic verification
- semantic acceptance Store
- automatic quality score / uniqueness threshold
- best-of-N candidate selection

### caller / orchestration owns

- same-context prior候補の選択
- #363がある経路でのaccepted-only filtering
- semantic rejection後のbounded repair orchestration

#330はStoreを検索しない。

---

## 9. #434 Lab interpretation

#434のsame-Plan repeated variant試験は**quality characterization**であり、本番で10候補を生成する仕様ではない。

batch開始時にproduction `SpeechSemanticPlan`を1回だけcommitし、全repetitionで同じPlan object / plan_idを再利用する。

variation characterizationでは:

- exact-text分布
- naturalness
- semantic acceptance
- latency / token cost

を観測する。

一方、production-flow検証は`character_language_semantic_repair_contracts.md`に従い:

```text
initial x1
#363
REJECTED時だけrepair x1
```

を別測定として扱う。

Labのrepetition数をproduction candidate countとして解釈してはならない。

---

## 10. Regression requirements

### Domain

- 0件priorは従来互換
- 最大3件受理 / 4件以上reject
- duplicate utterance ID/text reject
- different plan ID reject
- different character ID/schema/definition revision reject
- current constraint ID/revision不一致reject
- Plan commitより古いprior reject
- future committed_at reject
- committed `CharacterUtterance`からproduction projectorでprior構築
- request payloadへCONFIRMED Profile + bounded priorだけ投影
- raw history fieldなし

### Provider

- input schema ID = `character.language.context.v2`
- production instructionsがpriorをweak style-only repetition-awarenessとして扱う
- 同一表現の再使用を許容する
- semantic preservationがvariationより明示的に上位
- output schema / provider formatはv1維持

### Live / #434

固定のunique率をCore hard gateにしない。

評価:

- semantic acceptance
- exact duplicate率
- unique表現数
- 語彙 / 語順 / rhythm / phrase segmentation
- naturalness
- latency / token cost増加

Human quality evaluationと実測比較で判断する。

---

## 11. Explicit non-goals

本契約で次は行わない。

- temperature固定引上げ
- random seedをvariation Authorityにする
- `ね / よ / かな`等の有限語尾ローテーション
- synonym辞書
- lexical distance hard reject
- unique率hard threshold
- best-of-N generation / ranking
- #363へvariation品質判定を追加
- unrelated conversation historyを#330へ注入

これらは意味品質低下、テンプレート化、責務混在を招くため採用しない。
