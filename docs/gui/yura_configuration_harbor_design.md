# Yura 設定コンソール設計書

**画面名:** 設定の入り江  
**英語名:** YURA / CONFIGURATION HARBOR  
**対象:** `gui/yura-config-console`

## 1. 目的

分割された設定ファイルを、YAMLの直接編集なしで参照・変更できるスタンドアロンWeb画面を提供する。

本画面はCoreへ依存しない。設定の取得、検証、保存、履歴管理は専用のConfiguration Serverが担当する。

## 2. 責務境界

### Browser GUI

- 設定カテゴリの表示
- 型に応じたフォーム表示
- 入力値の保持
- 未保存差分の表示
- 検証・保存要求
- 変更履歴と構造化プレビューの表示

### Configuration Server

- manifestとカテゴリ情報の提供
- UI向けフィールドメタデータの提供
- 型・必須・範囲検証
- revisionによる楽観ロック
- 原子的保存
- 変更履歴の保持
- 反映ポリシーの提示

### Core

- 本画面の取得・保存処理には関与しない
- 将来、明示的なreload APIを追加する場合のみ接続対象とする

## 3. 対象カテゴリ

|category|owner file|用途|
|---|---|---|
|runtime|runtime.yaml|実行環境、ログ、入力受付|
|character|character.yaml|固定プロフィール|
|speech|speech.yaml|音声合成、VoiceVox、辞書|
|memory|memory.yaml|記憶機能|
|services|services.yaml|外部サービス接続|
|models|models.yaml|モデル定義|
|llm|llm.yaml|役割別LLMルーティング|
|emotion|emotion.yaml|感情評価|
|streaming|streaming.yaml|OBS、YouTube、配信|
|plugins|plugins.yaml|プラグイン有効化|

## 4. 画面構成

カテゴリ移動は左サイドバーへ一本化し、上部ヘッダーにカテゴリメニューを置かない。

```text
Header
├─ 画面タイトル
├─ Configuration Server接続状態
├─ 変更履歴
└─ 保存

Summary Row
├─ manifest / revision
├─ validation
├─ apply policy
└─ owner files

Workspace
├─ Category List
├─ Dynamic Form
└─ Compact Inspection Strip
   ├─ 未保存件数
   ├─ 検証結果
   ├─ 反映方法
   ├─ 保存処理説明
   └─ 構造化プレビュー
```

## 5. デザインコンセプト

### 5.1 他画面との統一

`YURA / INNER STATE`画面と同じく、上部は大きなカードとして囲わず、背景へ溶け込む細いヘッダーとして扱う。

- 左側に英語識別名と明朝体の画面タイトルを配置する
- 右側に接続状態、変更履歴、保存を配置する
- ヘッダー下端に細い境界線を置く
- 背景説明用の大きな装飾テキストは表示しない
- UIの情報階層はタイトル、状態、作業領域の順に明確化する

### 5.2 PC版の一画面配置

デスクトップでは主要機能を原則として一画面内へ収める。

- `main`は`100dvh`を基準に利用可能な高さを計算する
- Summaryを4枚の横一列へまとめる
- 左カテゴリ一覧は細い固定幅とし、一覧内だけスクロール可能にする
- 編集フォームは中央パネル内だけスクロール可能にする
- 未保存件数、検証結果、反映方法、保存処理は編集パネル下の横長ストリップへまとめる
- デスクトップでは`body`のスクロールを止め、作業領域内スクロールだけを使用する
- 1180px未満ではUIを通常の縦スクロールへ戻すが、背景はビューポートへ固定したままとする

### 5.3 ガラス表現

カードは白い不透明カードではなく、水中背景が透けるすりガラスとする。

- 青緑の半透明背景
- 18px前後の`backdrop-filter: blur()`
- 薄い水色の境界線
- 内側の弱いハイライト
- 黒に近い影で背景との奥行きを出す
- 入力欄はカードより少し暗くし、編集可能領域を明確化する

### 5.4 海中背景

