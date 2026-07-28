# プラグイン分離監査結果・移行計画

**Document Version:** v1.0.0  
**基準ブランチ:** `develop`  
**基準コミット:** `91bdb8a8f358b48ef6e102c6a83d0ccc7013c470`  
**基準タグ:** `develop-snapshot-20260729`

## 1. 目的

本書は、AI VTuber「ゆら」の現行実装を、次の原則に沿って再整理するための監査結果と移行計画を定義する。

> 各プラグインを無効化、または物理的に削除しても、Coreが起動し、自律発話・通常会話・感情・記憶・テキスト出力を継続できること。

本Phaseではコード移動や実装変更を行わず、現状の依存、責務漏れ、二重構造、移行順序、受け入れ条件を確定する。

## 2. 分類基準

### 2.1 Coreに残す責務

- 自律活動
- 通常会話
- 感情・内的状態
- 記憶モデルと抽象契約
- Event / Activity / Action
- EventBuffer / EventFilter / EventPrioritizer
- ActivityManager / ActionPlanner / ActionScheduler
- 発話占有・割り込み・並行実行の調停
- 共通安全制御
- 応答生成Portと生成結果検証
- Plugin Protocol / Registry / Capability Registry
- Plugin Context
- Plugin失敗時の隔離
- Pluginなしでも起動する仕組み

### 2.2 Pluginへ移す責務

- Games / Shiritori
- Streaming lifecycle
- YouTube連携
- OBS制御
- 配信コメント処理
- 配信向けModeration / Ranking / Response
- Streaming Admin
- Avatar / Live2D
- Speech / VoiceVox
- STT
- 外部検索・外部ツール
- 具体的なStorage実装
- 特定LLM Provider実装

### 2.3 Adapterとして扱う責務

- OpenAI / Ollama等のAPI通信
- VoiceVox通信
- YouTube API
- OBS WebSocket
- PostgreSQL / JSON / SQLite
- STTサービス通信
- Live2D SDKまたは外部アバター制御アプリとの通信

## 3. 現状監査結果

## 3.1 依存境界テスト

既存の`tests/test_architecture_boundaries.py`は、次の違反を検査している。

- DomainからRuntime / Adapter / Plugin / Bootstrapへの依存
- PortからAdapterへの依存
- UseCaseからBootstrapへの依存
- Runtimeから外部SDKへの依存
- Adapter間の横断依存
- Pluginから非公開Coreモジュールへの依存

一方、次の重要条件は未検査である。

- Core / Runtimeから具体Plugin実装をimportしない
- PluginからCore Runtime具象へ依存しない
- Pluginディレクトリを物理削除してもCoreがimport・起動できる
- Plugin無効時に設定読込やComposition Rootが失敗しない
- Streaming固有Domain / UseCaseがCore側へ残っていない

既知違反としてbaselineに次の3件が残っている。

- OpenAI AdapterからPrompt Adapterへの依存
- Streaming AdapterからOBS Adapterへの依存2件

## 3.2 Core Composition Root

`app/bootstrap/runtime.py`が、Core Runtime構築だけでなく次の具体実装を直接import・生成している。

- OpenAI / Ollama / Dummy LLM
- VoiceVox
- System Audio Player
- JSON Agent Memory
- JSON Relationship Memory
- PostgreSQL Topic Memory
- Embedding Generator
- Memory Summary Generator
- Games Plugin
- LLM Provider Plugin
- Memory Plugins
- Voice Output Plugin

このため、設定で無効化できても対象パッケージを物理削除するとimport時点でCore起動が失敗する。

### 判定

- 設定による無効化: 一部達成
- 物理削除可能性: 未達
- Plugin自己構成: 未達
- Composition Rootの責務分離: 未達

## 3.3 Games / Shiritori

`app/plugins/games`内では、Games固有実装が比較的よくまとまっている。

- ゲームIntent解釈
- Command検証
- Game Engine
- Shiritori定義・状態・Service
- Activity Definition
- Plugin Capability

