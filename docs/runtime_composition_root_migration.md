# Runtime Composition Root移行方針

## 目的

`RuntimeCoordinator.__init__()`が保持しているコンポーネント生成・依存配線を、段階的に`RuntimeCompositionRoot`へ移動する。

## 移行済み: 実行系

以下の生成順序と依存配線を`RuntimeCompositionRoot.build_execution()`へ集約する。

- `RuntimeEventExecutor`
- `RuntimeLoop`
- `RuntimeHostController`

生成結果はimmutableな`RuntimeExecutionComposition`として返す。

`RuntimeCoordinator`の公開コンストラクタ引数は維持し、既存の依存注入済みインスタンスもそのまま優先する。

`InteractionReactionPolicy`は`RuntimeCompositionRoot`を経由して
`RuntimeEventExecutor`へ渡し、`USER_INTERACTION`の接触反応制御を維持する。

## 移行済み: Event受付・入力経路

以下の生成順序と依存配線を`RuntimeCompositionRoot.build_event_pipeline()`へ
集約する。

- `DefaultEventFilter`
- `DefaultEventPrioritizer`
- `EventBuffer`
- `EventSubscriberRegistry`
- `UserInputEventLogger`
- `UserInputEventRouter`
- `BufferedEventDispatcher`
- `UserInputInterruptionCoordinator`
- `EventTypeRouter`
- `EventDispatchProcessor`
- `ConversationLogger`
- `ConversationInputRecorder`
- `EventIngressProcessor`

生成結果はimmutableな`RuntimeEventPipelineComposition`として返す。

`RuntimeCoordinator.__init__()`の既存引数名、型、デフォルト値は変更せず、
全対象コンポーネントの完全注入と部分注入を維持する。上位コンポーネントが
注入された場合、その内部依存は差し替えない。未注入の
`ConversationInputRecorder`は、明示注入を含む解決済みの
`ConversationLogger`を使用する。

Event処理の依存方向は次のとおり。

```text
RuntimeCoordinator
  -> RuntimeCompositionRoot.build_event_pipeline()
  -> RuntimeEventPipelineComposition
  -> EventIngressProcessor
       -> EventFilter
       -> ConversationInputRecorder -> ConversationLogger
       -> AgentLifeService
       -> EventSubscriberRegistry
  -> EventTypeRouter
       -> UserInputInterruptionCoordinator
       -> UserInputEventLogger
       -> UserInputEventRouter
  -> EventDispatchProcessor
       -> EventPrioritizer
       -> UserInputInterruptionCoordinator
       -> BufferedEventDispatcher -> EventBuffer -> EventQueue
```

`publish_events()`の
Ingress、Filter、会話入力記録、Life Service、Subscriber、foreground取得、
種別ルーティング、優先度付与・割り込み・Buffer投入、flushという順序は
変更しない。`USER_INTERACTION`も従来どおりFilter、Prioritizer、Buffer、
EventQueueを通り、実行系の`InteractionReactionPolicy`へ到達する。

## 移行済み: Behavior・Plugin系

以下の生成順序と依存配線を
`RuntimeCompositionRoot.build_behavior_composition()`へ集約する。

- `BehaviorFallbackRouter`
- `ConfirmationResolver`
- `ConfirmationCoordinator`
- `OngoingActivityCoordinator`
- `PluginOngoingActivitySynchronizer`
- `BehaviorPlanningContextBuilder`
- `ExplicitActivityExecutor`
- `PluginActivityCoordinator`
- `ActivitySwitchCoordinator`
- `BehaviorRoutingCoordinator`

生成結果はimmutableな`RuntimeBehaviorComposition`として返す。

生成条件は次のとおり。

- `BehaviorFallbackRouter`と`OngoingActivityCoordinator`は常に生成する。
- `ConfirmationResolver`は注入値を優先し、未注入時だけ生成する。
- `ConfirmationCoordinator`は注入値を優先する。未注入時は
  `PendingConfirmationManager`と`ActivityPlanValidator`の両方がある場合だけ
  生成し、それ以外は`None`とする。
- `PluginOngoingActivitySynchronizer`、`ExplicitActivityExecutor`、
  `PluginActivityCoordinator`、`ActivitySwitchCoordinator`、
  `BehaviorRoutingCoordinator`は注入値を優先し、未注入時だけ生成する。
- `BehaviorPlanningContextBuilder`は注入値を優先する。未注入時は
  `PluginManager`がある場合だけ生成し、それ以外は`None`とする。

