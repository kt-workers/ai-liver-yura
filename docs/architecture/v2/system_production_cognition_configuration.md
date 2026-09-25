# SystemのS2本番認知構成（#692）

Ownerは#360配下の#692。System compositionの設定・起動・資源所有・運用証拠を定め、Domain Stateを新設しない。工程状態はIssue / PR / Checkpointへ記録する。

## 1. 正本と固定する境界

[System契約](system_integration_contracts.md) §4のSystemCompositionSnapshotと§5のS2を具体化する。[Brain結合](brain_integration_contracts.md)、[最小本体構成](minimum_brain_production_configuration.md)、[Appraisal構成](appraisal_production_configuration.md)、[Executive構成](executive_production_configuration.md)、[Provider契約](llm_provider_adapter_contracts.md)のOwner・意味・数値・失敗を変更しない。

#690のAppraisal factory、#691のExecutive factory、#333のAttentionSchedulingPolicy.production()、#611のCoreCognitionConfiguration.compose()を使用する。#692はpolicy値やRequirements規則を作り直さない。#620が実際のSystem受入れを所有する。

## 2. S2専用設定

本番設定は`resources/config/v2/cognition_s2.yaml`、loader / 不変DTOは`app/config/cognition_s2.py`の`load_s2_config(source: str | bytes)` / `S2ProductionConfig`とする。設定の存在では起動しない。

| field | 初期値・契約 |
| --- | --- |
| schema_id | `yura.cognition-s2.production-config.v1` |
| config_id / config_revision | `yura.cognition-s2.production` / `1` |
| activation_id | `yura.cognition-s2.explicit` |
| composition_id / composition_revision | `yura.system.cognition-s2` / `1` |
| minimum_config | resource_ref=`resources/config/v2/minimum_brain.yaml`、config_id=`yura.minimum-brain.production`、config_revision=`1` |
| appraisal_config | resource_ref=`resources/config/v2/appraisal.yaml`、config_id=`yura.appraisal.production`、config_revision=`1` |
| executive_config | resource_ref=`resources/config/v2/executive.yaml`、config_id=`yura.executive.production`、config_revision=`1` |
| attention_policy | policy_id=`attention-scheduling-production`、policy_revision=`1` |
| provider_deployment | resource_ref=`resources/config/v2/provider_deployment_s2.yaml`、deployment_id=`yura.provider-deployment.s2`、deployment_revision=`1` |
| character_definition | resource_ref=`resources/character_definitions/v2/yura.yaml`、character_id=`yura`、definition_revision=`1` |

この表が最上位fieldの全件で、参照objectも記載fieldだけを許可する。identityは非空、revisionはboolでない1以上の整数。attention値は実production()のidentity/revisionと一致を要求し、その予算表は複製しない。人物参照はminimum構成のcharacter_definition_pathと同じ文書を指し、実`CharacterDefinitionDocument.definition_revision`と照合する。人物内容をSystemが定義しない。

resource_refはリポジトリ内の公開相対参照で、絶対path・上位脱出・外部URL・秘密参照を拒否する。解決後も許可root外を参照しない。Owner別loaderで読んだ実identity/revisionと完全一致しなければ拒否する。内部execution / Decay / Requirements値をS2 YAMLへ複製しない。

設定内容の変更はconfig_revisionを進める。構成の契約・登録集合の変更はcomposition_revisionも進める。参照先の変更はそのOwnerの変更管理に従い、旧参照をlatestへ自動更新しない。重複key・未知/欠落field・不明schema・未知enum・非文字列key・循環alias・任意タグを拒否し、DTOはfrozen / tuple / 再帰的不変値とする。

## 3. Provider deployment sourceと供給API

`resources/config/v2/provider_deployment_s2.yaml`は秘密を含まないdeployment manifestとする。schema_id=`yura.provider-deployment.s2.v1`、deployment_id / deployment_revisionは§2と一致し、`role_bindings`に登録Roleを一度ずつ保持する。manifest loaderと型は`app/config/provider_deployment.py`へ配置する。SystemがModelPolicyの計算・数値検証・retryを再実装しない。

各bindingは`role_id, availability_mode, mapping_ref, role_config_ref`を持つ。参照は`source_id, identity, revision`の3fieldで、revisionは非負整数、identity/source_idは非空の公開識別子。source_idはprivate pathや環境変数の生値ではない。availability_modeは`unconfigured`または`configured`。

