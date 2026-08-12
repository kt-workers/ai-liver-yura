# Character Semantic Response Cloud Validation Lab v1.2.0

## 位置づけ

Issue #223 / Parent #225。

本設計は `character_semantic_response_cloud_validation_lab_v1.1.0.md` を、Issue #229で確定したIndependent Character Realization Observer境界へ追従させる。

このLabは意味決定ロジックを独自実装せず、productionの発話生成・検証境界を全体Runtimeから切り離して観測する。

```text
SemanticUtterancePlan
→ Semantic Validator
→ Character Language Realizer
→ CharacterUtterance
→ Independent Character Realization Observer
→ RealizedSemanticObservation
→ Runtime typed comparison
→ Post-Observation Character Realization Validator
→ Runtime structured residual comparison
→ accept / reject
```

## 恒久的に確認する契約

- predicate
- state / polarity
- certainty
- non-null concept
- required content
- forbidden addition
- supporting proposition
- unknownをpresent/absent等へ勝手にcommitしない
- intensityをpresenceへ弱めない／別強度へ変えない
- regeneration後も同じ必須facetを保持する
- Character Profileによる表面表現差が入っても意味を変更しない

台詞の可愛さ、ゆららしい語尾・語彙、Relationship本格表現、談話品質、音響的pause/prosody、Voice/Body統合は本Labの合否対象外とする。

## 最新Liveで確認した構造問題

Basic4 + Extended E1-E8のユーザーVerificationでは12 request自体は成功したが、意味保持結果は1 validated / 11 fallbackだった。

個別文言ではなく次の4原因クラスへ整理し、#229側でtyped boundaryを修正した。

1. `concept=null` でもPost-Observation modelがconcept evidenceを返すことによるstructural false reject。
2. state/intensity mismatch後のregeneration feedbackがstate fidelity修復へ接続されない問題。
3. Semantic PlanとObserverでcertainty定義が一致せず `unknown + high` を表現不能にする問題。
4. Observer JSON envelope差と、Post-Observation modelのfree-form `accepted/reason` がstate/certaintyを再審査できる残存authority。

Labはこれらの修正済みproduction contractを観測し、finite自然語辞書を代替実装しない。

## Observer境界

ObserverはCharacter speechが実際に表している意味を独立にtyped化する。

Observerへ渡す:

- Character speech
- realization対応用のcanonical ID / kind / predicate
- primary predicateの意味枠を特定するためのbounded User Wording Hint

Observerへ渡さない:

- expected state
- expected certainty
- expected concept
- expected intensity
- raw Emotion / Desire / Drive
- Planとの一致判定

Observerの出力 `RealizedSemanticObservation` とSemanticUtterancePlanの比較はRuntimeでtyped structure同士に対して行う。Runtimeはspeech中の有限語彙、正規表現、substring等からstate/intensity/certaintyを再推定しない。

### certainty

`observed_certainty` は、**「このpredicateのstateはobserved_stateである」という命題へのepistemic certainty**として扱う。Semantic Planの `certainty` も同じ意味である。

そのため `observed_state=unknown` でも `certainty=high/medium/low` を定義上許容する。

- `unknown + high`: 現在のstateがunknownであることを明確に述べる。
- `unknown + medium/low`: unknownという判定自体にも留保を残す。

`unknown => certainty=low` の固定対応は行わない。certaintyをstate intensity、文体上の勢い、Observer自身の判定自信度と混同しない。

### Observer JSON envelope

正規出力は `{ "observations": [...] }` とする。

同じtyped observation配列をmodelがtop-level `[...]` で返した場合、Runtimeは**構文上のenvelope差だけ**を正規化してよい。observation要素内のstate/certainty等を補完・推定してはいけない。

## Runtime typed comparison

Runtimeが決定論的に比較するのは自然言語理解後のtyped structureだけである。

- schema / enum / realization ID
- `predicate_realized`
- `observed_state == planned.state`
- `observed_certainty == planned.certainty`
- required evidence spanの存在とspeech内実在
- missing / duplicate / unexpected observation

state mismatchは `restore_state_fidelity`、certainty mismatchは `restore_certainty_as_epistemic_modality` へ原因facetを保持したままregenerationする。

Runtimeはspeech/evidenceの単語、phrase、regex、substringから意味facetを再推定しない。

## Post-Observation Validator境界

`state / polarity / intensity / epistemic certainty` の意味authorityはObserverとRuntime typed comparisonに一本化する。

Observerのtyped比較を通過した後のCharacter Realization Validatorは、speechからこれらのfacetを再抽出・再解釈しない。後段で確認するのは次に限定する。

- predicateの対象意味
- non-null concept
- required content
- forbidden additions
- unsupported new fact
- existence boundary
- question / new-direction budget

したがってLabのValidator fakeも `state_preserved`、`state_fidelity`、`certainty_preserved`、`intensity_semantics_preserved`、`surface_evidence` 等の旧schemaを返さない。Post-Observation schemaとして、5個のsemantic checkと、各realizationの `predicate_preserved / predicate_evidence_spans / concept_preserved / concept_evidence_spans` だけを返す。

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

