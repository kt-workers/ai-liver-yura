# V2 Variable LLM Role Contracts

Status: Implementation Contract / Issue #323

Parent architecture:
- `docs/architecture/v2/cognitive_llm_architecture.md`
- `docs/architecture/v2/concurrency_architecture.md`

Implementation packages:
- `app/domain/llm/`
- `app/usecases/ports/llm.py`

## 1. Purpose

LLM Roleを固定個数のAPI callとしてではなく、独立した責務・入出力schema・failure policyを持つlogical contractとして定義する。

FoundationはRoleの実行候補を運搬するが、Input Meaning、Appraisal、Executive、Speech、Body等のDomain Authorityを所有しない。Provider SDK、model固有response、Prompt自由文をCore公開境界へ露出しない。

## 2. Dependency boundary

```text
Domain module typed input/output
        ↓
LLMRoleDescriptor / LLMRoleRequest / LLMRoleResult
        ↓
LLMRolePort
        ↓
Infrastructure Provider Adapter
```

- DomainはProvider Adapterをimportしない。
- PortはProvider SDK型を返さない。
- logical RoleとProvider/model選択を分離する。
- 同一Provider instanceが複数Roleを実行してよい。
- 1回のProvider callで複数logical Roleをfusionする最適化は、各Roleのtyped resultとfailure isolationを失わない場合だけ許可する。

## 3. Role descriptor

`LLMRoleDescriptor`:

- `role_id`: stable logical identity
- `responsibility`: 独立質問を表す説明
- `input_schema_id` / `output_schema_id`: owning Domainが管理するschema identity
- `authority_scope`: Roleが生成できるcandidateの範囲。権限付与そのものではない
- `activation`: required / conditional / optional / background
- `failure_policy`: fail-closed / deterministic-fallback / skip-optional / retry-bounded
- `default_execution_policy`

Role registryはdescriptor discoveryを所有できるが、Role総数や列挙をarchitecture invariantにしない。

## 4. Structured payload

`StructuredPayload`は次を持つ。

- `schema_id`
- `value`: immutable strict JSON object

`schema_id`一致はschema validationの代替ではない。Owning Moduleまたはschema registryが構造・意味制約を検証する。

Core FoundationはJSON object key、finite number、不変snapshotを保証する。Prompt文字列やProvider response objectをtyped candidateとして扱わない。

## 5. Role request

`LLMRoleRequest`:

- `request_id`
- `role_id`
- `input`: `StructuredPayload`
- `source_event_ids`
- `revisions`: #321 `RevisionVector`
- `preconditions`: #321 `PreconditionRef`
- `priority`: foreground / normal / background
- `interruptibility`
- `stale_policy`: reject / mark-stale / revalidate
- `created_at` / optional `deadline_at`
- `trace_id`

不変条件:

- aware datetime、deadlineはUTC絶対時刻でcreatedより後
- source event、preconditionはimmutable owned tuple
- requestはresult commit権限を持たない
- Runtime queue/backpressure/max-in-flightの執行は#322。#323はpolicy値だけをtransportする

## 6. Model and reasoning policy

`LLMExecutionPolicy`:

- `model_class`: capability classでありProvider model名ではない
- `reasoning_effort`: minimal / low / medium / high
- `timeout_seconds`
- `max_attempts`
- `max_output_tokens`
- `temperature?`

値域をvalidateし、boolをcount/numberとして受け入れない。Provider Adapterがpolicyを実model設定へ解決する。Domain/UseCaseは`gpt-*`、Gemini、Claude等の固有名へ依存しない。

## 7. Typed failure and result

`LLMRoleFailure`:

- schema_invalid
- provider_unavailable
- provider_error
- timeout
- cancelled
- stale
- superseded
- rejected
- policy_violation

`LLMRoleResult`:

- `request_id` / `role_id`
- `status`: succeeded / failed / cancelled / timed_out / stale / superseded / rejected
- revisions copied from request
- optional typed `output`
- optional `failure`
- started/completed timing
- trace / model class / attempt count / token usage / latency facts

不変条件:

