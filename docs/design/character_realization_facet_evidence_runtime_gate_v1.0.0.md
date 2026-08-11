# Character Realization Facet Evidence Runtime Gate v1.0.0

## 位置付け

Parent #225 / Work #229 / Draft PR #233。

この文書は、2回目Live Verification後に導入したfacet evidence Runtime gateの経緯と、今回のArchitecture Regression是正後の正規契約を記録する。

**重要:** 旧版に記載していた有限個のdegree markerをRuntimeで検出する方式は廃止した。現在の正規設計は `character_realization_observed_state_gate_v1.0.0.md` である。

## 2回目Liveで確認した問題

### E8 Drive Energy low

Semantic Plan:

```text
predicate=energy
state=low
certainty=high
```

Character:

```text
うん、元気はあるよ。
```

Plan-aware Validatorは `state_fidelity=exact` と誤判定した。しかしspeechはenergyのpresenceしか示しておらず、`low` と `present` の差が失われている。

### E4 mixed current feeling

`calm=low` supporting propositionをbare presence表現でrealizeしてもexactとしてacceptされた。同じ原因クラスである。

### E3 / current_desire false reject

unknownの自然表現や `current_desire + certainty=medium + concept` の自然な言い換えを、Plan-aware Validatorが過剰にrejectするケースも確認した。

## 旧Runtime degree guardの廃止

一時的に以下の方式を導入したが、Architecture Regressionとして撤去した。

- `_EXPLICIT_INTENSITY_MARKERS`
- `_explicit_intensity_markers`
- `_has_explicit_degree_evidence`
- `_deterministic_surface_differences`
- finite phrase / keyword / regex / substringによるdegree evidence判定

理由:

1. open-ended自然言語には未列挙paraphraseが必ず存在する
2. false negativeのたびに語彙追加が必要になり辞書が肥大化する
3. Runtimeへ自然言語意味判定責務が逆流する
4. test wordingをProduction既知語へ合わせる誘因を生む
5. `それなりに` のような自然なvariationを正当に扱えない

Runtimeが「low/moderate/highを表す日本語」を有限列挙する方式は、guard / safety net / compatibility / fallback等の名称に関係なく使用しない。

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
Plan-aware Character Realization Validator
      ↓
accept / reject
```

### Independent Observer

Observerは期待される `state / certainty / concept` を受け取らず、speechが実際に表している意味を観測する。

Observerへ渡すのは:

- speech
- canonical realization ID
- proposition対応用のkind / predicate
- predicateの自然語意味枠を補助するbounded User Wording Hint

Observerへ渡さない:

- expected state
- expected certainty
- expected concept
- expected intensity
- raw Emotion / Desire / Drive
- Planとの一致判定

Observerはtypedな `RealizedSemanticObservation` を返す。

### Runtime typed comparison

Runtimeが決定論的に行うのは自然言語理解後の構造比較だけである。

許可:

- schema / enum / ID検証
- `predicate_realized` の確認
- `observed_state == planned.state` の比較
- `observed_certainty == planned.certainty` の比較
- required evidence spanの存在確認
- evidence spanがspeech中に実在するかの確認

禁止:

- speechやevidence span内の単語からstate/intensity/certaintyを再推定する
- regex / substring / finite dictionaryで自然文をsemantic categoryへ分類する

例:

```text
Plan: energy=low
Observer: observed_state=present
Runtime: low != present
=> reject
```

`それなりに` 等の未列挙paraphraseでも、Observerがspeechの意味として `low` を観測できればRuntimeは語彙を知らずに比較できる。

## Facet evidence contract

Plan-aware Validatorが返す以下のevidence配列は維持する。

- `predicate_evidence_spans`
- `certainty_evidence_spans`
- `concept_evidence_spans`
- `intensity_evidence_spans`

Runtimeは各spanについて:

- non-empty stringか
- Character speechの実部分文字列か

だけを検証する。

spanの文字列自体から意味カテゴリを推定しない。

`surface_evidence.intensity_markers` も診断情報に限定する。値がある場合にspeech実在だけを確認し、markerをaccept根拠やstate分類に使わない。

## Plan-aware Validatorが引き続き検証するもの

- predicate
- state / polarity
- certainty
- concept
- required semantic content
- forbidden addition
- supporting proposition
- unknown非commit
- state_fidelity
- question/new-direction budget
- existence boundary
- regeneration後の意味保持

Independent Observerはこれらを置き換えるのではなく、Plan-aware自己申告だけでは見逃したstate/certaintyの意味変化を独立観測で補強する。

## Fail closed

以下ではsemantic validation済みと扱わない。

- validation model unavailable
- Observer invocation failure
- Observer schema invalid
- observation missing / duplicate / unexpected
- typed observed state/certainty mismatch
- required evidence欠落
- evidence spanがspeech外

失敗時にfinite lexical fallbackへ戻らない。

## Unit / Adjacent Gate

最低限次を固定する。

1. E8 `energy=low` + bare presence → Observer `present` → reject
2. E4 realized supporting intensityのbare presence → typed mismatchでreject
3. unseen paraphrase (`それなりに` 等) → Observerがplanned stateを観測すればaccept可能
4. unknownをlow/presentへcommit → typed mismatchでreject
5. valid unknown → accept
6. medium/low certainty evidence contract
7. non-null concept evidence contract
8. model unavailable/schema invalid → fail closed
9. Observer Promptへexpected state/certainty/conceptを含めない
10. Runtime sourceへfinite degree semantic dictionaryを再導入しない

## 次のGate

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
