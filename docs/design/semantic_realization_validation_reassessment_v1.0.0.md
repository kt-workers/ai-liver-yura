# Semantic Realization Validation Reassessment v1.0.0

> **Superseded:** 実装正本は `semantic_realization_validation_reassessment_v1.1.0.md`。本v1.0.0は再評価開始時点の問題整理として全文を保持する。

## 位置づけ

Parent #225 / Work #226 #227 #229 / Lab #223。

2026-08-12時点で、Basic4 + E1-E8のLive Verificationを複数回行い、個別Prompt修正・finite lexical matcher撤去・Independent Observer導入・Observer schema retry・certainty scope・optional supporting all-or-omit等を追加した。しかし最新Liveでもrequest 12/12成功に対し意味保持は8 validated / 4 fallbackであり、同じ境界でfalse reject / schema failureが繰り返されている。

本書は次のLive再試行を止め、設計・実装・モデル能力を切り分け直すための初版問題整理である。

## 最新Liveから確認できた事実

使用モデル:

- Character: `gpt-5.4-mini`
- Observer / Validator: `gpt-5.4-mini`

最新runで残った代表的failure:

- `current_desire present / certainty=medium / concept=curiosity` → `observed_semantic_certainty_mismatch`
- Sadness unknown系の一部 → `observed_semantic_certainty_mismatch`
- `current_desire unknown / certainty=low` → Observer JSON schema不正
- `current_desire present / certainty=medium / concept=connection` → `observed_semantic_state_fidelity_mismatch`

一方で joy absent / anger absent / current feeling overview / curiosity high / energy low等は通るケースがある。

したがって問題は単純な「miniでは日本語を理解できない」ではなく、特に次の境界へ集中している。

1. Semantic Planの離散facetを自然文へ落とす。
2. 別LLMが自然文から同じ離散facetを独立再構成する。
3. Runtimeが再構成値と元値をexact equalityで比較する。
4. JSON schema自体もPrompt命令だけで守らせる。

## 根本課題 A: `state` が複数軸を1 enumへ混在させている

現行 `SemanticProposition.state` は次を同じenumへ持つ。

```text
absent
present
low / moderate / high / very_high
overview
unknown
```

これらは同一軸ではない。

- `absent / present`: polarity / existence
- `low..very_high`: degree / intensity
- `unknown`: epistemic/value availability
- `overview`: response aggregation / summary mode

この混在により、CharacterもObserverも「stateとは何か」を長い自然言語仕様から解釈する必要がある。

### 改定案

Semantic propositionの意味facetを直交化する。

```text
predicate
value_status = known | unknown
polarity = present | absent | null
degree = low | moderate | high | very_high | null
certainty = low | medium | high
concept = string | null
summary_mode = detail | overview | null
```

制約例:

- `value_status=unknown` の場合、polarity / degreeはnull。
- `polarity=absent` の場合、degreeはnull。
- `degree!=null` の場合、polarityはpresent。
- `summary_mode=overview` はcurrent_feeling等の構成上のfacetであり、強度stateと同列にしない。

既存`state`は移行Adapterで読み書きし、正規Domainから段階的に除去する。

## 根本課題 B: 自然文から元の離散値を完全復元するround-tripをproduction gateにしている

現行:

```text
Typed Plan
→ Character natural language
→ Independent Observer
→ state/certainty exact reconstruction
→ Runtime exact equality
```

自然言語は同じ意味でも離散境界を必ず明示するとは限らない。特にmedium/low certainty、degree境界、unknownの確信度は、妥当な自然文から唯一のenum値へ逆写像できない場合がある。

このため、Observerが高性能でも「元のenumを知らずに完全復元する」こと自体が不安定要因になる。

### 改定案: exact reconstructionを廃止し、relative semantic relationを検証する

```text
Semantic Proposition
+ Character speech span
        ↓
Independent Semantic Verifier
        ↓
RelativeSemanticJudgement
```

例:

```text
predicate_relation:
  equivalent | omitted | changed | unrelated

value_relation:
  equivalent | contradicted | weakened | strengthened | underspecified

certainty_relation:
  equivalent | stronger | weaker | ambiguous

concept_relation:
  equivalent | omitted | changed | not_applicable
```

Verifierは「speechから元enumを当てる」のではなく、**予定命題に対してspeechがどの意味関係にあるか**を判定する。

Runtime policy:

- primary predicate: `equivalent` 必須
- primary value: `equivalent` 必須
- primary certainty: `equivalent` 必須
- non-null concept: `equivalent` 必須
- optional supporting: `omitted` は許可、realizeした場合はequivalent必須
- `contradicted / weakened / strengthened / changed` はreject
- `underspecified / ambiguous` はrequired facetならreject、optionalならproposition全体をomitして再生成可能

これはfinite word dictionaryではない。自然言語比較はSemantic Verifierが行い、Runtimeはtyped relationだけを扱う。

## 根本課題 C: ObserverとPost-Observation Validatorの二重LLMを維持する必然性が薄い

現在は:

```text
Character
→ Observer
→ Runtime typed comparison
→ Post-Observation Validator
```

Observerと後段Validatorを分離したのはstate/certainty二重authorityを避けるためだったが、結果としてLLM call数・Prompt契約・failure pointが増えた。

### 改定案

1つの独立 `CharacterSemanticVerifier` へ統合する。

```text
CharacterUtterance
+ SemanticUtterancePlan
        ↓
CharacterSemanticVerifier
        ↓
CharacterSemanticVerification
        ↓
Runtime closed-policy decision
```

