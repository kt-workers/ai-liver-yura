# Yura Issue Graph

GitHub Issueの親子関係・依存関係と、GitHub Projects v2「プロジェクトゆら」の進行状態をノードグラフで表示するread-only管理GUIです。

## 機能

- 親Issue → 子Issueを実線矢印で表示
- 親子treeごとに階層配置し、tree単位のグループ枠で視覚的に分離
- 親子関係を持たないIssueは `親子関係なし` エリアへ分離してcompact grid表示
- 親子線はdepth間の空き領域へbranch busを置き、通常treeで別ノードを横切らないように描画
- 依存線は初期状態では全表示しない。node選択時はそのIssueへ入る/出る直接依存だけ表示
- `依存線を全表示` switchをONにした場合のみ全dependency edgeを表示
- dependency routingは描画済みDOMノードの実サイズを障害物として測定し、直交経路探索で迂回
- ノードを突っ切るBezier fallbackは使用しない
- node選択時、選択Issue・直接parent/child/dependency以外のnodeを背景化
- 初期viewportは全体fitで文字が小さくなりすぎる場合、読める倍率を維持してactive Issue付近から表示
- `全体表示` buttonでは全graphをfitして俯瞰可能
- 初期表示はOpen Issueのみ。`Closedも表示` switchでClosed Issueを含む表示へ切替
- Closed表示切替時はserver-sideのGitHub取得条件自体を切り替え、通常時にClosed Issueを先読みしない
- Closed Issueには`Closed`バッジを追加し、Projects v2 Statusとは別情報として表示
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

## Render / Blueprint

Renderではリポジトリ直下の既存 `render.yaml` をBlueprintの正本として利用します。

Issue Graphは次のWeb Serviceとして定義済みです。

```text
yura-issue-graph
```

Blueprintではbuild/start/health check/Free plan/Auto Deployを定義し、`GITHUB_TOKEN`だけを `sync: false` としてRender側でSecret入力する構成です。

現在のVerification branch:

```text
feature/issue-graph-dashboard
```

ユーザー確認後に常設branchへ統合した場合は、Render serviceの追跡branchも統合先へ切り替えます。

## API

```text
GET /api/health
GET /api/graph
GET /api/graph?include_closed=true
```

`/api/graph`は既定でOpen Issueのみを返します。`include_closed=true`の場合はOpen / Closed両方を取得対象にします。tokenは返しません。

## データ正本

- Issue hierarchy: GitHub parent/subIssues
- Project state: GitHub Projects v2
- Compatibility only: Issue本文の`Parent:` / `Depends on:`

詳細設計:

- `docs/design/issue_graph_dashboard_architecture_v1.0.0.md`
- `docs/design/issue_graph_dashboard_readability_v1.1.0.md`
