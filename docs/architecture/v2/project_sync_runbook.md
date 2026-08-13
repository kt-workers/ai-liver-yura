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
- dry-run A → 必要Option bootstrap → dry-run B → mutation → re-audit
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
同名fieldが複数ならSTOP。

## 6. `領域` Option bootstrap

Manifest §4がcanonical taxonomy。

### 6.1 既存Option

live Projectに既に存在する以下はそのまま利用する。

- Core
- 入力意味解析
- 内部指示器
- 感情・欲望・善悪
- Body
- Avatar／Live2D
- GUI
- Memory
- Infrastructure

### 6.2 V2追加Option

不足する場合のみ次の8個を追加する。

- Management
- Character
- Plugin
- Subsystem
- Streaming
- Game
- Validation
- System Integration

旧Optionは削除・renameしない。

### 6.3 安全なsingle-select field update

GitHub Projects v2 GraphQLの`updateProjectV2Field`でsingle-select optionsを更新する場合、提供したoption listは既存optionを上書きする扱いになるため、**現在存在する全Optionをlive取得して保持したまま、新しい8 Optionのうち不足分だけを末尾追加する**。

既存Optionは`ProjectV2SingleSelectFieldOptionInput.id`へ現在のoption IDを必ず含め、identityを保持する。

つまり:

```text
updated options
= all current options with their current IDs
+ only missing canonical V2 options without IDs
```

既存Optionのname/color/descriptionもlive値を保持する。

禁止:
- field削除/recreate
- existing option IDを省略して作り直す
- existing option rename/delete
- existing option color/descriptionを理由なく変更
- canonicalにないOptionを推測追加

mutation後、field-list/GraphQLで全旧OptionのIDが維持され、新Optionだけ増えたことを確認する。

安全なGraphQL mutationを組み立てられない場合はOption bootstrap前にSTOPする。

## 7. `作業種別`

Manifest §3/§6がcanonical。
Codexが推測してはならない。

Manifestに全50 Issueの一意値が明示されている。

利用値:
- 設計
- 実装
- 検証
- 調査
- ドキュメント

`不具合`は今回対象なし。

## 8. Project item一意登録

Manifest対象50 Issueについて`content.number`で確認。

- exactly one: no-op
- zero: item-add
- two以上: STOP

```bash
gh project item-add "$PROJECT" --owner "$OWNER" \
  --url "https://github.com/$REPO/issues/$ISSUE" --format json
```

## 9. Dry-run A

全50 Issueについて:

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

さらに:
- duplicate items
- same-name fields
- missing work-type/status/priority options
- missing V2 Area options
- schedule conflicts
- current different parents

を列挙する。

## 10. Option bootstrap → Dry-run B

Dry-run Aで不足AreaがManifest §6.2の8 canonical optionだけなら§6.3で非破壊追加してよい。

その後すべてlive再取得し、Dry-run Bを実行する。

**Dry-run BでSTOP条件0の場合のみ**field/formal hierarchy mutationへ進む。

## 11. Field mutation

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

Manifest §6のStatus / 作業種別 / 領域 / 優先度 / 工程 / Start / Targetを同期する。

Design Gate中:
- #317 = In progress
- #318 = In progress
- #319 = Blocked
- その他47 = Blocked

## 12. Formal Parent/Sub-issue

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

## 13. STOP conditions

次が1つでもあれば該当phase以降のmutationをSTOPする。

- duplicate Project item
- duplicate same-name field
- Area bootstrapが既存option identityを保って安全に実行できない
- bootstrap後もcanonical Area option不存在
- Manifestに必要な作業種別/Status/Priority option不存在
- Issue本文Start/TargetとManifest矛盾
- #317 Design Gate policyとStatus矛盾
- unexplained existing different parent
- Project/account/repo identity mismatch
- canonical remote contentsと本runbook/manifest矛盾
- active implementation lineage conflict

## 14. Re-audit

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
- #333 Area `Core` / 工程330

Area Option bootstrapについて:
- old option IDs unchanged
- only missing V2 canonical options added
- no old option deleted/renamed

## 15. #319 Sync Checkpoint

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

## 16. 禁止

- product code変更
- implementation branch/PR
- V1 merge/cherry-pick/一括close
- canonicalをliveへ合わせて改変
- ID推測
- duplicate追加
- 理由不明reparent
- Design Gate解除
- #317/#318以外をIn progressへ変更（#319はBlocked）

## 17. 現ChatGPT環境

Projects v2 field mutation / formal Sub-issue mutationはローカル認証済み`gh`/Codexで実行する。

ChatGPT側はManifest/Runbook/Issue正本化と、Codex結果受領後のGitHub live再監査を担当する。