明るい浅瀬の海底付近から、頭上の海面を見上げる構図とする。ただし写実的な写真表現ではなく、CSSグラデーションと単純な図形による抽象表現とする。

- 画面上部に揺れる海面と表面光を置く
- 海面から複数の光線を下方へ伸ばす
- 中景から遠景へ向かうほど暗い青緑へ変化させる
- 海底と海水の境界はハードな線にせず、グラデーションとぼかしで連続させる
- 海底には海草と岩を控えめに置く
- 背景装飾がフォームの可読性を妨げない濃度に抑える
- 背景レイヤーは`position: fixed`でビューポートに固定し、UIスクロールに追従させない
- `100dvh`と`translateZ(0)`を使用し、Safariでの固定背景の再描画を安定させる

### 5.5 魚影

魚影は単一方向へ流すのではなく、異なる高さ、速度、大きさ、方向で移動させる。

- 尾鰭は胴体の後方に配置する
- 左向きと右向きを混在させる
- 水平方向だけでなく斜め上・斜め下への移動を含める
- 近景は大きく濃く、遠景は小さく薄くする
- 同じタイミングで画面へ入らないよう負のanimation delayを使う
- `prefers-reduced-motion`では静止させる

### 5.6 縦長画面

スマートフォンではUIを一画面固定にせず、通常の縦スクロール構成へ切り替える。一方、海中背景はビューポートへ固定し、ページをスクロールしても動かさない。

- `body`は通常の縦スクロールを許可する
- 背景レイヤーは`position: fixed`と`100dvh`を維持する
- Summary、カテゴリ、編集、検査を縦に並べる
- フォーム内スクロールを解除する
- 560px以下ではフォームを1列にする
- iOS Safariで背景描画が一時的に外れても黒い空白を出さないよう、`body`自身にも背景色を持たせる

## 6. API

|Method|Path|用途|
|---|---|---|
|GET|`/health`|Renderヘルスチェック|
|GET|`/api/v1/config/manifest`|カテゴリとrevision取得|
|GET|`/api/v1/config/categories/{category}`|カテゴリ設定取得|
|POST|`/api/v1/config/validate`|未保存値の検証|
|PUT|`/api/v1/config/categories/{category}`|カテゴリ保存|
|GET|`/api/v1/config/history`|保存履歴取得|

## 7. 保存設計

1. UIが取得時のrevisionを送信する。
2. Serverが現在revisionと比較する。
3. 競合時はHTTP 409を返す。
4. 型・必須・範囲を検証する。
5. 一時ファイルへJSONを書き込む。
6. `Path.replace()`で原子的に置換する。
7. revisionを進め、変更前後を履歴へ記録する。

現実装は画面検証用のJSON repositoryである。実際のYAML owner fileへ接続する際は、`ConfigStore`をYAML repository実装へ差し替える。

## 8. Render

- Build: `python -m compileall gui/yura-config-console`
- Start: `python gui/yura-config-console/server.py`
- Health check: `/health`
- Python: `3.10.5`

Render無料Web Serviceのファイルシステムは永続保存用途にしない。今回の保存内容は画面動作確認用であり、再デプロイや再起動で失われる可能性がある。

## 9. 今回の実装範囲

- デスクトップ一画面レイアウト
- Inner State画面と統一したヘッダー
- 背景説明テキストの撤去
- すりガラスカード
- ぼかした海底と海水の境界
- 遠景ほど暗くなる水中背景
- 正しい尾鰭方向
- 複数方向へ移動する魚影
- ビューポートへ固定した海中背景
- UIスクロールと背景スクロールの分離
- 既存の設定取得、検証、保存、履歴機能の維持
- モバイル縦スクロール対応の維持

## 10. 次工程

- Python設定SchemaからUIメタデータを自動生成
- 実際のYAMLコメント保持方式を決定
- owner file単位のYAML round-trip repository
- secretsのマスクと明示的削除
- バックアップ復元
- Core reload planとの接続
- SSEによる外部変更通知
