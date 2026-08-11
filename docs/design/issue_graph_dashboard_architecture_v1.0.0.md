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

### 6.1 Canvas / hierarchical component packing

2026-08-12 の実画面確認で、depth seedからforce relaxationする自由配置は親子の読み順を崩し、線の追跡も悪化したため採用しない。

一方で、全Issueを同一のdepth列へ強制する単純な2列・3列表示にも戻さない。**親子ツリーごとに読みやすい階層配置を作り、独立したツリーを2次元へパッキングする**。

配置方針:

- parent/subIssue relationship から親子forestを作る
- 各rootごとに独立したtree componentを作る
- 子を持つnodeは、自分のdescendant blockの縦中央へ配置する
- sibling subtreeは必要な縦幅を先に計算し、node同士が重ならない間隔で積む
- 同一tree内では親から子へ左→右へ進むため、親子関係の読み順を保証する
- depthはtree内の相対X距離にのみ利用し、全rootを同じglobal列へ揃えない
- disconnected root / 管理Issue / 親なしWork Issueは、それぞれ独立componentとして扱う
- componentごとの実boundsを計算し、canvas上へrow packingして2次元に配置する
- component間にはedge routing用の余白を確保する
- Issue番号由来jitter、force relaxation、ランダム位置補正は使用しない
- 同じデータ・filter状態では毎回同じ位置になるdeterministic layoutとする

この方式では、単一tree内に自然な階層性は残るが、画面全体を「2列に揃える」制約は存在しない。独立した枝・rootは上下左右へパッキングされる。

共通操作:

- 親子: 実線矢印
- 依存: 破線矢印
- mouse/touch drag で pan
- wheel / control で zoom
- Reset view
- 親 node ごとの collapse

### 6.2 Parent edge routing / branch bus

親子線については汎用A*へ任せず、tree layoutそのものと整合する専用routingを使う。

親nodeと子nodeの間にはnodeが存在しない水平gapを保証するため、そのgap内へbranch busを置く。

```text
parent ─────┐
            ├──── child A
            ├──── child B
            └──── child C
```

方針:

- parent右辺中央をsource portとする
- child左辺中央をtarget portとする
- parentと次depthの水平gap内へ専用bus Xを置く
- `source → bus → target Y → target` の直交線で接続する
- siblingへの線は同じbusを共有してtree trunkとして読めるようにする
- busはnodeが配置されないdepth gap内に限定するため、別nodeの背面を通らない
- parentとchildの位置関係が壊れた異常データだけdependency routingへfallbackする

これにより親子線は「可能な限り回避」ではなく、**通常のtreeでは構造上nodeを横切らない**ことを目標とする。

### 6.3 Dependency edge routing / measured obstacle routing

依存線は親子treeをまたぐ可能性があるため、障害物回避routingを使用する。ただし旧実装のように定数だけでnode rectangleを推測しない。

方針:

- node DOMを先に配置・描画する
- `offsetLeft / offsetTop / offsetWidth / offsetHeight` から実際のnode rectangleを取得する
- 実rectangleにclearanceを加えた領域をobstacleとする
- source/targetの左右・上下port候補を作る
- obstacleの左右端・上下端とcanvas外周余白からorthogonal visibility latticeを作る
- lattice上でManhattan距離 + bend penaltyを用いた経路探索を行う
- source/target以外のnode rectangleを横切るsegmentは候補から除外する
- 最短の有効routeを選択し、不要な同一直線上の点を削除する
- 角は小さく丸めるが、線そのものは直交routingを維持する
- 経路が求まらない場合はcanvas外周laneを使うfallbackを行い、nodeを突っ切るBezier fallbackは使用しない

### 6.4 Selected node edge focus

nodeをclickして詳細panelを表示した場合、選択Issueを起点とするedgeを強調する。

- `edge.source === selected issue number` の親子・依存edgeをforegroundとして描画する
- foreground edgeは通常より高いopacity・太いstrokeとする
- foreground edgeのarrow headも同じ視覚強度にする
- 選択中はその他のedgeを低opacityにして背景化する
- 強調対象は「選択Issueから伸びる線」とし、選択Issueへ入ってくるedgeは背景edgeとする
- 選択解除時は通常表示へ戻す
- edge kindの意味は維持し、親子は実線、依存は破線のまま強調する

### 6.5 Node

常時表示:

- Issue number
- title
- Status
- Issueレベル
- Closedの場合はClosedバッジ

Status は色だけに依存せず text badge を必ず表示する。

### 6.6 Detail panel

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

### 6.7 Issue state display mode

ヘッダーへ `Closedも表示` スイッチを置く。

- 初期値はOFFで、Open Issueだけを表示する
- ONにした場合は `/api/graph?include_closed=true` を再取得してClosed Issueもグラフへ含める
- OFFへ戻した場合は `/api/graph?include_closed=false` を再取得する
- Closed Issueを常時先読みしてブラウザだけで非表示にする方式にはしない
- switch切替時も検索、Status filter、pan/zoom等の基本機能は維持する
- OFFへ切り替えた結果、選択中のClosed Issueが取得対象外になった場合はselection/detailを解除する
- Issue `state` とProjects v2 `Status` は別概念として扱い、混同しない

### 6.8 Filter

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
- free-layout relaxationが撤去されている
- tree component packingが存在する
- parent edgeにbranch bus routingが存在する
- dependency edgeがDOM実測rectangleを障害物としてroutingする
- nodeを突っ切るBezier fallbackを使用しない
- selected issueをsourceとするedge focusが存在する
- 親子と依存の形状差を維持する
- `Closedも表示` switchがserver-side取得条件を切り替える

実画面:

- 3階層以上の親子表示
- 親子の読み順が崩れない
- 全rootが同じglobal列へ強制されず、tree componentが2次元に配置される
- node同士が重ならない
- parent edgeが別nodeの背面を通らない
- dependency edgeも表示nodeを横切らない
- 選択Issueから伸びるedgeが強調され、その他のedgeが背景化する
- `Closedも表示` OFFでOpenのみ、ONでClosedを含めて表示される
- In progress / Verification / Blocked 視認性
- pan / zoom / reset / collapse / search / filter
- local 起動
- Render Blueprint sync / deploy
