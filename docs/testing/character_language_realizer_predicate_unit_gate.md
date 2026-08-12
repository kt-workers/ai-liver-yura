# Character Language Realizer Predicate Unit Gate

## Scope

Issue #227 / PR #232 の current internal-state slice に対する追加Unit gate。

対象:
- primary proposition の `predicate` をrequired semantic facetとして投影する
- predicateの内部英語ラベルではなくtarget meaningをspeechへ保持する契約をPromptへ提示する
- `concept` は predicate を修飾し、置換しない
- `semantic_realizations` IDだけでpredicate保持済みとみなさない
- Validatorからpredicate欠落が返った場合に `restore_target_predicate_meaning` を再生成feedbackへ投影する
- 既存の certainty/intensity 分離、unknown、strict schema、raw-state-free boundaryを維持する

対象外:
- #229 Validator実装変更
- #223 Lab / 実LLM
- TTS / Body / Avatar / System integration

PASS後に #226→#227 Adjacent を再実行する。
