# V2 Character Language Provider Contracts

Owner Issue: #330
Parent canonical: `docs/architecture/v2/character_language_contracts.md`
Related canonical: `docs/architecture/v2/character_language_variation_contracts.md`
Related canonical: `docs/architecture/v2/character_language_semantic_repair_contracts.md`
Related: #323 / #357 / #362 / #363 / #434
Status: Canonical Supplement / Provider Verification Gate

## 1. Purpose

本書は、#330 Character Language のDomain契約を production OpenAI Responses path で実行するための **production-owned Provider contract** を定義する。

#330の基本Authorityは変更しない。

- `SpeechSemanticPlan` = sole What-to-say Authority
- `CharacterLanguageProfile` = confirmed static How-to-say Style Authority
- bounded relationship/discourse constraints = read-only language guidance
- bounded same-Plan prior realizations = weak style-only repetition-awareness reference
- `CharacterUtterance` structural commit != #363 semantic acceptance

productionは**原則1回生成**であり、best-of-N候補探索を行わない。
semantic `REJECTED`時のbounded repairだけは`character_language_semantic_repair_contracts.md`に従う。

Dedicated Lab #434 は本書のproduction instructions / output schema / Role configを再利用し、Lab専用Prompt・schema・provider formatを発明してはならない。

---

## 2. Layering

Provider契約は依存方向を守って2層に分ける。

```text
app/domain/character_language/
  realizer.py             logical Role / request-result IDs
  schemas.py              production instructions + strict output JSON Schema

app/adapters/llm/
  openai_responses.py     generic #357 Responses Adapter
  character_language.py   production Character Language OpenAI Role config helper
```

Domainは`OpenAIResponsesRoleConfig`やSDK型をimportしない。
Adapter composition側だけがDomainのRole/schema定数と#357 provider型を結合する。

---

## 3. Production Role identity

#330 bounded variation input拡張後のlogical Role identityを使用する。

```text
role_id: character_language
input_schema_id: character.language.context.v2
output_schema_id: character.language.candidate.v1
provider_output_format_name: character_language_candidate_v1
failure_policy: FAIL_CLOSED
```

`context.v2`は`prior_realizations`を追加したinput contractである。
output candidate shapeは変更しないため`character.language.candidate.v1`を維持する。

`output_schema_id`はDomain identity、`provider_output_format_name`はOpenAI Structured Output用safe nameであり、同一概念として扱わない。
Provider format nameは他Roleと重複させない。

---

## 4. Production instructions contract

production instructionsは最低限次を明示する。

### 4.1 Authority

- 入力`semantic_plan`だけを発話内容のAuthorityとして扱う。
- REQUIRED propositionを実現する。
- OPTIONAL propositionはSituationに自然なら実現できるが、省略してよい。
- FORBIDDEN propositionは実現しない。
- polarity / certainty / degree / execution status / self-disclosure / question budget / new-direction budgetを変更しない。
- Planに存在しないmaterial claim、経験、好み、事実、約束、質問、話題展開を追加しない。

### 4.2 Character style

- `character_profile.facets`は表現Styleにだけ使う。
- Profileを新しいFact sourceとして扱わない。
- すべてのfacetを毎回盛り込まない。
- 普通のneutral speechが自然なSituationでは自然体を優先する。
- Characterらしさを口癖、固定導入、固定締め、過剰な修辞だけで表現しない。
- 語彙、語順、rhythm、phrase segmentation等の自然なvariationを**許可**するが、unique表現生成を義務化しない。

### 4.3 Bounded prior realizations

- `prior_realizations`はDomainでsame Plan / Character revision / constraint revisionを確認済みの最大3件だけを受け取る。
- priorはHow-to-say上の**weak repetition-awareness reference**であり、Fact source / conversation history / additional propositionではない。
- current `semantic_plan`だけをactual meaning sourceとして使う。
- equally natural **かつ意味安全**な代替が明らかにあるときだけ、priorとの過度なexact/near-exact収束を避けてもよい。
- priorと同じ表現を使う方が自然・意味安全なら、そのまま再使用してよい。
- variationのために意味を追加・削除・弱化・強化しない。
- certaintyを弱める婉曲表現、不自然な同義語置換、過剰なCharacter演技で差分を作らない。
- semantic preservation / naturalnessをrepetition avoidanceより優先する。

