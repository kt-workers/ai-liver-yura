# Streaming Plugin移行ロードマップ v1.0.0

## 1. 方針

- 基準コミット: `bd7f6df05db9a359a8aa66006d15a1898fcd65b2`
- すべての実装PRは、その時点の最新
  `feature/plugin-separation-development`から分岐する
- PR Baseは`feature/plugin-separation-development`
- 1 PRにつき一つのrollback可能な責務単位とする
- `develop`へ直接入れない
- 各PRは関連テスト、全体テスト、Ruff、`git diff --check`成功までDraftを維持する
- Factory内で具体Adapterを生成しない
- Core entrypointへStreaming登録処理を追加しない

実装は次の10 PRに分割する。

```text
PR 1 Composition Root抽出
  -> PR 2 Public contract／Facade
    -> PR 3 Capability authority統合
      -> PR 4 YouTube Adapter builder
        -> PR 5 OBS Adapter builder
          -> PR 6 Streaming Plugin Factory
            -> PR 7 Admin Facade／動的composition
              -> PR 8 境界・Core単独保証
                -> PR 9 Config／Demo分離
                  -> PR 10 Compatibility削除
```

## 2. PR 1: Streaming Composition Rootを`runtime.py`から抽出

### 目的

`StreamPreparationRuntime`、`create_stream_preparation_runtime()`、
`create_streaming_demo_config()`とStreaming専用helperをCore Runtimeの
Composition Rootから機械的に分離する。挙動とimport方式は変えない。

### Base

最新`feature/plugin-separation-development`

### 主な変更ファイル

- `app/bootstrap/runtime.py`
- 新規`app/bootstrap/streaming_runtime.py`
- `app/bootstrap/__init__.py`
- `app/runtime/runtime_factory.py`
- `tests/test_stream_preparation_factory.py`
- `tests/test_runtime_factory_typed_boundary.py`

### 先行PR

なし。本ロードマップで最初に実装する。

### 完了条件

- `runtime.py`にStreaming dataclass、構築関数、Streaming `TYPE_CHECKING` importがない
- 既存call siteは一時re-export経由で同じ挙動を維持する
- Fake／Google YouTube、Fake／Disabled／WebSocket OBS選択が不変
- migration baselineの6件はまだ変更しない

### テスト範囲

- Runtime factory
- Stream preparation factory
- Streaming demo
- Production config split
- import smoke
- 全体テスト

### 想定リスク

- import順変更
- re-exportによるcycle
- dataclass annotation解決の差

### rollback単位

新moduleとre-exportを丸ごと戻せる。Domain、Adapter、Configは変更しない。

## 3. PR 2: Streaming public contracts／Facadeを確定

### 目的

Core HostとAdminがPlugin内部Application ServiceやRuntime dataclassを参照しないための
型付き公開境界を追加する。

### Base

PR 1マージ後の最新集約ブランチ

### 主な変更ファイル

- 新規`app/plugins/streaming/public/facade.py`
- 新規`app/shared/contracts/plugins/streaming_host.py`
- `app/plugins/youtube_streaming/ports/core_activity.py`
- `app/plugins/youtube_streaming/public/views.py`
- contract tests

### 先行PR

PR 1

### 完了条件

- `StreamingPublicFacade`と`StreamingAdminFacade`のProtocolが確定
- Host Activity/Event、Admin Command／Query／Health DTOが型付き
- Facade contractはCore Runtime、Admin、具体Adapter、AppConfigをimportしない
- 現行Serviceを包む互換Facadeが存在する

### テスト範囲

- Facade contract
- Activity provider
- public view mapping
- Plugin architecture boundary

### 想定リスク

- 現在dictで返すAdmin payloadの項目漏れ
- Event型を早期に固定しすぎる

### rollback単位

新Facadeとwrapperだけを戻せる。既存call pathは残す。

## 4. PR 3: Capability Registry／Plugin lifecycleの正本を統合

### 目的

Streamingで併存する`PluginRegistry`、`PluginManager`、
`CapabilityRegistry`、`StaticCapabilityProvider`の役割を整理し、
可用性・Healthを`PluginManager`側へ一本化する。

### Base

PR 2マージ後の最新集約ブランチ

