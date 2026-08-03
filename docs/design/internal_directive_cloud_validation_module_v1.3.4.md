# 内部指示器クラウド検証モジュール設計 v1.3.4

## 1. 目的

「強い好奇心で話題を広げる」プリセットへ対象別関心とKnowledge Gapを追加した後、GUI同期処理によって`related_knowledge`内のオブジェクトが次の文字列へ変換される問題を確認した。

```json
{
  "related_knowledge": [
    "[object Object]"
  ]
}
```

この状態ではPlannerへ対象ID、関心値、Knowledge Gapが伝わらず、全体Curiosityだけを理由に質問しない既存制約によって、検証対象の質問許可を確認できない。

## 2. 原因

内部状態GUIの関連知識欄が、文字列配列用の次の処理を使用していた。

- 表示: `String(item)`
- 読み取り: 改行ごとの文字列配列

JavaScriptオブジェクトへ`String`を適用すると`[object Object]`となり、元構造を復元できない。

## 3. 修正方針

関連知識欄は1行1JSONオブジェクトのJSON Lines形式として扱う。

### GUIへ表示

- 文字列項目はそのまま表示する
- オブジェクト項目は`JSON.stringify`で1行JSONへ変換する

### GUIから読み取り

- 各行へ`JSON.parse`を試みる
- JSONオブジェクトとして解析できた行は構造を維持する
- 手動入力された通常文字列は文字列のまま維持する

これにより、プリセット適用、GUI表示、JSON表示、API送信、Exportのすべてで同じオブジェクト構造を保持する。

## 4. 対象プリセット

高好奇心プリセットでは次を維持する。

```json
{
  "target_type": "topic",
  "target_id": "deep_sea_unknown_life",
  "interest": 0.94,
  "known_facts": [
    "深海には未分類の生物が多く存在する"
  ],
  "knowledge_gaps": [
    "未発見生物が多いと考えられている深度や環境"
  ]
}
```

## 5. 画面表示

関連知識欄のPlaceholderを次へ変更する。

```text
1行につきJSONオブジェクト1件
```

複雑な編集は従来どおり内部状態セクションのJSON入力も利用できる。

## 6. テスト

次を完成HTMLの画面契約テストで固定する。

- 高好奇心プリセットの`related_knowledge`が辞書オブジェクトの配列である
- `target_type`、`target_id`、`interest`、`knowledge_gaps`を維持する
- GUI同期処理が`JSON.stringify`と`JSON.parse`を使用する
- 完成HTMLに`[object Object]`が含まれない
- Renderで配信する完成HTMLにも同じ修正が反映される
