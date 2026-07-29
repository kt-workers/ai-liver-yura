# Relationship Memory Plugin Factory移行監査 v1.0.0

## 1. 目的

Relationship Memory Pluginを既存のPlugin Factory／Loader基盤へ移行する前に、現在の依存関係、生成責務、初期化条件、失敗時挙動、必要テストを整理する。

この監査では実装コードと`app/bootstrap/runtime.py`を変更しない。

## 2. 現状

`app/plugins/relationship_memory/__init__.py`は`RelationshipMemoryPlugin`のみを公開しており、`plugin_factory`は存在しない。

`RelationshipMemoryPlugin`は`SnapshotStore[MemoryT] | None`を受け取る。Plugin自身はJSONやPostgreSQLなどの具体Storeを生成しない。

- Plugin ID: `relationship_memory`
- Capability: `memory.relationship`
- Storeあり: HealthyとしてCapabilityを公開
- Storeなし: 登録・初期化はできるがCapabilityを公開しない縮退状態
- `load()`または`save()`失敗: Capabilityを利用不可へ変更し、例外を再送出

## 3. 責務境界

Factory移行後も、以下はComposition Root側へ残す。

1. 設定読込
2. 具体Store Adapterの選択と生成
3. Storeのライフサイクル管理
4. Coreの関係性記憶処理へ共有契約として渡す処理

Factoryへ移すのは`RelationshipMemoryPlugin(store)`という具体Plugin生成だけとする。

## 4. 推奨Factory入力

`PluginFactoryContext.services`から共有Store契約を受け取る。

```python
{
    "relationship_memory_store": relationship_memory_store,
}
```

Factoryは具体Storage Adapterをimportしない。Storeが`None`でもPlugin生成を許容し、既存の縮退初期化を維持する。

## 5. 依存方向

```text
Composition Root
  -> Plugin Loader / Factory契約
  -> 文字列モジュール名 app.plugins.relationship_memory

Relationship Memory Factory
  -> Shared SnapshotStore契約
  -> RelationshipMemoryPlugin

RelationshipMemoryPlugin
  -> Shared contractsのみ
```

最終的に`app/bootstrap/runtime.py`から`RelationshipMemoryPlugin`の静的importを削除する。

## 6. 既存テストで保証されている契約

`tests/test_relationship_memory_plugin.py`では次を保証している。

- Store経由の保存・読込
- 正常時のCapability公開
- Store失敗時のCapability喪失
- Store例外の再送出

Factory移行でこれらを変更してはいけない。

## 7. 追加テスト

### Factory単体テスト

- servicesからStoreを受け取りPluginを生成する
- Storeが`None`でもPluginを生成できる
- 不正型は明確な`TypeError`にする
- Factoryが具体Storage Adapterをimportしない

### Loader／登録テスト

- 無効時に`app.plugins.relationship_memory`をimportしない
- 有効時にFactory経由で登録する
- Store不在時でも登録自体は成功する
- Store不在時にCapabilityを公開しない

### Runtime・境界テスト

- `runtime.py`から静的importを削除できている
- 無効設定でCoreが起動できる
- 正常StoreでCapabilityが利用可能になる
- Store不在でもCoreが起動を継続する
- PluginとFactoryが具体Storage Adapterへ依存しない

## 8. 推奨PR分割

### PR 1: Factory追加

- `app/plugins/relationship_memory/factory.py`
- `plugin_factory`公開
- Factory単体テスト

`runtime.py`は変更しない。

### PR 2: Runtime統合

Games PluginのRuntime Factory統合後に行う。

- 静的import削除
- Factory経由登録への置換
- 境界baseline更新
- Runtime統合テスト

## 9. 並行可能範囲

Games対応を待たずに実施可能:

- Factory追加
- Factory単体テスト
- Shared contracts依存確認
- Runtime統合テスト設計

Games対応完了前に実施しない:

- `runtime.py`の登録置換
- 境界baselineからRelationship Memory例外を削除
- Gamesと同一PRでのRuntime変更

## 10. 完了条件

- `app.plugins.relationship_memory`が`plugin_factory`を公開する
- FactoryがShared `SnapshotStore`を受け取る
- Factoryが具体Storage Adapterを生成しない
- 無効時にPluginモジュールをimportしない
- Runtimeが具体Pluginを静的importしない
- Store不在時の縮退挙動を維持する
- Store失敗時のCapability喪失と例外再送出を維持する
- 関連テストと全体テストが成功する
