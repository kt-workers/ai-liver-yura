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

## 残存: Behavior・Plugin系

以下をComposition Rootへ移動する。

- `BehaviorFallbackRouter`
- `ConfirmationCoordinator`
- `PluginOngoingActivitySynchronizer`
- `ExplicitActivityExecutor`
- `PluginActivityCoordinator`
- `ActivitySwitchCoordinator`
- `BehaviorRoutingCoordinator`

次工程では、これらのBehavior／Plugin系生成責務を独立したComposition結果型へ
段階的に移す。Event受付系との境界はCallableのまま維持し、Plugin Managerや
各Coordinatorの循環参照を避ける。

## 境界方針

- Composition Rootは`RuntimeCoordinator`本体を受け取らない。
- Composition Rootは`RuntimeCoordinator`のprivate属性を参照しない。
- Event受付系からBehavior／Plugin系へ向かう
  `behavior_router`、`plugin_router`、`fallback_router`と、
  `behavior_routing_available`、`plugin_routing_available`は明示的なCallable契約
  として渡す。
- availability判定は構築時ではなくEventルーティング時に遅延評価する。
- Componentの既存注入値がある場合は再生成しない。
- Runtimeの公開API、Traceログ、Event payload、ActivityTurnResultの契約は変更しない。