`short_term_memory`と`topic_history`は、未注入の
`BehaviorPlanningContextBuilder`を生成する場合だけ使用する。
`PluginManager`がない場合も、Fallback、Plugin Activity、Activity Switch、
Behavior Routingの各Coordinatorは従来どおり生成でき、通常会話への
フォールバックを維持する。

部分依存注入では、注入された各コンポーネントをそのまま返し、その内部依存を
差し替えない。ほかの未注入コンポーネントは解決済み依存から生成する。
`OngoingActivityCoordinator`は
`PluginOngoingActivitySynchronizer`と`RuntimeHostController`へ同一インスタンスを
渡す。`ExplicitActivityExecutor`も未注入の`PluginActivityCoordinator`へ
同一インスタンスを渡す。

Behavior処理の依存方向は次のとおり。

```text
RuntimeCoordinator
  -> RuntimeCompositionRoot.build_behavior_composition()
  -> RuntimeBehaviorComposition
       -> BehaviorRoutingCoordinator
            -> BehaviorPlanningContextBuilder
            -> ConfirmationCoordinator
            -> PluginActivityCoordinator
                 -> ExplicitActivityExecutor
                 -> PluginOngoingActivitySynchronizer
                      -> OngoingActivityCoordinator
            -> ActivitySwitchCoordinator
            -> BehaviorFallbackRouter
  -> RuntimeCompositionRoot.build_event_pipeline()
       -> RuntimeCoordinator._route_behavior
       -> RuntimeCoordinator._route_plugin_user_input
  -> RuntimeCompositionRoot.build_execution()
       -> RuntimeHostController
            -> OngoingActivityCoordinator
```

## 境界方針

- Composition Rootは`RuntimeCoordinator`本体を受け取らない。
- Composition Rootは`RuntimeCoordinator`のprivate属性を参照しない。
- Event受付系からBehavior／Plugin系へ向かう
  `behavior_router`、`plugin_router`、`fallback_router`と、
  `behavior_routing_available`、`plugin_routing_available`は明示的なCallable契約
  として渡す。
- availability判定は構築時ではなくEventルーティング時に遅延評価する。
- Behavior Compositionには、Plugin入力を委譲する`plugin_router`、実行失敗を
  会話Fallbackへ変換する`execution_fallback`、現在のOngoing Activityを返す
  `current_ongoing_activity`を明示的なCallableとして渡す。
- `PluginActivityCoordinator`と`ActivitySwitchCoordinator`は同一の
  `execution_fallback`を共有する。
- `current_ongoing_activity`はActivity切替時に遅延評価し、構築時の値を固定しない。
- Componentの既存注入値がある場合は再生成しない。
- Runtimeの公開API、Traceログ、Event payload、ActivityTurnResultの契約は変更しない。

`RuntimeCoordinator.__init__()`の既存引数名、型、順序、デフォルト値は変更して
いない。確認待ち、Plugin availability、Ongoing Activity同期、Activity切替、
execution fallbackのEvent payload、診断プロパティも従来の契約を維持する。

## RuntimeCoordinatorに残る責務

- 基本依存と公開注入値の保持
- `AgentLifeService`と`TraceLogger`の解決
- Composition Root呼び出しとComposition結果のprivate属性への保持
- Event Enricher一覧の管理
- 公開Runtime APIと各Composition間を接続するCallable境界
- Event publish、Runtime起動・停止、診断スナップショットのFacade

初期化順序は、基本依存、`AgentLifeService`、`TraceLogger`、
Behavior／Plugin Composition、Event Pipeline Composition、Event Enricher、
Execution Compositionの順とする。これによりEvent Pipelineが参照する
Behavior系属性は先に初期化される。

## 次工程とComposition Rootの規模

実行系、Event受付・入力経路、Behavior／Plugin系の3領域は移行済みである。
次工程では、`RuntimeCoordinator`に残るFacade処理と初期化補助の責務を再評価し、
必要に応じて診断・Enricher・Lifecycle境界を分離する。

`runtime_composition_root.py`は3つのComposition結果型とbuildメソッドを保持するため
規模が増えている。現時点ではRuntime全体の生成順序を一箇所で追える利点があるが、
各buildメソッドの依存関係は独立している。今後さらに対象領域や生成条件が増える
場合は、公開Facadeとして`RuntimeCompositionRoot`を残しつつ、
Execution、Event Pipeline、Behaviorの内部Builderへファイル分割することを検討する。
