# V2 Character Language Lab — Strict Same-Plan Variation Verification

Owner Validation Work: #434
Production dependency: #330
Parent canonical:
- `character_language_lab_contracts.md`
- `character_language_lab_evidence_gate.md`
- `character_language_variation_contracts.md`
Status: Canonical Supplement / Live Variation Verification

## 1. Purpose

#434の旧`repetitions`実装は、各repetitionでsemantic contentは同一でも新しい`SpeechSemanticPlan.plan_id`をcommitしていた。

そのため旧10-run evidence:

- `今日は少し涼しいね。` x8
- `今日は少し涼しいよ。` x2
- #363 accepted 10/10

は**same-content repeated generation baseline**として有効だが、#330が定義したbounded same-Plan repetition-awarenessのstrict verificationには使用しない。

本補助正本は、#434 repeated-variant runを「1 batch = 1 committed SpeechSemanticPlan」へ修正する。

## Cross-Plan conversation観測

Strict same-Plan repeated generationは、同一Planに対するCharacter Languageの挙動を観測するprobeとして残す。
しかし、同一Planのunique率だけを#330 production Prompt変更の根拠にしてはならない。Cross-Plan baselineでは、別turn・別Plan・別contextだけで自然なvariationが生じるかを観測する。

Cross-Plan conversationはIsolation fixtureとして、gratitude → userの中心speech actを維持した次の5 contextを順にcommitする。

1. 作業を手伝ってもらった
2. 情報を教えてもらった
3. 待ってもらった
4. 修正してもらった
5. 結果を確認してもらった

各turnの`SpeechSemanticPlan`はproduction `SpeechSemanticsPlanner` / `SpeechSemanticAuthority`経由で個別にcommitする。plan IDだけを変更して別contextを偽装しない。

`CharacterLanguagePriorRealizationView`はsame-Plan専用のprovenance契約である。Cross-Plan baselineはその契約を変更・偽装せず、全turnで`prior_realizations = []`とする。accepted utteranceの蓄積・注入はしない。same-Plan prior probeの既存動作は変更しない。

Cross-Planも各utteranceを#363へ独立投入し、`isolation_only`のままとする。#354未完了によるIntegrated Blockedを回避・偽装しない。

---

## 2. Strict batch identity

1回のLab `/api/run` requestを1 variation batchとする。

batch開始時に:

1. controlled scenarioからproduction `SpeechSemanticsPlanner` / `SpeechSemanticAuthority`経由でPlanを1回だけcommitする。
2. その`SpeechSemanticPlan` object / `plan_id`を全repetitionで再利用する。
3. repetitionごとにPlanを再commitしない。

したがって全runで次がexact一致しなければならない。

```text
semantic_plan.plan_id
semantic_plan.candidate semantics
semantic_plan.committed_at
```

request identity / Character utterance identityは各repetition固有でよい。

---

## 3. Bounded prior flow

#330 production `CharacterLanguagePriorRealizationView`と`prior_realization_from_utterance()`だけを使用する。

### repetition 1

```text
prior_realizations = []
```

### repetition 2以降

成功してcommitされたactual `CharacterUtterance`からproduction projectorでprior viewを作る。

- exact textが既存priorと同じなら重複priorを追加しない。
- unique priorだけを保持する。
- 直近最大3件だけを次repetitionのsnapshotへ渡す。
- failed / uncommitted Character candidateをpriorへ入れない。
- #363 accepted/rejectedはprior eligibility条件にしない。priorは「actual committed Character expression」のstyle-only referenceでありsemantic proofではない。

#330 Domain側のsame Plan / Character revision / constraint revision / freshness gateをそのまま通す。
Lab側で同じvalidationを別実装してAuthority化しない。

---

## 4. Semantic boundary

prior realizationはvariation用How-to-say negative referenceである。

Labは:

- priorをSpeechSemanticPlanへ混ぜない。
- priorからpropositionを作らない。
- priorを#363 expected semantic sourceへ追加しない。
- priorとの差を作るためにCharacter outputをpost-processしない。
- lexical replacement / ending rotation / synonym substitutionをしない。

各actual `CharacterUtterance`は従来どおり同じcommitted Planとpairで#363 production `SemanticVerifier`へ独立投入する。

---

## 5. Export observability

各`runs[]`は最低限次を監査可能にする。

- `semantic_plan.plan_id`
- `prior_realizations_used[]`
  - source_utterance_id
  - text
  - committed_at
- actual `character_utterance`
- Character provider latency / token usage
- #363 result

batch top-levelへ次を追加してよい。

```text
variation_batch
- semantic_plan_id
- repetitions
- strict_same_plan: true
- max_prior_realizations: 3
```

`strict_same_plan=true`はLabの自己申告だけでPASSとせず、Export consumer / regression testで全`runs[].semantic_plan.plan_id`一致を確認できること。

---

## 6. Isolation / Integrated evidence

本修正はIsolation / Integrated両modeのrepetition mechanicsへ適用できる。

ただし:

- Isolation runは引き続き`isolation_only`。
- bounded prior導入でIsolation evidenceをIntegratedへ昇格しない。
- Integratedは#354 production Character Definitionが準備されるまでfail-closed BLOCKEDを維持する。
- Integrated machine/Human gateは`character_language_lab_evidence_gate.md`を変更しない。

---

## 7. Baseline comparison

旧same-content baseline:

```text
model: gpt-5.6-sol
class: balanced
reasoning: medium
scenario: neutral_fact
repetitions: 10
Character texts:
  今日は少し涼しいね。 x8
  今日は少し涼しいよ。 x2
unique full text: 2 / 10
#363 accepted: 10 / 10
```

新strict same-Plan runでは以下を比較する。

- unique full-text count
- dominant exact-text count/rate
- 語彙 variation
- 語順 variation
- rhythm / phrase segmentation
- Human naturalness
- #363 semantic acceptance
- Character latency/token overhead
- #363 latency/token overhead

固定のunique率閾値をCore hard gateにはしない。
自然さ・意味保持を犠牲にした人工的variationは改善と数えない。

---

## 8. Required regression

- repetitions=3以上でもPlan commitは1回だけ
- 全runsのplan ID exact一致
- first Character requestの`prior_realizations=[]`
- second requestはfirst committed utteranceをpriorとして持つ
- exact duplicate outputはprior listへ重複追加しない
- unique outputsは直近最大3件まで
- Character input schemaは`character.language.context.v2`
- failed Character outputはpriorにならない
- #363は各actual utteranceをsame Planと独立評価
- Exportからsame-Plan/prior chainを監査可能
- Isolation evidence classは変わらない

---

## 9. Non-goals

本Labはvariationを作るための独自Prompt/schemaを持たない。
#330 production Prompt/context contractだけを利用する。

また以下をLabへ追加しない。

- temperature tuningによる強制variation
- finite phrase/ending rotation
- synonym dictionary
- text distanceによるcandidate reject
- post-generation rewrite
- #363をvariation quality judgeへ変更
