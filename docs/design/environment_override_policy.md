# 環境別override設計方針

## 1. 目的

`config/index.yaml`を入口とする現行設定へ、環境別差分を安全に追加するための最終方針を定める。

現行の次の保証は維持する。

- 各トップレベルキーは単一owner fileだけが所有する
- owner file間のdeep mergeを行わない
- nested importsを禁止する
- 未知キーと重複キーを拒否する
- 設定エラーのsource fileを追跡できる

## 2. 環境の選択

環境名は次で選択する。

```text
AI_LIVER_CONFIG_ENV
```

未指定または空文字の場合はoverrideを適用しない。

環境名には英小文字、数字、ハイフン、アンダースコアだけを許可する。

## 3. manifest形式

`config/index.yaml`へ任意の`environments` mappingを追加する。

```yaml
imports:
  app: runtime.yaml
  services: services.yaml
  # 省略

environments:
  local: environments/local.yaml
  test: environments/test.yaml
```

`environments`は環境名とoverride fileの対応だけを持つ。同じ環境名の重複、空path、未知のmanifestキーは拒否する。

## 4. override file形式

暗黙deep mergeは採用しない。差分は明示的なpath操作として記述する。

```yaml
overrides:
  - path: app.mode
    value: console
  - path: services.ollama.base_url
    value: http://127.0.0.1:11434
  - path: streaming.health_timeout_seconds
    value: 60
```

各operationは`path`と`value`だけを持つ。未知フィールド、重複path、空pathは拒否する。

## 5. v1で許可する変更

v1では、既存設定に存在するleaf値の同型置換だけを許可する。

許可対象：

- string
- integer
- number
- boolean
- nullを許容する既存フィールドへのnull

禁止対象：

- 新しいキーの追加
- 既存キーの削除
- mapping全体の置換
- list全体またはlist要素の置換
- 型の変更
- wildcard
- 配列index指定
- 複数環境の重ね合わせ
- override fileからのimport

listやmappingの変更が必要な場合は、owner fileまたは別のroot manifestを用意する。

## 6. 適用順序

1. root entryを解決する
2. manifestの`imports`を読み込む
3. top-level ownershipを検証する
4. base設定を構成する
5. `AI_LIVER_CONFIG_ENV`を解決する
6. 対象override fileを1回だけ読み込む
7. pathが既存leafを指すことを検証する
8. base値とoverride値の型互換性を検証する
9. overrideを適用したraw mappingを`AppConfig`へ渡す
10. strict parserと参照グラフ検証を実行する

参照グラフはoverride適用後の最終設定だけで検証する。

## 7. source追跡

トップレベルsourceだけではoverride後のエラー元を特定できないため、path単位のsource追跡を追加する。

`ConfigSourceBundle`は次を保持する。

```text
source_by_top_level_key
source_by_yaml_path
```

`source_by_yaml_path`にはoverrideされた完全pathだけを記録する。

`source_for(path)`は次の優先順位でsourceを決定する。

1. 完全一致するoverride path
2. 最長prefixで一致するoverride path
3. top-level owner file
4. root manifest

例：

```text
services.ollama.base_url
→ config/environments/local.yaml

services.ollama.timeout_seconds
→ config/services.yaml
```

## 8. legacy設定との関係

v1のenvironment overrideはmanifest entryにだけ対応する。

legacy単一設定を明示指定した状態で`AI_LIVER_CONFIG_ENV`が設定されている場合は、overrideを無視せず明確な`ConfigError`にする。

これによりlegacy互換経路の意味を変更しない。

## 9. secretの扱い

環境別overrideはsecret管理機能ではない。

API keyやpasswordは既存どおり環境変数名を設定へ記述し、実値はOS、CI、クラウドのsecret機能から取得する。override fileへ実secret値を保存しない。

## 10. エラー方針

次は起動時エラーとする。

- 未登録または不正な環境名
- override fileが存在しない、fileでない、mappingでない
- `overrides`がlistでない
- operationがmappingでない
- 未知operation field
- 重複path、空path、存在しないpath
- mappingまたはlistを指すpath
- 型が異なるvalue
- override後のstrict parserまたは参照グラフ違反
- legacy entryとenvironment overrideの同時使用

エラーにはpath、期待値、実値、source fileを含める。

## 11. テスト方針

最低限、次を固定する。

- 環境未指定時は現行結果と完全一致する
- 登録済み環境のleaf値を置換できる
- 複数owner fileのleafを同一override fileから変更できる
- overrideされたpathだけsourceがoverride fileになる
- overrideされていない兄弟pathは元owner fileをsourceに保つ
- 未登録環境、不正環境名、重複path、未知pathを拒否する
- mapping、list、削除、型変更を拒否する
- override後のmodel／service参照グラフを検証する
- legacy entryとの併用を拒否する
- directory指定とfile指定で同じ結果になる
- `AI_LIVER_CONFIG_PATH`と`AI_LIVER_CONFIG_ENV`の優先関係を固定する

## 12. 実装分割

### Phase 1: manifest schema

- `environments`のstrict parse
- `AI_LIVER_CONFIG_ENV`の解決
- legacy entryとの併用拒否
- environment fileの存在確認

### Phase 2: explicit override engine

- dot path解決
- leaf限定置換
- 型互換性検証
- 重複path拒否

### Phase 3: source tracking

- `source_by_yaml_path`
- 最長prefixによる`source_for`
- override source回帰テスト

### Phase 4: production sample

- `config/environments/local.example.yaml`を追加
- 実環境固有値とsecret実値はコミットしない
- 運用ドキュメントを更新

## 13. 非採用案

次は採用しない。

- owner file同士のdeep merge
- ファイル名規則による自動探索
- `config.local.yaml`などの暗黙読込
- 複数override fileの順序依存合成
- YAML merge key
- nullを削除命令として扱う方式
- listをindex単位で書き換える方式
- override fileによる別override fileのimport

## 14. 完了条件

- 環境未指定時の全体テストが現状どおり成功する
- override適用時もstrict parserと参照グラフ検証を通る
- source追跡がbase ownerとoverride fileを正しく区別する
- deep merge、削除、list変更、型変更ができない
- legacy entryとの同時使用が明示エラーになる
- サンプルにsecret実値が含まれない
