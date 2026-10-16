# Executiveの本番構成（#691）

Ownerは#328配下の構成Work #691。利用側は#692 / #360、System受入れは#620である。本書は構成の恒久契約を定める。実装・試験・採用・レビューの工程状態はIssue / PR / Checkpointに記録する。

## 1. 正本と依存方向

本書をExecutive実行方針とRequirements本番構成の初期採用値・保存形式・構築境界の正本とする。[Executive契約](executive_authority_contracts.md) §9・§9.9・§11.1、[LLM数値契約](llm_execution_numeric_contracts.md)、[Role契約](llm_role_contracts.md)、[Provider契約](llm_provider_adapter_contracts.md)の意味・型・制約を変更しない。[最小本体構成](minimum_brain_production_configuration.md) §12のExecutive側留保を具体化する。

#328だけが意識的Goal / Actionを確定する。#630は要件導出・単一規則選択・候補完全一致・世代・最終Fence、#695はDirect source、#610は正規読取、#611は認知配送を所有する。構成層はこれらの公開APIを使用し、別の意味Ownerや全体lockを追加しない。

値が未選定という理由だけで不足契約とは扱わず、本書でrevision 1の初期運用値を選定する。試験用fixture、過去の偶然値、実測最適値を根拠にしない。値の意味・制約・Ownerが未定義なら構成値で隠さない。

## 2. Executive実行方針の初期値

値域はLLM数値契約 §2と既存enumによる。数値にboolを許さず、実数は有限とする。以下は運用初期値であり、応答時間SLO・成功保証・Human校正結果ではない。

| field | 採用値 | 許容範囲・制約 | 採用理由と失敗・再試行への影響 | 後続変更 |
| --- | --- | --- | --- | --- |
| policy_id | `yura.executive.execution` | 非空の安定identity | 他Roleと区別し要求・結果の由来を照合する。不一致を代替しない | 同じ方針系列では固定 |
| policy_revision | `1` | 非負整数。本構成では1以上 | 初期系列を明示。旧要求へ新方針を付替えない | 内容変更時に増加 |
| model_class | `balanced` | FAST / BALANCED / DEEP_REASONING / MULTIMODALの既存enum | 構造化された判断候補に汎用の論理classを選ぶ。具体モデルを指定せず、未対応mappingは拒否 | config・execution revisionを増加 |
| reasoning_effort | `medium` | minimal / low / medium / high | 複数参照の判断用に中間の論理予算を選ぶ。未対応時のeffort変更は禁止 | 同上 |
| timeout_seconds | `20.0` | 有限、0より大きい | 判断待機を有限に制限。deadline残時間との小さい方を使い、超過はTIMED_OUT | 同上 |
| max_attempts | `1` | 1以上の整数。初回を含む | 古い判断候補の蓄積を避ける。FAIL_CLOSEDのまま自動再試行しない | 同上。増加だけではretry有効化にならない |
| max_output_tokens | `4096` | 1以上の整数。既知Provider上限以下 | intent・Goal/Commitment遷移・要件由来を含む構造化候補の出力枠。上限で切れた候補を補完しない | config・execution revisionを増加 |
| temperature_normalized | `null` | nullまたは有限の[0,1] | 人格や判断の意味を温度で新設しない。mappingはparameter非送信を明示 | 同上 |
| retry_policy.initial_backoff_seconds | `1.0` | 有限、0より大きい | 必須DTOへ有効値を明示する。今回待機は発生しない | 同上 |
| retry_policy.backoff_multiplier | `2.0` | 有限、1以上 | 後続で許可された場合の指数式を明示。現FAIL_CLOSEDでは未使用 | 同上 |
| retry_policy.max_backoff_seconds | `4.0` | 有限、initial以上 | 必須backoff値を有限に制限。現revisionでは未使用 | 同上 |

retry式・retryable分類・取消・deadlineの意味は既存Adapterに従う。再試行の有効化にはRoleのfailure契約との整合が必要で、max_attemptsだけ変更してFAIL_CLOSEDを回避しない。出力上限4096を超えるProvider非対応は呼出前POLICY_VIOLATIONとし、silent clamp・別modelへのfallbackをしない。出力上限は既存D10のcontext・候補・保存容量制約を拡張しない。

