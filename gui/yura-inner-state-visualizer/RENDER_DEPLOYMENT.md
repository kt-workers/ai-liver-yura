# Yura Inner State Visualizer Render公開設計

## 1. 目的

`gui/yura-inner-state-visualizer` の画面を、GitHubからRenderへ自動デプロイし、インターネット経由で確認できるようにする。

## 2. 対象範囲

今回の公開対象は画面システムの確認環境である。

- HTML / CSS / JavaScriptの配信
- SSEによる状態スナップショット配信
- クリック、ダブルクリック、長押し、ドラッグの画面刺激
- Renderのヘルスチェック
- GitHubコミットを契機とした自動デプロイ

AI Core、OBS、VOICEVOX、Live2D、ローカルUDP通信をクラウドへ移すものではない。

## 3. 構成

```text
Browser
  ├─ GET /                 静的画面
  ├─ GET /events           状態SSE
  ├─ GET /state            最新状態・ヘルスチェック
  └─ POST /api/stimuli     画面刺激
          ↓
Render Web Service
  ├─ render_server.py
  ├─ server.py
  └─ InteractiveStateSimulator
```

RenderではローカルCoreからのUDPを受信できないため、`render_server.py`が`InteractiveStateSimulator`を同一プロセス内で起動する。画面刺激もUDPへ転送せず、シミュレーターへ直接渡す。

ローカル運用では従来どおり`server.py`とUDP経路を使用する。Render対応によってローカル通信仕様は変更しない。

## 4. 実行モード

### ローカル実Core接続

```bash
python gui/yura-inner-state-visualizer/server.py
```

- HTTP: `127.0.0.1:8765`
- Core状態入力: UDP `127.0.0.1:8766`
- Core刺激出力: UDP `127.0.0.1:8771`

### Render公開確認

```bash
PORT=10000 python gui/yura-inner-state-visualizer/render_server.py
```

- HTTP: `0.0.0.0:${PORT}`
- 状態入力: 同一プロセス内シミュレーター
- 刺激入力: HTTPから同一プロセス内シミュレーターへ直接入力

## 5. Render Blueprint

リポジトリルートの`render.yaml`を使用する。

- Runtime: Python
- Python: 3.10.5
- Plan: Free
- Build: Pythonソースのコンパイル検査
- Start: `render_server.py`
- Health check: `/state`
- Auto deploy: GitHub commit

## 6. デプロイ手順

1. RenderへGitHubアカウントを接続する。
2. **New +** → **Blueprint** を選択する。
3. `ktan514/ai-liver-yura`を選択する。
4. Branchに`deploy/render-inner-state-visualizer`を指定する。
5. `render.yaml`を検出させてサービスを作成する。
6. デプロイ完了後、Renderが発行したURLを開く。
7. `/state`がJSONを返し、画面上の粒子が表示されることを確認する。
8. 画面クリックなどで粒子反応と`POST /api/stimuli`の成功を確認する。

## 7. 制約

- Render Freeでは無通信時にスリープするため、初回表示に時間がかかる場合がある。
- 公開版はデモ状態であり、ローカルで動作するゆら本体の実状態ではない。
- Renderから家庭内LANのUDPポートへ直接接続しない。
- 実Core連携を公開する場合は、認証付きHTTPSの状態中継APIを別途設計する。

## 8. 将来拡張

実Coreの状態を公開画面へ反映する場合は、次の構成へ移行する。

```text
Local Core
  ↓ 認証付きHTTPS送信
Cloud State Ingress API
  ↓
StateHub
  ↓ SSE
Browser
```

この場合も、ブラウザからCoreへ任意命令を直接送らず、許可された刺激だけを認証・検証・レート制限した上で中継する。
