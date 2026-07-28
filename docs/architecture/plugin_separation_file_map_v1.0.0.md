# プラグイン分離ファイルマップ

**Document Version:** v1.0.0  
**基準コミット:** `91bdb8a8f358b48ef6e102c6a83d0ccc7013c470`  
**関連文書:** `plugin_separation_audit_v1.0.0.md`

## 1. 目的

現行ファイルをCore、Plugin、Adapter、shared/contracts、Composition Root、Compatibility、削除候補へ分類し、移行先と実施Phaseを明確にする。

本書は実装変更を指示する設計資料であり、このPhaseではファイル移動・削除を行わない。

## 2. 分類記号

|分類|意味|
|---|---|
|Core|ゆら自身の自律活動・会話・感情・記憶・活動制御に必要|
|Plugin|なくてもCoreが成立する任意機能|
|Adapter|外部SDK、API、DB、デバイスとの具体接続|
|Shared|CoreとPlugin間で共有する安定契約|
|Composition|具象を組み立てる起動時配線|
|Compatibility|移行期間だけ保持する旧import pathまたは変換層|
|Delete|重複解消後に削除する旧実装|

## 3. Core・Plugin基盤

|現行ファイル|現在の責務|分類|目標位置・方針|Phase|主な回帰テスト|
|---|---|---|---|---:|---|
|`app/core/plugins.py`または`app/core/plugins/`|Plugin Manager、Capability管理|Core|CoreのPlugin基盤として維持|1-2|Pluginゼロ構成、障害隔離|
|`app/shared/contracts/plugins/runtime.py`|Plugin Context、Command、Result、Gateway|Shared|公開契約として維持し、Core private型を排除|1-2|PluginからRuntime具象import禁止|
|`app/shared/contracts/plugins/registration.py`|Capability Registration、Lifecycle|Shared|汎用Plugin登録契約として維持|1-2|無効Pluginが登録されない|
|`app/shared/plugin_host.py`|Registry、Command/Query/Activity Dispatcher|Core|汎用Hostとして維持|1-2|未知Capability拒否、失敗隔離|
|`app/runtime/plugin_activity_coordinator.py`|Plugin ActivityとCore Activityの調停|Core|具体Plugin名を知らない状態で維持|1|Core→Plugin具象import禁止|
|`app/runtime/plugin_ongoing_activity_synchronizer.py`|Plugin継続活動の同期|Core|汎用契約のみを利用|1|PluginなしでRuntime構築|
|`app/runtime/activity_registry.py`|Activity Definition登録|Core|Capability経由の動的登録へ統一|2|有効PluginだけDefinition登録|

## 4. Composition Root・起動経路

|現行ファイル|現在の責務|分類|目標位置・方針|Phase|主な回帰テスト|
|---|---|---|---|---:|---|
|`app/__main__.py`|Core起動、Console/Web入力受付|Core/Composition|Core単独起動入口として維持。任意Pluginを静的importしない|2|Pluginディレクトリなしで起動|
|`app/bootstrap/runtime.py`|Core構築、全Adapter生成、全Plugin登録|Composition|`core_runtime.py`と`plugin_host.py`へ分割。具象Plugin importを除去|2,6|Pluginゼロ、Voiceなし、Storageなし|
|`app/bootstrap/runtime_composition_root.py`|Runtime内部コンポーネント生成|Core/Composition|Core内部配線専用として維持|1-2|具象Plugin名が存在しない|
|`app/bootstrap/streaming.py`|Streaming具象構築、Core接続、Admin生成|Plugin Composition|Streaming Plugin側のFactoryへ移し、Core側は汎用接続のみ|4-5|Streaming物理削除でCore起動|
|`app/bootstrap/runtime_preflight.py`|設定事前検証|Composition|無効Pluginの設定・SDKを要求しない検証へ変更|2|無効Plugin設定欠落を許容|
|`app/config/app_config.py`|Core・全Plugin設定の統合型|Compatibility/Composition|Core設定とPlugin設定を分離。旧設定は互換層を経て廃止|2,8|Plugin設定なしでCore設定読込|
|`config/config.yaml`|全機能設定|Composition|Core設定とPlugin単位設定ファイルへ段階分割|2,8|最小Core設定で起動|

## 5. Games / Shiritori

