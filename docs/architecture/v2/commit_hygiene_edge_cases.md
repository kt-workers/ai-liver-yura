# V2 Commit Hygiene — 境界条件

Status: Proposed canonical supplement
Effective: 2026-08-13
Management Issue: #384
Related canonical:
- `docs/architecture/v2/branch_lifecycle_and_commit_hygiene.md`
- `docs/architecture/v2/commit_message_language_policy.md`
- `docs/architecture/v2/commit_hygiene_merge_semantics.md`

## 1. Placeholder修正の扱い

`NOOP`、`nonexistent`等のplaceholder pathは新規導入・再導入・内容変更を禁止する。

一方、誤って共有履歴へ入ったplaceholderを削除するための明示的な是正コミットは許可しなければならない。

したがってCommit Hygiene Guardはpath名だけで判定せず、change statusを確認する。

### 拒否

- `A`: placeholder pathの追加
- `M`: placeholder pathの変更
- その他、結果としてplaceholderをlineageへ残す非削除変更

### 許可

- `D`: 既存placeholder pathの削除

rename/copy判定の曖昧さで回避されないよう、Guard内部のpath status取得ではrename detectionを無効化し、削除+追加として扱う。

これにより:

- placeholder -> 正規pathへのrenameは `D placeholder + A 正規path` となり許可可能
- 正規path -> placeholderへのrenameは `D 正規path + A placeholder` となり拒否される

## 2. 日本語文字判定

コミット件名の日本語必須判定では、日本語ブロック全体ではなく実際の文字範囲だけを使用する。

許可判定に使用する文字:

- ひらがな文字
- カタカナ文字
- 半角カタカナ文字のうち実際の字母
- 漢字（CJK Unified Ideographs / Extension A）

句読点・中黒・括弧・長音記号など、日本語文中で使われる記号だけでは日本語件名として認めない。

全角・半角を問わず、長音記号単体は日本語文字として数えない。特に半角カタカナ領域のU+FF70 `ｰ`を字母範囲へ含めない。

例えば次はどちらも拒否する。

```text
API・schema update
APIｰschema update
```

中黒 `・` または半角長音記号 `ｰ` が含まれていても、日本語のひらがな・カタカナ字母・漢字が存在しないためである。

## 3. 回帰テスト

最低限、次を固定する。

- placeholder追加は拒否
- placeholder変更は拒否
- 既存placeholder削除は許可
- 正規pathからplaceholderへのrename相当は拒否
- `API・schema update` は日本語件名として拒否
- `APIｰschema update` は日本語件名として拒否
- 正規の日本語件名は許可