### 4.4 Relationship / discourse constraints

- `constraints[].language_guidance`はbounded style/discourse constraintとして守る。
- constraint ID文字列やsource refを新しいsemantic contentとして解釈しない。
- constraintから新しいRelationship Fact、質問、話題を発明しない。

### 4.5 Candidate identity / provenance

出力では入力値をexactにコピーする。

- request_id
- semantic_plan.plan_id -> semantic_plan_id
- semantic_plan.candidate.decision_id -> source_decision_id
- semantic_plan.candidate.intent_id -> source_intent_id
- source_event_ids
- revisions
- character_profile.character_id
- character_profile.schema_version
- character_profile.definition_revision

LLMはこれらのtrusted identityを言い換え・再生成しない。

### 4.6 Segments

- `segments[].text`には実際に発話する自然言語だけを入れる。
- Markdown説明、分析、schema説明を混ぜない。
- `realization_refs`はそのsegmentが実現しようとしたnon-FORBIDDEN Plan proposition IDだけを参照する。
- realization refはsemantic proofではない。
- boundary / emphasis / hesitationは既存closed enumだけを使う。
- TTS parameter / SSML / Body gesture / motionを出力しない。

### 4.7 Budget self-report

`question_budget_used` / `new_direction_budget_used`はactual candidateで使用した数を申告し、Plan上限を超えない。
ただしこの自己申告はsemantic proofではなく、actual textは#363が独立観測する。

---

## 5. Strict output JSON Schema

production JSON Schemaは`CharacterUtteranceCandidate` parserと同じfield集合だけを許可する。

Top-level required fields:

```text
candidate_id
request_id
semantic_plan_id
source_decision_id
source_intent_id
source_event_ids
revisions
character_id
character_schema_version
character_definition_revision
segments
question_budget_used
new_direction_budget_used
```

原則:

- top-level `additionalProperties: false`
- revision object `additionalProperties: false`
- segment object `additionalProperties: false`
- `segments`は1件以上
- segment textはnon-empty string
- linguistic enumはDomain enum valueだけ
- budgets / revisionsは0以上のinteger。goal/attention revisionはnullable
- candidate schemaへsemantic override fieldを追加しない
- `created_at`はProvider出力へ要求しない。trusted Provider result completion timeからRuntime parserが付与する

Provider schema成功だけでsemantic preservation PASSとはみなさない。

---

## 6. OpenAI Responses Role config

production helperは#357 `OpenAIResponsesRoleConfig`を返し、以下を固定する。

- role/input/output schema identity
- provider output format name
- strict output JSON Schema
- production instructions
- `FAIL_CLOSED`

model policyは呼出側から**明示mapping**として受け取る。

```text
LLMModelClass -> provider model string
LLMReasoningEffort -> provider reasoning effort string
```

Character Language v1 outputはtext generation Roleのため、`FAST` / `BALANCED` / `DEEP_REASONING`だけを許可対象とし、`MULTIMODAL`を暗黙変換しない。

reasoning effortはFoundation enum `minimal / low / medium / high`をProviderへ明示mappingする。
未登録model class / reasoning combinationはProvider呼出前にfail-closedとする。

model名をcanonical Character意味仕様として固定しない。#434でquality / schema stability / latency / token usageを比較し、運用policyは実測結果から決められるようにする。

---

## 7. Failure / isolation

- unknown Role -> no Character config fallback
- wrong input schema -> fail-closed
- unsupported model class/reasoning -> fail-closed before Provider call
- malformed / mismatched prior realization -> fail before Provider call
- Provider error/timeout -> no `CharacterUtterance` commit
- Provider output schema invalid -> no commit
- fixed generic Character phraseへfallbackしない
- 他Roleのinstructions/schema/provider formatをCharacter Languageへ流用しない
- Character Language configを他Roleへ暗黙適用しない

