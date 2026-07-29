# Streaming Plugin分離 再監査 v1.0.0

## 1. 文書情報

- 基準ブランチ: `feature/plugin-separation-development`
- 基準コミット: `bd7f6df05db9a359a8aa66006d15a1898fcd65b2`
- 調査日: 2026-07-30
- 対象: Streaming Session、YouTube、OBS、Live Chat、Streaming Admin
- 性質: 実装前の再監査。コード、Config、schema、migrationは変更しない

本書は、Factory移行済みのGames、Voice Output、Relationship Memory、
Agent Memory、LLM Providerに続いて、Streaming subsystemをCoreから分離する
ための現状判断を確定する。

## 2. 結論

推奨構成は、**単一の`streaming` Pluginと、注入されるYouTube／OBS／Live
Chat Adapter**である。

- Session、Preparation、Readiness、Run of Show、Comment、Lifecycleは
  一つの整合性境界であり、単一Pluginが所有する
- YouTube、OBS、Live ChatはPluginではなく、交換可能な外部I/O Adapterとする
- Plugin Factoryは具体Adapterを生成せず、共有Portとしてservicesから受け取る
- 最終Composition Rootは`app/bootstrap/streaming_runtime.py`とする
- Core entrypointはこのComposition Rootをimportしない
- AdminはPlugin内部classやRuntime dataclassではなく、
  `StreamingAdminFacade`だけに依存する
- Capabilityの可用性・Healthの正本は`PluginManager`／`CapabilityReporter`へ統一する
- 現在の`PluginRegistry`はCommand／Query／Activity dispatchの互換層として
  段階的に縮小し、`StaticCapabilityProvider`は廃止する

複数Pluginへの分割は、Session開始・終了の原子性、Plugin間依存、Config、
障害時の補償処理を増やすため、現段階では採用しない。将来Twitch等を追加する
場合も、platform Adapterを差し替えることで対応する。

## 3. 現状

### 3.1 二つのComposition Root

Streaming構築は現在二段に分かれている。

1. `app/bootstrap/runtime.py:create_stream_preparation_runtime()`
   - YouTube／OBS／TTS Adapter選択・生成
   - Repository、Publisher、Usecase生成
   - Readiness、Requirements生成
   - `CapabilityRegistry`／`StaticCapabilityProvider`生成
   - Demo用status列注入
   - `StreamPreparationRuntime`生成
2. `app/bootstrap/streaming.py:compose_streaming()`
   - `StreamingApplicationService`生成
   - Comment系Repository Factory生成
   - Core Runtime Bridge生成
   - 旧`PluginRegistry`への`PluginRegistration`登録
   - `AdminApiService`生成
   - Config内部を読むAdmin向けstatus lambda生成

`runtime.py`から一部が`bootstrap/streaming.py`へ抽出済みではあるが、責務分離は
完了していない。外部I/O構築とPlugin Application構築が別々のBootstrapに残り、
両者を`StreamPreparationRuntime`という具象集約dataclassで接続している。

### 3.2 現在の実行入口

|入口|Streaming依存|評価|
|---|---|---|
|`app/__main__.py`|`app.bootstrap.runtime`だけを静的import。Streaming構築関数は呼ばない|Core単独入口として概ね正常|
|`app/admin_api/__main__.py`|`app.bootstrap`からStreaming構築を静的importし、ConfigとOBS設定内部を読む|Streaming専用入口だが境界が太い|
|`app/bootstrap/__init__.py`|CoreとStreamingの両方を eager import|package importだけでStreaming graphをロードする危険|
|`app/runtime/runtime_factory.py`|`runtime.py`のStreaming factoryを再export|Compatibility負債|

`python -m app`は現在、YouTube／OBS Adapterを実行時importしない。ただし
`runtime.py`自身がStreaming dataclass、Config型、TYPE_CHECKING import、動的構築
関数を保持するため、物理削除可能なCoreにはなっていない。

## 4. 現在の依存グラフ

