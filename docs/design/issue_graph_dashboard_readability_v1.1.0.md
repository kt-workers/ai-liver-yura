# Issue Graph Dashboard Readability v1.1.0

## 1. 背景

Render実画面でIssue数が増えた状態を確認した結果、親子treeを階層配置しても、親子関係のないIssueと依存edgeを同じcanvasへ常時混在させると、画面全体の関係線が多くなり、どの塊が1つのtreeなのか判断しづらいことが分かった。

このためv1.1では「全関係を同時表示すること」より、**Issueの親子関係を第一に読み取れること**を優先する。

本資料は `issue_graph_dashboard_architecture_v1.0.0.md` のBrowser表示方針を補足し、可読性に関して競合する記述がある場合はこちらを優先する。

## 2. 表示レイヤの優先順位

### 2.1 主表示: 親子関係

親子edgeは常時表示する。

- parent/subIssue treeを1つのvisual groupとして扱う
- treeごとに薄いgroup frameを表示する
- tree内はparentからchildへ左→右の階層配置を維持する
- group間は十分な余白を確保する

### 2.2 補助表示: dependency

依存edgeは初期状態で全表示しない。

- node未選択時: dependency edgeを表示しない
- node選択時: 選択nodeへ入る/選択nodeから出る直接dependencyだけ表示する
- `依存線を全表示` switchをONにした場合のみ全dependency edgeを表示する
- dependencyの意味は破線で維持する

これにより、親子treeを読むときに別treeを横断する依存線が常時ノイズにならないようにする。

### 2.3 dependency arrow geometry

2026-08-12のRender実画面確認では、selected edgeのstrokeを太くした際にSVG markerがstroke幅へ連動して拡大し、大きな三角形がnode間へ食い込んだ。またtarget直前で90度に曲がった直後へmarkerが付くrouteでは、線と矢印の向きが視覚的に分断された。

このためdependency edgeの矢印には以下を適用する。

- SVG markerは `markerUnits="userSpaceOnUse"` とし、stroke幅に比例して拡大させない
- 通常時・focus時で矢印headの外形寸法を変えない
- arrow headは小型の固定サイズとし、focusはedge stroke/opacityだけで表現する
- target portの直前に最低24px程度のstraight approach segmentを確保する
- routing探索はtarget nodeそのものではなくtarget側lead pointまで行い、最後を `lead point -> target port` の直線で接続する
- source側にもlead segmentを設け、node border直後で90度に折れないようにする
- 最後のbendとarrow headが重なるrouteは採用しない

これにより、拡大・focus時でも矢印だけが巨大化せず、線の進行方向とarrow headの向きが自然につながることを目標とする。

## 3. 親子関係なしIssueの分離

parent edgeを1本も持たないsingle node componentを、親子treeと同じ領域へ混在させない。

- 親子edgeを持つtree componentをcanvas上部の主領域へ配置する
- 親子edgeを持たないIssueは `親子関係なし` セクションへまとめる
- single nodeはcompact gridで配置する
- dependencyでのみ他Issueと関連する場合でも、親子グラフ上はsingle nodeとして扱う

目的はIssueを隠すことではなく、**hierarchyがあるものとないものを視覚的に分離すること**である。

## 4. 選択フォーカス

node選択時は線だけでなくnode自体もfocusする。

foreground:

- 選択Issue
- 直接parent
- 直接child
- 選択Issueと直接dependencyで接続するIssue

background:

- 上記以外のIssue node
- 選択Issueに直接関係しないedge

background nodeはopacityを下げるが、位置とtitleは確認できる程度に残す。

## 5. 初期viewport

全グラフを必ず画面内へ収める自動fitは、Issueが多い場合にnodeを小さくしすぎるため初期表示では使用しない。

- graph全体が読みやすい倍率で収まる場合だけfitする
- fit倍率が閾値を下回る場合、0.65程度の読める倍率を維持する
- In progress / Verification / Blockedなどactive statusのtreeを初期viewport中心へ寄せる
- `全体表示` buttonでは従来どおり全graph fitを実行できる

## 6. Collapse / Expand 契約

親Issueの `[-]` は「descendantを一時的に隠す」操作であり、親Issue自体や再展開操作を失わせてはいけない。

- collapse後もparent nodeは同じtree component内に残す
- collapse後もparent node上に `[+]` buttonを必ず表示する
- `[+]` clickだけでページreloadなしにdescendantを復帰させる
- collapse対象の子が非表示になっても、元のparent/subIssue relation情報を使って「子を持つnode」であることを保持する
- collapseしたrootがvisible node 1件になっても `親子関係なし` sectionへ再分類しない
- collapse / expandで現在のpan・zoom・選択状態を不必要に初期化しない
- selectionがcollapseによって非表示descendantを指す場合だけselectionを解除する

表示用 `visible` 集合と、filter適用後かつcollapse適用前の `hierarchy candidate` 集合を分離し、collapse button・tree classificationには後者を使用する。

## 7. Verification

- 親子treeごとのgroupが視覚的に区別できる
- 親子関係なしIssueがtree領域から分離される
- 初期状態ではdependency edgeが全画面を横断しない
- node選択時に直接dependencyだけ確認できる
- `依存線を全表示` ONで全dependencyを表示できる
- dependency arrow headがfocus時にも巨大化しない
- dependency edgeはtarget直前にstraight approach segmentを持ち、90度bend直後へarrow headを置かない
- node選択時に直接関係するnode以外が背景化する
- 初期表示のnode title/statusが読める倍率になる
- `全体表示`で従来どおり全体俯瞰できる
- `[-]` collapse後もparent nodeと`[+]`が残り、reloadなしで復帰できる
- collapseしたrootが `親子関係なし` sectionへ移動しない
- Closed表示切替、検索、Status filter、collapse、pan/zoomを維持する