遅い要求は既存の非直列認知配送で扱い、foregroundや無関係traceを停止・取消しない。timeout / cancellation / supersede / staleを判断成功にしない。

### 2.1. RoleとProvider境界

既存`deliberator.descriptor(ExecutivePolicy)`を使用する。role_id=`executive_deliberation`、入力=`executive.context.v2`、出力=`executive.candidate.v2`、output_contract=`executive_candidate_only`、activation=REQUIRED、failure=FAIL_CLOSEDを維持する。要求とdescriptorには同一の不変execution policyを渡す。入力は既存v2 serializerを使い、旧v1形式を拡張しない。

既存`CANDIDATE_INSTRUCTIONS`と`parse_candidate`、型付きpayload、Goal/Commitment semantic specが候補の意味を所有する。schemaに適合してもcommit成功を意味しない。構成loaderが候補形式・意味・instructionsをYAMLから上書きする機能は持たない。

論理model / reasoningのsourceは本書と本番YAMLである。concrete model名、Provider reasoning値、mapping ID/revision/source、Role別mapping供給、runtime登録、`SystemCompositionSnapshot.provider_bindings`は#692 / #360の責務。#357の型・mapping検証を再実装しない。#691の構成factoryはProviderを構築せず環境変数・credentialを読まない。mappingの欠落や非対応をtest providerへの置換で隠さない。

## 3. Requirementsの本番規則

policy_id=`yura.executive.requirements`、revision=`1`。非空安定identityと非負整数という既存制約を満たす。本構成ではrevisionを1以上とする。rule set identityはこのpolicy ID/revisionと下表の全規則のidentity/revision・内容であり、別の推測的generationを作らない。

全6規則はrevision=`1`、selector.field=`kind`、selector.value=`null`、policy_id / policy_revisionは所属方針と同一。各kindに1規則だけ登録する。以下のsuffixは`executive.requirements.production.`に連結した完全rule_idを表す。

| intent_kind | rule_id suffix | mode | capabilities / preconditions | sourceと根拠 |
| --- | --- | --- | --- | --- |
| SPEECH | `speech` | CONSTANT | `()` / `()` | None。§9.9の#697採用値をそのまま使用 |
| BODY | `body` | CONSTANT | `()` / `()` | None。§9.9の#697採用値をそのまま使用 |
| ATTENTION | `attention` | CONSTANT | `()` / `()` | None。§9.9の#697採用値をそのまま使用 |
| ACTIVITY | `activity` | UPSTREAM | rule自身は`()` / `()` | 下記Direct sourceから導出。空要件という意味ではない |
| PLAN_EXECUTION | `plan_execution` | PLAN_SCOPE | rule自身は`()` / `()` | None。§9.5の正規PlanExecutionScopeから投影 |
| PLAN_PROGRESS | `plan_progress` | CONSTANT | `()` / `()` | None。§9.3で許容する明示定数方式。完了評価に実行能力を追加要求しない。§9.5のPlanProgressContextとclaims検証は必須 |

PLAN_PROGRESSの空は追加commit要件なしの明示設定であり、完了事実や評価成功を捏造する許可ではない。Plan由来publicationは正規Ownerから既存readerが取得する。factoryがscope/contextを生成しない。

ACTIVITY sourceは`DirectActivityRequirementSourceSpec(route_id="executive.requirements.production.direct", contract_id="executive.direct-activity-requirements.v1", reference_field="binding_ref")`。route IDは構成識別子、contractと参照fieldは#695既存固定値である。候補のactivity_typeから最初のbindingを選んだり、operationから能力を推測したりしない。

これらの設定は現在性検査・候補完全一致・下流Owner validationを変更しない。RULE_UNREGISTERED、source不足、曖昧さ、stale、candidate mismatchは既存型付き非確定を維持する。規則追加・変更時はconfigとRequirements policyのrevision、変更ruleのrevisionを増加する。3種の意味変更には§9.9のOwner契約変更が必要で、任意YAML値による上書きは許容しない。