```text
app.__main__
  -> bootstrap.runtime
       -> Core Runtime / Core Adapter
       -> [TYPE_CHECKING] Streaming Plugin / Ports / Repository具象
       -> [関数内dynamic import] Streaming / YouTube / OBS具象

admin_api.__main__
  -> bootstrap.__init__
       -> bootstrap.runtime
       -> bootstrap.streaming
            -> Streaming Adapter具象
            -> Streaming Application Service / public registration
            -> Core RuntimeCoordinator
            -> AdminApiService

Streaming Application
  -> Streaming Domain
  -> app.ports.streaming_* / youtube_* / comment_*
  -> app.config.app_config
  -> shared Plugin Event / Activity契約

YouTube / OBS / Streaming Adapter
  -> Streaming Domainまたはapp.ports
  -> 外部SDK

AdminApiService / HTTP
  -> shared PluginRegistry / dispatch契約
  -> Streaming capability名とYouTube／OBS状態shape
```

### 4.1 ファイル単位の主要依存

|Source|Target|load種別|分類|判断|
|---|---|---|---|---|
|`app/__main__.py`|`app.bootstrap.runtime`|実行時静的|正常|Core入口はStreaming compositionを呼ばない|
|`app/bootstrap/runtime.py`|Streaming Adapter／Plugin／Port|関数内動的|移行負債、責務混在|Core Composition RootにStreaming外部I/O構築が残る|
|`app/bootstrap/runtime.py`|Streaming具象型|`TYPE_CHECKING`|移行負債|実行時非importだが物理分離と境界baselineを妨げる|
|`app/bootstrap/streaming.py`|Streaming Plugin public/application|実行時静的|移行負債|既存6 importのうち4件を所有|
|`app/bootstrap/streaming.py`|`app.adapters.streaming`|実行時静的|責務混在|Repository具象をBootstrapが生成|
|`app/bootstrap/streaming.py`|Core domain/runtime|実行時静的|Compositionとして一部正常|YouTube固有event enrichまで担う点は過剰|
|`app/bootstrap/streaming.py`|`app.admin_api.service`|実行時静的|責務混在、循環危険|Plugin compositionがAdmin compositionまで所有|
|`app/bootstrap/__init__.py`|`bootstrap.streaming`|実行時静的|移行負債|Core向けpackage importでもStreamingを巻き込む|
|`app/admin_api/__main__.py`|`app.bootstrap`|実行時静的|移行負債|Streaming専用public composition入口がない|
|`app/admin_api/service.py`|shared Plugin host|実行時静的|構造上正常|実態はStreaming capability名と状態shapeへ固定|
|`app/admin_api/server.py`|`AdminApiService`|実行時静的|正常|HTTP Adapterとして分離可能|
|`youtube_streaming/application/**`|`youtube_streaming/domain/**`|実行時静的|正常|Plugin内向き依存|
|`youtube_streaming/application/**`|`app.ports.streaming_*`等|実行時静的|移行負債|Plugin専用Portがglobal Port namespaceにある|
|`youtube_streaming/application/comment_*`|`app.config.app_config`|実行時静的|明確な境界違反|Plugin applicationが全体Config型を直接知る|
|`youtube_streaming/application/start_session.py`|`app.utils.trace`|実行時静的|移行負債|shared observability契約へ寄せる|
|`app/ports/streaming_preparation.py`|Streaming Domain|実行時静的|明確な逆依存|global Portが具体Plugin domainをimport|
|`app/ports/comment_*`|Streaming Domain|実行時静的|明確な逆依存|所有者をPlugin内Portへ戻す必要がある|
|`app/adapters/youtube/**`|Streaming Domain／YouTube Port|実行時静的|配置上の移行負債|依存方向自体はAdapter→Port/Domainで正常|
|`app/adapters/obs/**`|Streaming Domain|実行時静的|配置上の移行負債|Plugin slice外にあるため物理削除単位にならない|
|`app/adapters/streaming/__init__.py`|`app.adapters.obs`|実行時静的|既知の横断違反|dependency baseline登録済み|
|`fake_streaming_control.py`|OBS error mapper|実行時静的|既知の横断違反|FakeがOBS具象エラーを借用|
|`public/registration.py`|Application Service|実行時静的|Plugin内部では正常|Bootstrapが直接importすることが負債|
|`public/activity_provider.py`|shared registration契約|実行時静的|正常|Core Activity具象を知らない|

