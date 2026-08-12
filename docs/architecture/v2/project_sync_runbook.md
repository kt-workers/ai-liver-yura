# AI Liver ゆら V2 GitHub Projects Sync Runbook

Status: Draft / #319 / Canonical field values resolved 2026-08-13
Project: `ktan514 / project #6`
Repository: `ktan514/ai-liver-yura`
Manifest: `docs/architecture/v2/project_sync_manifest.md`

## 1. 目的

`project_sync_manifest.md`をGitHub Projects v2 liveへ安全に反映する。

重要原則:

- 古いfield ID / option ID / item IDを使わない
- mutation前に必ずlive取得
- existing itemをduplicate追加しない
- existing Parent/Sub-issueを理由不明で上書きしない
- dry-run→必要Option bootstrap→再dry-run→mutation→re-auditの順
- canonical Manifestをlive状態へ都合よく書き換えない

## 2. 前提

```bash
gh --version
gh auth status
gh auth refresh -s project
```

Repository Issue/Sub-issue write権限も確認する。

## 3. Canonical authority

必ずremote liveの以下を読む。

- #207
- #317
- #319
- `origin/rebuild/v2-foundation:docs/architecture/v2/project_sync_manifest.md`
- `origin/rebuild/v2-foundation:docs/architecture/v2/project_sync_runbook.md`
- `origin/rebuild/v2-foundation:docs/architecture/v2/system_architecture.md`

local checkoutが古ければremoteを正本とする。

## 4. Live snapshot

```bash
OWNER=ktan514
PROJECT=6
REPO=ktan514/ai-liver-yura
TMP="${TMPDIR:-/tmp}/yura-v2-project-sync"
mkdir -p "$TMP"

gh project view "$PROJECT" --owner "$OWNER" --format json > "$TMP/project.json"
gh project field-list "$PROJECT" --owner "$OWNER" --format json -L 100 > "$TMP/fields.json"
gh project item-list "$PROJECT" --owner "$OWNER" --format json -L 500 > "$TMP/items.before.json"
```

liveから解決する:
- PROJECT_ID
- field IDs
- option IDs
- item IDs
- current Project item presence
- current Parent

## 5. Required fields

- Status
- 作業種別
- 領域
- 優先度
- 工程
- Start date
- Target date

既存fieldを削除・再作成しない。

不足field自体がある場合は、そのfieldの安全な追加方法を確認してから追加する。既存同名fieldが複数ならSTOP。

## 6. `領域` Option bootstrap

Manifest §4の32個をcanonical exact option namesとする。

旧Area Optionは削除・renameしない。

### 6.1 初回dry-run

live `領域` optionsとManifest §4を比較し、missing canonical optionsだけを列挙する。

### 6.2 非破壊追加

GitHub UIまたはProjects v2 GraphQLで、**missing canonical optionsのみ**existing `領域` single-select fieldへ追加する。

禁止:
- field削除/recreate
- existing option rename
- existing option delete
- canonicalにないOptionを推測追加

GraphQLを使う場合、mutation直前にfield ID/project IDをlive解決する。

GitHub API/CLI制約でsingle-select optionを安全に追加できない場合はSTOPし、UI操作が必要なOption一覧を返す。

### 6.3 再取得

Option追加後:

```bash
gh project field-list "$PROJECT" --owner "$OWNER" --format json -L 100 > "$TMP/fields.after-option-bootstrap.json"
```

32 canonical optionsがexact matchで存在することを確認する。

## 7. `作業種別`

Manifest §3/§6がcanonical。

Codexが推測してはならない。

Manifestに全50 Issueの一意値が明示されているため、その値をそのまま利用する。

利用値:
- 設計
- 実装
- 検証
- 調査
- ドキュメント

`不具合`は今回対象なし。

## 8. Project item一意登録

Manifest対象50 Issueについて`content.number`で確認する。

- exactly one: 何もしない
- zero: item-add
- two以上: STOP

```bash
gh project item-add "$PROJECT" --owner "$OWNER" \
  --url "https://github.com/$REPO/issues/$ISSUE" --format json
```

## 9. Field mutation

mutation直前に毎回live JSONから:
- PROJECT_ID
- ITEM_ID
- FIELD_ID
- OPTION_ID

を解決する。

### Date

```bash
gh project item-edit --id "$ITEM_ID" --project-id "$PROJECT_ID" \
  --field-id "$FIELD_ID" --date "YYYY-MM-DD"
```

### Number

