# Yura Streaming Admin

配信準備、開始・終了、コメント状況、進行、診断、実行時設定をブラウザから操作する
管理画面です。`ai-liver-yura` モノレポの `gui/` 配下で、Streaming Subsystem Admin APIとは
別プロセスとして動作します。Coreの起動は任意です。

## 起動

先にリポジトリ直下でStreaming Subsystem Admin APIを起動します。

```bash
.venv/bin/python -m subsystems.streaming.admin_api --host 127.0.0.1 --port 8781
```

別のターミナルで管理画面のローカルサーバーを起動します。

```bash
.venv/bin/python gui/yura-streaming-admin/server.py
```

ブラウザで <http://127.0.0.1:8780> を開きます。待受ポートは `--port` で変更できます。

## 通信

- Web画面: HTTP/SSE `127.0.0.1:8780`
- Streaming Subsystem Admin API: HTTP/SSE `127.0.0.1:8781`

ブラウザはStreaming Adminのローカルサーバーとのみ通信します。Subsystem APIのトークンは
ブラウザへ渡しません。接続設定には `STREAMING_SUBSYSTEM_ADMIN_API_URL`、
`STREAMING_SUBSYSTEM_ADMIN_API_TOKEN`、`STREAMING_SUBSYSTEM_ADMIN_API_TIMEOUT`、
`STREAMING_SUBSYSTEM_ADMIN_OPERATOR` を使用します。旧`AI_LIVER_ADMIN_*`はKまでfallbackとして
利用できます。Core停止時はcontent execution／comment decisionが`disconnected`表示になります。

構成確認だけを行う場合:

```bash
.venv/bin/python -m subsystems.streaming.admin_api --check
```

接続できない場合は8781の起動状態、新旧URL環境変数の優先順位、Bearer tokenの一致を確認します。

依存関係だけを個別に導入する場合は次を実行します。

```bash
.venv/bin/python -m pip install -r gui/yura-streaming-admin/requirements.txt
```
