# Character Realization Facet Evidence Runtime Gate v1.0.0

## 位置付け

Parent #225 / Work #229 / Draft PR #233。

この文書は2回目Live後に導入したfacet evidence Runtime gateの経緯と、finite degree dictionary撤去後の正規契約を記録する。

詳細なsemantic authorityは `character_realization_observed_state_gate_v1.0.0.md` を正本とする。

## 旧Runtime degree guardの廃止

以下はArchitecture Regressionとして撤去済み。

- `_EXPLICIT_INTENSITY_MARKERS`
- `_explicit_intensity_markers`
- `_has_explicit_degree_evidence`
- `_deterministic_surface_differences`
- finite phrase / keyword / regex / substringによるdegree evidence判定

Runtimeが「low/moderate/highを表す日本語」を有限列挙する方式はguard / safety net / compatibility / fallback等の名称に関係なく使用しない。

## 第三回Liveで追加確認した問題

Independent Observer導入後、次の誤観測がLiveで確認された。

- `overview → present`
- `certainty=medium/low → high`
- absence表現 → `low`

さらにE8では同じspeechについてObserverが `low`、後段Plan-aware Validatorが `polarity_changed` と別解釈した。

これにより、state/certainty/intensityをObserverと後段Validatorの双方で自然言語から判定する二重semantic authorityを廃止する。

## 現在の正規フロー

```text
Character speech
      ↓
Independent Character Realization Observer
      ↓
RealizedSemanticObservation
      ↓
Runtime typed comparison
      ↓
Post-Observation Character Realization Validator
      ↓
accept / reject
```

## Independent Observer evidence

Observerが返す:

- `predicate_evidence_spans`
- `state_evidence_spans`
- `certainty_evidence_spans`

Runtimeは各spanについて:

- non-empty stringか
- Character speechの実部分文字列か

だけを検証する。

spanの文字列からstate/intensity/certaintyをRuntimeが再推定しない。

Observerの意味定義:

- absentとlowを区別する
- presentとordered intensityを区別する
- overviewとpresentを区別する
- unknownをspecific polarityへcommitしない
- certaintyは対象stateへのepistemic certaintyとして扱い、文のassertivenessやObserver自身の自信度と混同しない

これらを有限自然語リストで実装しない。

## Runtime typed comparison

Runtimeが決定論的に行う:

- schema / enum / ID検証
- `predicate_realized`
- `observed_state == planned.state`
- `observed_certainty == planned.certainty`
- required evidence span存在
- evidence spanのspeech実在
- missing / duplicate / unexpected observation

Runtimeが行わない:

- natural-language word → state mapping
- degree marker lookup
- polarity regex
- evidence spanのsemantic category推定

## Post-Observation evidence

Observer + Runtime typed comparison通過後、Post-Observation Validatorが返すevidenceは次へ限定する。

- `predicate_evidence_spans`
- `concept_evidence_spans`

後段ではstate/certainty/intensity evidenceを返さない。

理由は、同一facetをもう一度自然文から再判定するとsemantic authorityが二重化するため。

後段Runtimeはpredicate/concept spanについて:

- requiredなら非空か
- Character speechの実部分文字列か

だけを検証する。

## Post-Observation Validatorの責務

検証する:

- predicate target meaning
- concept
- required semantic content
- forbidden addition
- unsupported new fact
- existence boundary
- question/new-direction budget
- Character Profile由来の表面表現差だけを理由にrejectしないこと

検証しない:

- state / polarity
- intensity
- certainty
- state fidelity
- intensity counterfactual

Post-Observation Plan viewからexpected state/certainty/intensityを除外する。

## Fail closed

以下ではsemantic validation済みと扱わない。

- validation model unavailable
- Observer invocation/schema failure
- observation missing / duplicate / unexpected
- typed observed state/certainty mismatch
- Observer evidence欠落 / speech外
- Post-Observation schema invalid
- required predicate/concept evidence欠落 / speech外

失敗時にfinite lexical fallbackへ戻らない。

## Unit / Adjacent Gate

最低限次を固定する。

1. E8 `energy=low` + bare presence → Observer `present` → reject
2. E4 realized supporting intensity bare presence → typed mismatchでreject
3. unseen paraphrase → Observerがplanned stateを観測すればfinite dictionaryなしでaccept可能
4. unknownをlow/presentへcommit → typed mismatchでreject
5. valid unknown → accept
6. medium/low epistemic certaintyをObserverで保持
7. absenceをlowへ誤分類しない契約
8. overviewをpresentへ縮退しない契約
9. non-null conceptをPost-Observation側で保持
10. Observer Promptへexpected state/certainty/conceptを含めない
11. Post-Observation Promptへexpected state/certainty/intensityを含めない
12. Runtime sourceへfinite natural-language semantic dictionaryを再導入しない
13. model unavailable/schema invalid → fail closed

## Gate順序

```text
#229 Unit / Architecture
        ↓ PASS
#226 → #227 → #229 Adjacent
        ↓ PASS
Representative Desire / Drive / Memory-Knowledge / Profile variation
        ↓ PASS
Full regression
        ↓ PASS
#223 Labへ同期
        ↓
Basic 4 + E1-E8 + 少数paraphrase Live
```

Characterの自然さ・ゆららしさ・Discourse・Speech Performanceは本Issueの完了条件へ広げない。
