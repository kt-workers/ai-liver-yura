# V2 Runtime Lifecycle Contract

Status: Implementation Contract / Issue #350

Parent: `docs/architecture/v2/runtime_kernel_contracts.md`

## 1. 目的

Optional Provider、Output、Persistence、Plugin、Subsystemが未接続または一時的に失敗しても、Core Runtimeを停止させず、観測可能なdegraded operationとして継続・復旧・終了する。

## 2. Authority

- `RuntimeCoordinator`はtask所有、admission停止、取消伝播、close順序を所有する。
- Lifecycle serviceはavailability、retry/backoff、rate-limited diagnosticを所有する。
- Provider Adapterは具体的な接続/呼出だけを所有し、Domain StateやGlobal shutdownを決めない。
- いずれのProvider failureもGoal、Internal State、Execution Factを直接変更しない。

## 3. Availability と retry

- dependencyごとに`available`、`degraded`、`unavailable`、`closing`、`closed`をtyped snapshotで管理する。
- retryはdependency単位のbounded backoffであり、shutdown開始後は新規retryを開始しない。
- repeated failureは同じfingerprintをrate limitして診断へ記録する。credential、payload、Prompt、SDK responseは記録しない。
- unavailableなoptional dependencyはtyped failureを返し、無関係laneのadmissionを停止しない。

## 4. Shutdown

1. normal external workのadmissionを閉じる。
2. queued workをcancel/supersedeし、新しいprepared candidateを作らない。
3. interruptible workへcancelを伝播し、non-interruptible workはbounded grace後にlate resultをcommit対象外にする。
4. frame/event producerを停止し、Adapter/workerを依存順の逆順でcloseする。
5. optional persistence snapshotを試みるが、失敗してもresource closeを妨げない。
6. owned taskが0であることを確認して`stopped`へ遷移する。

`stop()`とresource closeはidempotentである。close hook失敗は他hookのcloseを阻害せず、集約したsanitized diagnosticとして報告する。

## 5. 検証

- provider未設定、reconnect、retry上限、diagnostic rate limit
- TTS/Body/DB/PluginなしでのCore継続
- 複数worker中のshutdown、Ctrl+C相当の二重要求、pending task 0
- shutdown後retry/admission拒否、late resultの非commit
