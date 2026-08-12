# AI Liver ゆら V2 GitHub Projects Sync Runbook

Status: Draft / #319
Project: `ktan514 / project #6`
Repository: `ktan514/ai-liver-yura`
Manifest: `docs/architecture/v2/project_sync_manifest.md`

## 1. 目的

`project_sync_manifest.md`をGitHub Projects v2のlive状態へ安全に反映するための実行手順。

重要原則:

- 古いfield ID / option ID / item IDを使わない
- mutation前に必ずlive取得する
- 既存itemを重複追加しない
- 既存Parent/Sub-issueを無条件上書きしない
- dry-runとmutationを分離する
- mutation後に再取得してManifestと比較する

## 2. 前提

GitHub CLIが必要。

```bash
gh --version
gh auth status
```

Projects操作には`project` scopeが必要。

```bash
gh auth refresh -s project
```

Repository Issue/Sub-issue操作にはIssue write権限が必要。

## 3. Live snapshot

```bash
OWNER=ktan514
PROJECT=6
REPO=ktan514/ai-liver-yura
TMP="${TMPDIR:-/tmp}/yura-v2-project-sync"
mkdir -p "$TMP"

gh project view "$PROJECT" --owner "$OWNER" --format json \
  > "$TMP/project.json"

gh project field-list "$PROJECT" --owner "$OWNER" --format json -L 100 \
  > "$TMP/fields.json"

gh project item-list "$PROJECT" --owner "$OWNER" --format json -L 500 \
  > "$TMP/items.before.json"
```

この時点で次を確認する。

- project ID
- Status / 作業種別 / 領域 / 優先度 / 工程 / Start date / Target date field IDs
- single-select option IDs
- V2 Issueがすでにitemとして存在するか
- duplicate project itemがないか

## 4. 必要field

Manifest上の管理項目:

- Status
- 作業種別
- 領域
- 優先度
- 工程
- Start date
- Target date

既存fieldを削除・再作成してIDを変えることは原則禁止。

不足fieldのみ作成する例:

```bash
gh project field-create "$PROJECT" --owner "$OWNER" \
  --name "工程" --data-type NUMBER

gh project field-create "$PROJECT" --owner "$OWNER" \
  --name "Start date" --data-type DATE

gh project field-create "$PROJECT" --owner "$OWNER" \
  --name "Target date" --data-type DATE
```

Single-select fieldは既存optionをlive確認する。`領域`のV2 optionが不足している場合、既存fieldを削除して作り直さず、GitHub UIまたはProjects v2 GraphQLでoption追加した後に再度`field-list`してoption IDを取得する。

## 5. V2 IssueをProjectへ一意登録

対象IssueはManifestの#317〜#365のうち記載されたV2 Issue群。

Issue URL:

```text
https://github.com/ktan514/ai-liver-yura/issues/<NUMBER>
```

item-listの`content.number`を確認し、存在しないIssueだけ追加する。

例:

```bash
gh project item-add "$PROJECT" --owner "$OWNER" \
  --url "https://github.com/$REPO/issues/365" --format json
```

追加後に再取得する。

```bash
gh project item-list "$PROJECT" --owner "$OWNER" --format json -L 500 \
  > "$TMP/items.after-add.json"
```

## 6. Field value更新

各mutation直前に、以下をlive JSONから解決する。

- `PROJECT_ID`
- `ITEM_ID`
- `FIELD_ID`
- single-selectの場合`OPTION_ID`

### Date

```bash
gh project item-edit \
  --id "$ITEM_ID" \
  --project-id "$PROJECT_ID" \
  --field-id "$START_FIELD_ID" \
  --date "2026-08-12"
```

### Number

```bash
gh project item-edit \
  --id "$ITEM_ID" \
  --project-id "$PROJECT_ID" \
  --field-id "$PROCESS_FIELD_ID" \
  --number 230
```

### Single select

```bash
gh project item-edit \
  --id "$ITEM_ID" \
  --project-id "$PROJECT_ID" \
  --field-id "$STATUS_FIELD_ID" \
  --single-select-option-id "$STATUS_OPTION_ID"
```

Manifestに記載されたStatus / Area / Priority / 工程 / Start / TargetをIssue単位で設定する。

Design Gate中は原則:

- #317: In progress
- #318: In progress
- #319: Blocked
- Product/Design Work・Parent・Integration: Blocked

## 7. Formal Parent/Sub-issue同期

GitHubのSub-issue REST APIを使用する。

### 現在Parent確認

```bash
gh api \
  -H "Accept: application/vnd.github+json" \
  "repos/$REPO/issues/$SUB_NUMBER/parent"
```

404相当でparentなしの場合のみ新規追加する。

### Sub-issueのdatabase ID取得

```bash
SUB_ID=$(gh api "repos/$REPO/issues/$SUB_NUMBER" --jq '.id')
```

### parentへ追加

```bash
gh api --method POST \
  -H "Accept: application/vnd.github+json" \
  "repos/$REPO/issues/$PARENT_NUMBER/sub_issues" \
  -F "sub_issue_id=$SUB_ID"
```

既に別Parentが設定されている場合は自動置換しない。ManifestとGitHub liveを比較し、意図したreparentであることを確認した場合だけ:

```bash
gh api --method POST \
  -H "Accept: application/vnd.github+json" \
  "repos/$REPO/issues/$PARENT_NUMBER/sub_issues" \
  -F "sub_issue_id=$SUB_ID" \
  -F "replace_parent=true"
```

## 8. Parent/Sub-issue pairs

```text
317 <- 318 319 320 325 335 342 350 356 345 360
320 <- 321 322 323 324
324 <- 354 355
325 <- 349 326 327 328 361 329 362 330 363 331 348 332 364 333 334
335 <- 336 337 338 339 340 341
342 <- 343 344
356 <- 357 358 359
345 <- 346 347 365 351 352 353
```

注意: #324は#320のSub-issueであり、同時に#354/#355のParent。

## 9. Dry-run

mutation前に少なくとも次の差分を出力する。

```text
Issue
current project item: present / absent
current Status -> desired Status
current Area -> desired Area
current Priority -> desired Priority
current 工程 -> desired 工程
current Start -> desired Start
current Target -> desired Target
current parent -> desired parent
```

以下が1つでもあればSTOP:

- 同一Issueのproject item重複
- Manifestにない別Parentが設定済みで理由不明
- 同名fieldが複数存在
- desired single-select optionが存在しない
- Issue本文Start/TargetとManifestが矛盾
- #317 Design Gate policyとStatusが矛盾

## 10. 再監査

mutation後:

```bash
gh project field-list "$PROJECT" --owner "$OWNER" --format json -L 100 \
  > "$TMP/fields.after.json"

gh project item-list "$PROJECT" --owner "$OWNER" --format json -L 500 \
  > "$TMP/items.after.json"
```

全V2 Issueについて以下を確認する。

- exactly one project item
- Status一致
- Area一致
- Priority一致
- 工程一致
- Start/Target一致
- formal Parent一致

PASS後に#319へSync Checkpointを記録する。

## 11. 現ChatGPT環境の制約

2026-08-12確認時点、このChatGPT GitHub ConnectorにはProjects v2 field mutation / formal Sub-issue mutation actionが公開されていない。また実行containerには`gh` CLI / GitHub tokenがない。

そのため本環境ではManifest・Issue本文・runbookまでを正本化し、実mutationは`gh`が認証済みのローカル/Codex環境で実行する。

この制約を理由に古いIDを推測して書き込まないこと。
