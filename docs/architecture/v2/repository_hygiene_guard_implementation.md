# Repository Hygiene Guard 実装設計

Status: Proposed canonical supplement
Effective: 2026-08-22
Management Issue: #384
Parent canonical: `docs/architecture/v2/repository_hygiene_and_mutation_safety.md`
Related canonical: `docs/architecture/v2/branch_lifecycle_and_commit_hygiene.md`

## 1. 目的

Pull Requestが共有履歴へ導入するcommitを決定論的に検査し、過去に発生した次の事故をCIでfail-closedに検出する。

- 差分0の履歴操作用commit
- `NOOP` / `nonexistent` / 一時marker等のplaceholder追加
- CIやreviewを起動するためだけの一時file追加と直後の削除
- `tmp/*`等の共有履歴へ残すべきでない一時path

このGuardはcommitの品質を主観評価しない。小さな正当変更や一行だけの修正を拒否せず、有限の構造条件だけを判定する。

## 2. 責務境界

Guardが所有するもの:

- 指定されたbase SHAからhead SHAまでのcommit range取得
- 各commitのparent / tree / changed pathの決定論的検査
- 禁止placeholder pathの導入検出
- 同一PR range内のplaceholder add -> delete pair検出
- findingの安定したreason codeと日本語診断
- CI exit code

Guardが所有しないもの:

- branch ref削除
- commit rewrite / rebase / force push
- Pull Requestのclose / merge
- Issue / Project field更新
- GitHub APIへのmutation
- commit内容の意味・品質・設計妥当性の判定
- commit messageからの意図推測
- LLMによる分類

## 3. 実装配置

```text
tools/
  __init__.py
  repository_hygiene/
    __init__.py
    commit_hygiene.py

tests/
  tools/
    repository_hygiene/
      test_commit_hygiene.py
```

既存V2製品Domainへ依存させない。

## 4. 実行方式

CLI:

```bash
python -m tools.repository_hygiene.commit_hygiene \
  --base-sha <base_sha> \
  --head-sha <head_sha>
```

入力はGit revisionとして存在し、`base_sha..head_sha`を取得可能でなければならない。

network、GitHub API、環境固有DB、LLM、Node.jsへ依存しない。

## 5. Exit code

- `0`: findingなし
- `1`: policy violationを1件以上検出
- `2`: invocation / revision / Git inspection自体が成立しない

入力不正やGit inspection失敗を「問題なし」へfallbackしない。

## 6. Commit range

commit順序は次で固定する。

```bash
git rev-list --reverse --topo-order <base_sha>..<head_sha>
```

結果順序とfinding出力順序をdeterministicにする。

base/head自身の文字列だけを信頼せず、Git revisionとしてresolveできることを検証する。

## 7. Empty commit検出

### 7.1 対象

**single-parent commitだけ**をempty commit判定対象にする。

single-parent commitで、commit tree SHAとparent tree SHAが完全一致する場合:

```text
reason_code = empty_single_parent_commit
```

として拒否する。

### 7.2 Merge commit

merge commitは、first parentとtreeが同一という理由だけでempty扱いしない。

reconciliation merge、ancestry記録、既に他parentで導入済みの履歴合流等で正当なmerge commitが存在し得るためである。

merge commitのchanged pathはplaceholder検査対象にできるが、tree equalityだけをempty判定に使わない。

## 8. 禁止placeholder path

### 8.1 Exact path

最低限、次を禁止する。

```text
NOOP
nonexistent
.trigger
.issue_sync_marker
tmp-never-used
tmp.txt
ISSUE_PLAN.md
DO_NOT_USE
```

### 8.2 Prefix

次のrepository path prefixを禁止する。

```text
tmp/
```

`tmp/`という文字列を含む任意pathではなく、repository rootからのpath prefixとして判定する。

### 8.3 判定対象

禁止pathの`added`または`modified`を検出したcommitを拒否する。

```text
reason_code = prohibited_placeholder_path
```

既に存在していた禁止placeholderを**削除だけするcorrective commit**は、それ自体を違反にしない。

事故回復でfileを消せなくなることを防ぐためである。

## 9. Add -> Delete pair

同じPR range内で、禁止placeholder pathが追加され、後続commitで削除された場合、各commit個別findingに加えてrange-level findingを出す。

```text
reason_code = prohibited_placeholder_add_delete_pair
```

findingには最低限次を含む。

- path
- add commit SHA
- delete commit SHA

「最終treeに残っていないから問題なし」としない。

