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

Scenic Background
├─ 空と雲
├─ 数羽のカモメ
├─ 遠景の岬
├─ 左側の森・草地
├─ 地平線まで続く砂浜と白波
├─ 右側へ広がる海
└─ 海岸線途中の小さな船着場と小舟

Workspace（左下へ寄せる）
├─ Summary Strip
│  ├─ manifest / revision
│  ├─ validation
│  └─ apply policy
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

### 5.1 情景

「港湾施設」ではなく、人の少ない海岸に小さな船着場がある穏やかな入り江を表現する。

視点は浜辺に立つ近景ではなく、高台または低空から長い海岸線を見下ろす遠景とする。

- 左側に森と草地
- 中央に奥へ細く収束する砂浜
- 砂浜と平行に複数の白波
- 右側に広く開けた海
- 地平線と空を広く確保
- 船着場と小舟は中遠景の小さな目印
- カモメは3羽程度を異なる大きさと速度で表示

背景全体の主役は船着場ではなく、地平線まで続く海岸線と海の広がりである。

### 5.2 UI配置

- 作業領域はデスクトップ幅の約3分の2に抑え、左下へ寄せる
- 中央から右側の砂浜、白波、海、地平線を常時見せる
- カテゴリ移動は左サイドバーだけで行う
- Summaryは高さを抑えた状態表示として配置する
- Inspectionは編集フォーム下の横長ストリップにする
- 背景の上へ過剰にカードを並べない

### 5.3 表現

- 乳白色の半透明ガラスパネル
- 明朝体の画面タイトル
- 海水色と青緑のアクセント
- 森は彩度を抑えた緑
- 砂浜は薄い黄土色
- 正常は青緑、注意は琥珀色、エラーは淡赤
- 320px以上で利用可能なレスポンシブ構成

### 5.4 アニメーション

- 海面模様を低速で横移動する
- 白波をわずかに前後させる
- 小舟を小さく上下させる
- カモメをゆっくり移動させる
- `prefers-reduced-motion`ではすべて静止させる

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
- 遠景海岸背景
- サイドバーへのカテゴリナビゲーション一本化
- 背景を残す左寄せワークスペース
- Render Blueprint定義

## 10. 次工程

- Python設定SchemaからUIメタデータを自動生成
- 実際のYAMLコメント保持方式を決定
- owner file単位のYAML round-trip repository
- secretsのマスクと明示的削除
- バックアップ復元
- Core reload planとの接続
- SSEによる外部変更通知