### 4.2 正常な依存

- Plugin DomainはPlugin外のCore Runtime、Adapter、Adminをimportしない
- YouTube／OBS Adapterは外部I/OとPlugin Port／Domainの変換を担当する
- `public/activity_provider.py`はshared `PluginActivitySpec`を返す
- `AdminApiService`のCommand／Query dispatch自体はshared契約を使用する
- `app/__main__.py`はStreaming Admin、YouTube、OBSを直接importしない

### 4.3 明確な問題

1. `runtime.py`にCoreとStreamingのComposition Rootが共存する
2. `bootstrap/streaming.py`がPlugin、Core Bridge、Repository、Adminを同時に構築する
3. global `app.ports`がPlugin Domainをimportする逆依存がある
4. Plugin Applicationがglobal `AppConfig`の具体設定型をimportする
5. `PluginManager`、`CapabilityRegistry`、`PluginRegistry`の三層が併存する
6. `StaticCapabilityProvider`と`PluginRegistration`が同じStreaming capabilityを
   異なるモデルで管理する
7. Adminはshared dispatcherを使う一方、capability名、YouTube／OBS status shape、
   Config由来runtime statusを固定で知る
8. `app.bootstrap`のeager exportがCore importとStreaming importを再結合する
9. Adapter横断依存が2件baseline化されている

### 4.4 循環依存の危険

現時点でPython import cycleは顕在化していないが、次の経路は拡張時に循環しやすい。

```text
bootstrap.streaming
  -> admin_api.service
  -> shared PluginRegistry
  -> Plugin registration
  -> Streaming application
  -> Core bridge supplied by bootstrap.streaming
```

また、`app.ports -> Plugin Domain`という逆依存があるため、Plugin側へPortを戻す
際に互換re-exportを双方向に置くとcycleが発生する。互換moduleは旧pathから新pathへの
一方向re-exportに限定する。

## 5. 責務境界

### 5.1 Core側に残す

- 配信に依存しない会話、自律活動、感情、記憶
- 共通Activity、Event、Actionと安全制御
- Plugin Factory／Loader／Manager
- shared Plugin Event／Activity／Capability契約
- Pluginが発行した汎用EventとActivityをCoreへ変換する最小Host Adapter
- Pluginなしでの起動、診断、正常終了

Coreは`YOUTUBE_COMMENT`、OBS scene、broadcast status、Run of Showを判断しない。
必要なevent type変換規則はStreaming Pluginのpublic bridgeから提供する。

### 5.2 Streaming Plugin側へ移す

- Session、Preparation、Start、End、Emergency Stop
- Readiness、Requirements、Run of Show、Lifecycle Gate
- Opening、Main、Closing
- Live Chat poll、Moderation、Ranking、Response
- Streaming capability宣言とHealth変換
- Streaming repository Portと既定Repository Factory
- YouTube／OBS lifecycleのオーケストレーション
- `StreamingPublicFacade`、`StreamingAdminFacade`
- Streaming固有DTO、view、event enrichment規則

### 5.3 Adapter側に残す

- Google YouTube API、OAuth、Client Factory、retry、error mapping
- OBS WebSocket、接続、retry、status mapping
- Fake／Disabled I/O
- concrete health check
- YAML／In-memoryなどRepository実装

AdapterはAppConfig全体を受けず、Adapter固有config dataclassとPlugin Portだけを
受け取る。

### 5.4 Admin側に残す