## 10. 明示的に禁止しないもの

次だけを理由に拒否しない。

- 変更行数が少ない
- 1 fileだけの変更
- 1 lineだけの変更
- commit messageが短い
- `dummy` / `noop`等の単語が通常コード・テスト・説明文に含まれる
- fixture/test doubleとして正当なdummy実装を持つ
- merge commitがfirst parentと同じtreeを持つ

自然言語やcommit messageから「これはCI trigger目的だろう」と推測しない。

## 11. Git inspection

Python標準libraryの`subprocess`からGit CLIを呼び、stdout/stderr/return codeを明示的に扱う。

最低限必要なinspection:

- revision resolve
- commit range取得
- parent数取得
- commit tree取得
- parent tree取得
- path status取得

shell文字列連結を避け、argument listで実行する。

Git command失敗時:

```text
reason_code = git_inspection_failed
exit_code = 2
```

revision/range不成立時:

```text
reason_code = invalid_revision_range
exit_code = 2
```

## 12. Finding model

内部findingは少なくとも次を保持する。

```text
reason_code
commit_sha | null
path | null
related_commit_sha | null
message_ja
```

reason codeはmachine-readable、説明は日本語とする。

初期reason code:

```text
empty_single_parent_commit
prohibited_placeholder_path
prohibited_placeholder_add_delete_pair
invalid_revision_range
git_inspection_failed
```

出力順はcommit range順、同一commit内はpath辞書順、range-level findingは最後にpath辞書順とする。

## 13. CI接続

既存 `.github/workflows/v2-ci.yml` の exact head identity確認直後、Ruffより前に追加する。

```bash
python -m tools.repository_hygiene.commit_hygiene \
  --base-sha "${{ github.event.pull_request.base.sha }}" \
  --head-sha "${{ github.event.pull_request.head.sha }}"
```

既存checkoutは`fetch-depth: 0`なのでfull historyを利用できる。

Guard導入後はtool sourceも既存quality gateへ含める。

```bash
ruff check app tests tools
mypy --strict app tests tools
python -m compileall -q app tests tools
```

full pytestは既存`python -m pytest -q`を維持し、`tests/tools/**`もtestpaths=`tests`により実行対象とする。

## 14. Unit / regression test

最低限次を固定する。

1. 通常のreal commitはPASS。
2. 正当な1-line commitはPASS。
3. single-parent tree-equal commitは`empty_single_parent_commit`。
4. root `NOOP`追加は`prohibited_placeholder_path`。
5. `tmp/example.txt`追加は`prohibited_placeholder_path`。
6. placeholder add -> deleteはpair findingを持つ。
7. 既存placeholderのdelete-only corrective commitはPASS。
8. merge commitをfirst-parent tree equalityだけでempty扱いしない。
9. invalid SHA / rangeはexit `2`。
10. finding順序が反復実行で一致する。
11. commit messageだけが`noop`等でもreal legitimate diffがあり禁止pathでなければPASS。

テスト用Git repositoryはtemporary directoryへ作り、実repositoryのbranch/refを変更しない。

## 15. Security / safety

- Guard自身はread-only Git inspectionだけを行う。
- `git reset`、`git rebase`、`git checkout`、`git switch`、`git branch -D`、`git push`、`git update-ref`を実行しない。
- repository fileを書き換えない。
- secretやenvironment credentialを取得しない。
- findingから外部commandを組み立てない。

## 16. Branch protectionとの関係

このGuardはGitHub branch protection / Rulesetの代替ではない。

別途repository settingsで少なくとも次を検討する。

- `main`
- `develop`
- `rebuild/v2-foundation`

へのdirect push/write制限。

GuardはPR historyの内容検査、Rulesetはshared targetへの物理的mutation制御を担当する。

## 17. 実装Gate

local Codexは実装開始前に次をlive確認する。

- Issue #207
- Issue #384最新checkpoint
- PR #441
- `management/v2-repository-hygiene-guard` current HEAD
- 本設計
- parent hygiene canonical
- competing #384 lineageがないこと

一致しない場合は実装せずSTOPする。

## 18. 完了条件

- Guard実装とunit/regression test追加
- `.github/workflows/v2-ci.yml`へdeterministic gate追加
- Ruff PASS
- strict Mypy PASS
- full pytest PASS
- compileall PASS
- diff whitespace PASS
- exact-head CI PASS
- review blocking 0
- branch cleanup対象の最終分類完了
- cleanup後に#384 checkpointへ削除対象/保持対象/理由を記録