Coreとの接続には`app.shared.contracts`が使われており、方向性は良好である。

ただし`app/bootstrap/runtime.py`が`GamesPlugin`を静的importし、常にインスタンス生成してから設定で有効・無効を決めている。

### 判定

- Plugin内部構造: 概ね良好
- 設定無効化: 可能
- 物理削除: 不可
- 旧しりとり実装との重複: 継続調査・解消対象

## 3.4 Streaming / YouTube / OBS

`app/plugins/youtube_streaming`には、次の責務がまとまっている。

- 配信セッション
- Opening / Main / End
- ライブチャット取得
- コメントModeration
- コメントRanking
- コメントResponse
- Streaming lifecycle
- Capability Registration

Plugin RegistrationはCommand / Query / Activity Capabilityを公開しており、設計方針に合致する。

一方、`app/bootstrap/streaming.py`には次の責務が集中している。

- Core RuntimeとPlugin Activityの変換
- YouTubeコメントのCore Event変換
- Streaming lifecycle向けEvent Enricher
- Streaming固有Moderation購読
- Streaming Repository Factory
- Streaming Application Service生成
- Plugin Registry生成
- Admin API生成
- OBS / YouTube接続状態の集約

`RuntimeCoreActivityAdapter`は汎用Core Adapterを名乗るが、`YOUTUBE_COMMENT`などStreaming固有イベントを直接知っている。

### 判定

- Streaming Domain / UseCase: Plugin内で概ね適切
- Capability Registration: 良好
- Core接続Adapter: Streaming知識漏れあり
- Repository Factory: Pluginへ移動対象
- Bootstrap: 責務過多

## 3.5 Streaming Admin

`app.admin_api.service.AdminApiService`はCommand / QueryのDispatch自体は汎用契約を使っている。

しかし、実際には次のStreaming固有状態を固定で知っている。

- YouTube認証
- OBS状態
- 配信Session
- Opening / Main / Closing / End
- コメントPipeline
- コメントRanking
- YouTube Studio操作可否
- 配信責任分担

したがって、実質的にはStreaming Admin Application Serviceである。

### 判定

- `app/admin_api`: Streaming Plugin付属管理機能へ移動対象
- `gui/yura-streaming-admin`: Streaming Plugin付属UIとして管理対象
- 汎用Core状態表示UIとは分離する

## 3.6 TTS / VoiceVox

`VoiceOutputPlugin`は`SpeechSynthesizer`、`AudioPlayer`、`VoiceIntent`という抽象契約を利用し、障害時にCapabilityを無効化できる。

一方、VoiceVox具象生成は`app/bootstrap/runtime.py`が行い、`ExecuteActionUsecase`は従来Portとして`SpeechSynthesizer`と`AudioPlayer`を直接保持している。

### 判定

- 抽象契約: 良好
- 障害隔離: 良好
- Plugin自己構成: 未達
- VoiceVox物理削除: 不可
- Plugin Capability方式と旧Port方式の二重構造: あり

## 3.7 LLM

`LlmProviderPlugin`は役割別Capabilityを提供し、特定Providerを隠蔽している。

- `llm.provider.default`
- `llm.provider.character`
- `llm.provider.situation_evaluator`
- `llm.provider.response_validator`

しかしOpenAI / Ollama等の具象生成、APIキー解決、Role別Generator生成は`app/bootstrap/runtime.py`が担当している。

またCore RuntimeはPlugin登録後も`ResponseGenerator`としてGeneratorを直接保持し、`ActionPlanner`や`CharacterResponsePipeline`へ渡している。

### 判定

- Provider抽象化: 概ね達成
- Role別差し替え: 概ね達成
- Plugin障害隔離: 達成
- Provider物理削除: 不可
- Capability方式と旧Port方式の二重構造: あり

## 3.8 Storage

記憶モデルはCoreにあり、具体Storeは外側に置かれている。

