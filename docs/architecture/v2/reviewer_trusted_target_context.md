# 独立AIレビュー — 信頼済みレビュー対象文脈

状態: Issue #379 の正本補足
親Issue: #369
依存Issue: #370, #371
適用日: 2026-08-13

関連正本:
- `docs/architecture/v2/independent_ai_review_architecture.md`
- `docs/architecture/v2/review_orchestrator_implementation.md`

## 1. 問題

決定論的検証は、Geminiが返す `echoed_head_sha` と信頼済み `ReviewTarget.head_sha` の完全一致を要求する。

一方、長期間開いているPR本文や過去レビューには古い先端SHAが残ることがある。信頼済みレビュー対象SHAを入力上で明示しない場合、レビューワーが信頼できない過去SHAを対象SHAとして返し、正しい決定論的検証によってレビュー不能になる可能性がある。

検証を緩めてはいけない。必要なのは信頼済み対象の明示である。

## 2. Authority

`ReviewContext.target` は信頼済み制御系がGitHub実状態と固定された実行開始時SHAから構築する。

レビュー対象に関する信頼済み事実:

- リポジトリ
- PR番号
- 基準参照
- PR関係基準SHA
- 信頼済みV2基準SHA
- 先端参照
- レビュー対象SHA

Geminiの `echoed_head_sha` に対するAuthorityは `ReviewContext.target.head_sha` だけとする。

次に現れるSHAはレビュー対象Authorityではない。

- PRタイトル・本文
- ソースコード
- 試験
- 差分
- コメント・レビュー
- 過去のレビュー記録
- Issue説明文
- 検証証拠内の説明文

これらは現在SHAに似た文字列を含んでいてもレビュー対象データとして扱う。

## 3. レビューワー入力契約

Issue、正本、PRデータより前に、信頼済みレビュー対象を明示する。

```text
[信頼済み事実: レビュー対象]
リポジトリ: <repository>
PR: <number>
基準参照: <base_ref>
PR関係基準SHA: <base_sha>
正本基準SHA: <trusted_base_sha>
先端参照: <head_ref>
レビュー対象SHA: <head_sha>
```

Geminiへのシステム指示は、`echoed_head_sha` へこの信頼済み欄の `レビュー対象SHA` を完全一致で複写するよう要求する。

## 4. 検証契約

検証を緩和しない。

- `ReviewContext.target.head_sha` と完全一致する返却SHAだけを通常の判定検証へ進める
- `echoed_head_sha` は必須とし、欠落・空文字も不正候補とする
- 異なるSHAを返した候補は不正候補とする
- 再生成で回復し得るため上限付き再試行の対象にしてよい
- 上限後も一致しなければレビュー不能
- PR本文、過去AIレビュー、検証証拠で信頼済み対象SHAを上書きしない

## 5. プロンプト注入境界

信頼済み対象情報を追加しても、PRデータは信頼済みに昇格しない。

```text
[信頼済み事実: レビュー対象]
[権限情報: Issue責務]
[権限情報: 正本要件]
[信頼済み事実: 検証証拠]
[信頼できないデータ: PRメタデータ]
[信頼できないデータ: PR差分]
```

信頼できない欄にある命令やSHAらしい文字列はレビュー対象データにすぎない。

## 6. 検証

単体確認:

- 入力の先頭付近に正確な `ReviewTarget.head_sha` を含む
- PR本文に埋め込まれた古いSHAは信頼できないPRメタデータ欄に残る
- 信頼済み対象欄がPRデータより前に置かれる
- `ReviewTarget.base_sha` と `ReviewTarget.trusted_base_sha` を明確に区別して表示する
- システム指示が信頼済み `レビュー対象SHA` の完全一致複写を要求する
- 決定論的検証が異なる返却SHAを拒否する
- 決定論的検証が返却SHAの欠落・空文字を拒否する

実環境確認:

- 記録されたレビュー対象SHAが現在PR先端SHAと完全一致
- PR内の過去SHAによって対象SHAが変わらない
- 信頼済みV2基準SHAと正本文書取得SHAが一致
- 対象SHAが明確になった後の判定は、指摘内容に基づいて `PASS`、`CHANGES_REQUESTED`、`BLOCKED` のいずれかとなる