### 主な変更ファイル

- `app/core/plugins/plugin_manager.py`
- `app/core/plugins/capability_registry.py`
- `app/shared/plugin_host/**`
- `app/shared/contracts/plugins/registration/**`
- `app/plugins/youtube_streaming/public/registration.py`
- `tests/test_capability_health.py`
- `tests/test_streaming_plugin_registration.py`

### 先行PR

PR 2

### 完了条件

- 同じcapabilityを二つのRegistryへ可用登録しない
- Command／Query／Activity dispatchは互換Adapter経由で継続
- Streaming Healthを`CapabilityReporter`へ変換できる
- `output.cancel`をStreaming所有capabilityから外す
- `StaticCapabilityProvider`削除に必要な置換契約が確定

### テスト範囲

- Capability health／recovery
- Plugin lifecycle
- dispatch policy
- Streaming registration
- degraded／unavailable matrix

### 想定リスク

- Adminのcapability一覧変化
- Plugin start／stop順序
- Healthとdispatch availabilityの一時的不一致

### rollback単位

dispatch Adapter単位で旧Registryを再有効化できる。DomainとAdapterは変更しない。

## 5. PR 4: YouTube Adapter組み立てを分離

### 目的

Google／Fake／Unavailable YouTube、OAuth、Client Factory、Streaming Control、
Live Chatの生成を外側Composition RootからAdapter bundle factoryへ隔離する。

### Base

PR 3マージ後の最新集約ブランチ

### 主な変更ファイル

- 新規`app/adapters/youtube/runtime_factory.py`
- `app/adapters/youtube/**`
- `app/bootstrap/streaming_runtime.py`
- `app/ports/youtube_live_chat.py`
- `app/ports/youtube_errors.py`
- YouTube Adapter tests

### 先行PR

PR 3

### 完了条件

- Outer rootはYouTube service typeをAdapter configへ変換してfactoryを呼ぶだけ
- Adapter factoryはAppConfig全体を受けない
- Google設定不足は既存Unavailable動作を維持
- Fake／Demo status sequenceは明示的なtest profileから注入
- OAuth、timeout、retry、privacy設定の既存挙動を維持

### テスト範囲

- Google auth／error mapper／preparation
- Live Chat Adapter
- Fake／Google／Unavailable選択
- 外部接続なしfactory tests

### 想定リスク

- OAuth secret pathの変換漏れ
- Fakeとreal OBS併用時のspecial status設定
- Retry設定の型変換差

### rollback単位

YouTube bundle factory呼出しだけを旧inline constructionへ戻せる。

## 6. PR 5: OBS Adapter組み立てを分離

### 目的

Fake／Disabled／OBS WebSocketの生成をOBS bundle factoryへ隔離し、
Adapter横断依存baseline 2件を解消する。

### Base

PR 4マージ後の最新集約ブランチ

### 主な変更ファイル

- 新規`app/adapters/obs/runtime_factory.py`
- `app/adapters/obs/**`
- `app/adapters/streaming/__init__.py`
- `app/adapters/streaming/fake_streaming_control.py`
- `app/bootstrap/streaming_runtime.py`
- `tests/dependency_boundary_baseline.json`
- OBS Adapter tests

### 先行PR

PR 4

### 完了条件

- Outer rootはOBS Adapter bundleを受け取るだけ
- FakeがOBS具象error mapperをimportしない
- `app.adapters.streaming.__init__`が`app.adapters.obs`をimportしない
- websocket URL、host、port、password env、retryの既存解決順を維持
- dependency boundary baselineからStreaming関連2件を削除

### テスト範囲

- OBS preparation／streaming control
- Fake／Disabled／WebSocket選択
- error mapping
- dependency boundaries

### 想定リスク

- URLと個別host設定の優先順位
- Disabled OBS時のreadiness
- Fake error codeの互換性

### rollback単位

OBS bundle factoryとcross-adapter error契約を一括で戻せる。

## 7. PR 6: Session／Preparationを単一Streaming Plugin Factoryへ移行

### 目的

Domain、Usecase、Repository Factory、Readiness、Session lifecycleを所有する
単一`StreamingPlugin`を追加し、既存Factory／Loader基盤から登録する。

### Base