初期登録集合は`input_meaning`、`subjective_appraisal`、`executive_deliberation`の3Roleとし、実descriptorのrole_idと照合する。初期同梱manifestは全Roleをunconfigured、両refを明示nullとする。これは提供先未指定を正確に表す構成であり、mappingを選定済み・接続成功と主張しない。S2の構築成功と正常なLLM認知成功を区別する。

configuredでは両refが必須。deployment側から明示注入される`S2ProviderConfigurationSource`の公開APIを次のとおり固定する。

- `resolve_model_policies(role_id, mapping_ref)`は、参照と一致するsource identity/revision、および`Mapping[LLMModelClass, OpenAIResponsesModelPolicy]`を不変publicationとして返す。
- `resolve_role_config(role_id, role_config_ref, model_policies)`は、参照と一致するsource identity/revisionと既存`OpenAIResponsesRoleConfig`を返す。Appraisalは#690のhelperを利用する。その他RoleもOwnerの既存instructions / input-output契約に一致する明示設定を供給し、System内で候補意味を補作しない。
- sourceはSystem / deployment AuthorityでありDomain Ownerではない。publicationを一つの起動snapshotへfreezeし、同identity/revisionで内容を変えない。取得中のsource更新は拒否する。source実体は外部注入で借用し、Systemがcloseしない。

mapping publicationの全要素について、Role、論理model class、reasoning effort、mapping_id / mapping_revision、具体model参照、format/config参照を対応付ける。論理要求は読み込んだOwnerのexecution policyから取得し、YAMLへ二重保存しない。具体model / reasoning文字列はdeployment sourceの値だけを使う。本書でモデル名を発明しない。Role configのmodel_policiesはそのpublicationと同一内容とし、別mappingに差し替えない。

既存#357の型検証・model/effort対応・output上限・temperature mappingを使用する。入力schema、出力schema、instructions、failure_policyは登録descriptorのOwner契約と照合する。format nameは既存safe-name検証とRole間重複拒否を通す。構成済みなのにsource不在・未対応・不一致ならPROVIDER_MAPPING_FAILEDで起動前に拒否し、Unavailableや他モデルへfallbackしない。

### 3.1. 認証と資源の境界

manifestはAPI key・credential・SDK object・生環境値を含まない。credential確認とclient生成は既存Infrastructureの提供先構成境界に残す。Systemは認証値を取得・検査・公開しない。

全Roleがunconfiguredで、Infrastructureが提供先未構成と判定した場合は既存UnavailableLLMRolePortへ同じdescriptor集合を渡す。credentialが構成済みなのにmanifestがunconfiguredの場合や、configured manifestなのにcredential未構成の場合はactivationを拒否する。混在modeはrevision 1では未対応として拒否する。minimum起動の既存未構成動作は変更しない。

configured時のInfrastructure構築結果は`S2ProviderLease`としてSystemへ渡す。これは既存LLMRolePort、検証済みRole/mapping publication、非秘密なavailability、非同期release操作を束ねる構成契約である。既存Adapterの意味契約を置き換えない。Infrastructureが生成したclientを所有するleaseはそのclientの公開closeをreleaseに結び付け、外部注入clientを借用するleaseはそれをcloseしない。SystemはSDK型・private属性を辿って資源を破棄しない。既存のportだけを返すAPIにcloseがあると仮定せず、この所有契約を満たすInfrastructure composition入口で同じAdapterを構築する。

Systemが作ったlease / wrapperはowned、外部から既に完成したleaseを借用する場合はborrowedと構築時に固定する。所有の有無を例外の種類やclose属性の有無から推測しない。test providerは外部I/O置換として注入する試験だけで使用し、本番fallbackに登録しない。

## 4. 明示起動と構築順

入口は`app/bootstrap.py::build_s2_production_core(...)`、実構成は`app/composition/system_cognition_configuration.py`へ配置する。返却型は`S2ProductionApplication`とし、既存MinimumCoreApplicationを保持するSystem wrapperとする。`build_minimum_core(cognition=None)`とCLI既定のINPUT_MEANING-only経路は維持する。

入口はS2 config参照、`S2RunIdentity`、fresh-startの明示、既存RuntimeClock、deployment source / provider lease構築境界、借用するregistry / precondition router / bindings / Direct binding集合を必須の型付き引数で受ける。共有Ownerを作り直さない。fast appraisal rulesも正規Ownerが承認した明示tupleを受け、欠落を隠すdefaultにしない。任意のSpeech / Execution等の拡張は既存型をそのまま明示注入する。S2構築のために模擬Goal・scope・Memory・Factを生成しない。

