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

1. Repository Issues を pagination して取得する。既定は `OPEN` のみ、`include_closed=true` の場合は `OPEN` と `CLOSED` の両方を取得する
2. `parent` / `subIssues` を取得
3. ProjectV2 items を pagination して取得
4. 既知 Project fields を `fieldValueByName` で取得
5. Issue number で結合
6. Project itemを主集合とし、親・子・依存関係で必要な取得対象Issueだけをcontextとして追加

Token は server-side のみで使用し、browser response、HTML、log へ含めない。

### 4.2 認証なし / Project API failure

public repository では REST Issues API を利用し、Issue 本文から Compatibility parent/dependency を抽出する degraded mode へ移行する。

RESTでも既定は `state=open`、`include_closed=true` の場合は `state=all` を使用する。

この場合、Project Status 等は推測せず `null` とし、API response の diagnostics で degraded reason を通知する。

## 5. Read Model

```json
{
  "repository": "ktan514/ai-liver-yura",
  "project": {"owner": "ktan514", "number": 6},
  "include_closed": false,
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

### 6.1 Canvas / free layout

ノードを depth ごとの固定列へ並べる方式は使用しない。親子階層は読みやすさのため左から右へ進む傾向だけを維持し、最終位置は関係性と空き領域から自由配置する。

配置方針:

- parent/subIssue から depth を計算するが、depth は初期位置のseedにのみ使う
- 初期位置にはIssue番号由来の決定的なX/Yずらしを加え、同一depthのノードを完全な縦一列に揃えない
- seed後に複数回のlayout relaxationを行う
- node rectangle同士が近すぎる場合は衝突回避力で離す
- 親子edgeには左→右の方向制約と適度な距離を与えるが、固定X座標へsnapしない
- dependency edgeは親子より弱い引力だけを与え、遠すぎる関係を近づける
- 多数node時は反復回数を減らし、ブラウザ負荷を上限化する
- relaxation後に全nodeを正座標へnormalizeし、world sizeを実配置boundsから計算する
- disconnected rootも同一列へ強制せず、複数の開始位置へstaggerして配置する

目標は、**列の整然さよりも、ノード同士の重なり回避・線の短縮・枝分かれの追いやすさを優先すること**である。

共通操作:

- 親子: 実線矢印
- 依存: 破線矢印
- mouse/touch drag で pan
- wheel / control で zoom
- Reset view
- 親 node ごとの collapse

### 6.2 Edge routing / node avoidance

Issue数が増えた状態で単純なBezier曲線をsource右端からtarget左端へ引くと、途中の別Issue nodeの背面を通過して線が見えなくなる。このため、nodeを障害物として扱う経路計算をBrowser側で行う。

方針:

- 各表示nodeの矩形を、見た目の矩形より数px広げたobstacle rectangleとして登録する
- source/target node自身はobstacle判定から除外する
- sourceは原則右側port、targetは原則左側portから接続する
- source/targetの直近に短いlead segmentを設け、node border直後から経路探索を開始する
- obstacleを通過しない水平・垂直segmentを候補として、Manhattan/A*経路探索で迂回路を求める
- 探索gridはnode配置の余白より細かい固定stepを利用し、描画負荷を抑える
- 取得した経路は不要な同一直線上の中間点を削除して簡略化する
- 描画時は折れ線を基本とし、角は小さなradiusで丸めて方向を追いやすくする
- 親子=実線、依存=破線の形状差は維持する
- 経路探索が失敗した場合のみ、従来のBezier曲線へfallbackする

目標は「全線交差ゼロ」ではなく、**edgeがIssue nodeの裏へ隠れて接続先を追えなくなる状態を原則回避すること**である。edge同士の交差・重なりは許容するが、将来はedge lane分離で追加改善できる。

### 6.3 Selected node edge focus

nodeをclickして詳細panelを表示した場合、選択Issueを起点とするedgeを強調する。

- `edge.source === selected issue number` の親子・依存edgeをforegroundとして描画する
- foreground edgeは通常より高いopacity・太いstrokeとする
- foreground edgeのarrow headも同じ視覚強度にする
- 選択中はその他のedgeを低opacityにして背景化する
- 強調対象は「選択Issueから伸びる線」とし、選択Issueへ入ってくるedgeは通常の背景edgeとして扱う
- 選択解除時は通常表示へ戻す
- edge kindの意味は維持し、親子は実線、依存は破線のまま強調する

これにより、詳細を見ているIssueから「次にどのIssueへ枝分かれしているか」を視線で追えるようにする。

### 6.4 Node

常時表示:

- Issue number
- title
- Status
- Issueレベル
- Closedの場合はClosedバッジ

Status は色だけに依存せず text badge を必ず表示する。

### 6.5 Detail panel

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

### 6.6 Issue state display mode

ヘッダーへ `Closedも表示` スイッチを置く。

- 初期値はOFFで、Open Issueだけを表示する
- ONにした場合は `/api/graph?include_closed=true` を再取得してClosed Issueもグラフへ含める
- OFFへ戻した場合は `/api/graph?include_closed=false` を再取得する
- Closed Issueを常時先読みしてブラウザだけで非表示にする方式にはしない。通常時のAPI取得量とレイアウト負荷を抑えるため、取得対象自体をserver-sideで切り替える
- switch切替時も検索、Status filter、pan/zoom等の基本機能は維持する
- OFFへ切り替えた結果、選択中のClosed Issueが取得対象外になった場合はselection/detailを解除する
- Issue `state` とProjects v2 `Status` は別概念として扱い、混同しない

### 6.7 Filter

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
- Open-only / include-closed のGraphQL・REST取得条件
- `/api/graph?include_closed=true|false` のroute契約
- FastAPI route existence / health response
- `render.yaml` に `yura-issue-graph` が存在する
- Blueprint上でtokenが `sync: false` である
- Blueprintのhealth checkが `/api/health` を参照する
- Browser実装にfree-layout relaxationが存在し、固定列へsnapしない
- Browser実装にnode obstacle routingとBezier fallbackが存在する
- selected issueをsourceとするedge focusが存在する
- 親子と依存の形状差を維持する
- `Closedも表示` switchがserver-side取得条件を切り替える

実画面:

- 3階層以上の親子表示
- 同一depthでもノードが固定列に縛られず、関係性と空きに応じて配置される
- node同士が重ならず、親子の左→右方向は概ね維持される
- In progress / Verification / Blocked 視認性
- pan / zoom / reset
- collapse
- node click detail
- edgeが途中のIssue nodeを原則回避して描画される
- 選択Issueから伸びるedgeが強調され、その他のedgeが背景化する
- `Closedも表示` OFFでOpenのみ、ONでClosedを含めて表示される
- search / filter
- local 起動
- Render Blueprint sync / deploy