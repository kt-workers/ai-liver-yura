# Character Semantic / Response Lab UI v1.1

## 目的

#223 / Draft PR #234 の実LLM Verificationを、前回結果や大きなJSON textareaに視線を奪われず、1ケースずつ切り分けて確認できるようにする。

この変更は検証UIだけを対象とし、Semantic Planner / Character Language Realizer / Validator / TTS / Body / Runtime契約は変更しない。

## UI契約

### 1. 前回結果のクリア

以下の操作開始時に前回結果を即時クリアする。

- `プリセット読込`
- `実行`

クリア対象:
- `lastResult`
- Pipeline Result本文
- Status / Attempts / Elapsed KPI

プリセット読込後は新しい入力状態だけを表示し、前回ケースの結果を残さない。

### 2. 実行ステータス

ツールバー内に常時見える実行ステータスを置く。

状態:
- `待機`
- `プリセット読込済み`
- `実行中`
- `完了`
- `失敗`

詳細メッセージはInputカード内にも残し、コピー完了等の補助通知に使う。

### 3. 1画面レイアウト

デスクトップではページ全体を原則100vh内に収める。

- header / toolbarをcompact化
- workspaceを残り高さへ割当
- Input / Resultカード自体はviewportを越えて伸ばさない
- 内容が多い場合は各カード内部だけスクロールする
- JSON textareaの標準高さを縮小する
- mobile幅では通常の縦積みへ戻す

「すべてのJSON全文をスクロール無しで表示する」ことは目的にしない。検証操作・主要状態・結果KPIが同じviewport内に存在することを優先する。

### 4. Emotion / Driveの可視化

Emotion / Driveはデフォルトでグラフ表示する。

- `emotion.current.reactive` の数値dimensionを0〜1横棒で表示
- Driveの数値dimensionを0〜1横棒で表示
- 値はラベル横にも数値表示
- 0〜1外の値が入力されても描画幅だけ0〜100%へclampし、元値表示は保持する

JSONを直接確認・編集したい場合のみ `JSON表示` switchをONにする。

- default: OFF = graph mode
- ON = Emotion / Drive JSON textarea
- OFFへ戻す時はtextareaをparseしてgraphを再描画
- parse error時はJSON modeを維持し、statusへ失敗理由を出す

プリセット読込時はgraphも即座に更新する。

## 非対象

- Semantic Plan生成規則
- Character発話生成規則
- Validator判定規則
- live API request/response schema
- Export JSON schema
- TTS / Body / Avatar / full runtime
