# Character Realization Observed State Gate v1.0.0

## 対象

Issue #229 / PR #233。

Character speechのopen-ended自然言語から `state / polarity / intensity / epistemic certainty` を観測し、有限語彙・regex・substringへ戻さずSemanticUtterancePlanとの意味保持を検証する契約を定義する。

## 背景

2回目Live VerificationではPlanが `energy=low` なのにCharacter speechがbare presenceへ弱まったケースを検出できなかった。その後Runtimeへfinite degree dictionaryを追加したが、未列挙paraphraseを扱えず自然言語意味判定をraw text matcherへ戻すため撤去した。

第三回LiveではIndependent Observer導入後に次を確認した。

- `current_feeling=overview` を `present` と誤観測
- `certainty=medium/low` の慎重表現を `high` と誤観測
- absence表現を `low` と誤観測
- E8でObserverが `low`、Plan-aware Validatorが `polarity_changed` と同じspeechを別解釈

最後のケースから、Observer導入後も後段Validatorがstate/certainty/intensityを再解釈するとsemantic authorityが二重化することが分かった。

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
      v                                             │
Runtime typed comparison <--------------------------┘
      │
      v
Post-Observation Character Realization Validator
      │
      v
accept / reject
```

## 1. Independent Character Realization Observer

ObserverはCharacter speechが**実際に何を表しているか**を独立観測する。

Observerへ渡してよいもの:

- Character speech
- observationをpropositionへ対応付けるcanonical `realization_id / kind / predicate`
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

### observed_state

`observed_state` は次のclosed typed vocabularyを使う。

```text
absent / low / moderate / high / very_high / present / overview / unknown / omitted
```

これは自然語辞書ではなく、自然言語理解後の内部protocolである。

意味:

- `absent`: 対象の存在・成立を否定している。
- `present`: 対象の存在・成立を表すが、順序づけられた強度差までは表していない。
- `low/moderate/high/very_high`: 対象が存在・成立し、speechから順序づけられた強度差を意味的に識別できる。
- `overview`: 単一状態のpresenceではなく、全体状態・総合状態を一つ以上の状態次元や性質で特徴づけている。
- `unknown`: 対象の存在・不在・強度・値を現時点で確定していない。
- `omitted`: speechがそのpredicateを意味として表現していない。

重要:

- 否定・非存在を `low` へ読み替えない。
- bare presenceを `low/moderate/high/very_high` へ読み替えない。
- 強度表現を特定の程度副詞・語尾・phraseへ固定しない。
- `overview` を単なる `present` へ縮退しない。
- `unknown` をhedge付きの特定polarityへcommitしない。

### observed_certainty

`observed_certainty` は **対象stateについてのepistemic certainty** である。

次ではない:

- Observer自身の判定自信度
- 文法上その文を強く断言しているか
- predicateの強度

意味:

- `high`: 対象stateへ明確にcommitしている。
- `medium`: 対象stateを暫定的・蓋然的に述べる。
- `low`: 対象stateについて明示的な不確かさ・判断困難を残す。
- `unknown`: speechからepistemic certaintyを観測できない。

`observed_state=unknown` で「判断できない」と明確に述べていても、「判断できないという事実を強く断言した」ことを理由にcertaintyをhighへ引き上げない。certaintyは対象stateに対するepistemic確かさとして観測する。

### Evidence spans

`predicate_evidence_spans / state_evidence_spans / certainty_evidence_spans` はCharacter speechに実在する原文だけを返す。

User Wording Hint、Candidate ID、Plan説明文をevidenceにしてはいけない。

## 2. Runtime typed comparison

Runtimeは自然言語理解をしない。Observerによる自然言語理解が完了した後のtyped構造だけを比較する。

Runtimeが決定論的に検証してよいもの:

- observation schema / enum / ID
- observation IDとrealized propositionの対応
- `predicate_realized`
- `observed_state == planned.state`
- `observed_certainty == planned.certainty`
- required evidence spanの存在
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
Runtime: present != low
=> reject
```

未列挙paraphraseでもObserverが意味として `low` を観測できれば、Runtimeはその日本語表現を知らずに比較できる。

## 3. Post-Observation Character Realization Validator

Observer + Runtime typed comparisonを通過した後、後段Validatorは**同じstate意味をもう一度自然文から解釈しない**。

後段Validatorが検証する:

- primary/supporting predicateの対象意味がspeechに残っているか
- non-null conceptがpredicate関係の中で保持されているか
- required semantic content
- forbidden addition
- unsupported new self-state / relation / experience / external fact / Activity result
- existence boundary
- question/new-direction budget
- Character Profileによる表面表現差だけを理由にrejectしていないか

後段Validatorが再判定してはいけない:

