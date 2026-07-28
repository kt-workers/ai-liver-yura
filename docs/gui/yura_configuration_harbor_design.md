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

```text
Header
├─ 画面タイトル
├─ カテゴリタブ
├─ Configuration Server接続状態
├─ 変更履歴
└─ 保存

Summary
├─ manifest / revision
├─ validation
└─ apply policy

Workspace
├─ Category List
├─ Dynamic Form
└─ Inspection Panel
   ├─ 未保存件数
   ├─ 検証結果
   ├─ 反映方法
   └─ 保存処理説明
```

## 5. デザイン

既存画面と同じ海モチーフを継承する。

- 深海色グラデーション
- 水面光と波の背景
- 半透明ガラスカード
- 明朝体の画面タイトル
- 水色アクセント
- 正常は水色・青緑、注意は琥珀色、エラーは淡赤
- 320px以上で利用可能なレスポンシブ構成

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

`render.yaml`へ`yura-configuration-harbor`を追加する。

- Branch: `feature/configuration-harbor`
- Build: `python -m compileall gui/yura-config-console`
- Start: `python gui/yura-config-console/server.py`
- Health check: `/health`
- Python: `3.10.5`

Render無料Web Serviceのファイルシステムは永続保存用途にしない。今回の保存内容は画面動作確認用であり、再デプロイや再起動で失われる可能性がある。実運用ではGit repositoryへの変更提案、永続ディスク、または外部DBへ保存先を変更する。

## 9. 今回の実装範囲

- スタンドアロン起動
- 10カテゴリ表示
- 動的フォーム
- 差分検知
- 入力検証
- revision競合検知
- 保存履歴
- 構造化プレビュー
- Render Blueprint定義

## 10. 次工程

- Python設定SchemaからUIメタデータを自動生成
- 実際のYAMLコメント保持方式を決定
- owner file単位のYAML round-trip repository
- secretsのマスクと明示的削除
- バックアップ復元
- Core reload planとの接続
- SSEによる外部変更通知
