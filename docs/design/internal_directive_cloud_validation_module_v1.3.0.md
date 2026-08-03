# 内部指示器クラウド検証モジュール設計 v1.3.0

## 1. 目的

内部指示器ラボで設定した検証条件とLLM結果を、ChatGPTへ渡しやすい単一のテキストファイルとして保存できるようにする。

また、入力領域が縦に長くなる問題を軽減するため、主要な5セクションを個別に折りたためるようにする。

## 2. 対象範囲

### 2.1 Export対象

必ず次の5領域を出力する。

1. `StructuredInputMeaning`
2. 内部状態
3. 利用可能Activity
4. 進行中Activity
5. `Character Profile / 存在境界`

LLM実行結果が画面に存在する場合は、次の情報も追記する。

- `valid`
- 実行モードとモデル
- 実行時間
- 停止位置
- `Parsed InternalDirective`
- `Raw LLM Response`
- Prompt（画面に含めて実行した場合のみ）

APIキー、Basic認証のユーザー名・パスワード、Renderの環境変数は出力しない。

### 2.2 折りたたみ対象

次の5セクションに個別の開閉ボタンを設ける。

- `StructuredInputMeaning`
- 内部状態
- 利用可能Activity
- 進行中Activity
- `Character Profile / 存在境界`

## 3. Export仕様

### 3.1 操作

画面上部のプリセット操作領域に `ChatGPT用テキストをExport` ボタンを置く。

押下時に、現在表示中のGUIまたはJSON入力を内部モデルへ同期してからファイルを生成する。JSON入力が不正な場合はダウンロードせず、既存のJSONエラーを表示する。

### 3.2 ファイル形式

- 拡張子: `.txt`
- 文字コード: UTF-8 with BOM
- MIME Type: `text/plain;charset=utf-8`
- ファイル名: `yura-internal-directive-lab-YYYYMMDD-HHMMSS.txt`

### 3.3 本文構成

本文はMarkdown互換のプレーンテキストとし、ChatGPTへファイル添付または本文貼り付けした際に構造を認識しやすくする。

```text
# ゆら 内部指示器ラボ 検証データ

## 確認してほしい内容
入力条件とInternalDirectiveの整合性を評価してください。

## StructuredInputMeaning
```json
...
```

## 内部状態
```json
...
```
```

プリセットを選択している場合は、その名称もメタ情報へ含める。

## 4. 折りたたみ仕様

### 4.1 共通動作

- 初期状態はすべて展開する。
- 各セクションのヘッダー右側に `折りたたむ / 展開する` ボタンを置く。
- ボタンは `aria-expanded` と `aria-controls` を持つ。
- 開閉は表示だけを変更し、入力値・GUI/JSONモード・プリセット値を変更しない。
- プリセット適用時も現在の開閉状態を維持する。

### 4.2 内部状態の例外

内部状態の円形サマリー (`stateOverview`) は常時表示する。

折りたたむ対象は次のみとする。

- 感情・欲求・関係性・動機・善悪の詳細入力
- 状況・記憶コンテキスト
- 内部状態のJSON編集欄

円形サマリーはGUI/JSONモードや折りたたみ状態にかかわらず、現在の内部状態を表示する。

## 5. 実装方針

既存のHTTP、認証、API、プリセット処理は変更せず、Renderで配信する完成HTMLへ次を追加する。

- Exportボタンと状態表示
- Export用JavaScript
- セクション開閉用JavaScript
- 開閉ボタンと折りたたみ領域のCSS

DOMノードを移動する場合も、既存イベントリスナーが付いたノード自体を再生成せず移動することで、GUI/JSON同期処理を維持する。

## 6. テスト方針

- 完成HTMLにExportボタンが存在すること
- 5セクションすべてが開閉対象として定義されること
- 内部状態の円形サマリーを折りたたみ領域外へ移す処理があること
- Export前に `syncAllSections()` を呼ぶこと
- Export本文に5入力領域の見出しが含まれること
- LLM結果が存在する場合に結果を追記する処理があること
- 完成HTML内の全JavaScriptを `node --check` で構文検査すること
- 既存API、認証、プリセット、責務分離テストが成功すること
