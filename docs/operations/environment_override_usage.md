# 環境別設定override運用ガイド

## 目的

環境別overrideは、本番設定のownership分割を維持したまま、ローカル開発など特定環境で必要なleaf値だけを明示的に差し替える仕組みです。

暗黙的なdeep mergeは行いません。既存設定の構造変更、新規キー追加、mappingやlist全体の置換には使用できません。

## 基本的な使い方

通常起動では環境別overrideは適用されません。

```bash
python -m app
```

`local`環境を選択する場合は、`AI_LIVER_CONFIG_ENV`を指定します。

```bash
AI_LIVER_CONFIG_ENV=local python -m app
```

設定入口を明示する場合も、manifest形式の`config/index.yaml`を使用します。

```bash
AI_LIVER_CONFIG_PATH=config/index.yaml \
AI_LIVER_CONFIG_ENV=local \
python -m app
```

legacy単一設定である`config/config.yaml`と`AI_LIVER_CONFIG_ENV`は併用できません。

## manifestへの登録

環境名とoverride fileの対応は`config/index.yaml`の`environments`に記載します。

```yaml
environments:
  local: environments/local.example.yaml
```

環境名には英小文字、数字、ハイフン、アンダースコアだけを使用できます。

## override file形式

環境ファイルのトップレベルには`overrides`だけを記載します。

```yaml
overrides:
  - path: trace.level
    value: DEBUG
  - path: input_receivers.timer.interval_seconds
    value: 5.0
```

各operationで指定できるfieldは`path`と`value`だけです。

## 許可される変更

- 既に存在するleaf値の置換
- 元の値と同じscalar型への置換
- `float`項目に対する`int`値の指定
- 1つのenvironment file内で異なるpathを複数指定

## 拒否される変更

- 存在しないpathへの新規キー追加
- mappingまたはlist全体の置換
- 値の削除
- scalar型の変更
- `bool`と`int`の相互置換
- 同じpathの重複指定
- 空pathまたは空segmentを含むpath
- environment fileへの未知field追加

不正なoverrideが1件でもある場合、全operationは適用されません。

## source追跡

設定検証エラーのsource fileはpath単位で解決されます。

- overrideされたpath: environment file
- overrideされていない兄弟path: 元のowner file
- top-level ownership外: root manifest

これにより、環境別の値に問題がある場合は該当environment fileがエラー元として表示されます。

## 秘密情報の扱い

リポジトリへ保存するenvironment fileに、APIキー、パスワード、トークン、秘密鍵などの実値を記載してはいけません。

秘密情報は既存の環境変数・secret管理機構を使用してください。environment overrideは、ログレベル、タイムアウト、ローカル接続先など、リポジトリへ保存して安全な非機密値だけを対象とします。

## 新しい環境を追加する手順

1. `config/environments/<environment>.example.yaml`を追加する。
2. `config/index.yaml`の`environments`へ環境名と相対pathを登録する。
3. 既存leafだけを同型値でoverrideしていることを確認する。
4. 秘密情報が含まれていないことを確認する。
5. `AI_LIVER_CONFIG_ENV=<environment>`を指定して全体テストまたは起動確認を行う。

## local.example.yaml

`config/environments/local.example.yaml`は、そのまま実行可能な安全な例です。ローカル開発で詳細ログと短いtimer intervalを試す用途を想定しています。