- FastAPI REST／SSE
- 認証、HTTP error mapping
- Operator command受付
- 状態・診断表示
- Admin独自DTO、UI用整形、snapshot保存

AdminはPlugin内部Application Service、具体Adapter、In-memory Repository、
AppConfig内部構造を参照しない。

## 6. Plugin構成の比較

|評価軸|案A: 単一Streaming Plugin|案B: 複数Plugin|
|---|---|---|
|Coreからの独立|高い。単一Factoryを無効化可能|高いがHost設定が複雑|
|Plugin間依存|なし|Session→YouTube→OBS→Chat等が発生|
|単独無効化|Adapter capability単位で可能|Plugin単位で明示的|
|差し替え|Port注入で可能|Provider選択機構が別途必要|
|テスト容易性|一つのvertical sliceで検証可能|契約テストは増えるが組合せが爆発|
|Config複雑性|一つのPlugin config|依存Pluginごとに重複しやすい|
|Capability粒度|一つのPlugin内で細分化可能|細かいが所有権調停が必要|
|障害分離|Capability単位のdegradedで対応|process内では完全隔離にならない|
|実装工数|中|大|
|Twitch拡張|platform Port追加で対応|新PluginとSession依存更新が必要|
|OBSなし配信|Disabled Adapter＋readiness設定|依存Plugin optional化が必要|
|YouTubeなしローカル配信|Local/Fake Adapterで対応|Session Pluginの条件分岐が必要|
|AdminなしCore|Admin Adapterを構築しなければ成立|成立するがregistry配線が増える|

**案Aを採用する。** Plugin名はplatformを限定する`youtube_streaming`から
`streaming`へ最終的に変更する。旧plugin IDは互換期間中だけaliasとして扱う。

## 7. Composition Rootの最終配置

最終配置は`app/bootstrap/streaming_runtime.py`とする。

このmoduleはStreaming専用entrypointからだけimportされ、次を担当する。

- AppConfigからPlugin configとAdapter configへの変換
- 選択されたYouTube／OBS／Live Chat／Health Adapter Factoryの呼出し
- Repository／Publisher具象生成
- servicesを組み立ててStreaming Plugin Factoryへ渡す
- Plugin初期化後の`StreamingPublicFacade`取得
- 任意のCore Host BridgeとAdmin HTTP Adapterの接続

Plugin内部の`factory.py`は、注入済みPortとPlugin configからPluginを生成する。
具体Adapter、OAuth、WebSocket、AppConfigをimportしない。

`app/plugins/streaming/bootstrap.py`へ外部I/O構築を置く案は、PluginからConfigと
Adapter具象への外向き依存を作るため採用しない。`app/admin/streaming_runtime.py`
案も、Adminなしの配信実行やCore Bridge利用をAdmin配下へ従属させるため採用しない。

## 8. Factory／Loader適用範囲

### 8.1 適用する範囲

- Streaming全体を一つの`StreamingPluginFactory`で生成する
- `register_optional_plugin_from_factory()`で有効時だけ動的import・登録する
- Plugin configurationにはStreaming固有の正規化済みmappingを渡す
- servicesには共有Port、Repository Factory、Publisher、Event Brokerを渡す
- Plugin objectは`StreamingPublicFacade`と`StreamingAdminFacade`の共有Protocolを
  実装する
- 外側には型付き`StreamingCompositionServices` dataclassを返す

### 8.2 適用しない範囲

- YouTube／OBSを別Plugin Factoryにしない
- Plugin Factory内でGoogle／OBS／Fake Adapterを生成しない
- Plugin Managerから複数UsecaseやRepository具象を直接返さない
- AdminがFactory contextやPlugin具象を参照しない

単一Plugin戻り値だけでLifecycleとCapability登録は足りるが、AdminとHostが使う
操作面には型付きFacadeが必要である。FacadeはPlugin自身が実装し、初期化済みPluginを
共有Protocolへcastして取得する。

## 9. Capability設計

### 9.1 所有権

