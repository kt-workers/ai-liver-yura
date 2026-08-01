# Streaming Plugin分離 ファイル移行マップ v1.0.0

## 1. 前提

- 基準コミット: `bd7f6df05db9a359a8aa66006d15a1898fcd65b2`
- 推奨構成: 単一`streaming` Plugin＋YouTube／OBS／Live Chat Adapter
- 最終Composition Root: `app/bootstrap/streaming_runtime.py`
- 本書は移行先を確定する資料であり、現時点ではファイルを移動しない

優先度はP0が分離の前提、P1がFactory移行、P2が境界完成、P3が互換削除を示す。
互換期間の「2 PR」は、導入PRを含まず、その後の2実装PRを意味する。

## 2. Core entrypoint／Bootstrap

|現在位置|現在責務|最終責務|移動先|変更方法|優先度|先行条件|削除可否|互換期間|
|---|---|---|---|---|---:|---|---|---|
|`app/__main__.py`|Core process入口|Streaming非依存のCore入口|現位置|Streaming module非importテストを追加|P2|Factory移行|不可|なし|
|`app/bootstrap/runtime.py:StreamPreparationRuntime`|Streaming具象の型付き集約|Streaming専用composition result|`app/bootstrap/streaming_runtime.py:StreamingCompositionServices`|機械的移動後、具象fieldをFacade／shared Portへ縮小|P0|なし|旧定義は可|2 PR re-export|
|`app/bootstrap/runtime.py:create_stream_preparation_runtime()`|YouTube／OBS／TTS／Repository／Capability／Usecase構築|Core Runtime構築のみ|Streaming構築は`app/bootstrap/streaming_runtime.py`|関数とhelperを抽出し、最終的に旧関数削除|P0|なし|可|2 PR re-export|
|`app/bootstrap/runtime.py:create_streaming_demo_config()`|Core ConfigをStreaming Demo用に変換|Streaming demo profile生成|`app/bootstrap/streaming_runtime.py`または`app/shared/testing/streaming_demo.py`|Core用設定変換から分離|P2|Config境界|可|2 PR|
|`app/bootstrap/runtime.py`のStreaming `TYPE_CHECKING` import|Streaming具象型解決|なし|削除|抽出時に全件除去|P0|なし|可|なし|
|`app/bootstrap/streaming.py`|Core bridge、Repository、Plugin、Adminの混合composition|一時互換module|`app/bootstrap/streaming_runtime.py`＋Plugin public／Admin adapter|責務ごとに分割し旧pathはre-exportのみ|P0|public contract|可|3 PR|
|`app/bootstrap/streaming.py:RuntimeCoreActivityAdapter`|Plugin Activity/EventをCoreへ変換、Streaming固有enrich|汎用Core Host Bridge|`app/bootstrap/streaming_runtime.py`のprivate host adapter|Streaming固有規則をPlugin public bridgeから注入|P1|public event contract|旧classは可|2 PR|
|`app/bootstrap/streaming.py:DefaultStreamingRepositoryFactory`|In-memory Repository生成|Plugin infrastructure factory|`app/plugins/streaming/infrastructure/repository_factory.py`|Plugin Portを実装し、servicesで注入|P1|Port移設|可|なし|
|`app/bootstrap/streaming.py:StreamingComposition`|Application、Admin、Registry、Broker集約|Facade中心の外側composition result|`app/bootstrap/streaming_runtime.py:StreamingCompositionServices`|具象Application fieldをshared Facadeへ置換|P1|Facade導入|旧型は可|2 PR|
|`app/bootstrap/__init__.py`|Core／Streaming factoryのeager export|Core向けexportのみ|現位置|Streaming exportを削除、専用moduleからimportさせる|P2|専用root安定|一部可|2 PR|
|`app/bootstrap/emotion_runtime.py`|Core factory compatibility|Coreのみ|現位置|Streaming importがないことを固定|P2|境界テスト|不可|なし|
|`app/runtime/runtime_factory.py`|Core／Streaming factory re-export|Core compatibilityのみ|現位置|Streaming symbolを削除|P3|呼出元移行|一部可|2 PR|

