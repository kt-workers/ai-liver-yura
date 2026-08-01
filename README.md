# AI Liver Yura

AI Liver「ゆら」の本体とブラウザ画面をまとめたモノレポです。

## 構成

```text
ai-liver-yura/
├── app/                                 # AI Liver本体
├── config/
├── docker/                              # ローカル開発用コンテナ初期化
├── docs/
├── tests/
└── gui/
    ├── yura-web-conversation/           # 会話画面
    ├── yura-inner-state-visualizer/     # 内部状態ビジュアライザー
    └── yura-streaming-admin/            # 配信管理画面
```

各コンポーネントの詳細は、それぞれのREADMEを参照してください。

- [Web Conversation](gui/yura-web-conversation/README.md)
- [Inner State Visualizer](gui/yura-inner-state-visualizer/README.md)
- [Streaming Admin](gui/yura-streaming-admin/README.md)

## 起動

ターミナルを分け、必要なGUIと本体を起動します。

```bash
# 会話画面
cd gui/yura-web-conversation
python3 server.py

# 内部状態ビジュアライザー
cd gui/yura-inner-state-visualizer
python3 server.py

# 配信管理画面
.venv/bin/python -m subsystems.streaming.admin_api --port 8781
.venv/bin/python gui/yura-streaming-admin/server.py

# AI Liver本体（リポジトリ直下）
.venv/bin/python -m app
```

CoreからStreaming Subsystemへ接続する場合は、Subsystem起動後に
`YURA_STREAMING_SUBSYSTEM_API_URL=http://127.0.0.1:8781`を設定してCoreを起動します。
未設定または接続不能でもCoreはNull／degraded状態で単独動作します。YouTube／OBS設定と
SecretはCoreではなくStreaming Subsystem側で管理します。

Subsystem分離工程A〜K（15/15）は完了しています。旧Streaming Plugin／Core側
YouTube・OBS Adapter／専用Portは削除済みです。

会話画面は <http://127.0.0.1:8770>、内部状態ビジュアライザーは
<http://127.0.0.1:8765>、配信管理画面は <http://127.0.0.1:8780> で開けます。

## PostgreSQL（Docker Compose）

Topic MemoryはPostgreSQLとpgvectorを使用します。リポジトリ直下の`compose.yaml`で、
PostgreSQL 16とpgvectorを含むローカル開発環境を起動できます。

### 1. 環境変数を用意する

```bash
cp .env.example .env
```

`.env`はGit管理対象外です。ローカルネットワーク外へ公開する場合は、
`POSTGRES_PASSWORD`を必ず変更してください。パスワードを変更した場合は、
`AI_LIVER_DATABASE_URL`内のパスワードも同じ値にします。

### 2. 以前の`docker run`コンテナから移行する場合

すでに`postgres-m4`を手動起動している場合、コンテナ名が競合します。
次の操作で古いコンテナだけを削除してください。

```bash
docker stop postgres-m4
docker rm postgres-m4
```

データは名前付きボリューム`ai_liver_postgres_data`に残るため、
`docker volume rm ai_liver_postgres_data`を実行しない限り引き継がれます。

### 3. PostgreSQLを起動する

```bash
docker compose up -d postgres
docker compose ps
docker compose logs -f postgres
```

`docker compose ps`で`postgres`が`healthy`になれば起動完了です。
ログ表示は`Ctrl+C`で終了してもコンテナは停止しません。

### 4. アプリ用の環境変数を読み込む

Docker Composeは`.env`を自動的に読み込みますが、ホスト上で動かすPythonにも
`AI_LIVER_DATABASE_URL`を渡す必要があります。

```bash
set -a
source .env
set +a
```

### 5. Topic Memory用テーブルを初期化する

```bash
.venv/bin/python scripts/init_topic_memory_db.py
```

この処理はpgvector拡張、`topic_memories`テーブル、必要なインデックスを
冪等に作成します。

### 起動・停止・削除

```bash
# 停止
docker compose stop postgres

# 再開
docker compose start postgres

# コンテナとネットワークを削除（DBデータは保持）
docker compose down

# DBデータを含めて完全削除
# 注意: Topic Memoryの全データが消えます
docker compose down -v
```

### 接続設定

既定値は次のとおりです。

```text
Host: 127.0.0.1
Port: 5432
Database: ai_liver
User: ai_liver
Container: postgres-m4
Volume: ai_liver_postgres_data
DSN environment variable: AI_LIVER_DATABASE_URL
```

ホスト側ですでに5432番ポートが使われている場合は、`.env`の
`POSTGRES_PORT`と`AI_LIVER_DATABASE_URL`のポートを同じ番号へ変更してください。

## VoiceVox

`VoiceVox Engine`を起動して使用します。

```bash
cd VoiceVoxEngineのパス
./run
```
