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
├─ 上部に揺れる海面
├─ 海面から差し込む複数の光線
├─ 浅瀬特有の明るい青緑色の水中
├─ 水中の揺らぐ光模様
├─ 下部に白砂の海底
├─ 海草と小さな岩
├─ 遠景の小魚
└─ 海面へ昇る気泡

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

明るい浅瀬の海底付近から、頭上の海面を見上げる構図とする。

深海の暗さや海岸の遠景ではなく、海面から日光が十分に届く穏やかな海中を表現する。

- 画面上部に明るく揺れる海面を配置する
- 海面中央付近を最も明るくし、視線が自然に上へ向かうようにする
- 海面から下方へ複数の光線を放射状に伸ばす
- 水中全体は明るい水色から青緑のグラデーションとする
- 下部に白砂の浅い海底を配置する
- 海底には海草、小さな岩、砂紋を控えめに置く
- 遠景に小魚、右側に海面へ昇る気泡を配置する
- 背景の主役は海面光と水中の透明感とする

画面名の「入り江」は地上の港湾風景ではなく、静かで守られた浅瀬の水中空間として表現する。

### 5.2 UI配置

- 作業領域はデスクトップ幅の約3分の2に抑え、左下へ寄せる
- 上部中央から右側の海面光を常時見せる
- カテゴリ移動は左サイドバーだけで行う
- Summaryは高さを抑えた状態表示として配置する
- Inspectionは編集フォーム下の横長ストリップにする
- 背景の上へ過剰にカードを並べない

### 5.3 表現

- 水中の透明感を残す乳白色の半透明ガラスパネル
- 明朝体の画面タイトル
- 水色と青緑のアクセント
- 海底は淡い砂色
- 海草は彩度を抑えた緑
- 正常は青緑、注意は琥珀色、エラーは淡赤
- 320px以上で利用可能なレスポンシブ構成

### 5.4 アニメーション

- 海面をゆっくり上下に揺らす
- 海面光を緩やかに明滅させる
- 光線を小さく左右へ揺らす
- 水中の光模様を低速で移動させる
- 海草をゆっくり揺らす
- 小魚を遠景で横切らせる
- 気泡を海面へ上昇させる
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
- 浅瀬の海中背景
- 海面を見上げる光線構図
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
