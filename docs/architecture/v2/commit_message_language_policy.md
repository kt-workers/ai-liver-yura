# V2 コミットメッセージ日本語運用

Status: Proposed canonical supplement
Effective: 2026-08-13
Parent: #317
Management Issue: #384
Related canonical:
- `docs/architecture/v2/project_v2_management_spec.md`
- `docs/architecture/v2/branch_lifecycle_and_commit_hygiene.md`

## 1. 原則

V2で人間またはAIが作成するコミットメッセージは、日本語を主要言語とする。

技術識別子として必要な英字・数字は使用してよい。

例:

- `V2管理: ブランチライフサイクルを整理する (#384)`
- `Body: 姿勢生成契約の回帰テストを追加する (#335)`
- `Foundation: revision検証の回帰テストを追加する (#321)`
- `Codex修正基盤: 認証情報の隔離境界を強化する (#372)`

英語のConventional Commits接頭辞を標準形式として使用しない。

禁止例:

- `feat(v2): add validation`
- `fix: repair state transition`
- `docs(v2): update architecture`
- `test: add regression case`
- `chore: cleanup`
- `fix!: 不具合を修正する`
- `fix(v2)!: 不具合を修正する`
- `security(v2)!: 認証処理を修正する`
- `deps: 依存関係を更新する`

Conventional Commitsのbreaking-change記法である任意の`!`を付けても、この禁止を回避できない。

## 2. 件名

コミット件名は次を満たす。

1. 日本語文字（ひらがな、カタカナ、漢字）のいずれかを含む。
2. 変更目的を日本語で説明する。
3. 英語Conventional Commit形式の接頭辞で開始しない。scopeやbreaking-change用`!`を付けた形式も同様に禁止する。
4. ASCIIだけの`<type>:`形式を使用する場合、プロジェクトが明示的に許可した技術領域名だけを使用できる。
5. `x` / `noop` / `trigger` 等、意味のない履歴生成用件名を使用しない。
6. 対象Issueがある場合は原則として末尾に `(#番号)` を付ける。

## 3. 許可するASCII技術領域prefix

日本語説明の前に置く技術領域名として、次を許可する。

- `Body:`
- `Foundation:`

上記以外のASCII-only `<type>:` / `<type>(scope):` / `<type>!:` / `<type>(scope)!:` はConventional Commit形式または曖昧な英語prefixとして拒否する。

新しいASCII技術領域prefixが必要な場合は、この正本へ先に追加してから使用する。

`V2管理:` や `Codex修正基盤:` のようにprefix自体へ日本語が含まれる形式は、このASCII allowlistの対象外であり通常の日本語件名として扱う。

## 4. 本文

コミット本文を付ける場合も説明文は日本語を主要言語とする。

ただし、次はそのまま記載してよい。

- ファイルパス
- コマンド
- API名
- 型名・クラス名・関数名
- SHA
- テストツール名
- GitHub Status名などの技術識別子

## 5. Merge commit

GitHubでmerge commitを作成する場合、merge commitのタイトル・本文も日本語を主要言語とする。

PRタイトルが日本語でない場合でも、merge時に日本語タイトルを明示してから実行する。

Gitが自動生成する英語の`Merge ...`件名をそのまま使用しない。

## 6. 機械検査

V2 Commit Hygiene Guardは少なくとも次を拒否する。

- 件名に日本語文字が1文字もないコミット
- 許可されていないASCII-only colon prefix
- scope付き・`!`付きの任意の英語Conventional Commit形式
- placeholder / no-op / trigger-onlyコミット

技術識別子に英字が含まれること自体は拒否しない。

## 7. 既存履歴

未マージbranchの英語コミットメッセージは、他lineageが依存していないことを確認したうえでmerge前に日本語へ修正する。

すでに共有trunkへmerge済みの履歴は、メッセージ修正だけを理由に無計画なforce rewriteを行わない。履歴を書き換える場合は、影響するbranch、PR、checkpoint、SHA参照を列挙し、専用のreconciliation手順で一括して実施する。
