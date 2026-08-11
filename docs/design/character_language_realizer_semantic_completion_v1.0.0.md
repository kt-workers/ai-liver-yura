# Character Language Realizer Semantic Completion v1.0.0

## 位置付け

Parent #225 / Work #227 / Draft PR #232。

12ケースLive Verificationで、SemanticUtterancePlan自体は正しいにもかかわらず、Character Language Realizerが意味facetを自然文上で省略・置換する一般的な失敗が残ったため、#227の恒久責務として意味保持契約を強化する。

## 観測した失敗クラス

- `current_desire / present / medium / concept=curiosity` を、欲求predicateを落として「気になる」だけへ置換する
- `current_desire / present / medium / concept=connection` を無標の断定へし、certainty=mediumを落とす
- Drive由来`curiosity / high`を「今はかなり強いよ」のような対象省略へする
- mixed overviewでoptional supporting propositionを多く採用し、各state fidelityを同時に保てなくなる

入力source固有の問題ではなく、Semantic Plan → speechの一般契約として扱う。

## 完成契約

### Primary predicate

primary predicateは、User Wording Hintや直前質問を見なくてもspeech本文だけから質問対象・述語関係を識別できるように実現する。

`ある / 強い / はっきりしない`等のstateだけを述べ、対象を会話文脈から補わせる実現は禁止する。

固定の日本語辞書やtarget別テンプレートは導入しない。

### Concept

non-null conceptはpredicateの代替ではなく修飾facetである。

```text
predicate relation + concept
```

の両方をspeechへ残す。conceptだけを関心・感覚・対象名として述べてpredicate relationを消さない。

### Certainty

`certainty=medium/low`はepistemic modalityとして明示的に実現する。程度・強度へ変換しない。

`state=unknown`では同一の慎重表現がunknown stateとcertaintyを同時に担ってよい。それ以外でmedium/lowを無標の断定文へ縮退させない。

### Supporting proposition

supporting propositionはoptionalであり、primaryだけで自然に完結できる場合は省略を優先する。

採用する場合のみ、predicate/state/certainty/non-null conceptをfacet-completeに実現し、そのrealization IDを列挙する。

## Regeneration

Validator差分の語彙が完全一致しなくても、`predicate / concept / certainty / state_fidelity`を含む診断から対応repair constraintへ正規化する。

- restore_target_predicate_meaning
- restore_required_concept_within_predicate
- restore_certainty_as_epistemic_modality
- restore_state_fidelity

## 非目標

- current_desire専用台詞
- Drive専用台詞
- Character Bible / CharacterProfile品質
- fixed target→日本語辞書
- Validator責務の取り込み
- TTS / Body

## Gate

1. Unitで上記Prompt契約を固定
2. #226↔#227 Adjacentを回帰確認
3. #229へ同一#227 HEADを同期
4. Lab全12ケースで再検証