## 3. Streaming Plugin

|現在位置|現在責務|最終責務|移動先|変更方法|優先度|先行条件|削除可否|互換期間|
|---|---|---|---|---|---:|---|---|---|
|`app/plugins/youtube_streaming/__init__.py`|空に近いpackage入口|旧plugin ID互換入口|`app/plugins/streaming/__init__.py`|新package公開後にre-export／alias|P3|Factory完成|可|3 PR|
|`app/plugins/youtube_streaming/domain/**`|Session、Readiness、Lifecycle、Comment、YouTubeモデル|platform-neutral Streaming Domain|`app/plugins/streaming/domain/**`|YouTube固有モデルだけ`domain/platform/youtube.py`へ分離|P1|public contract|旧pathは可|3 PR|
|`application/prepare_session.py`|準備、Health、Requirement集約|Streaming preparation usecase|`app/plugins/streaming/application/prepare_session.py`|Port移設に追従|P1|Port移設|旧pathは可|3 PR|
|`application/start_session.py`|OBS開始、YouTube transition|Session start orchestration|`app/plugins/streaming/application/start_session.py`|platform-neutral Port名へ変更|P1|Adapter Port確定|旧pathは可|3 PR|
|`application/end_session.py`|正常終了、緊急停止、補償|Session end orchestration|`app/plugins/streaming/application/end_session.py`|Capability所有権に合わせる|P1|Capability設計|旧pathは可|3 PR|
|`application/opening.py`、`main_segment.py`、`lifecycle_gate.py`|配信進行とCore Activity gate|Streaming進行|`app/plugins/streaming/application/**`|Core bridgeをshared Protocolへ限定|P1|public activity contract|旧pathは可|3 PR|
|`application/live_chat_poller.py`|YouTube chat pollとPlugin Event化|platform chat polling|`app/plugins/streaming/application/live_chat_poller.py`|YouTube DTOをplatform-neutral DTOへ変換|P1|Live Chat Port移設|旧pathは可|3 PR|
|`application/comment_moderation.py`|コメントモデレーション|Streaming固有moderation|`app/plugins/streaming/application/comment_moderation.py`|`AppConfig`型依存をPlugin config Protocolへ置換|P1|Plugin config|旧pathは可|3 PR|
|`application/comment_ranking.py`|ランキング|Streaming固有ranking|`app/plugins/streaming/application/comment_ranking.py`|`CommentRankingConfig`をPlugin内へ移設|P1|Plugin config|旧pathは可|3 PR|
|`application/comment_response.py`|コメント応答|Streaming固有response|`app/plugins/streaming/application/comment_response.py`|`CommentResponseConfig`をPlugin内へ移設|P1|Plugin config|旧pathは可|3 PR|
|`application/service.py`|全Usecase集約、Admin向け操作面|Plugin内部orchestrator|`app/plugins/streaming/application/service.py`|外部公開をFacadeへ限定し1000行級classを分割|P1|Facade contract|旧pathは可|3 PR|
|`ports/core_activity.py`|Core Activity／Event gateway|shared Host gateway|`app/shared/contracts/plugins/streaming_host.py`|Streaming非依存の最小Protocolだけsharedへ昇格|P0|契約レビュー|旧pathは可|2 PR|
|`ports/repositories.py`|Repository Factory|Plugin内部Port|`app/plugins/streaming/ports/repositories.py`|`Any`を段階的に型付きProtocolへ変更|P1|Domain配置|旧pathは可|3 PR|
|`ports/runtime_components.py`|12個の`Any` fieldを持つruntime view|廃止|型付きFactory services／Facade|fieldごとのProtocolへ分解|P1|Factory context|可|1 PR|
|`public/registration.py`|旧PluginRegistry用Command／Query／Activity登録|互換dispatch Adapter|`app/plugins/streaming/public/dispatch.py`|Capability宣言はPlugin本体へ移しdispatchだけ残す|P2|Capability統合|可|2 PR|
|`public/activity_provider.py`|ActivitySpec生成|Streaming public activity provider|`app/plugins/streaming/public/activity_provider.py`|shared契約依存を維持|P1|package移設|旧pathは可|3 PR|
|`public/evidence.py`|Manual check recorder Protocol|Streaming public evidence Port|`app/plugins/streaming/public/evidence.py`|維持しPlugin Factory serviceへ追加|P1|Factory context|旧pathは可|3 PR|
|`public/views.py`|DomainからAdmin向けdictへ変換|型付きpublic view mapper|`app/plugins/streaming/public/views.py`|Admin Facade DTOへ変換|P1|Facade contract|旧pathは可|3 PR|
|新規`factory.py`|なし|単一Streaming Plugin生成|`app/plugins/streaming/factory.py`|configurationと共有servicesだけを使用|P1|Port／Facade確定|不可|なし|
|新規`plugin.py`|なし|Lifecycle、Capability、Facade実装|`app/plugins/streaming/plugin.py`|PluginManager契約とAdmin Facadeを実装|P1|Capability統合|不可|なし|
|新規`public/facade.py`|なし|Core Host／Adminの公開契約|`app/plugins/streaming/public/facade.py`|Plugin内部classを隠す|P0|なし|不可|なし|

