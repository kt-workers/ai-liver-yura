# V2 Runtime Lifecycle Contract

Status: Implementation Contract / Issue #350

Parent: `docs/architecture/v2/runtime_kernel_contracts.md`
Related: `docs/architecture/v2/persistence_repository_contracts.md`

## 1. 目的

Optional Provider、Output、Persistence、Plugin、Subsystemが未接続または一時的に失敗しても、Core Runtimeを停止させず、観測可能なdegraded operationとして継続・復旧・終了する。

## 2. Authority

- `RuntimeCoordinator`はtask所有、admission停止、取消伝播、close順序を所有する。
- Lifecycle serviceはavailability、retry/backoff、rate-limited diagnosticを所有する。
- Provider Adapterは具体的な接続/呼出だけを所有し、Domain StateやGlobal shutdownを決めない。
- Persistenceは保存機構を所有するが、何をrestart-safe stateとして保存/復元するかは各Domain owner契約が決める。
- いずれのProvider failureもGoal、Internal State、Execution Factを直接変更しない。

## 3. Availability と retry

- dependencyごとに`available`、`degraded`、`unavailable`、`closing`、`closed`をtyped snapshotで管理する。
- retryはdependency単位のbounded backoffであり、shutdown開始後は新規retryを開始しない。
- repeated failureは同じfingerprintをrate limitして診断へ記録する。credential、payload、Prompt、SDK responseは記録しない。
- unavailableなoptional dependencyはtyped failureを返し、無関係laneのadmissionを停止しない。

## 4. Shutdown

Shutdownはresource dependencyを守る。特にPersistenceを利用するfinal snapshot/flushはPersistence Adapterをcloseした後には実行できない。

正規順序:

1. **Close external admission**
   - normal external workのadmissionを閉じる。
   - shutdown開始後は新しいretry/background consolidation/new prepared speechを開始しない。

2. **Quiesce queued / future work**
   - queued workをcancel/supersedeする。
   - 新しいprepared speech candidate、Reflection batch、Plugin/Subsystem operation admission等を止める。

3. **Settle in-flight work within bounded grace**
   - interruptible workへcancelを伝播する。
   - non-interruptibleまたはexternal effect済みworkはbounded grace/effect reconciliationを行う。
   - grace後のlate resultはcurrent runtimeへ新規commitしない。ただし既に起きたexternal effect evidenceは失わない。

4. **Stop high-frequency/event producers**
   - new frame/event/comment/game telemetry等のproducerを止める。
   - current outputの終了処理はowner contractに従う。

5. **Capture and flush eligible restart-safe state while Persistence is still open**
   - ownerが明示したrestart-safe snapshotだけをcaptureする。
   - #359へlatest eligible snapshot/final durability workをbounded grace内で渡す。
   - snapshot失敗/timeoutはdiagnostic/degraded durabilityとして記録するが、残りresource closeを無期限に妨げない。
   - shutdown-only flushを唯一のdurability mechanismにしない。通常runtime commit時のbackground persistenceを維持する。

6. **Close dependent Subsystems / Providers / Adapters in dependency-safe reverse order**
   - speech/output、Avatar、Streaming/Game、Plugin lifecycle、LLM/TTS等を各owner contractに従ってcloseする。
   - Persistence pool/connectionはfinal snapshot/transaction settlement後にcloseする。
   - resource同士に依存がある場合、利用側を先に、利用される側を後にcloseする。

7. **Stop persistence/retry workers and close Persistence**
   - pending transactionをsettle/abortする。
   - retry loopを停止する。
   - pool/connectionをidempotentにcloseする。

8. **Join runtime-owned tasks**
   - `RuntimeCoordinator`がowned task数0を確認する。
   - expected cancellationをunretrieved exceptionとして残さない。
   - その後のみ`stopped`へ遷移しevent loop closeを許可する。

### 4.1 Shutdown invariants

- Persistence close後に新しいsnapshot writeを開始しない。
- optional snapshot failureで他resource closeを止めない。
- close hook失敗で後続closeを省略しない。
- `stop()` / resource closeはidempotent。
- shutdown中にretry loopを再起動しない。
- provider/output failureを理由にDomain stateを捏造/rollbackしない。
- Streaming Activity終了とSystem shutdownを同一視しない。

## 5. Startup / reconnect

- optional dependency unavailableでもminimum Coreが成立する場合はdegraded起動を許可する。
- reconnectはdependency単位で行い、Core global startupを再実行しない。
- new provider/subsystem generationへold in-flight resultを適用しない。
- #359 rehydrationはPersistence decode後に各Domain ownerがvalidate/applyする。generic `set_state`をLifecycleが行わない。

## 6. 検証

- provider未設定、reconnect、retry上限、diagnostic rate limit
- TTS/Body output/DB/Plugin/SubsystemなしでのCore継続
- final restart-safe snapshotがPersistence close前に実行される
- snapshot timeout/failure後も残りresource close完了
- Persistence close後snapshot admission拒否
- 複数worker中のshutdown、Ctrl+C相当の二重要求
- shutdown後retry/admission拒否
- late resultの非commitとalready-applied effect evidence保持
- close hook一部失敗でも他resource close実行
- pending task 0後のみevent loop close