Post-Observation modelのtop-level `accepted / reason / differences` は診断情報であり、最終semantic authorityにはしない。Runtimeは上記closed structured checksからaccept/rejectを導出する。

`concept=null` のpropositionではconcept facetはtyped contract上N/Aである。modelが余分なconcept evidenceを返してもsemantic failureにはしない。non-null conceptの場合だけ `concept_preserved` とevidenceを厳格に要求する。

この分離により、Observerが `low` と観測した候補を後段Validatorが再び自然文から別stateとして判定する二重semantic authorityをLabでも再導入しない。

## Lab Export

トップレベルで以下を観測可能にする。

- `semantic_utterance_plan`
- `semantic_validation`
- `character_utterance`
- `character_model_boundary`
- `realization_observation`
- `observer_model_boundary`
- `realization_validation`
- `validator_model_boundary`
- `linguistic_performance`
- `semantic_realizations`
- `pipeline_boundaries`

`model_calls`にはattempt順で主に次のroleが記録される。

1. `character_language_realizer`
2. `character_realization_observer`
3. `character_realization_validator`

Observerでtyped mismatchを検出した候補はPost-Observation Validatorへ到達せずrejectされ得る。この場合、当該attemptにValidator callが存在しないことは正常である。

## Model boundary

Character / Observer / Validatorの各model invocationへ、次のraw runtime stateを渡さない。

- full `response_context`
- `event_payload`
- `activity_execution_result`
- `ongoing_activity`
- raw `emotion`
- raw `drive`

Labの診断用top-level snapshotにEmotion / Driveが存在することと、model inputへ渡すことを区別する。

## fake mode

fake modeの目的は**wiring検証だけ**であり、自然言語品質・意味理解能力の検証には使用しない。

Independent Observer追加後もfake modeで全境界を通せるよう、Character fakeはspeechへLab専用の閉じたtyped診断markerを付与し、Observer fakeはそのmarkerだけをdecodeする。

```text
Character fake
→ closed Lab typed marker
→ Observer fake
→ RealizedSemanticObservation
→ Runtime typed comparison
→ Post-Observation Validator fake
```

markerが運ぶ `state / certainty` を読むのはObserver fakeだけである。Validator fakeはexpected state/certainty/intensityを受け取らず、Post-Observation Semantic Contractに含まれるpredicate/concept等の残余契約だけを返す。

これはopen-ended自然言語の意味判定ではない。Lab内部の閉じたテストプロトコルであり、自然語の有限単語表、phrase dictionary、regex、substringをstate/intensity分類へ使用しない。

live modeではこのmarkerを使用せず、実Character speechを実Observer modelが独立に解釈する。

## Verificationケース

Liveの完了対象は `character_semantic_response_extended_verification_v1.1.0.md` に従う。

- Basic 4
- Extended E1-E8
- 少数のunseen paraphrase

合計を不必要に35ケース規模へ拡張しない。

Memory / Knowledgeについては#226のproduction projectionを先行実装しない。#229ではSemanticUtterancePlan fixtureに対するsource-independent contractをUnit/Adjacentで確認済みとし、Live Labは現在productionで確定しているinternal-state sliceを対象とする。

## Live判定

特に再確認する既知回帰:

- E8: `energy=low` をbare presenceへ弱めた候補をObserverが `present` と観測し、typed mismatchでrejectできること
- E4: supporting `calm=low` 等をbare presenceへ弱めた候補を同様にrejectできること
- E3: explicit unknownを `state=unknown` と観測し、Planのcertaintyも同じ命題certainty定義で保持できること
- current_desire: predicate / concept / certaintyを保持した自然表現をfalse rejectしないこと
- concept=null: concept evidenceの有無だけでfalse rejectしないこと
- Post-Observation: free-form accepted/reasonがtyped state/certaintyを再審査するauthorityにならないこと
- unseen paraphrase: productionの有限語彙リストに依存せず意味保持を判定できること

## CI Gate

latest #233 `3d317f2e2f4ecbd4a814be9346e989b285d1dc9d` をbaseに、Lab固有差分23ファイルだけをrestackしたコード/test snapshot:

- snapshot: `3b31d6577a0ccb06df85336e0625f43cb9c6823f`
- GitHub Actions run: `31564288526`
- workflow: `Cloud character semantic response validation`
- result: **PASS**
- focused tests: **144 passed / 0 failed in 3.19s**
- Lab module compile: **PASS**

## 完了条件

1. Lab compile / Focused CI PASS。
2. Character / Observer / Validator model boundaryにraw state漏洩なし。
3. ObserverとPost-Observation Validatorのsemantic authorityが分離され、後段でstate/polarity/intensity/certaintyを再判定しない。
4. Basic4 + E1-E8 + 少数unseen paraphraseを同一条件でLive実行。
5. false accept / false rejectを個別文言ではなく原因クラスで評価。
6. predicate / state / certainty / concept / required / forbidden / supporting / unknown / intensity / regenerationの基盤契約が成立。
7. ユーザー実機確認まではPR #234をDraftのまま維持し、Ready化・mergeしない。
