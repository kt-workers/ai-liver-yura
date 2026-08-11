# Yura Issue Graph

GitHub Issueの親子関係・依存関係と、GitHub Projects v2「プロジェクトゆら」の進行状態をノードグラフで表示するread-only管理GUIです。

## 機能

- 親Issue → 子Issueを実線矢印で表示
- `Depends on:` / `依存:` を破線矢印で表示
- Status / Issueレベルをノードへ表示
- In progress / Review / Verification / Blocked等のStatus filter
- Issue番号・タイトル検索
- pan / zoom / 全体表示
- 親Issue単位の折りたたみ
- node clickでProject field、親子、依存、関連PR、Issue概要を表示
- GitHub token未設定時はpublic Issueだけを使うdegraded mode

## ローカル起動

repository rootで実行します。

```bash
export GITHUB_TOKEN=YOUR_TOKEN
python -m gui.yura_issue_graph
```

既定URL:

```text
http://127.0.0.1:8000
```

Projects v2のStatus等を表示するには、`GITHUB_TOKEN`に対象Projectを読み取れる権限が必要です。Tokenはブラウザへ送信されません。

### 設定

```bash
export YURA_ISSUE_GRAPH_OWNER=ktan514
export YURA_ISSUE_GRAPH_REPOSITORY=ai-liver-yura
export YURA_ISSUE_GRAPH_PROJECT_NUMBER=6
export YURA_ISSUE_GRAPH_HOST=127.0.0.1
export PORT=8000
```

## Render

このrepositoryでは既存のルート `render.yaml` をBlueprintの正本として使用します。Issue Graph用に別サービスを手入力する必要はありません。

Blueprint内のサービス名:

```text
yura-issue-graph
```

定義済み設定:

```text
Runtime: Python
Plan: Free
Branch: feature/issue-graph-dashboard
Build: pip install -r requirements.txt
Start: python -m uvicorn gui.yura_issue_graph.server:app --host 0.0.0.0 --port $PORT
Health Check: /api/health
Auto Deploy: commit
```

### Blueprintから作成

Render DashboardでBlueprintを新規作成し、このrepositoryの `render.yaml` を指定します。

`GITHUB_TOKEN` は `render.yaml` で `sync: false` としているため、Blueprint初回同期時にRender側で値を入力します。Tokenの実値はGitへ保存しません。

その他はBlueprintに定義済みです。

```text
YURA_ISSUE_GRAPH_OWNER=ktan514
YURA_ISSUE_GRAPH_REPOSITORY=ai-liver-yura
YURA_ISSUE_GRAPH_PROJECT_NUMBER=6
PYTHON_VERSION=3.10.5
```

Verification中は `feature/issue-graph-dashboard` を追跡します。PRを `develop` へ統合して常設運用する場合は、検証用branchを削除する前にRender serviceの追跡branchを統合先へ切り替えます。

## API

```text
GET /api/health
GET /api/graph
```

`/api/graph`はtokenを返しません。

## データ正本

- Issue hierarchy: GitHub parent/subIssues
- Project state: GitHub Projects v2
- Compatibility only: Issue本文の`Parent:` / `Depends on:`

詳細設計は `docs/design/issue_graph_dashboard_architecture_v1.0.0.md` を参照してください。