## 4. 保存形式と厳密loader

| 要素 | 配置・採用値 | 制約・理由 |
| --- | --- | --- |
| 本番データ | `resources/config/v2/executive.yaml` | minimum YAMLから分離しINPUT_MEANING-only起動を変えない |
| schema_id | `yura.executive.production-config.v1` | 既知形式のみ受理。形式変更は別schemaとして設計 |
| config_id | `yura.executive.production` | 非空・固定の構成系列identity |
| config_revision | `1` | 1以上の整数。内容変更時に増加 |
| loader | `app/config/executive.py::load_executive_config(source: str | bytes)` | ファイルI/O・env読取を行わない純粋なparse/validate境界 |
| DTO | `ExecutiveProductionConfig` | frozen。配列はtuple、再帰的JSONもfreezeし可変aliasを保持しない |
| factory | `app/composition/executive_configuration.py` | 既存Ownerの構築と公開API呼出のみ |

YAMLの最上位fieldは`schema_id, config_id, config_revision, execution, requirements, direct_activity`の全6項目のみ。

- executionは§2の全field。retry_policyは既存3field。
- requirementsは`policy_id, revision, rules`。rules各要素は既存`ExecutiveIntentRequirementRule`の全field、selectorは`field, value`。Noneは明示null、空tupleは明示配列とする。sourceはACTIVITYだけ上記3fieldを持ち、それ以外はnull。
- direct_activityは`route_id, records`。route_idは§3と一致。records各要素は既存`DirectActivityRequirementRecord`の全field：owner_id、contract_id、record_id、revision、binding_ref、binding_revision、activity_type、target_ref、capabilities、preconditions。
- capabilities各要素はcapability_type / operation / allow_degraded、preconditions各要素はprecondition_id / expected。expectedは既存の型付きJSONで、boolと数値を変換しない。未知field・欠落fieldを補完しない。

revision 1に同梱するDirect recordsは明示`[]`とする。現在のapp / resourcesには具体的な本番ActivityBindingAuthorityの生成・登録がなく、注入境界だけが存在するためである。これは本番bindingや要件を発明しない構成選択であり、ACTIVITYが空要件で実行可能という主張ではない。空の正規routeを登録しても、具体bindingのsourceが要求された場合はSOURCE_UNAVAILABLEとなる。後続で実bindingを登録するには、承認された宣言と同じbinding Ownerを供給し、config_revisionと追加recordのrevisionを明示する。bindingの選択・操作・要件内容の意味は#695と各既存Ownerに従い、#692の配備選択を#691で代行しない。

loaderはYAML重複key・非文字列key・未知field・欠落・未知schema/enum・不正identity/revision・bool数値・非有限値・範囲違反を拒否する。任意タグ・循環aliasを許容せず、parse例外の入力断片を公開しない。DTO直接構築でも同じ不変条件を検査する。

rule ID重複、kind重複、selector重複、6規則の欠落、所属policy不一致、§3の方式不一致、Direct宣言のbinding_ref / owner_id / record_id重複、契約不一致を拒否する。既存Domain型の検証を利用し、意味を再実装しない。初期値表はrevision 1の出荷データの正本であり、後続revisionの合法な数値調整をloader内部の暗黙defaultへしない。変更は正本とデータを同期する。

構成読取側はファイル不在・読取不能を構成失敗として伝播する。loader/factoryは公開する失敗を`ExecutiveConfigurationError`と固定code（MALFORMED_CONFIG / UNSUPPORTED_CONFIG / INVALID_CONFIG / BINDING_MISMATCH / INITIALIZATION_FAILED）で区別する設計とし、raw YAML、例外原文、private pathを診断へ出さない。ファイル不在の診断は読取側でMISSING_CONFIGとする。既存Requirementsの実行時失敗を成功や構成defaultへ変換しない。

## 5. factory・世代・由来

