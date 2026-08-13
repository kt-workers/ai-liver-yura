# V2 Commit Hygiene — Merge Commit検査基準

Status: Proposed canonical supplement
Effective: 2026-08-13
Management Issue: #384
Related canonical:
- `docs/architecture/v2/branch_lifecycle_and_commit_hygiene.md`
- `docs/architecture/v2/commit_message_language_policy.md`

## 1. 背景

V2では通常PRの統合方式としてmerge commitを使用する。

そのためCommit Hygiene Guardが2-parent以上のmerge commitを正当な履歴として扱えなければならない。

`git diff-tree <merge-commit>`をmerge diff modeなしで実行すると、正当なmergeでもchanged pathが空になる場合がある。この結果だけで空コミット判定してはならない。

## 2. 判定基準

各コミットのchanged pathは次の基準で取得する。

### 親を持つコミット

第1親と対象コミットのtree差分を使用する。

```text
first-parent-tree
        ↓ diff
current-commit-tree
```

merge commitが2親以上を持つ場合も、第1親との差分をCommit Hygiene上の「そのコミットがlineageへ導入した変更」として扱う。

### root commit

親が存在しない場合だけroot tree全体を導入差分として扱う。

## 3. 空コミット判定

第1親との差分が空である場合、そのコミットはCommit Hygiene上の空/history-only候補として拒否する。

ただし、merge commitであること自体を理由に拒否しない。

## 4. コミットメッセージ

merge commitも通常コミットと同じ日本語件名ルールに従う。

Gitが自動生成する英語の `Merge ...` 件名をそのまま使用しない。merge操作時に日本語のmerge commitタイトル・本文を明示する。

## 5. 回帰テスト

最低限、次を固定する。

- 2-parent mergeは第1親との差分pathを取得する
- merge commitに実変更があれば空コミット扱いしない
- 日本語件名の正当なmerge commitを許容する
- 第1親との差分が本当に空なら拒否する