|Capability群|所有者|備考|
|---|---|---|
|`stream.session.*`|`streaming`|prepare/start/end/emergency/status|
|`stream.readiness.*`|`streaming`|依存Adapter Healthを集約|
|`stream.activity.*`|`streaming`|CoreへActivitySpecを提供|
|`stream.comment.*`|`streaming`|poll/moderation/ranking/response|
|`stream.broadcast.*`|`streaming`|platform非依存のgeneric操作|
|`youtube.*`|`streaming`|YouTube Adapter有効時だけ公開する具体capability|
|`obs.*`|`streaming`|OBS Adapter有効時だけ公開する具体capability|
|`output.cancel`|Voice Output／Core Output provider|Streamingは要求側であり所有しない|

### 9.2 無効・縮退

- Streaming無効: Plugin未import、未登録、Streaming capabilityなし
- YouTube無効: `youtube.*`は非公開。local/fake broadcast providerがあれば
  `stream.broadcast.*`は公開可能
- OBS無効: `obs.*`は非公開。`require_obs=False`ならSessionは継続可能
- required Adapter unavailable: `stream.session.prepare`をunavailable
- optional Adapter degraded: Session capabilityはdegraded、原因をHealthへ保持
- Provider障害: 関係する具体capabilityを失効し、Session capabilityを再評価

### 9.3 Registry統合

可用性とHealthの正本は`PluginManager`内の`CapabilityRegistry`とする。
`CapabilityReporter`へReadiness結果を報告し、Adminも同じHealth snapshotを読む。

旧`PluginRegistry`はCommand／Query／Activity dispatchを提供する一方、
`PluginManager`はLifecycle／Availabilityを提供している。移行中はdispatch Adapterを
置くが、同一capabilityの可用性を両方へ登録しない。`StaticCapabilityProvider`と
`StreamPreparationRuntime.capability_registry`はStreaming Plugin移行時に削除する。

## 10. Config境界

|設定|最終所有|
|---|---|
|Plugin enabled、config reference|Core `plugins.registrations.streaming`|
|readiness、run of show、moderation、ranking、response、health timeout|Streaming Plugin config|
|YouTube OAuth、timeout、retry、privacy|YouTube Adapter config|
|OBS接続、scene、source、retry|OBS Adapter config|
|Admin host、port、token、log表示|Admin Adapter config／環境変数|
|Demo broadcast、status sequence、Fake I/O|Streaming test/demo profile|
|`app.mode=streaming_demo`|専用Streaming entrypoint optionへ移しCore modeから除外|

当面は`AppConfig.streaming`と`services.youtube/obs`を外側Composition Rootで
正規化して渡す。将来は`plugins.registrations.streaming.config_reference`と
opaque configへ分割し、service schemaもAdapter registry側へ移す。

## 11. Admin境界

Adminは現在、具体AdapterやPlugin Application classを直接importしてはいない。
しかし次へ意味的に直接依存している。

- YouTube／OBS固有capability名
- Runtime statusの`adapter_modes`、`obs_connection`、`streaming_capabilities`
- Session／Opening／Main／End query結果の内部shape
- `bootstrap/streaming.py`が読む`runtime_components.config.services["obs"]`
- `admin_api/__main__.py`が読む`runtime.config`と`runtime.usecase`

`StreamingAdminFacade`を導入し、次だけを公開する。

- `execute(command: StreamingAdminCommand) -> AdminCommandResult`
- `query(query: StreamingAdminQuery) -> AdminView`
- `health_snapshot() -> StreamingHealthView`
- `diagnostic_snapshot() -> StreamingDiagnosticView`
- `subscribe() -> AsyncIterator[StreamingAdminEvent]`

HTTP routeとSSEはFacadeだけに依存する。Command／Query capability文字列の変換は
Plugin public層に置き、Admin独自DTOへの整形はAdmin層に残す。

## 12. Core単独成立条件

次をすべて満たした状態を完了とする。

