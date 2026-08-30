# Repository hygiene path encoding契約

状態: 正本への追加提案
管理Issue: #384
親設計: `docs/architecture/v2/repository_hygiene_guard_implementation.md`

## 1. 目的

Repository hygiene guardが、日本語などASCII以外の文字を含むpathでもGitの表示用引用形式に依存せず、実際のrepository pathを決定論的に検査できることを保証する。

## 2. 問題

`git diff-tree --name-status` の通常テキスト出力は、Git設定やpath内容によってC形式の引用表現を返すことがある。

例:

```text
A\t"tmp/\\346..."
```

この表示用文字列をそのまま `tmp/` 接頭辞判定へ渡すと、実際には禁止pathである `tmp/日本語.txt` を見逃す可能性がある。

## 3. 正本となるpath取得方式

changed path取得は `git diff-tree` の `-z` を使用し、NUL区切りの出力を解析する。

- Gitの表示用quoted pathへ依存しない。
- pathは実際の文字列として取得する。
- rename/copyはstatusと旧path・新pathをNUL区切りtokenとして解析し、検査対象には新pathを使用する。
- malformed token列はPASSへ倒さず `git_inspection_failed` とする。

## 4. 文字コード

Git subprocessのstdoutはUTF-8として扱う。復号できない場合は検査失敗としてfail-closedする。

## 5. 禁止path判定

ASCII / 非ASCIIを区別しない。

次は同じ `prohibited_placeholder_path` として拒否する。

```text
tmp/example.txt
tmp/日本語.txt
tmp/検証/一時.txt
```

## 6. 回帰試験

最低限次を固定する。

1. `tmp/日本語.txt` の追加を拒否する。
2. 通常ASCII pathの既存判定を維持する。
3. rename/copyの新path判定を維持する。
4. malformed NUL token列はfail-closedする。
5. merge commit固有pathの検査を維持する。

## 7. 安全性

この変更はread-only Git inspectionの出力形式だけを変更し、branch/ref/historyへのmutationを追加しない。
