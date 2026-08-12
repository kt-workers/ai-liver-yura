# Semantic Realization Validation Reassessment v1.1.1

## Status

`semantic_realization_validation_reassessment_v1.1.0.md` の実装時補正。その他の設計はv1.1.0を継承する。

## Optional proposition omission

実装時に、optional propositionを完全省略した場合の`certainty_relation`へ評価対象外状態が必要であることを確認した。

v1.1.0の:

```text
CertaintyRelation = preserved | stronger | weaker | ambiguous
```

を次へ補正する。

```text
CertaintyRelation = preserved | stronger | weaker | ambiguous | not_applicable
```

規則:

- `realized=false`かつ`realization_policy=optional`では、`predicate_relation=omitted`とし、意味facetのrelationは`not_applicable`を使用する。
- required propositionで`realized=false`は引き続きrejectする。
- realized propositionのcertaintyで`not_applicable`を使用して検証を回避してはいけない。realized=trueなら`preserved / stronger / weaker / ambiguous`のいずれかを返す。

この補正はfinite lexical matcherや意味判定の緩和ではなく、完全省略された命題について存在しないsurface certaintyを無理に評価しないための型整合である。