1. S2 / minimum / deployment manifestを厳密loadし、人物文書を既存loaderで一度だけ取得する。期待する参照identity/revisionと実値を照合し、activation_idを明示要求したcallerか確認する。git/runtime/run identityを検証する。
2. 既存bootstrapのFoundation生成・参照文脈生成を共有する準備段階を置く。同じGoal / Activity OwnerからCoreInputReferenceContextBindingを作り、その実snapshotのsource_context_revisionを取得する。この準備文脈を後続Coreへそのまま渡し、Core側で別Ownerを再生成しない。固定revision=0で代替しない。
3. #690のloader / build_appraisal_configurationへ明示fresh-start、上記実revision、同じclockのaware UTC時刻、同じruntime_epochを渡す。以前の主体の復元が必要なら本fresh-start入口では拒否する。Reducer、execution、Decay policyとprovenanceをそのまま保持する。Decayの別timer・規則をSystemが生成しない。
4. #691のread/load / create_executive_configurationへ同じboundsと正規Direct binding集合を渡す。実RequirementsOwner・initial generation・cleanupをそのまま利用する。
5. AttentionSchedulingPolicy.production()を取得して参照identity/revisionを照合し、S2が所有するAttentionTurnStoreを構築する。
6. minimumのInput Meaning、Appraisal、Executiveの同じpolicy実体からdescriptorを取得し、§3のmanifest/sourceを解決する。検証済み同一snapshotのprovider leaseを構築する。
7. CoreCognitionConfigurationへAppraisalのstate/policy、Executiveのpolicy/RequirementsOwner、Attention、借用registry/routerと明示bindingを設定する。既存compose / deliveryを再利用する。
8. minimumの共通構成処理へ、上記認知構成・同じProvider port・同じ準備済みFoundation / reference / clockを明示注入する。_load_coreが再度Providerを暗黙構築しないよう、S2の明示引数付き経路と既存既定経路を分ける。minimumの公開既定動作は変えない。
9. 全構成のidentity・generationを再照合後、§5のsnapshotを発行して返す。タスク受付開始は返却後の明示start()のみ。途中構築物・部分provenanceを成功として公開しない。

CoreInputReferenceContextBindingとAppraisal初期化のrevision照合を受付前に行う。取得と結合の間の正規Owner更新を新revisionへ付替えずINITIALIZATION_FAILEDとする。runtimeの以後の現在性は既存Owner / #611 / 最終Fenceに従う。

## 5. typed System provenance

`app/composition/system_cognition_configuration.py`にfrozenな`SystemCompositionSnapshot`を定義し、既存System正本§4の概念に対応する唯一のSystem DTOとする。component/provider/subsystem bindingsは不変typed tupleとする。

| field | 実際の供給元 |
| --- | --- |
| composition_id / composition_revision | 検証済みS2 config |
| config_id / config_revision / activation_id | 同じS2 config |
| git_head | S2RunIdentityの検証済みexact HEAD |
| runtime_epoch / system_run_id | 同じS2RunIdentity |
| created_at | 構築完了時の既存RuntimeClock、aware UTC |
| character_definition_revision / character_id | 実際にCoreへ渡す検証済み文書 |
| component_bindings | minimum構成のidentity、#690 / #691の既存provenance、Attentionの実policy ID/revisionと登録identity |
| provider_bindings | 実Role ID、mode、deployment/source/ref identity/revision、解決済みmapping ID/revision・論理class/effort、schema/format/config識別。unconfiguredは解決済みmappingなしを明示 |
| subsystem_bindings | 実際の明示登録だけ。未登録は空tupleで成功を補作しない |
| requirements_generation | #691の実initial_generation.serialと既存serializerの安全な世代識別情報 |

`S2RunIdentity(git_head, runtime_epoch, system_run_id)`の発行AuthorityはSystem起動caller（#360）とする。git_headはcheckoutのGitで取得したexact commitまたは信頼済みbuild manifest由来の40桁hexを、稼働artifactの値と照合する。未知値・dirty artifactを本番exact HEAD証拠にしない。DomainでGitを実行せず、branch名だけで代替しない。

runtime_epochはそのプロセスのSystem lifecycleが発行する非空identityで、同じAppraisal・Core・永続結合へ使う。system_run_idはSystem起動試行の非空identityで、#620が起動を所有する場合は既存Validation runのrun_idとの対応を明示して渡す。Systemは実行中に再発行しない。新プロセス/新試行のidentityと同一runtimeでのresumeを混同しない。これらはSystem由来でありDomain revisionの代替ではない。

