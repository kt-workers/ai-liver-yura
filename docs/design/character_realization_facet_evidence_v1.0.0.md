# Character Realization Facet Evidence v1.0.0

## 位置付け

Parent #225 / Work #229 / Draft PR #233。

12ケースLive Verificationで、Validatorが`predicate_preserved=true`等を返していてもspeech本文がそのfacetを実際には保持していないfalse acceptと、自由文differencesと構造checkが矛盾するfalse rejectが観測された。

本設計は意味を再計算せず、SemanticUtterancePlanとspeechの対応根拠を明示させることで#229の判定を安定化する。

## 観測した失敗クラス

- `curiosity/high`に対する「今はかなり強いよ」をpredicate保持済みとしてaccept
- `current_desire/unknown/low`に対する「まだはっきりはしないかな」をpredicate保持済みとしてaccept
- `current_desire/present/medium/concept=connection`の無標断定をcertainty保持済みとしてaccept
- mixed supporting stateで`低め`のようなdegree表現をweakenedとしつつ、bare presenceをmoderateの根拠とする自己矛盾

## Facet evidence contract

各`realized_proposition_checks`は既存bool/state fidelityに加え、次のspeech原文spanを診断として返す。

- `predicate_evidence_spans`
- `certainty_evidence_spans`
- `concept_evidence_spans`
- `intensity_evidence_spans`

### Predicate evidence

`predicate_preserved=true`なら、speechだけから対象・述語関係を識別可能にする実文字列を1件以上示す。

`ある / 強い / わからない / はっきりしない`等の対象非依存表現だけをpredicate evidenceにしない。User Wording Hintによる省略補完もしない。

### Certainty evidence

`certainty=medium/low`をpreservedとする場合、epistemicな慎重さを担うspeech中のspanを示す。`state=unknown`では同じspanがstateとcertaintyを兼ねてよい。

`certainty=high`は無標でもよいためemptyを許可する。

### Concept evidence

non-null conceptをpreservedとする場合、そのconceptを担うspeech中のspanを示す。conceptはpredicateを置換せず、predicate relationと同時に保持される必要がある。

### Intensity evidence

既存contractを維持する。explicit intensity stateをexactとする場合、mere presenceとの差を担うspanが必要。

`低め / 強め`等はdegree evidenceになり得るが、`落ち着いている / いらだちもある`等のbare presenceだけはlow/moderate/highの根拠にしない。

## 診断整合

`accepted / reason / differences`と`realized_proposition_checks`を矛盾させない。

あるfacetをreject理由にする場合、対応checkにもfalse/non-exactを反映する。逆に構造checkがexactでevidenceも成立するfacetを、自由文differencesだけで不一致扱いしない。

## 非目標

- raw Emotion / Drive再計算
- target別固定辞書
- 自然さ・ゆららしさ評価
- Character Realizer責務の取り込み

## Gate

1. #229 UnitでPrompt契約を固定
2. #226→#227→#229 Adjacentを回帰確認
3. Lab全12ケースを再実行
4. false accept / false rejectが残る場合のみ、evidence schemaのRuntime fail-closed化を次段で行う