## 4. YouTube Adapter

|現在位置|現在責務|最終責務|移動先|変更方法|優先度|先行条件|削除可否|互換期間|
|---|---|---|---|---|---:|---|---|---|
|`app/adapters/youtube/google_youtube_auth_service.py`|OAuth|YouTube infrastructure|現位置または`plugins/streaming/infrastructure/youtube/`|Adapter固有configのみ受ける|P1|YouTube Port|不可|なし|
|`google_youtube_client_factory.py`|Google client生成|YouTube infrastructure factory|同上|外部SDK生成を局所化|P1|Auth config|不可|なし|
|`google_youtube_preparation_adapter.py`|broadcast／stream／health|YouTube preparation Adapter|同上|Plugin Port実装へ追従|P1|Port移設|不可|なし|
|`google_youtube_streaming_control_adapter.py`|broadcast transition|Broadcast control Adapter|同上|generic broadcast Portも実装|P1|Port移設|不可|なし|
|`google_youtube_live_chat_adapter.py`|Live Chat read|Chat read Adapter|同上|platform-neutral DTOへ変換|P1|Chat Port|不可|なし|
|`youtube_api_error_mapper.py`|Google error→Port error|Adapter内部mapper|同上|維持|P1|Port error移設|不可|なし|
|`models.py`|Google DTO変換用model|Adapter内部model|同上|Plugin Domain importをpublic DTO依存へ縮小|P1|public DTO|不可|なし|
|新規`runtime_factory.py`|なし|YouTube Adapter bundle生成|`app/adapters/youtube/runtime_factory.py`|Outer rootからAdapter configを受ける|P1|Adapter config|不可|なし|

## 5. OBS Adapter

|現在位置|現在責務|最終責務|移動先|変更方法|優先度|先行条件|削除可否|互換期間|
|---|---|---|---|---|---:|---|---|---|
|`app/adapters/obs/obs_websocket_client_factory.py`|OBS client生成|OBS infrastructure factory|現位置またはPlugin infrastructure配下|Adapter configだけを受ける|P1|OBS Port|不可|なし|
|`obs_websocket_preparation_adapter.py`|scene／source／health|OBS preparation Adapter|同上|Plugin public snapshotへ変換|P1|Port移設|不可|なし|
|`obs_websocket_streaming_control_adapter.py`|配信出力start／stop|Streaming output control Adapter|同上|generic output Portを実装|P1|Port移設|不可|なし|
|`obs_error_mapper.py`、`obs_status_mapper.py`、`models.py`|OBS内部変換|Adapter内部|同上|Fakeから参照させない|P1|Fake error契約|不可|なし|
|新規`runtime_factory.py`|なし|OBS Adapter bundle生成|`app/adapters/obs/runtime_factory.py`|Outer rootからAdapter configを受ける|P1|Adapter config|不可|なし|

