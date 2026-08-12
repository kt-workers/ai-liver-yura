# Yura System Architecture Visualizer 設計

## 1. 目的

`ai-liver-yura` の実装上のモジュール構造と依存方向を、ノードと方向付きエッジで可視化する開発支援GUIを提供する。

対象は「設計書に手で描いた静的構成図」ではなく、現在のリポジトリをread-only解析して生成した依存グラフとする。

Issue: #312

## 2. 責務境界

### Dependency Graph Analyzer

所有する責務:

- リポジトリ内Pythonファイルの列挙
- Python ASTによる `import` / `from ... import ...` 抽出
- import先をリポジトリ内部モジュールへ解決
- ファイル単位依存を論理モジュール単位へ集約
- Graph JSON DTO生成

所有しない責務:

- production runtimeの変更
- DI containerやActivity実行状態の観測
- importだけでは表現されない動的依存の推測
- GUIレイアウト

### Web API

所有する責務:

- Analyzerの実行
- Graph JSONの配信
- 静的Web UIの配信

### Browser UI

所有する責務:

- ノード・方向付きエッジ描画
- 自動配置
- ズーム / パン / Fit to view
- 検索 / カテゴリ絞り込み
- 選択ノードと接続エッジの強調
- 詳細パネル

## 3. ノード粒度

初版の正本表示は論理モジュール単位とする。

`app` 配下は基本的に `app/<第一階層>` を1ノードとする。ただし責務が大きく独立している `plugins` は `app/plugins/<plugin>`、将来的な `subsystems` 相当の独立単位も第二階層まで分割できる規則を持つ。

`gui` 配下は `gui/<tool>` を1ノードとする。

将来の階層モデル:

```text
System
  -> LogicalModule
    -> Package
      -> PythonModule
        -> Class / Function
```

初版APIも `level` と `parent_id` を保持できる形にし、上位互換で詳細展開可能にする。

## 4. エッジ意味

エッジ `A -> B` は「AのPython実装がBをimportしている」を意味する。

複数ファイルから同一論理モジュール間へimportしていても、GUIでは1本のエッジへ集約し、`weight` にimport参照数を保持する。

同一論理モジュール内の自己参照は初期表示では除外する。

## 5. Graph JSON

```json
{
  "generated_at": "ISO-8601",
  "root": "repository path",
  "nodes": [
    {
      "id": "app.runtime",
      "label": "runtime",
      "path": "app/runtime",
      "category": "runtime",
      "level": "logical_module",
      "parent_id": "app",
      "file_count": 12,
      "files": ["app/runtime/foo.py"],
      "incoming_count": 3,
      "outgoing_count": 5
    }
  ],
  "edges": [
    {
      "id": "app.runtime->app.core",
      "source": "app.runtime",
      "target": "app.core",
      "kind": "python_import",
      "weight": 4
    }
  ]
}
```

`files` は詳細表示用。巨大化した場合に将来API分割できるよう、UIは必須項目として扱わない。

## 6. モジュール分類

表示色・グルーピング用にpathからcategoryを付与する。

主なcategory:

- bootstrap
- runtime
- core
- domain
- service
- port
- plugin
- adapter
- integration
- infrastructure
- config
- admin
- gui
- validation
- other

categoryは可視化上の属性であり、productionの責務定義を変更するものではない。

## 7. import解決

Analyzerは `ast.Import` と `ast.ImportFrom` を読む。

内部依存として採用する条件:

1. absolute importが `app.*` / `gui.*` 等の解析対象rootに一致する。
2. relative importは現在ファイルのpackageからabsolute moduleへ正規化する。
3. 解決後のmoduleが解析対象Python module集合に存在するか、そのpackage prefixとして存在する。

標準ライブラリ・外部ライブラリは初版グラフから除外する。

syntax errorを含むファイルがあっても全体解析を停止せず、diagnosticsへ記録する。

## 8. UI設計

画面は以下の3領域を基本とする。

```text
+----------------+------------------------------+------------------+
| Filter / Nav   | Architecture Canvas          | Selected Detail  |
|                |                              |                  |
| Search         | [node] ---> [node]           | path             |
| Category       |    |                         | files            |
| Legend         |    +------> [node]            | inputs/outputs   |
+----------------+------------------------------+------------------+
```

### Canvas

- SVGで描画し、外部JSライブラリを必須にしない
- categoryごとにレーンを作り、ノード重なりを避ける
- エッジは方向付き矢印
- 選択ノードへ接続するedgeを強調し、無関係edgeを薄くする
- wheel zoom、drag pan、Fit to viewを提供する

### Detail panel

選択ノードについて以下を表示する。

- label / id
- path
- category
- file_count
- incoming module一覧
- outgoing module一覧

## 9. 起動方式

FastAPI + Uvicornを使用し、既存root `requirements.txt` の依存範囲で動作させる。

ローカル:

```bash
python gui/yura-system-architecture-visualizer/server.py
```

Render:

```bash
python gui/yura-system-architecture-visualizer/server.py
```

`PORT` 環境変数があればその値を使用する。

## 10. テスト

Analyzerは一時ディレクトリに最小Python packageを構築して検証する。

最低限:

- absolute import
- relative import
- external import除外
- 同一logical module自己参照除外
- edge集約とweight
- syntax error時に全体解析継続

Serverはgraph DTO生成関数と静的ファイル解決を薄く保ち、AnalyzerのUnit testを中心とする。

## 11. 非目標

初版では以下を扱わない。

- runtime時系列・health監視
- 起動/停止操作
- GitHub Issue dependency
- class/function call graph
- reflection / dynamic importの完全解析
- UML仕様への完全準拠