snapshotは初期構成の証拠であり、後刻のcurrent stateを保証しない。#620の観測時には既存Ownerのpublic generationと実行結果を別途照合する。Owner instance object・lock・raw token・SDK object・credential・絶対/private pathを公開しない。Providerの具体model文字列や内部source実体をDomainへ流さず、公開証拠には安全な参照identityを保持する。

## 6. 所有と終了

System wrapperは生成した資源の所有台帳を持ち、成功時は同じ台帳を返却bindingへ移す。既存Ownerに新しいclose意味を追加しない。

| 対象 | 所有・終了操作 |
| --- | --- |
| S2生成Foundation / MinimumCoreApplication | owned。既存Core.stop()で配送・タスク・lifecycleを回収 |
| AppraisalProductionBinding / InternalStateReducer | owned。非同期資源やclose APIはない。Coreの利用終了後に参照を解放し、架空のcloseを呼ばない |
| ExecutiveProductionBinding | owned。#691のclose()のみ使用し、借用Direct bindingは破棄しない |
| S2生成AttentionTurnStore | owned。利用終了後に公開finalization_participant.retire() |
| S2生成Provider lease / composition wrapper | owned。利用終了後にrelease。内部clientの所有はInfrastructureのlease契約に従う |
| 注入registry/router/Direct Owner/Character source/shared infrastructure/external client | borrowed。台帳に終了操作を登録しない |

partial construction failureは台帳を逆順にunwindする。正常終了も、最後に構築したCoreの受付・子タスクを既存stop()で回収した後、Provider lease、Attention、Executive、Appraisal、残るowned準備資源の順に解放する。Coreへ所有移管済みのFoundationは二重終了しない。cleanup途中の失敗でも残りのowned解放を続け、失敗分類を保持する。

wrapper.stop()は同じ終了taskを共有しidempotentとする。取消下でも既存bootstrapのcleanup回収方式に従って最後まで待ち、その後取消を再送出する。失敗したstart()も同じ回収経路を通す。停止済みwrapperを再startせず、新しい明示起動で新run identityを使う。同一runtime resumeでfactoryを再実行してstate/generationを初期化しない。

## 7. 失敗とEarly Boot互換

公開例外は`S2ConfigurationError`、codeは次に限定する。診断には必要な安全なOwner codeを保持できるが、内部例外原文・生YAML・path・secretを含めない。

| code | 条件 |
| --- | --- |
| MISSING_SYSTEM_CONFIG | 明示S2起動でS2設定・参照manifestが取得不能 |
| INVALID_SYSTEM_CONFIG | schema/field/revision/identity/参照/実行identity不整合 |
| APPRAISAL_CONFIGURATION_FAILED | #690の読取・検証・factory失敗 |
| EXECUTIVE_CONFIGURATION_FAILED | #691の読取・factory失敗。既存固定codeを安全なcauseとして保持 |
| PROVIDER_MAPPING_FAILED | deployment/source/mapping/Role設定/availability整合失敗 |
| COGNITION_COMPOSITION_FAILED | CoreCognitionConfiguration・既存composeの結合失敗 |
| ACTIVATION_FAILED | 明示activation・fresh-start前提不成立、start失敗、停止済み再利用 |
| INITIALIZATION_FAILED | 世代変更・最終照合失敗・その他構築/回収失敗 |

実行開始後の既存Owner / Provider typed failureを構成成功に変換しない。CancelledErrorは取消として伝播し、cleanup後も成功や通常失敗へ潰さない。Appraisal / Executiveの正常なfactory結果をSystem独自の方針で再解釈しない。

S2 config欠落はS2を要求した起動だけの失敗である。minimum CLIがS2ファイルを探索したり、自動的にS2へ切り替わったりしない。S2失敗後に黙ってminimumとして成功を返さない。別途明示したminimum起動は従来どおり可能である。

## 8. #620への公開と受入境界

返却wrapperのread-only composition_snapshotから、稼働したS2 config、Owner構成、mapping、人物、exact HEAD、runtime/system run identityを一括取得できるようにする。#620はこれを実際に起動した同一System runの観測に束縛する。正常LLM応答・発話・実環境成功をsnapshotの存在だけで主張しない。

実装時は正規factory利用、identity/revision不一致、missing/malformed、未構成と構成不正の区別、Early Boot不変、source更新、部分構築回収、借用Owner保全、取消・繰返し停止・非直列foregroundを検証する。#620の8ケースやPR #689を先行変更せず、#692の採用後に同じ#620系統で受入れを再開する。