Provider/Verifier infrastructure failureを理由にCharacter文を別表現へ作り直して原因を隠さない。
semantic `REJECTED`だけがbounded Character repair triggerになり得る。

Prompt本文、API key、SDK exception本文をruntime output/metricsへ露出しない。

---

## 8. #434 reuse contract

Dedicated Character Language Lab #434はIntegrated Gateで最低限次をproductionから直接再利用する。

1. #355 production CharacterLanguageProfile projection
2. #362 production SpeechSemanticPlan contract/commit
3. #330 production `CharacterLanguageRealizer`
4. 本書のproduction instructions
5. 本書のstrict output schema
6. 本書のproduction OpenAI Role config helper
7. #357 production `OpenAIResponsesAdapter`
8. actual `CharacterUtterance`
9. downstream #363 production Semantic Verification

same-Plan variation characterizationではbatchごとに1つのproduction Planをcommitし、複数repetitionを**品質測定**として実行できる。ただしrepetition数をproduction候補数と解釈しない。

production-flow verificationは`character_language_semantic_repair_contracts.md`に従い:

```text
initial generation x1
#363
REJECTED時だけ repair x1
```

を別測定として扱う。

Labはmodel mappingだけを比較条件として差し替えられる。
Prompt/schema/format nameを差し替えたrunはIsolation診断であってIntegrated Gate evidenceにしない。

---

## 9. Required tests

### Domain schema / instructions

- output schema field集合が`parse_candidate()`契約と一致
- unknown top-level/segment/revision field reject
- unknown boundary/emphasis/hesitation reject
- empty segments/text reject
- negative budget/revision reject
- nullable goal/attention revision accept
- semantic override fieldをschemaが許可しない
- production instructionsがWhat-to-say / Style / weak repetition-awareness / constraint / provenance / budget / downstream semantic boundaryを分離している
- same prior表現の再使用を許可する
- semantic preservationがvariationより明示的に上位

### Input variation

- input schema ID = `character.language.context.v2`
- 0〜3件prior accept
- 4件以上reject
- duplicate prior ID/text reject
- plan/profile/constraint provenance mismatch reject
- future prior reject
- Provider payloadへstyle-only bounded viewだけを投影
- raw/unbounded historyなし

### Provider config

- role/input/output schema ID exact
- provider format name exact and safe
- production instructions/schema objectを使用
- supplied model class -> exact model mapping
- reasoning effort -> explicit provider effort mapping
- unsupported/missing model class fail-closed
- MULTIMODALを暗黙利用しない
- other Role configとのformat name isolation

### End-to-end fake Provider

- strict valid candidate -> existing `CharacterLanguageRealizer` commit可能
- extra/unknown field -> schema failure / no commit
- Provider timeout/error -> no commit / no generic fallback
- wrong Role/schema result -> no commit

### Semantic repair orchestration

- ACCEPTEDなら1 generationで終了
- REJECTED時だけ最大1 repair
- repairはsame Plan/Profile/constraintsで`prior_realizations=[]`
- repair後REJECTで追加生成なし
- #363 execution failureではCharacter repairしない
- REJECTED utteranceをfuture priorへ追加しない

---

## 10. Verification readiness gate

#330をDedicated Lab #434へ渡す前に:

- current `rebuild/v2-foundation`をactive #330 lineageへreconcile済み
- production instructions実装済み
- production strict output JSON Schema実装済み
- production OpenAI Role config/helper実装済み
- provider format / model-reasoning mapping明示
- bounded prior realization input / schema v2 regression PASS
- one-shot + bounded semantic repair policyの実装/回帰PASS
- Role/schema isolation regression PASS
- targeted / adjacent / full / Ruff / strict Mypy / compileall / diff check PASS
- exact-head CI SUCCESS
- current-head review blocking finding 0
- PR #423はそれまでDraft維持

上記PASS後にのみ#434 Integrated Character Language quality verificationを開始する。