|現行ファイル|現在の責務|分類|目標位置・方針|Phase|主な回帰テスト|
|---|---|---|---|---:|---|
|`app/plugins/games/plugin.py`|Games Plugin本体|Plugin|Games Plugin Factoryから生成|2-3|無効時にimportされない|
|`app/plugins/games/game_engine.py`|ゲームセッションと定義管理|Plugin|Games内に維持|3|Games単体テスト|
|`app/plugins/games/activity_factory.py`|Game Activity生成|Plugin|Games内に維持|3|Core型への依存禁止|
|`app/plugins/games/activity_matcher.py`|ゲーム開始・停止文の一致判定|Plugin|Games内に維持|3|しりとり以外へ拡張可能|
|`app/plugins/games/intent/interpreter.py`|ゲームIntent解釈|Plugin|Games内に維持|3|LLMなしfallback|
|`app/plugins/games/intent/validator.py`|ゲームCommand検証|Plugin|Games内に維持|3|不正Command拒否|
|`app/plugins/games/intent/prompt.py`|ゲーム固有Prompt|Plugin|Games内に維持|3|Core Promptからゲーム文言排除|
|`app/plugins/games/shiritori/definition.py`|しりとり定義|Plugin|`games/shiritori`に維持|3|Definition登録条件|
|`app/plugins/games/shiritori/rules.py`|しりとりルール|Plugin|`games/shiritori`に維持|3|ルール単体テスト|
|`app/plugins/games/shiritori/state.py`|しりとり状態|Plugin|`games/shiritori`に維持|3|状態遷移テスト|
|`app/plugins/games/shiritori/service.py`|しりとり進行|Plugin|`games/shiritori`に維持|3|開始・継続・終了|
|`app/domain/games/shiritori.py`|旧しりとりDomain|Delete/Compatibility|新Plugin型へのre-export後に削除|3,8|旧import利用箇所ゼロ|
|`app/domain/games/__init__.py`|旧ゲームDomain公開|Delete/Compatibility|段階的廃止|3,8|Coreからgame型消失|
|`app/runtime/shiritori_game_service.py`|旧しりとりRuntime処理|Delete|Plugin Serviceへ一本化後に削除|3|通常会話回帰|
|`app/runtime/game_input_classifier.py`|旧ゲーム入力分岐|Delete|Plugin Intent Interpreterへ一本化|3|Coreに`shiritori`分岐なし|
|`app/adapters/prompt/simple_prompt_builder.py`|汎用Prompt内のゲーム文脈混在候補|Core/Compatibility|ゲーム固有文脈をPlugin Prompt Providerへ移す|3|GamesなしPrompt生成|

## 6. Streaming / YouTube / OBS

|現行ファイル・範囲|現在の責務|分類|目標位置・方針|Phase|主な回帰テスト|
|---|---|---|---|---:|---|
|`app/plugins/youtube_streaming/domain/**`|配信Session、Lifecycle、Comment各モデル|Plugin|`app/plugins/streaming/**`配下へ整理|4|Plugin単体Domainテスト|
|`app/plugins/youtube_streaming/application/**`|Opening/Main/End、Polling、Moderation、Ranking、Response|Plugin|Streaming Plugin内に維持|4|CoreなしでUseCase単体テスト|
|`app/plugins/youtube_streaming/ports/**`|Core Activity、Repository、Runtime Components契約|Plugin/Shared|Coreとの境界だけSharedへ昇格し、Streaming内部PortはPlugin内維持|4|Plugin→Runtime具象禁止|
|`app/plugins/youtube_streaming/public/registration.py`|Command/Query/Activity Capability登録|Plugin|Plugin公開入口として維持|4|Capability一覧テスト|
|`app/plugins/youtube_streaming/public/activity_provider.py`|Streaming Activity仕様生成|Plugin|Plugin内に維持|4|Core Activityへの汎用変換|
|`app/adapters/youtube/**`|YouTube API・OAuth|Adapter|Streaming Plugin付属Adapterへ移動候補|4|Fake/Real差し替え|
|`app/adapters/obs/**`|OBS WebSocket|Adapter|Streaming Plugin付属Adapterへ移動候補|4|OBSなし縮退|
|`app/adapters/streaming/**`|Streaming Repository、Fake、変換|Plugin Adapter|Streaming Plugin内`infrastructure`へ移動|4|Adapter間横断依存ゼロ|
|`app/ports/streaming_control.py`|OBS/YouTube制御Port|Compatibility/Plugin Port|Streaming Plugin内Portへ移動。旧pathを一時re-export|4,8|Core importから消失|
|`app/ports/streaming_preparation.py`|Run of Show等のPort|Plugin Port|Streaming Plugin内へ移動|4|Core importから消失|
|`app/ports/youtube_live_chat.py`|ライブチャットPort/DTO|Plugin Port|Streaming Plugin内へ移動|4|CoreがYouTube DTOを知らない|
|`app/bootstrap/streaming.py:RuntimeCoreActivityAdapter`|Core/Plugin変換とYouTube固有処理|Composition|汎用Activity AdapterとStreaming Event Bridgeへ分割|4|Coreに`YOUTUBE_COMMENT`処理なし|
|`app/bootstrap/streaming.py:DefaultStreamingRepositoryFactory`|Streaming Repository生成|Plugin Adapter|Plugin内Factoryへ移動|4|BootstrapからRepository具象消失|

