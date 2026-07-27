# Runtime Composition Root移行方針

## 目的

`RuntimeCoordinator.__init__()`が保持しているコンポーネント生成・依存配線を、段階的に`RuntimeCompositionRoot`へ移動する。

## 第1段階: 実行系

以下の生成順序と依存配線を`RuntimeCompositionRoot.build_execution()`へ集約する。

- `RuntimeEventExecutor`
- `RuntimeLoop`
- `RuntimeHostController`

生成結果はimmutableな`RuntimeExecutionComposition`として返す。

`RuntimeCoordinator`の公開コンストラクタ引数は維持し、既存の依存注入済みインスタンスもそのまま優先する。

`InteractionReactionPolicy`は`RuntimeCompositionRoot`を経由して
`RuntimeEventExecutor`へ渡し、`USER_INTERACTION`の接触反応制御を維持する。

## 第2段階: Event受付系

以下をComposition Rootへ移動する。

- `EventSubscriberRegistry`
- `BufferedEventDispatcher`
- `UserInputInterruptionCoordinator`
- `EventTypeRouter`
- `EventDispatchProcessor`
- `ConversationInputRecorder`
- `EventIngressProcessor`

## 第3段階: Behavior・Plugin系

以下をComposition Rootへ移動する。

- `BehaviorFallbackRouter`
- `ConfirmationCoordinator`
- `PluginOngoingActivitySynchronizer`
- `ExplicitActivityExecutor`
- `PluginActivityCoordinator`
- `ActivitySwitchCoordinator`
- `BehaviorRoutingCoordinator`

## 境界方針

- Composition Rootは`RuntimeCoordinator`本体を受け取らない。
- Composition Rootは`RuntimeCoordinator`のprivate属性を参照しない。
- 循環依存が必要な箇所は、明示的なCallable契約として渡す。
- Componentの既存注入値がある場合は再生成しない。
- Runtimeの公開API、Traceログ、Event payload、ActivityTurnResultの契約は変更しない。