- state
- polarity
- intensity
- certainty
- state fidelity
- intensity counterfactual

そのためPost-Observation Validatorへ渡すPlan viewからexpected state/certainty/intensityを除外する。

出力schemaもstate/certainty/intensity診断を持たず、global content boundaryとpredicate/conceptだけを返す。

```text
semantic_checks:
  required_content_preserved
  forbidden_additions_absent
  unsupported_new_fact_absent
  existence_boundary_preserved
  budget_preserved

realized_proposition_checks:
  realization_id
  predicate_preserved
  predicate_evidence_spans
  concept_preserved
  concept_evidence_spans
```

これにより同じspeechについて

```text
Observer: low
Validator: polarity_changed
```

のような二重semantic authorityを構造上なくす。

## 4. Predicate / conceptとの境界

ObserverはCandidate predicateを用いてstate/certaintyを観測するが、後段Validatorによるpredicate/concept検証を置き換えない。

理由:

- Candidate predicateは観測対象IDとして必要。
- しかしCharacter speechが質問対象を省略・隣接概念へ置換したかは、Plan-awareな意味境界として別に確認する必要がある。
- conceptはexpected valueをObserverへ渡すとPlan anchoringになるため、Post-Observation Validatorで検証する。

したがってsemantic authorityはfacetごとに一意にする。

```text
state / polarity / intensity / certainty
  → Independent Observer + Runtime typed comparison

predicate target meaning / concept / content boundaries
  → Post-Observation Validator
```

## Prompt / Dependency boundary

RuntimeはConcrete Prompt Builderをimportしない。

`CharacterRealizationValidationPromptBuilder` Portを介しAdapter側が2種類のPromptを構築する。

- `build_observation(...)`: expected state/certainty/conceptを含まないObserver Prompt
- `build(...)`: state/certainty/intensityを除いたPost-Observation Validator Prompt

同じ `ResponseValidationModel` Portを異なる `llm_role` で再利用してよい。

- `character_realization_observer`
- `character_realization_validator`

Model providerが同じでも、意味上の役割・Prompt authorityは分離する。

## Fail closed

次ではsemantic validation済みと扱わない。

- model unavailable
- Observer invocation failure
- Observer JSON/schema invalid
- required observation欠落
- duplicate/unexpected observation
- Observer evidence spanがspeech外
- typed observed state/certaintyがPlanと不一致
- Post-Observation Validator schema invalid
- required predicate/concept evidence欠落
- Post-Observation evidence spanがspeech外

失敗時にfinite lexical fallbackへ戻らない。

## #229の終了条件との関係

本gateは#229の共通意味保持contractを次のように分担して固定する。

- predicate: Observerでrealized有無を確認し、Post-Observation Validatorで対象意味を確認
- state / polarity / intensity: Observer + typed comparison
- certainty: Observer + typed comparison
- concept: Post-Observation Validator
- required / forbidden content: Post-Observation Validator
- supporting proposition: realizedなものだけObserver + Post-Observation Validator両境界を通す
- unknown非commit: Observer + typed comparison
- regeneration後の意味保持: 各attemptを同じpipelineへ再投入
- Character Profile表面差: typed meaningとcontent boundaryが同じなら許容

Memory/Knowledgeについては#229の意味保持contractをSemantic Plan fixtureで検証してよいが、#226側production projectionを本Issueで先行実装しない。

## Verification

最低限次を確認する。

1. E8型: Plan `low` / bare presence → Observer `present` → typed comparisonでreject。
2. E4型: realized supporting intensityのbare presenceも同じ仕組みでreject。
3. absenceを `low` へ誤分類しない。
4. `overview` を単なる `present` へ縮退しない。
5. epistemic medium/lowを文のassertivenessと混同してhighへ上げない。
6. valid unknownをspecific polarityへcommitしない。
7. 未知paraphraseをfinite dictionaryなしで意味観測できる。
8. Observer Promptにexpected state/certainty/conceptが入っていない。
9. Post-Observation Validator Promptにexpected state/certainty/intensityが入っていない。
10. EmotionだけでなくDesire / Drive / Memory・Knowledge fixture / Character Profile差で同一contractを確認する。
11. Unit → Adjacent → Full regression → #223 Liveの順で検証する。

## 再発防止

- `_EXPLICIT_INTENSITY_MARKERS` 型の有限自然語semantic authorityを追加しない。
- test speechをProduction既知語へ変更してPASSさせない。
- Observerと後段Validatorに同じfacetの自然言語意味判定を重複させない。
- unseen paraphraseを回帰ケースとして残す。
- チャット切替時は本設計書と#229/#233の責務を再読してから実装を再開する。
- 他Issueで発見した同種問題を本Issueから横断修正せず、各Issueを実施する時にその責務内で是正する。