1. `app/__main__.py`からCoreが起動する
2. Streaming Plugin packageを削除してもCore importが成功する
3. YouTube／OBS／Streaming Adapter packageを削除してもCore importが成功する
4. Streaming Adminを起動しなくてもCoreが会話、自律活動、感情、記憶を利用できる
5. Core起動時にStreaming、YouTube、OBS、Admin moduleを`sys.modules`へロードしない
6. Streaming capabilityがPlugin Managerに存在しない
7. 非搭載は警告・例外ではなく正常な状態として診断される
8. Core Configの読込にYouTube／OBS service定義を必須としない
9. `app.bootstrap.__init__`がStreamingをeager importしない
10. `app/runtime/runtime_factory.py`がStreaming factoryを再exportしない

追加テストは`tests/test_core_without_streaming.py`に置き、module import遮断、
最小Config、テキスト会話、自律Activity、capability非存在を検証する。

## 13. Bootstrap migration baseline

現在のbaselineは次の6件である。

```python
{
    "app.plugins.youtube_streaming.application",
    "app.plugins.youtube_streaming.application.service",
    "app.plugins.youtube_streaming.domain",
    "app.plugins.youtube_streaming.public.activity_provider",
    "app.plugins.youtube_streaming.public.evidence",
    "app.plugins.youtube_streaming.public.registration",
}
```

削除計画:

- PR 6で`application`と`domain`を削除する
- PR 7で`application.service`、`public.activity_provider`、
  `public.evidence`、`public.registration`を削除する
- PR 7完了時にbaselineを空集合とする
- PR 8で空集合を固定し、Bootstrap全体、Core entrypoint、Admin entrypointを
  別々に検査する

Admin entrypointには、Plugin public facade以外のPlugin内部、Core Runtime内部、
具体YouTube／OBS Adapterを静的importしない境界テストを追加する。

## 14. 既存文書との整合

- `plugin_separation_audit_v1.0.0.md`の「単一Streaming vertical slice」、
  「Repository FactoryをPluginへ」、「Admin分離」という方向を維持する
- 同文書では`app/bootstrap/streaming.py`の責務集中を主に扱うが、本再監査では
  `runtime.py:create_stream_preparation_runtime()`にも大半の外部I/O構築が残ることを
  追加で明確化した
- `plugin_separation_file_map_v1.0.0.md`の`app/plugins/streaming/**`への整理方針を
  維持する
- 旧file mapの「YouTube／OBS AdapterをPlugin付属Adapterへ移動候補」は、
  **所有はStreaming slice、依存方向はAdapter→Plugin Port**と具体化する
- `plugin_migration_roadmap_v1.0.0.md`のPhase Eを、本監査の10 PRへ分解する
- Voice／Memory監査で確立した「Factoryは具体Adapterを生成しない」方針を
  Streamingにも適用する
- 旧文書の`develop`直Base記述は当時の運用であり、今回の実装PRは最新
  `feature/plugin-separation-development`をBaseとする

## 15. 未確定事項

実装開始前または該当PRで決める事項は次のとおり。

1. plugin IDを`youtube_streaming`から`streaming`へ変更する互換期間
2. `PluginRegistry` dispatch機能を`PluginManager`へ統合するか、独立Hostとして残すか
3. Twitch追加時のplatform Adapter選択をConfig module pathにするかregistryにするか
4. Streaming eventをCore `AgentEventType`へ変換する正規shared契約
5. Admin SSE eventのversioningと後方互換期間
6. Run of Show永続化をPlugin既定実装にするか外部必須serviceにするか
7. Streaming固有Configファイルの配置名とsecret参照方式
8. `output.cancel`をVoice Outputと汎用Outputのどちらが最終所有するか
9. YouTubeなし本番配信のplatform-neutral broadcast Port要件
10. 旧`app.ports.*` re-exportを何リリース維持するか

これらは単一Plugin採用、Composition Root配置、最初の実装PR着手を妨げない。
