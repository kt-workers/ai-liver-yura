# Issue Graph Dashboard Architecture v1.0.0

## 1. 目的

GitHub Issue の親子関係、依存関係、GitHub Projects v2 の進行状態を、一覧ではなくノードグラフとして把握できる read-only 管理画面を提供する。

対象は初期値として `ktan514/ai-liver-yura` と GitHub Projects v2 `ktan514 / project 6` とするが、環境変数で差し替え可能にする。

## 2. 責務境界

```text
GitHub Repository Issues
  - Issue title/body/state/url
  - parent/subIssues
        +
GitHub Projects v2
  - Status
  - Issueレベル
  - 作業種別
  - 領域
  - 優先度
  - 工程
  - Start date / Target date
        ↓
IssueGraphService
  - 正規化
  - Compatibility relation extraction
  - Project field join
        ↓
IssueGraph Read Model
        ↓
FastAPI read-only endpoint
        ↓
Browser Graph Renderer
```

GUI は Issue/Project を更新しない。Core Runtime、Body、Character、Memory 等の製品ランタイムにも依存しない。

## 3. 正本とCompatibility

### 3.1 親子関係

正本は GitHub の Issue `parent` / `subIssues` relationship とする。

Issue 本文に残っている `Parent: #123` は、正式な relationship が未設定の既存 Issue を可視化するための Compatibility fallback としてのみ利用する。

### 3.2 依存関係

GitHub の Issue dependency 専用 relationship が本プロジェクトで一意に運用されていないため、初期版では Issue 本文の `Depends on:` / `依存:` を補助情報として抽出する。

依存エッジは親子関係と混同せず破線で描画する。

### 3.3 Project 状態

GitHub Projects v2 を正本とし、Project item の field value を Issue number へ join する。

初期版で取得する field:

- Status
- Issueレベル
- 作業種別
- 領域
- 優先度
- 工程
- Start date
- Target date

Project に未登録の Issue は field を未設定として扱う。

## 4. GitHub API

### 4.1 認証あり

`GITHUB_TOKEN` が存在する場合、GitHub GraphQL API を使用する。

1. Repository の Open Issues を pagination して取得
2. `parent` / `subIssues` を取得
3. ProjectV2 items を pagination して取得
4. 既知 Project fields を `fieldValueByName` で取得
5. Issue number で結合
6. Project itemを主集合とし、親・子・依存関係で必要なOpen Issueだけをcontextとして追加

Token は server-side のみで使用し、browser response、HTML、log へ含めない。

### 4.2 認証なし / Project API failure

public repository では REST Open Issues API を利用し、Issue 本文から Compatibility parent/dependency を抽出する degraded mode へ移行する。

この場合、Project Status 等は推測せず `null` とし、API response の diagnostics で degraded reason を通知する。

## 5. Read Model

```json
{
  "repository": "ktan514/ai-liver-yura",
  "project": {"owner": "ktan514", "number": 6},
  "degraded": false,
  "diagnostics": [],
  "nodes": [
    {
      "number": 225,
      "title": "...",
      "state": "OPEN",
      "status": "In progress",
      "issue_level": "Parent",
      "parent_number": null,
      "child_numbers": [226, 227],
      "dependency_numbers": [],
      "related_pr_numbers": []
    }
  ],
  "edges": [
    {"source": 225, "target": 226, "kind": "parent"},
    {"source": 226, "target": 227, "kind": "dependency"}
  ]
}
```

親子 edge は `parent -> child`。依存 edge は `prerequisite -> dependent` とし、作業の流れと同じ向きにする。

## 6. Browser UI

### 6.1 Canvas

- 左から右へ depth ごとに配置
- 親子: 実線矢印
- 依存: 破線矢印
- mouse/touch drag で pan
- wheel / control で zoom
- Reset view
- 親 node ごとの collapse

### 6.2 Node

常時表示:

- Issue number
- title
- Status
- Issueレベル

Status は色だけに依存せず text badge を必ず表示する。

### 6.3 Detail panel

node click で以下を表示する。

- Issue title / number / URL
- Issue state
- Status
- Issueレベル
- 作業種別
- 領域
- 優先度
- 工程
- Start / Target date
- parent / children / dependencies
- related PR
- body summary

### 6.4 Filter

- text search: Issue number / title
- Status filter
- active filter: In progress / Review / Verification / Blocked

filter 対象の子を持つ ancestor は context 維持のため表示する。

## 7. 設定

| 環境変数 | default | 用途 |
|---|---|---|
| `GITHUB_TOKEN` | none | GitHub GraphQL / authenticated REST |
| `YURA_ISSUE_GRAPH_OWNER` | `ktan514` | repository/project owner |
| `YURA_ISSUE_GRAPH_REPOSITORY` | `ai-liver-yura` | repository name |
| `YURA_ISSUE_GRAPH_PROJECT_NUMBER` | `6` | Projects v2 number |
| `YURA_ISSUE_GRAPH_HOST` | `127.0.0.1` | local bind host |
| `PORT` | `8000` | bind port; Render 互換 |

## 8. 起動

### Local

```bash
export GITHUB_TOKEN=...
python -m gui.yura_issue_graph
```

### Render / Blueprint

リポジトリ直下の既存 `render.yaml` をRender Blueprintの正本とする。

既存のRenderサービス定義は維持し、その中へ `yura-issue-graph` を追加する。Issue Graph専用に別のBlueprintファイルを作らない。

`yura-issue-graph` の設定:

```yaml
- type: web
  name: yura-issue-graph
  runtime: python
  plan: free
  branch: feature/issue-graph-dashboard
  buildCommand: pip install -r requirements.txt
  startCommand: python -m uvicorn gui.yura_issue_graph.server:app --host 0.0.0.0 --port $PORT
  healthCheckPath: /api/health
  autoDeployTrigger: commit
```

環境変数はBlueprintで以下を管理する。

- `GITHUB_TOKEN`: `sync: false` とし、値をGitへ保存しない
- `YURA_ISSUE_GRAPH_OWNER=ktan514`
- `YURA_ISSUE_GRAPH_REPOSITORY=ai-liver-yura`
- `YURA_ISSUE_GRAPH_PROJECT_NUMBER=6`
- `PYTHON_VERSION=3.10.5`

Verification中はDraft PRのhead `feature/issue-graph-dashboard` を明示的に追跡する。ユーザー確認・merge後に常設運用する場合は、Render serviceの追跡branchを正本統合branchへ切り替える。検証用branch削除後も古いbranchを参照し続けないこと。

## 9. セキュリティ

- read-only
- token を HTML/JSON/log へ露出しない
- arbitrary GitHub URL を browser から server へ渡させない
- repository/project target は server environment で固定
- GitHub error body に token が含まれる可能性を考慮し、生の request header を exception message 化しない
- `render.yaml` に `GITHUB_TOKEN` の実値を書かず、`sync: false` でRender側Secret入力を要求する

## 10. Verification

自動:

- config parsing
- Parent/Depends on/PR compatibility extraction
- project field normalization
- graph edge generation
- Project scope + relation context保持
- token absence degraded mode
- FastAPI route existence / health response
- `render.yaml` に `yura-issue-graph` が存在する
- Blueprint上でtokenが `sync: false` である
- Blueprintのhealth checkが `/api/health` を参照する

実画面:

- 3階層以上の親子表示
- In progress / Verification / Blocked 視認性
- pan / zoom / reset
- collapse
- node click detail
- search / filter
- local 起動
- Render Blueprint sync / deploy
