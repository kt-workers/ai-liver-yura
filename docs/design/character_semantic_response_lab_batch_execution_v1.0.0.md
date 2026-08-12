# Character Semantic Response Lab Batch Execution v1.0.0

## 目的

Extended Verificationをケース単位の局所修正へ偏らせず、複数プリセットを同一条件でまとめて実行・比較できるようにする。

## スコープ

本変更はSemantic Lab固有の検証支援機能であり、#226 SemanticUtterancePlan、#227 Character Language Realizer、#229 Character Realization ValidatorのProduct契約・実装は変更しない。

## 一括実行

プリセット選択に `すべて実行（全プリセット）` を追加する。

選択した状態で実行すると、ブラウザが `/api/character-response` を各プリセットについて順番に呼び出す。単件用とは別のProduct pipelineやbatch APIを作らない。

- 実行順は `/api/presets` が返した順序を維持する。
- 1ケースがHTTP/JSONエラーになっても、残りのケースは継続する。
- 実行状態に `現在件数 / 総件数` を表示する。
- 各ケースについて `preset_key`、`label`、`success`、成功時の `result`、失敗時の `error` を保持する。
- 最終結果は1つのJSONとして画面表示・コピーできる。
- 集計には total / succeeded / failed / elapsed_ms を含める。

## Prompt出力設定

`Promptも結果に含める` は詳細設定の奥ではなく、実行ボタンの近くに常時表示する。

- 単件実行では現在の入力スナップショットへ適用する。
- 一括実行では全プリセットへ同じ設定を上書き適用する。
- プリセット自身の `include_prompts` 初期値より、実行時のチェック状態を優先する。

## UI

通常プリセット選択時:

- `プリセット読込` で従来どおり編集フォームへ展開する。
- `実行` で現在フォーム内容を単件実行する。

`すべて実行` 選択時:

- `プリセット読込` は不要なので無効化する。
- `実行` は全プリセットの順次実行になる。
- Input Snapshotは最後に明示的に読み込んだ単件内容を保持し、一括実行のたびにフォームを切り替えない。

## 非目標

- Product側batch APIの追加
- 並列LLM呼び出し
- 自動PASS/FAIL採点
- 途中失敗時の全体abort
- Character/Validatorの意味契約変更

## 検証

UIテストで次を固定する。

1. 全件実行optionが存在する。
2. batch実行は全presetを順番に単件APIへ送る。
3. 各requestでtoolbarの `includePrompts` を適用する。
4. 途中失敗をresultsへ記録して次へ継続する。
5. Prompt checkboxがtoolbar内にあり、Constraints詳細内には置かない。
6. 単件実行・既存グラフ・JSON copyの挙動を維持する。