`create_executive_configuration(config, *, bounds, activity_bindings)`を公開する。configは上記DTO、boundsは正規`BrainOperationalBoundsPolicy`、activity_bindingsはbinding_refをkeyとする実`ActivityBindingAuthority`のMappingとする。scope/contextやProvider、clockを新規生成しない。

1. 全構成とboundsを検証し、宣言のbinding_ref集合と注入binding集合の完全一致を要求する。欠落・余剰・別identityを拒否する。初期recordsが空なら注入集合も空でなければならない。
2. 各宣言について実Ownerのbinding publicationとidentity / revision / activity_type / targetを照合する。#695のprimary capability exactly 1、型、重複、容量検査を使う。binding_ref以外からbindingを推定しない。
3. 宣言ごとに`DirectActivityRequirementsOwner`を作り、既存publishで明示recordを公開する。tokenやbinding publicationを複製・自己申告しない。
4. 正規routeへ実Direct Ownerを登録し、`ExecutiveRequirementsOwner(bounds, direct_routes=...)`へ§3のpolicyをpublishする。共有publishにはDirect publicationを渡さず、#695既存request-local captureに任せる。初期の非Direct sourcesは空tupleで、計画の出典を補作しない。
5. 同じexecution policyとboundsから`ExecutivePolicy`を作る。返却bindingは構成DTO・ExecutivePolicy・RequirementsOwner・Direct Owner集合・安全なprovenanceを保持する。partial failureでは新規Direct Ownerをcloseし、新規RequirementsOwnerの公開finalization_participantをretireする。注入したbinding Ownerはcloseしない。失敗した半構築物を公開しない。

生成数・規則数・source数・JSON bytesには同じD10 boundsを注入する。上限不足は構築/公開失敗へ閉じ、件数を削除したり容量値を追加しない。利用終了時も自分で構築したDirect OwnerのcloseとRequirementsOwnerのparticipantのretireだけを行い、注入Ownerを破棄しない。

初回publishのserialは既存Ownerが発行する`0`で、以後はそのOwnerの公開規則で増加する。これは構成revision=`1`とは別の値である。generationは実`ExecutiveRequirementsOwner.publish()`が発行する`RequirementsGeneration`のserial・tokenであり、config_revisionや固定値1を代入しない。factoryが実Ownerから取得したinitial generationと、その後の既存readerによるcurrent generationを区別する。runtime更新・capture・stale拒否・最終Fenceは#630 / #695の公開APIに従い、構成層に別の世代管理を作らない。

公開provenanceはconfig source（上記リポジトリ相対path）、schema/config IDとrevision、execution policy ID/revision、Requirements policy ID/revision、rule ID/revision、Direct宣言ID/revision、bounds ID/revision、実generation serialと既存serializerで安全に公開できる識別値を保持する。Owner実体・lock・token内部参照・credential・private pathは出さない。Systemのexact Git HEAD、配備mappingのsource/revision、character revisionとの結合は#692、実際に使用した構成との照合は#620が所有する。

再構築は受付前の明示的な初期化境界だけで行う。同一runtimeのresumeで新Ownerを作って既存generationを巻き戻さない。live変更は既存Ownerのrevision/currentness契約を通し、in-flight要求を新世代で救済しない。永続状態の復元やSystem lifecycleを本factoryで代行しない。

## 6. 実装時の受入検証

正常load・全具体値・descriptor/requestの同一policy・不変DTO・provenanceを検証する。欠落、malformed、未知field/schema/enum、重複key、bool/非有限数値、不正revision、循環aliasは失敗となることを確認する。test helper identityが本番構成へ入らないことを検証する。

6規則のexact構築と単一選択、3定数の明示emptyと未登録failureの区別、Directの実Owner / binding整合・request-local capture・未選択更新、計画source欠落、stale policy/source、candidate不足・余剰・型違い、最終Fenceを既存公開API経由で確認する。構築失敗時のcleanup、注入Ownerの非破壊、duplicate/ambiguous rule拒否も確認する。既存Executive / Brain integrationを維持する。

#691はS2 wiringやSystem acceptanceを完了扱いしない。実装後の品質検査・CI・独立レビューとHuman実動作検証の状態はCheckpointに分けて記録する。