## 6. Streaming Adapter／Repository

|現在位置|現在責務|最終責務|移動先|変更方法|優先度|先行条件|削除可否|互換期間|
|---|---|---|---|---|---:|---|---|---|
|`app/adapters/streaming/__init__.py`|全具象とOBS具象のbarrel export|薄い互換export|各具象moduleを直接import|OBS cross importを除去|P1|builder導入|可|2 PR|
|`fake_streaming_control.py`|Fake YouTube／OBS control|Plugin test/demo Adapter|`app/plugins/streaming/infrastructure/fake/control.py`|OBS error mapper依存をshared Port errorへ変更|P1|error契約|旧pathは可|2 PR|
|`fake_*_preparation_adapter.py`|Fake preparation|Plugin test/demo Adapter|`plugins/streaming/infrastructure/fake/`|Plugin Portへ追従|P1|Port移設|旧pathは可|2 PR|
|`fake_live_chat_adapter.py`|Fake Live Chat|Plugin test/demo Adapter|同上|platform-neutral DTOへ追従|P1|Chat Port|旧pathは可|2 PR|
|`health_adapters.py`|TTS／Avatar health|Streaming dependency health Adapter|`plugins/streaming/infrastructure/health.py`|Voice Output capability queryへの置換を検討|P2|Capability統合|旧pathは可|2 PR|
|`in_memory_*repository.py`|Session／Comment／Opening／Main永続化|Plugin既定infrastructure|`plugins/streaming/infrastructure/repositories/`|Plugin内Factoryから生成|P1|Repository Port|旧pathは可|3 PR|
|`yaml_run_of_show_repository.py`|Run of Show読込|Plugin infrastructure|`plugins/streaming/infrastructure/run_of_show.py`|path configだけを受ける|P1|Plugin config|旧pathは可|3 PR|
|`preparation_publisher.py`|準備結果publish|Plugin event publisher Adapter|`plugins/streaming/infrastructure/events.py`|shared Event Brokerへ統合|P1|Event contract|旧pathは可|2 PR|
|`fake_output_adapters.py`|Demo出力|Streaming demo fixture|`app/shared/testing/streaming_demo.py`付属Adapter|Core runtimeのdemo分岐から分離|P2|Demo entrypoint|旧pathは可|2 PR|

## 7. Port／Shared Contract

|現在位置|現在責務|最終責務|移動先|変更方法|優先度|先行条件|削除可否|互換期間|
|---|---|---|---|---|---:|---|---|---|
|`app/ports/streaming_control.py`|OBS／YouTube制御Port|Plugin内部platform-neutral Port|`app/plugins/streaming/ports/control.py`|旧pathは一方向re-export|P0|なし|可|3 PR|
|`app/ports/streaming_preparation.py`|Preparation／Repository Port|Plugin内部Port|`app/plugins/streaming/ports/preparation.py`|Plugin Domainへの逆依存を解消|P0|Domain配置|可|3 PR|
|`app/ports/youtube_live_chat.py`|YouTube DTO／read Port|Plugin内部Chat Port|`app/plugins/streaming/ports/chat.py`|generic message DTOへ変更|P0|public DTO|可|3 PR|
|`app/ports/youtube_errors.py`|YouTube error contract|YouTube Adapter Port error|`app/plugins/streaming/ports/platform_errors.py`|platform codeをmetadata化|P1|Adapter移行|可|3 PR|
|`app/ports/comment_moderation.py`|Streaming moderation Port|Plugin内部Port|`app/plugins/streaming/ports/moderation.py`|移動＋re-export|P1|Plugin config|可|3 PR|
|`app/ports/comment_ranking.py`|Ranking Port|Plugin内部Port|`app/plugins/streaming/ports/ranking.py`|Plugin Domain逆依存を解消|P1|Domain配置|可|3 PR|
|`app/ports/comment_response.py`|Comment response Port|Plugin内部Port|`app/plugins/streaming/ports/response.py`|Plugin Domain逆依存を解消|P1|Domain配置|可|3 PR|
|`app/shared/contracts/plugins/runtime/**`|汎用Plugin Runtime契約|Core／Plugin共有|現位置|Streaming固有型を追加しない|P0|なし|不可|なし|
|新規`streaming_host.py`|なし|Core Host Bridge最小契約|`app/shared/contracts/plugins/streaming_host.py`|Activity/Eventの汎用Protocolだけ定義|P0|契約レビュー|不可|なし|