- Agent Memory: Plugin化済み
- Relationship Memory: Plugin化済み
- Topic Memory: 従来Port方式
- Embedding: Adapter方式
- Memory Summary: Adapter方式

無効時や接続失敗時にはインメモリ状態または`None`へ縮退するため、実行時の安全性は比較的高い。

ただし具象Storeの静的importがCore Bootstrapに残っているため、物理削除には耐えない。

## 3.9 Live2D / Avatar

現時点では本格的なAvatar PluginやLive2D Adapterの接続を確認できない。

Coreに残すべきものは次の抽象意図に限定する。

- ExpressionIntent
- MotionIntent
- GazeIntent
- LipSyncIntent

Live2D固有パラメータ、SDK、通信方式、描画周期はPlugin側の責務とする。

## 3.10 STT

現時点では本格的なSTT Pluginを確認できない。

Coreは正規化済み入力イベントだけを受け取る。

- UserTextReceived
- UserSpeechRecognized

マイク、音声形式、VAD、STT ProviderはPlugin側の責務とする。

## 4. 目標構成

```text
app/
├── core/
│   ├── plugins/
│   ├── capabilities/
│   └── lifecycle/
├── domain/
├── runtime/
├── shared/
│   └── contracts/
├── bootstrap/
│   ├── core_runtime.py
│   └── plugin_host.py
└── plugins/
    ├── games/
    │   └── shiritori/
    ├── streaming/
    │   ├── youtube/
    │   ├── obs/
    │   ├── lifecycle/
    │   ├── comments/
    │   ├── moderation/
    │   ├── ranking/
    │   └── administration/
    ├── speech/
    │   └── voicevox/
    ├── avatar/
    │   └── live2d/
    ├── input/
    │   └── stt/
    ├── llm/
    │   ├── openai/
    │   └── ollama/
    ├── storage/
    │   ├── json/
    │   └── postgres/
    └── tools/
```

Pluginを別Pythonパッケージへ分離する段階では、各Pluginに次を持たせる。

```text
plugin-package/
├── pyproject.toml
├── README.md
├── src/
└── tests/
```

ただし、最初の移行ではリポジトリ内の`app/plugins`で境界を確立してから、必要に応じて別パッケージ化する。

## 5. 移行方針

## Phase 0: 監査と分離マップ

- 本書の確定
- ファイル単位の責務分類
- Core / Plugin / Adapter / shared/contracts / compatibilityの分類
- 依存方向と移動先の確定

### 完了条件

- コード移動なし
- 全対象の責務分類が完了
- 移行順序と受け入れ条件がレビュー可能

## Phase 1: 依存方向テストの強化

追加する検査:

- Core / Runtimeから`app.plugins.*`具象への依存禁止
- Pluginから`app.runtime.*`具象への依存禁止
- PluginからCore private moduleへの依存禁止
- Adapter間の横断依存禁止
- Streaming固有コードのCore残存検査
- Optional Plugin import検査

追加するCore単独テスト:

- Plugin登録ゼロでCore構築可能
- GamesなしでCore構築可能
- StreamingなしでCore構築可能
- Voice Outputなしでテキスト出力可能
- Storageなしでインメモリ稼働可能
- 特定LLM ProviderなしでDummy / fallback起動可能

## Phase 2: Plugin Loader / Factory基盤

- Core Composition Rootから具体Pluginの静的importを除去
- 設定で有効なPluginだけ動的import
- import失敗をPlugin単位で隔離
- Plugin Factory契約を定義
- Plugin Lifecycleを統一
- Capability登録を統一

### 完了条件

- Pluginディレクトリが存在しなくてもCoreが起動
- 無効Pluginはimportされない
- Pluginロード失敗がCore起動を妨げない

## Phase 3: Games二重構造解消

- 旧しりとりDomain / Runtime実装の洗い出し
- `app/plugins/games`へ一本化
- Compatibility re-exportを必要最小限に限定
- 最終的に旧実装を削除

### 完了条件