PR 5マージ後の最新集約ブランチ

### 主な変更ファイル

- 新規`app/plugins/streaming/plugin.py`
- 新規`app/plugins/streaming/factory.py`
- 新規`app/plugins/streaming/config.py`
- `app/plugins/youtube_streaming/domain/**`
- `app/plugins/youtube_streaming/application/**`
- `app/plugins/youtube_streaming/ports/**`
- `app/plugins/streaming/infrastructure/**`
- `app/bootstrap/streaming_runtime.py`
- `tests/test_plugin_separation_boundaries.py`

### 先行PR

PR 5

### 完了条件

- Plugin Factoryは具体AdapterとAppConfigをimportしない
- configurationは正規化済みStreaming mapping
- servicesはYouTube／OBS／Chat／Health Port、Repository Factory、
  Publisher、Host Gateway
- Plugin無効時はmodule非import・未登録
- Adapterなし／optional degraded／required unavailableが明示的
- Factoryから返るPluginはFacade Protocolを実装
- baselineから`application`と`domain`を削除し、残り4件にする

### テスト範囲

- Factory validation
- Session preparation／start／end
- Opening／Main／Comment pipeline
- Capability matrix
- Plugin disabled non-import
- vertical flow

### 想定リスク

- 1000行超のApplication Service分割
- Usecase共有Repositoryのidentity
- Plugin初期化中のHealth取得
- old plugin ID互換

### rollback単位

Factory登録を無効化し、旧Streaming constructionへ戻せる。Adapter builderは維持可能。

## 8. PR 7: Adminをpublic Facadeへ移行し動的compositionを完成

### 目的

`bootstrap/streaming.py`のPlugin具象importを除去し、AdminとCore Hostを
初期化済みFacadeへ接続する。Bootstrap migration baselineを空にする。

### Base

PR 6マージ後の最新集約ブランチ

### 主な変更ファイル

- `app/bootstrap/streaming_runtime.py`
- `app/bootstrap/streaming.py`
- `app/admin_api/__main__.py`
- `app/admin_api/service.py`
- `app/admin_api/server.py`
- `app/admin_api/console.py`
- `app/plugins/streaming/public/facade.py`
- `tests/test_plugin_separation_boundaries.py`
- Admin API tests

### 先行PR

PR 6

### 完了条件

- Adminは`StreamingAdminFacade`だけに依存
- Admin entrypointはRuntime dataclass、Usecase、Config services内部を読まない
- Core Host BridgeはPlugin内部classをimportしない
- `bootstrap/streaming.py`は互換re-exportのみ、または削除可能
- baselineの残り4件を削除し空集合にする
- REST／SSE payload互換を維持

### テスト範囲

- Admin REST／SSE
- Console／diagnostics／settings
- Stream start API
- Plugin registration／lifecycle
- empty migration baseline

### 想定リスク

- UIが依存する非公開dict field
- lifespan start／stop順序
- Event Broker購読解除

### rollback単位

Admin Facade Adapterを旧`AdminApiService` wiringへ戻せる。Plugin Factoryは維持可能。

## 9. PR 8: Core単独起動と境界テストを強化

### 目的

Streaming package、YouTube／OBS Adapter、Adminが物理的に存在しない状態を模擬し、
Coreが正常な非搭載状態として成立することを固定する。

### Base

PR 7マージ後の最新集約ブランチ

### 主な変更ファイル

- 新規`tests/test_core_without_streaming.py`
- 新規`tests/test_streaming_admin_boundaries.py`
- `tests/test_plugin_separation_boundaries.py`
- `tests/test_architecture_boundaries.py`
- `app/bootstrap/__init__.py`
- `app/runtime/runtime_factory.py`

### 先行PR

PR 7

### 完了条件

- Core entrypoint import時にStreaming／YouTube／OBS／Admin moduleが未ロード
- import blocker下でCore Runtime生成、会話、Activity、感情、記憶が成立
- Streaming capabilityが存在しない
- 空のBootstrap migration baselineが再増加しない
- Admin entrypointがPlugin内部、Core Runtime内部、具体Adapterを静的importしない

### テスト範囲

- Core smoke／conversation／autonomous activity
- memory／emotion
- AST import boundaries
- module load assertions
- 全体テスト