- succeededだけがoutputを持ち、failureを持たない
- non-successはoutputを持たず、対応failureを持つ
- succeededはstarted_at必須
- stale / cancelled / supersededをsuccessへ書き換えない
- result到着だけではDomain commitしない
- request identity、role identity、schema identity、revision、authority/preconditionをowning Moduleがcommit前に再検証する
- token usageとattempt countは具体的なnon-negative intでありboolを拒否

### 7.1 所有ドメインの公開失敗契約 — #564

`LLMRolePort → LLMRoleResult → 所有ドメインによる採用確定`という責務境界を維持する。
所有ドメインの本番公開境界は、検証済みの非成功結果を汎用例外へ変換して型付きの失敗情報を失ってはならない。
一方、`LLMRoleResult`そのものを責務固有の公開データ型の代わりに露出しない。
各所有者は必要に応じて責務固有の結果型を定義し、想定される運用上の失敗を保持する。
失敗分類は既存の`LLMFailureCode`を使い、所有者ごとの分類列挙型を再発明しない。
提供サービスのSDKオブジェクトや生の例外は公開しない。

サービス不在、サービスエラー、時間切れ、役割単位の取消、古い結果、置換済み、拒否は、型付きの運用結果として保持できる。
これらとプログラムの誤用は分離する。不正なドメインオブジェクトの入力、要求構築の事前条件違反を無理に運用結果へ変換しない。
Pythonコルーチン自体への外部取消は`CancelledError`として伝播し、役割単位の`CANCELLED`結果とは区別する。
本節は共有原則を定める。入力意味解析の具体的な公開型と判定順序は`input_meaning_contracts.md`を正本とし、他の所有者の具体的な実装APIを本変更で規定しない。

## 8. Port

```python
class LLMRolePort(Protocol):
    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult: ...
```

Portの1回の`invoke`は1 logical request/result境界を表す。Runtime全体を直列化しない。複数requestの並行・優先・cancel・anti-starvationは#322が所有する。

Fake PortはRoleごとに独立response/delay/failureを設定でき、Provider SDKなしでUnit test可能にする。

## 9. Authority and commit boundary

```text
LLMRoleResult
→ status/schema/responsibility validation
→ current revision/precondition validation
→ owning Domain policy
→ typed candidate commit
```

禁止:

- LLM outputをInternal State、Goal State、Attention State、Execution Factへ直接代入
- Character RoleがWhat-to-sayを変更
- Verifier自由文をfinal Authority化
- Provider retry成功をDomain successと同一視
- stale outputをlatest contextへcommit

## 10. Sparse and non-serial invocation

- Role descriptorの存在は毎event起動を意味しない。
- required dependencyだけをawaitする。
- safe independent requestはfan-out可能。
- optional/background Role failureはunrelated Role contractを変更しない。
- shared Providerでもrequest/result/failure/metricsはRoleごとに分離する。
- fused Provider callを使う場合、partial schema failureを各logical Roleのtyped failureへ分離する。

## 11. Observability

最低限:

- request_id / role_id / trace_id
- queued_atは#322、started_at / completed_atは#323 result
- provider latency
- attempt count
- model class / reasoning effort
- input/output schema id
- token usage
- failure class
- stale / cancelled / superseded reason

Prompt本文、secret、Provider credentialをmetricsへ記録しない。

## 12. Explicit non-goals

- queue / scheduler / task group / backpressure実装 (#322)
- concrete OpenAI / Gemini / other Provider Adapter (#324以降)
- Role固有Domain DTO (#326〜#364等)
- Prompt内容
- schema registry implementation
- Executive / Goal / Attention / State authority
- global LLM count固定

## 13. Unit acceptance

- descriptorとrequest/resultの全公開snapshotがstrict JSON serializable
- immutable nested JSON payloadとowned tuple
- aware timestamp / UTC absolute deadline ordering
- strict numeric policy/count/token validation
- succeeded/non-success output/failure invariant
- role/request/schema/revision identity保持
- stale/cancelled/superseded non-committable
- schema mismatchをtyped failureとして表現可能
- Fake Portで異なるRoleを同一Provider相当instanceから独立実行可能
- slow Roleをawaitしているtaskと別Role invocationが独立して進行可能
- 1 Role failureが別Role resultを変更しない
- Provider/SDK importなし
- #322のqueue/scheduler実装を持ち込まない