## 8. Capability基盤

|現在位置|現在責務|最終責務|移動先|変更方法|優先度|先行条件|削除可否|互換期間|
|---|---|---|---|---|---:|---|---|---|
|`app/core/plugins/plugin_manager.py`|Plugin lifecycle／Capability|Streamingを含む正規authority|現位置|Command／Query dispatch bridgeを追加|P0|dispatch方針|不可|なし|
|`app/core/plugins/capability_registry.py`|可用性／Health正本|正規authority|現位置|Streaming HealthをReporter経由で受ける|P0|Capability mapping|不可|なし|
|`app/core/plugins/static_provider.py`|非Plugin source互換provider|Streamingでは不使用|現位置|Streaming利用を除去。全体削除は別監査|P2|Streaming Plugin化|条件付き|なし|
|`app/shared/plugin_host/**`|Command／Query／Activity dispatch|一時dispatch互換層|shared dispatch gatewayまたはPluginManagerへ統合|Adapter化して可用性を持たせない|P0|統合判断|条件付き|2 PR|
|`app/shared/contracts/plugins/registration/**`|旧PluginRegistration契約|dispatch互換契約|現位置またはruntime契約へ統合|Health／Lifecycle重複を除去|P2|PluginManager統合|条件付き|2 PR|

## 9. Admin

|現在位置|現在責務|最終責務|移動先|変更方法|優先度|先行条件|削除可否|互換期間|
|---|---|---|---|---|---:|---|---|---|
|`app/admin_api/__main__.py`|Config、Runtime具象、OBS設定を読む入口|Streaming Admin process入口|`app/admin_api/__main__.py`|`compose_streaming_admin()`だけを呼ぶ|P2|Facade／専用root|不可|なし|
|`app/admin_api/service.py`|dispatch、Streaming状態整形、診断|Admin application service|現位置または`app/admin/streaming/service.py`|`StreamingAdminFacade`だけに依存|P2|Facade|旧pathは可|2 PR|
|`app/admin_api/server.py`|REST／SSE／HTTP error|Admin HTTP Adapter|現位置|Facade DTOだけを受ける|P2|Admin service|不可|なし|
|`app/admin_api/console.py`|YouTube／OBS表示、設定、snapshot|Admin presentation|`app/admin/streaming/presentation.py`候補|Config／Trace具象をAdapterへ分離|P2|Admin DTO|旧pathは可|2 PR|
|`app/admin_api/__init__.py`|Admin public export|HTTP factory export|現位置|Plugin service具象exportを除去|P2|Facade|不可|なし|
|`gui/yura-streaming-admin/**`|Streaming管理UI|Streaming Admin UI|現位置またはPlugin付属UI package|versioned Admin DTOだけに依存|P2|API versioning|不可|API 1 version|

## 10. Config