- Coreに`shiritori`文字列・型・分岐がない
- Games Plugin削除状態で通常会話が動く
- Games有効時のみActivity Definitionが登録される

## Phase 4: Streaming基盤分離

- `RuntimeCoreActivityAdapter`を汎用Plugin Activity Adapterへ再設計
- YouTube固有Event変換をStreaming Plugin側へ移動
- Streaming Repository FactoryをPlugin内へ移動
- `app/bootstrap/streaming.py`を薄いCompositionへ縮小

### 完了条件

- Core側に`YOUTUBE_COMMENT`固有処理がない
- Streaming PluginなしでCore import・起動可能
- Streaming Plugin有効時のみCapabilityが登録される

## Phase 5: Streaming Admin分離

- `app/admin_api`をStreaming Plugin付属管理機能へ移動
- `gui/yura-streaming-admin`をStreaming Plugin付属UIとして整理
- 汎用Core状態表示と配信管理を分離

### 完了条件

- CoreはStreaming Adminを知らない
- Streaming AdminなしでCoreが起動
- Admin APIはPlugin Capabilityだけを利用

## Phase 6: Voice / LLM / Storage統一

- VoiceOutputのCapability方式と旧Port方式を一本化
- LLM Capability方式と旧ResponseGenerator方式を一本化
- Agent / Relationship / Topic MemoryのPlugin契約を統一
- Provider / Store具象生成を各Plugin Factoryへ移動

### 完了条件

- VoiceVox削除時もテキスト出力可能
- OpenAI削除時もOllama / Dummyで起動可能
- PostgreSQL削除時もインメモリで起動可能
- Core BootstrapがProvider名やStore具象を知らない

## Phase 7: Avatar / STT / Tools追加

新規Pluginとして実装する。

- Avatar / Live2D
- STT
- Web Search
- Calendar
- External API

### 完了条件

- Coreは抽象Intent / Eventだけを知る
- 具体SDKやProviderはPlugin内に閉じる
- PluginなしでもCore機能が破綻しない

## Phase 8: Compatibility層削除

- 旧import pathのre-export削除
- 旧Port方式削除
- baseline違反削除
- 廃止設定削除
- 移行用Factory削除

## 6. ファイル分類ルール

各ファイルは次のいずれかに分類する。

- Coreに残す
- Pluginへ移す
- Adapterへ移す
- `shared/contracts`へ移す
- Composition Rootへ集約
- Compatibility層として一時維持
- 重複のため削除

分類表には次を記録する。

- 現行ファイル
- 現在の責務
- 目標責務
- 移動先候補
- 依存元
- 依存先
- 必要な共通契約
- 移行Phase
- 削除可能時期
- 回帰テスト

## 7. 非機能・運用条件

- Python 3.10.5を維持する
- Coreの起動経路を常に保持する
- `develop`へ直接修正しない
- Phaseごとに最新`develop`から作業ブランチを作る
- PR経由で`develop`へ取り込む
- コミットは修正内容単位に分割する
- コミットメッセージは日本語で記載する
- 既存履歴を保持し、不要なSquashやRebaseを行わない
- CI成功後にマージする

## 8. 最終受け入れ条件

次の状態をすべて満たすこと。

1. Coreから具体Plugin実装への静的importがない
2. PluginからCore Runtime具象への依存がない
3. Plugin間に循環依存がない
4. 各Pluginを設定で無効化できる
5. 各Pluginを物理削除してもCoreがimport・起動できる
6. Pluginロード失敗が他PluginやCoreを停止させない
7. Core単独で自律発話・通常会話・感情・記憶・テキスト出力が動作する
8. VoiceVoxなしでもテキスト出力が動作する
9. StreamingなしでもCoreが動作する
10. Gamesなしでも通常会話が動作する
11. PostgreSQLなしでもインメモリで動作する
12. 特定LLM Providerなしでも代替ProviderまたはDummyで起動する
13. Streaming AdminなしでもCoreが動作する
14. 依存境界テストにbaseline違反が残らない