## 7. Streaming Admin

|現行ファイル・範囲|現在の責務|分類|目標位置・方針|Phase|主な回帰テスト|
|---|---|---|---|---:|---|
|`app/admin_api/service.py`|Streaming状態集約、Command/Query dispatch|Plugin|`plugins/streaming/administration`へ移動|5|CoreなしでAdmin Serviceテスト|
|`app/admin_api/console.py`|配信診断・表示モデル|Plugin|Streaming Administrationへ移動|5|OBS/YouTube表示テスト|
|`app/admin_api/**`のHTTP入口|Streaming管理API|Plugin Adapter|Streaming Plugin付属APIとして起動|5|AdminなしでCore起動|
|`gui/yura-streaming-admin/**`|配信専用管理UI|Plugin UI|Streaming Plugin付属UIとして管理|5|Core汎用画面との独立起動|
|`gui/yura-inner-state-visualizer/**`|ゆらの汎用状態表示|Core UI/Adapter|Streaming Adminから分離して維持|5|Streamingなしで状態表示|

## 8. Speech / VoiceVox

|現行ファイル・範囲|現在の責務|分類|目標位置・方針|Phase|主な回帰テスト|
|---|---|---|---|---:|---|
|`app/plugins/voice_output/plugin.py`|音声合成・再生Capability|Plugin|`plugins/speech`へ整理しFactory化|2,6|Voiceなしでテキスト出力|
|`app/adapters/tts/**`|VoiceVox、読み辞書、音声補正|Adapter|`plugins/speech/voicevox/infrastructure`へ移動|6|VoiceVox接続失敗の隔離|
|`app/ports/speech_synthesizer.py`|音声合成Port|Shared/Compatibility|公開出力契約へ統合し旧path廃止|6,8|CoreがVoiceVox型を知らない|
|`app/ports/audio_player.py`|音声再生Port|Shared/Compatibility|公開出力契約へ統合|6,8|再生失敗後もCore継続|
|`app/shared/contracts/output.py`|SpeechSynthesizer/AudioPlayer契約|Shared|正規契約として一本化|6|二重Protocol解消|
|`app/usecases/execute_action_usecase.py`|発話、音声、テキスト、記憶を一括実行|Core|出力Capability Dispatcher経由へ変更。音声具象を直接保持しない|6|音声なしSPEAK成功|

## 9. LLM

|現行ファイル・範囲|現在の責務|分類|目標位置・方針|Phase|主な回帰テスト|
|---|---|---|---|---:|---|
|`app/plugins/llm_provider/plugin.py`|役割別LLM Capability|Plugin|Provider Factoryと共に独立化|2,6|Role別利用可否|
|`app/adapters/llm/openai_response_generator.py`|OpenAI通信|Adapter|`plugins/llm/openai`へ移動候補|6|OpenAIなしで起動|
|`app/adapters/llm/ollama_response_generator.py`|Ollama通信|Adapter|`plugins/llm/ollama`へ移動候補|6|Ollamaなしfallback|
|`app/adapters/llm/dummy_response_generator.py`|Core検証用Dummy|Core Adapter|Coreのfallbackとして残す候補|6|全外部LLMなし起動|
|`app/ports/response_generator.py`|旧ResponseGenerator Port|Compatibility|Capability Gatewayへ統合後に削除|6,8|旧Port参照ゼロ|
|`app/ports/llm_roles.py`|Role Adapter|Compatibility/Shared|Role Capability契約へ一本化|6,8|Role routingテスト|
|`app/runtime/character_response_pipeline.py`|応答文脈、生成、検証|Core|Providerではなく生成Capabilityへ依存|6|Provider交換回帰|
|`app/runtime/action_planner.py`|Action生成でResponseGeneratorを直接利用|Core|生成Capability Gatewayへ置換|6|Dummy構成でAction生成|

## 10. Storage / Memory Adapter