|現在位置|現在責務|最終責務|移動先|変更方法|優先度|先行条件|削除可否|互換期間|
|---|---|---|---|---|---:|---|---|---|
|`AppConfig.streaming`|全Streaming設定|外側で読む互換設定|Plugin opaque config|Composition Rootで正規化|P2|Factory config|可|3 PR|
|`Streaming*Settings`|Readiness／OBS／Demo／Comment設定|Plugin config＋Adapter config|`plugins/streaming/config.py`とAdapter config|Config型を分割|P2|public config schema|旧型は可|3 PR|
|`service_schema.YouTube*`|YouTube service設定|YouTube Adapter config|Adapter factory module|外側mapperを追加|P2|YouTube builder|旧型は可|3 PR|
|`service_schema.Obs*`|OBS service設定|OBS Adapter config|Adapter factory module|外側mapperを追加|P2|OBS builder|旧型は可|3 PR|
|`app.mode=streaming_demo`|CoreとStreaming demo切替|Streaming entrypoint profile|Streaming専用CLI／config|Core modeから分離|P2|Demo composition|旧値は可|2 PR|
|`plugins.registrations`|Plugin有効設定|Streaming enabled／config reference|現位置|`streaming` registrationを正規入口にする|P1|Factory|不可|なし|

## 11. Tests

|現在位置|現在責務|最終責務|移動先|変更方法|優先度|先行条件|削除可否|互換期間|
|---|---|---|---|---|---:|---|---|---|
|`tests/test_stream_preparation_factory.py`|巨大Runtime factoryのAdapter選択|Streaming composition contract|`tests/streaming/test_composition.py`|YouTube／OBS builder単体とcompositionへ分割|P0|Root抽出|旧testは可|2 PR|
|`tests/test_prepare_stream_session_usecase.py`等|Usecase単体|Plugin application単体|`tests/plugins/streaming/`|import path追従|P1|package移設|旧pathは可|なし|
|`tests/test_streaming_plugin_registration.py`|旧Registry registration|Factory／Capability／Facade契約|`tests/plugins/streaming/test_factory.py`等|PluginManager基準へ変更|P1|Factory|旧testは可|1 PR|
|`tests/integration/test_streaming_vertical_flow.py`|Core＋Streaming vertical flow|Facade越しvertical flow|現位置|具象Application importを除去|P2|Facade|不可|なし|
|`tests/test_stream_preparation_ui.py`、`test_stream_start_api.py`|Admin API|Facade contract＋HTTP Adapter|`tests/admin/streaming/`候補|Runtime dataclass生成をfixtureから除去|P2|Admin移行|旧pathは可|なし|
|`tests/test_streaming_demo*.py`|Demo end-to-end|専用demo composition|現位置|Core modeへの依存を除去|P2|Demo config|不可|なし|
|`tests/test_plugin_separation_boundaries.py`|Bootstrap 6 import baseline|空baseline固定|現位置|PR 6／7で縮小、PR 8で空にする|P0|Factory移行|不可|なし|
|`tests/dependency_boundary_baseline.json`|Adapter横断違反2件ほか|Streaming関連0件|現位置|builder／shared error移行時に2件削除|P1|Adapter分離|不可|なし|
|新規`tests/test_core_without_streaming.py`|なし|物理非搭載Core起動保証|同path|import blocker＋最小Config＋capability検査|P2|Factory／Config分離|不可|なし|
|新規Admin境界テスト|なし|Admin→Facade以外の依存禁止|`tests/test_streaming_admin_boundaries.py`|AST import検査|P2|Facade|不可|なし|

## 12. baseline 6 importの削除割当

|baseline import|現在の発生源|削除PR|
|---|---|---:|
|`app.plugins.youtube_streaming.application`|`runtime.py`のTYPE_CHECKING／関数内import|PR 6|
|`app.plugins.youtube_streaming.domain`|`runtime.py`の関数内import|PR 6|
|`app.plugins.youtube_streaming.application.service`|`bootstrap/streaming.py`|PR 7|
|`app.plugins.youtube_streaming.public.activity_provider`|`bootstrap/streaming.py`|PR 7|
|`app.plugins.youtube_streaming.public.evidence`|`bootstrap/streaming.py`|PR 7|
|`app.plugins.youtube_streaming.public.registration`|`bootstrap/streaming.py`|PR 7|

PR 7で空集合にし、PR 8で再増加を禁止する。