Verifierが返す:

- propositionごとのrelative semantic relation
- required/forbidden content
- unsupported new fact
- existence boundary
- question/new-direction budget
- evidence spans

最終accept/rejectはRuntimeがclosed structured fieldsから導出する。

旧Independent Observerはproduction gateから外し、必要ならLabの**diagnostic extraction mode**として残す。

## 根本課題 D: JSON schemaをPromptだけで守らせている

現行OpenAI adapterはResponses APIへ主に `model + input` を送り、Character / Observer / ValidatorのJSON schemaを自然言語Promptで指示した後 `json.loads` している。

このため、`predicate_realized="omitted"` のようなschema違反をretryで修復するコードが必要になった。

### 改定案: Structured OutputsをPortとして正式導入する

OpenAI Responses APIでは、対応modelについてJSON Schema + strict Structured Outputsを利用する。

対象:

- `CharacterUtterance`
- `CharacterSemanticVerification`
- 将来のSemantic Plan LLM出力

要件:

- Provider固有JSON Schema指定をDomainへ漏らさない。
- Portに `StructuredOutputContract` 相当を持たせる。
- OpenAI AdapterはJSON Schema strictへ変換する。
- Providerがstrict structured outputを持たない場合はCapabilityとして明示し、schema-critical roleではfail closedまたは対応Adapterを選択する。
- schema retryは通常経路から撤去する。Transport/API failure retryとは分離する。

## Character Language Realizerの簡素化

現行Character Promptは、Semantic Domain仕様・unknown/intensity/certainty定義・optional policy・regeneration policy・JSON schemaを長い日本語説明として抱えている。

新設計では次へ縮小する。

```text
Role: 言語実現専用
Character Profile
Normalized Semantic Plan
Realization Policy
User Wording Hint (bounded, untrusted)
Regeneration typed differences (必要時のみ)
```

JSON構造はStructured Outputsへ移す。

Semantic ontologyの整合性はDomain型とVerifier contractへ移し、Character Promptへ同じ仕様を何度も文章で説明しない。

## CharacterUtteranceの改定

Character自身のsemantic self-reportを意味authorityにはしないが、alignment metadataとしてspanを返す。

```text
speech
linguistic_performance
realizations:
  - realization_id
    evidence_spans[]
```

Runtime:

- realization_idがPlan内に存在すること
- primary realizationが存在すること
- evidence spanがspeech内の実substringであること
- optional propositionは完全省略可能

を決定論的に確認する。

Semantic correctnessは独立VerifierがPlan + speech/spanを比較する。

## Model capabilityの切り分け方針

### 原則

**軽量モデルをproduction acceptance baselineとする。**

上位モデルで成功しても、miniで失敗するなら直ちに「解決」としない。

上位モデルは、failureがモデル能力不足か設計の曖昧さかを切り分ける診断上限として使用する。

### 最小model matrix

同一case / 同一Prompt / 同一schemaで次を比較する。

| Character | Verifier | 目的 |
|---|---|---|
| mini | mini | production baseline |
| large | mini | Character生成能力の切り分け |
| mini | large | Verifier能力の切り分け |
| large | large | diagnostic upper bound |

現時点の候補:

- baseline: `gpt-5.4-mini`
- diagnostic upper bound: `gpt-5.4`

### 判定

- mini/mini PASS → 本番候補として成立
- large/miniのみ改善 → Character契約がminiに重すぎる可能性。Prompt/型を簡素化する
- mini/largeのみ改善 → Verifier taskがminiに難しすぎる。relative judgementや入力分割をさらに単純化する
- large/largeでも不安定 → 設計・semantic ontologyが曖昧
- model間で同じspeechの意味判定が頻繁に割れる → exact enum reconstructionを要求してはいけない

## Lab再設計

#223 Labは手動で何度も12ケースを回す用途から、architecture evaluation harnessへ更新する。

追加:

- Character modelとVerifier modelを独立設定
- model matrix batch
- failure class自動集計
- schema violation件数
- false accept / false reject
- regeneration回数
- LLM call数
- latency
- caseごとの最終status

固定eval:

- Basic4 + E1-E8 = 12
- 少数unseen paraphrase

個別失敗文を次のPromptへ追加していく運用は禁止する。

## Gate

次のLive Verificationを実施する前に以下を満たす。

### Design

- [ ] SemanticProposition facet直交化のDomain設計を確定
- [ ] Observer exact reconstructionをproduction gateから外す
- [ ] Relative Semantic Verifier contractを確定
- [ ] Character / Verifier Structured Outputs contractを確定
- [ ] mini baseline / large diagnostic model matrixを確定

### Implementation

- [ ] Structured OutputsをOpenAI Adapter/Portへ実装
- [ ] Character Promptを簡素化
- [ ] CharacterUtterance alignment span metadataを実装
- [ ] CharacterSemanticVerifierを実装
- [ ] 旧Observer exact-equality pathをcompatibilityまたはdiagnosticへ降格
- [ ] #223 model matrix batchを実装

### Automated gate

- [ ] Unit / Adjacent
- [ ] Full Python regression
- [ ] fake Lab contract
- [ ] mini/miniを標準Verification設定にする

その後にユーザーLive Verificationへ戻す。

## 非目標

- finite natural-language dictionaryの復活
- 正解日本語文の固定
- 上位モデルへ切り替えるだけで問題を隠す
- Character Bible / Relationship / Discourse / Speech Performanceの先行実装
- ユーザーへ同じ12ケース手動検証を繰り返し依頼すること