### 想定リスク

- test moduleの先行importによる偽陽性／偽陰性
- compatibility exportからの間接import

### rollback単位

境界テストとeager export削除を一括で戻せる。

## 10. PR 9: Streaming Config／Demo／Fake境界を分離

### 目的

`AppConfig.streaming`、YouTube／OBS service schema、`app.mode=streaming_demo`を
Plugin config、Adapter config、Streaming専用profileへ段階移行する。

### Base

PR 8マージ後の最新集約ブランチ

### 主な変更ファイル

- `app/config/app_config.py`
- `app/config/service_schema.py`
- `app/plugins/streaming/config.py`
- `app/adapters/youtube/runtime_factory.py`
- `app/adapters/obs/runtime_factory.py`
- `app/shared/testing/streaming_demo.py`
- Streaming settings／demo tests

### 先行PR

PR 8

### 完了条件

- Core最小ConfigにStreaming、YouTube、OBS設定が不要
- Streaming有効時だけPlugin config referenceを解決
- Adapterは固有config型だけを受ける
- DemoはCore modeではなくStreaming専用profileで構築
- 旧Config pathはdeprecation付きで互換変換

### テスト範囲

- Config validation
- Production config split
- Streaming settings
- Demo end-to-end
- Core minimal config

### 想定リスク

- 配置済みConfigとの互換
- secret環境変数名の移行
- CLI／運用手順の変更

### rollback単位

Config mapperを旧path優先へ戻せる。Plugin／Adapter構造は維持可能。

## 11. PR 10: Compatibility pathと旧`youtube_streaming`構造を削除

### 目的

観測期間後に旧re-export、旧plugin ID、旧Port、旧Runtime factory、
旧Registry経路を削除し、最終構造を固定する。

### Base

PR 9マージ後、互換利用がないことを確認した最新集約ブランチ

### 主な変更ファイル

- `app/plugins/youtube_streaming/**`
- `app/plugins/streaming/**`
- `app/ports/streaming_*.py`
- `app/ports/youtube_*.py`
- `app/bootstrap/streaming.py`
- `app/runtime/runtime_factory.py`
- `app/shared/plugin_host/**`
- imports／tests／docs

### 先行PR

PR 9と互換利用調査

### 完了条件

- 正規plugin IDは`streaming`
- 旧`youtube_streaming` importとIDが0件
- 旧global Streaming Port re-exportが0件
- `StaticCapabilityProvider`をStreamingが利用しない
- 旧Runtime factory re-exportが0件
- dependency baselineにStreaming項目が0件
- 全体テスト、Admin UI smoke、運用確認が成功

### テスト範囲

- repository-wide import search
- Core without Streaming
- Streaming vertical flow
- Admin API／UI
- Config migration
- 全体テスト

### 想定リスク

- 外部scriptや未追跡consumerの旧import
- plugin IDを永続化した診断データ
- Admin UIの旧capability名

### rollback単位

Compatibility re-exportだけを復活できる。新構造は戻さない。

## 12. baseline縮小タイムライン

|時点|Bootstrap具体Plugin import baseline|
|---|---:|
|現在|6|
|PR 1〜5|6|
|PR 6|4|
|PR 7|0|
|PR 8以降|0を固定|

## 13. 最初に実装すべきPR

最初に実装するのは**PR 1: Streaming Composition Rootを`runtime.py`から抽出**である。

理由:

- Domainや外部I/Oの挙動を変えずに責務の物理境界を作れる
- 後続のFactory、Adapter builder、Admin Facadeの変更先を
  `streaming_runtime.py`へ一本化できる
- rollbackが単純で、現在の全Streamingテストをそのまま回帰利用できる
- Core `runtime.py`のStreaming `TYPE_CHECKING`／dynamic import負債を先に除去できる

PR 1ではFactory化、Capability統合、Config変更、Admin変更を同時に行わない。

## 14. 各PR共通の検証

```bash
.venv/bin/python -m pytest -q <関連テスト>
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check <変更したPythonファイル>
git diff --check
```

ドキュメントだけのPRではコードテストを必須とせず、Markdown lint環境がある場合は
lintし、変更ファイルが意図した文書だけであることを確認する。
