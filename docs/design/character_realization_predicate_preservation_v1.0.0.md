# Character Realization Predicate Preservation v1.0.0

## 目的

Character Realization Validator が、primary proposition の `state / certainty / concept` だけでなく、`predicate` が示す質問対象・述語関係の意味を Character speech が保持していることを独立facetとして検証する。

実OpenAI Labの `current_desire / state=present / certainty=medium / concept=curiosity` では、Character再生成後に:

```text
うん、気になる感じはあるよ。
```

が生成された。これは `concept=curiosity`、`state=present`、epistemicな慎重さを表現し得る一方、ユーザーが尋ねた「何かしたい」という `current_desire` のpredicate meaningがspeechから消えている。

従来Validatorは `concept_preserved=true` 等を確認したが `predicate_preserved` を独立検証しておらず、このconcept-only realizationをacceptedにした。

## 責務境界

#227 Character Language Realizer:
- predicateを含むrequired facetsを正しくspeechへ言語実現する第一責任

#229 Character Realization Validator:
- Character出力後の第二防衛線として、predicate meaningがspeechに残っているか独立検証する
- predicate/state/certainty/conceptを再計算しない
- raw Emotion / Desire / Driveを見ない

## Validator semantic_checks

accepted=trueのmodel応答では、primary propositionについて最低限次を必須とする。

```json
{
  "semantic_checks": {
    "required_facets_preserved": true,
    "predicate_preserved": true,
    "state_preserved": true,
    "certainty_preserved": true,
    "concept_preserved": true,
    "unsupported_intensity_added": false
  }
}
```

`concept=null`の場合、`concept_preserved`は従来どおり必須対象から外してよい。`predicate_preserved`はprimary propositionが存在する限り常に必須。

## Predicate preservation

`predicate_preserved=true`とは、内部英語ラベルがspeechに含まれることではない。

```text
predicate preservation
= speech本文だけを見ても、何について答えた発話か意味的に識別できる
```

User Wording Hintはユーザーがtargetをどう表現したかを確認するlexical/semantic frameとして使えるが、事実・state・certainty・conceptの正本にはしない。Semantic Planが意味の正本である。

## Conceptとの関係

conceptはpredicateを修飾するfacetであり、predicateの代替ではない。

例:

```text
Plan:
  predicate=current_desire
  state=present
  certainty=medium
  concept=curiosity

BAD:
  「気になる感じはあるよ」
  -> conceptはあるが、desire predicateが識別できない
  -> predicate_preserved=false

GOOD class:
  欲求/したさ/向かいたいこと等のtarget meaningを保持し、その内容・由来・方向としてcuriosityを自然に表現する
```

固定日本語句やtarget別辞書は契約にしない。

## Runtime fail closed

modelが`accepted=true`を返しても、以下の場合はRuntimeがfail closedする。

- `predicate_preserved` field欠落
- `predicate_preserved`がboolでない
- `predicate_preserved=false`

`false`の場合:

```text
accepted = false
reason = semantic_facet_validation_failed
claim_differences に predicate_preserved を含める
```

Schema欠落/型不正の場合:

```text
accepted = false
reason = realization_validator_schema_invalid
```

## semantic_realizations

`semantic_realizations=["proposition:0:<predicate>"]` は補助診断であり、predicate preservationの証拠ではない。

IDが存在してもspeech本文がconcept-onlyでtarget meaningを失っていればrejectする。

## Deterministic guardとの境界

日本語の固定語彙リストやtarget別regexを deterministic guardとして追加しない。

理由:
- predicate meaningは多様な自然語言い換えを許す
- Character Profileに応じた自然な表現を阻害しない
- Validator LLMがSemantic Plan + User Wording Hint + speechの意味関係を判定する責務

既存のdeterministic intensity guardやActivity fact validationは維持する。

## 非目標

- raw内部状態のValidator再投入
- current_desire専用テンプレート
- predicate→日本語固定辞書
- Character Profileの文体採点
- #227との同時実装修正（#227はUnit/Adjacent PASS後にfreeze済みのものを同期する）

## 検証順序

1. freeze済み#227 predicate contractを#229へ同期
2. #229 Unit
   - accepted=true + predicate_preserved=falseをRuntimeがreject
   - accepted=trueでpredicate_preserved欠落/型不正をschema invalid
   - promptがpredicateをrequired facetとして示す
3. #226→#227→#229 Adjacent
   - concept-only bad speechをreject
   - predicate+conceptを保持するgood speechをaccept
4. Lab focused CI
5. `現在の欲求` live再Verification