|現行ファイル・範囲|現在の責務|分類|目標位置・方針|Phase|主な回帰テスト|
|---|---|---|---|---:|---|
|`app/plugins/agent_memory/**`|Agent Memory保存Capability|Plugin|Storage Plugin契約へ統一|6|Storeなしインメモリ|
|`app/plugins/relationship_memory/**`|Relationship Memory保存Capability|Plugin|Storage Plugin契約へ統一|6|破損Storeのfallback|
|`app/adapters/storage/json_agent_memory_store.py`|JSON保存|Adapter|`plugins/storage/json`へ移動|6|JSONなし起動|
|`app/adapters/storage/json_relationship_memory_store.py`|JSON保存|Adapter|`plugins/storage/json`へ移動|6|JSONなし起動|
|`app/adapters/storage/postgres_topic_memory_store.py`|PostgreSQL Topic Memory|Adapter|`plugins/storage/postgres`へ移動|6|DSNなし起動|
|`app/ports/topic_memory_store.py`|Topic Memory Port|Compatibility/Shared|共通Memory Store Capabilityへ統合|6,8|PostgreSQLなし動作|
|`app/ports/relationship_memory_store.py`|Relationship Store Port|Compatibility/Shared|Storage Capabilityへ統合|6,8|旧Port参照ゼロ|
|`app/shared/contracts/memory.py`|Memory Store共通契約|Shared|正規契約として拡張|6|各Store契約テスト|
|`app/adapters/embedding/**`|Embedding Provider|Adapter/Plugin|LLMまたはStorage Pluginの明確な所有へ移す|6|Embeddingなし縮退|
|`app/adapters/memory/**`|Memory Summary Provider|Adapter/Plugin|Memory Plugin付属Adapterへ移す|6|Summaryなしfallback|

## 11. Avatar / Live2D・STT・Tools

|現行ファイル・範囲|現在の責務|分類|目標位置・方針|Phase|主な回帰テスト|
|---|---|---|---|---:|---|
|現時点で本格実装なし|Expression/Motion/Gaze/LipSync|Plugin|`plugins/avatar/live2d`を新設|7|PluginなしでCore動作|
|CoreのAction/Expression型|抽象的な表現意図|Core/Shared|SDK非依存のIntentだけ保持|7|Live2D固有名なし|
|現時点で本格STTなし|Mic、VAD、認識|Plugin|`plugins/input/stt`を新設|7|テキスト入力だけで動作|
|`app/adapters/input/**`|Console/Web入力|Adapter|Core標準入力Adapterとして維持。STTとは分離|7|Console/Web回帰|
|将来のWeb Search/Calendar等|外部ツール|Plugin|`plugins/tools/<tool>`単位で追加|7|未導入Toolを呼ばない|

## 12. テスト分類

|テスト|分類・方針|Phase|
|---|---|---:|
|`tests/test_architecture_boundaries.py`|Core→Plugin具象禁止、Plugin→Runtime具象禁止を追加|1|
|`tests/dependency_boundary_baseline.json`|既知違反をPhaseごとに削減し、Phase 8で空にする|1-8|
|`tests/test_runtime_factory.py`|Pluginゼロ、無効Plugin非import、Loader失敗隔離を追加|1-2|
|`tests/test_shiritori_game.py`|Games Plugin配下の単体テストへ移動候補|3|
|`tests/test_game_input_classifier.py`|旧Runtime実装削除時にPlugin Intentテストへ統合|3|
|`tests/test_game_command_validator.py`|Games Plugin内テストへ整理|3|
|`tests/test_game_intent_interpreter.py`|Games Plugin内テストへ整理|3|
|Streaming関連テスト|Plugin単体、Core Bridge、Adminの3群へ分割|4-5|
|TTS関連テスト|Voice Plugin単体とCoreテキストfallbackを分離|6|
|LLM関連テスト|Provider単体とCore Dummy構成を分離|6|
|Storage関連テスト|Store単体とCoreインメモリ構成を分離|6|

## 13. 移行時の禁止事項

- `develop`へ直接変更しない。
- CoreからPlugin具象への新規importを追加しない。
- 移動と旧コード削除を同一コミットで一括実施しない。
- Compatibility層を恒久実装として扱わない。
- Pluginを無効化しただけで物理削除可能と判定しない。
- テストをbaselineへ追加することで新しい境界違反を恒久的に許容しない。

## 14. Phase 0完了判定

Phase 0は次を満たした時点で完了とする。

1. 監査結果文書がレビュー済みである。
2. 本ファイルマップがレビュー済みである。
3. 各対象に移行Phaseと受け入れテストが割り当てられている。
4. 実装コードの移動・削除が行われていない。
5. 次Phaseの作業ブランチは、Phase 0を`develop`へ取り込んだ後の最新`develop`から作成する。