```bash
gh project item-edit --id "$ITEM_ID" --project-id "$PROJECT_ID" \
  --field-id "$FIELD_ID" --number 235
```

### Single select

```bash
gh project item-edit --id "$ITEM_ID" --project-id "$PROJECT_ID" \
  --field-id "$FIELD_ID" --single-select-option-id "$OPTION_ID"
```

Manifest §6のStatus / 作業種別 / 領域 / 優先度 / 工程 / Start / Targetを完全同期する。

Design Gate中:
- #317 = In progress
- #318 = In progress
- #319 = Blocked
- その他47 = Blocked

## 10. Formal Parent/Sub-issue

current parentを先に確認:

```bash
gh api -H "Accept: application/vnd.github+json" \
  "repos/$REPO/issues/$SUB_NUMBER/parent"
```

parentなしの場合のみ追加:

```bash
SUB_ID=$(gh api "repos/$REPO/issues/$SUB_NUMBER" --jq '.id')

gh api --method POST \
  -H "Accept: application/vnd.github+json" \
  "repos/$REPO/issues/$PARENT_NUMBER/sub_issues" \
  -F "sub_issue_id=$SUB_ID"
```

desired parentと同じならno-op。

別Parentなら自動置換しない。Manifest/canonicalから意図したreparentと100%確定できる場合のみ`replace_parent=true`。不明ならSTOP。

Desired pairs:

```text
317 <- 318 319 320 325 335 342 350 356 345 360
320 <- 321 322 323 324
324 <- 354 355
325 <- 349 326 327 328 366 361 329 362 330 363 331 348 332 364 333 334
335 <- 336 337 338 339 340 341
342 <- 343 344
356 <- 357 358 359
345 <- 346 347 365 351 352 353
```

49 links。

## 11. STOP conditions

次が1つでもあれば、該当phase以降のmutationをSTOPする。

- duplicate Project item
- duplicate same-name field
- canonical 32 Area option bootstrapが安全に実行できない
- bootstrap後もcanonical option不存在
- Manifestに必要なWork Type/Status/Priority option不存在
- Issue本文Start/TargetとManifest矛盾
- #317 Design Gate policyとStatus矛盾
- unexplained existing different parent
- Project/account/repo identity mismatch
- canonical remote contentsと本runbook/manifest矛盾
- active implementation lineage conflict

Option不足は、Manifestでcanonical exact nameが確定済みの`領域`に限り、§6の非破壊bootstrapを先に試してよい。

## 12. Dry-run sequence

### Dry-run A

mutation前に全50 Issueについて:

```text
Issue
current/desired project presence
current/desired Status
current/desired 作業種別
current/desired 領域
current/desired 優先度
current/desired 工程
current/desired Start
current/desired Target
current/desired parent
```

### Option bootstrap

必要なら`領域`missing canonical optionsだけ追加。

### Dry-run B

全field/option/item/parentを再取得し、STOP条件が0であることを確認。

**Dry-run B PASS後のみProject field / Parent mutationへ進む。**

## 13. Re-audit

```bash
gh project field-list "$PROJECT" --owner "$OWNER" --format json -L 100 > "$TMP/fields.after.json"
gh project item-list "$PROJECT" --owner "$OWNER" --format json -L 500 > "$TMP/items.after.json"
```

全50 Issue:
- exactly one item
- Status一致
- 作業種別一致
- 領域一致
- 優先度一致
- 工程一致
- Start一致
- Target一致

全49 Sub-issue:
- desired Parent一致

特別確認:
- #366 parent #325 / 工程235
- #361 工程240
- #333 `Core / Brain / Attention & Autonomy` / 工程330

## 14. #319 Sync Checkpoint

完全PASSした場合のみ#319へコメント。

最低情報:
- timestamp
- github account
- Project ID
- branch/head
- Manifest blob SHA
- Runbook blob SHA
- target count=50
- Area options added
- field mutation count
- parent links added/replaced
- duplicate=0
- re-audit PASS

PARTIAL/STOPならPASSコメントを残さない。

## 15. 禁止

- product code変更
- implementation branch/PR
- V1 merge/cherry-pick/一括close
- canonicalをliveへ合わせて改変
- ID推測
- duplicate追加
- 理由不明reparent
- Design Gate解除
- #317/#318以外をIn progressへ変更（#319はBlocked）

## 16. 現ChatGPT環境

Projects v2 field mutation / formal Sub-issue mutationはローカル認証済み`gh`/Codexで実行する。

ChatGPT側はManifest/Runbook/Issue正本化と、Codex結果受領後のGitHub live再監査を担当する。
