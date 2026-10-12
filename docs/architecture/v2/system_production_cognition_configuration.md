# Systemのゆら本体構成（#692）

Ownerは#360配下の#692。System compositionの設定・起動・資源所有・運用証拠を定め、Domain Stateを新設しない。工程状態はIssue / PR / Checkpointへ記録する。

## 1. 正本と固定する境界

[System契約](system_integration_contracts.md) §4のSystemCompositionSnapshotと§5のゆら本体を具体化する。[Brain結合](brain_integration_contracts.md)、[本体Runtime構成](system_production_cognition_configuration.md)、[Appraisal構成](appraisal_production_configuration.md)、[Executive構成](executive_production_configuration.md)、[Provider契約](llm_provider_adapter_contracts.md)のOwner・意味・数値・失敗を変更しない。

#690のAppraisal factory、#691のExecutive factory、#333のAttentionSchedulingPolicy.production()、#611のCoreCognitionConfiguration.compose()を使用する。#692はpolicy値やRequirements規則を作り直さない。#620が実際のSystem受入れを所有する。

## 2. ゆら本体専用設定

本番設定は`config/core.yaml`、loader / 不変DTOは`app/config/core.py`の`load_core_config(source: str | bytes)` / `CoreConfig`とする。設定の存在では起動しない。

| field | 初期値・契約 |
| --- | --- |
| schema_id | `yura.core-config.v1` |
| config_id / config_revision | `yura.core` / `1` |
| activation_id | `yura.core.explicit` |
| composition_id / composition_revision | `yura.system.core` / `1` |
| input_meaning / scheduler / integration / shutdown | `config/core.yaml`内の本体Runtime方針 |
| appraisal_config | resource_ref=`config/appraisal.yaml`、config_id=`yura.appraisal.production`、config_revision=`1` |
| executive_config | resource_ref=`config/executive.yaml`、config_id=`yura.executive.production`、config_revision=`1` |
| attention_policy | policy_id=`attention-scheduling-production`、policy_revision=`1` |
| llm_connections | resource_ref=`config/llm_connections.yaml`、config_id=`yura.llm-connections`、config_revision=`1` |
| input_meaning_llm_connection_id | Input Meaningが参照する接続ID |
| character_definition | resource_ref=`config/character/yura.yaml`、character_id=`yura`、definition_revision=`1` |

この表が最上位fieldの全件で、参照objectも記載fieldだけを許可する。identityは非空、revisionはboolでない1以上の整数。attention値は実production()のidentity/revisionと一致を要求し、その予算表は複製しない。人物参照は実`CharacterDefinitionDocument.definition_revision`と照合する。人物内容をSystemが定義しない。

resource_refはリポジトリ内の公開相対参照で、絶対path・上位脱出・外部URL・秘密参照を拒否する。解決後も許可root外を参照しない。Owner別loaderで読んだ実identity/revisionと完全一致しなければ拒否する。内部execution / Decay / Requirements値をゆら本体 YAMLへ複製しない。

設定内容の変更はconfig_revisionを進める。構成の契約・登録集合の変更はcomposition_revisionも進める。参照先の変更はそのOwnerの変更管理に従い、旧参照をlatestへ自動更新しない。重複key・未知/欠落field・不明schema・未知enum・非文字列key・循環alias・任意タグを拒否し、DTOはfrozen / tuple / 再帰的不変値とする。

## 3. LLM接続集合と内部Adapter

`config/llm_connections.yaml`は秘密を含まない接続集合である。schema_idは`yura.llm-connections.v1`、各`llm_connections`要素は一意な`id`、内部Adapterを選ぶ`adapter`、接続固有の`settings`だけを持つ。接続が一件もない、IDが重複する、未知Adapter、settings不正、必要な資格情報の欠落は起動前に拒否する。未構成を`UnavailableLLMRolePort`や別接続へ変換しない。

AppraisalとExecutiveは各設定の`llm_connection_id`で、Input Meaningは本体設定の`input_meaning_llm_connection_id`で接続を選ぶ。これは各Ownerが使用する接続への参照であり、Role別の利用者設定ではない。Role、instructions、入出力schema、failure policyは既存Domain descriptorと内部Adapterだけが扱い、設定から変更できない。

構成層は接続IDごとにclientとclose操作を所有し、同じ接続を参照するOwnerへ共通`LLMRolePort`を渡す。起動失敗・取消・停止では生成済みclientを逆順に一度だけ回収する。snapshotへはRole IDと接続IDだけを記録し、credential、SDK object、endpoint、具体model、settingsを出さない。OpenAI接続は`YURA_OPENAI_API_KEY`だけを使用し、`OPENAI_API_KEY`へfallbackしない。

## 4. 明示起動と構築順

入口は`app/bootstrap.py::build_core(...)`、実構成は`app/composition/system_cognition_configuration.py`へ配置する。返却型は`CoreApplication`とし、既存`CoreRuntimeApplication`を保持するSystem wrapperとする。CLIはこの本体構成だけを使用する。

入口はゆら本体 config参照、`CoreRunIdentity`、fresh-startの明示、既存RuntimeClock、内部固定のLLM接続Adapter集合、借用するregistry / precondition router / bindings / Direct binding集合を必須の型付き入力として受ける。共有Ownerを作り直さない。fast appraisal rulesも正規Ownerが承認した明示tupleを受け、欠落を隠すdefaultにしない。任意のSpeech / Execution等の拡張は既存型をそのまま明示注入する。ゆら本体構築のために模擬Goal・scope・Memory・Factを生成しない。

1. ゆら本体 / minimum / LLM接続集合を厳密loadし、人物文書を既存loaderで一度だけ取得する。期待する参照identity/revisionと実値を照合し、activation_idを明示要求したcallerか確認する。git/runtime/run identityを検証する。
2. 既存bootstrapのFoundation生成・参照文脈生成を共有する準備段階を置く。同じGoal / Activity OwnerからCoreInputReferenceContextBindingを作り、その実snapshotのsource_context_revisionを取得する。この準備文脈を後続Coreへそのまま渡し、Core側で別Ownerを再生成しない。固定revision=0で代替しない。
3. #690のloader / build_appraisal_configurationへ明示fresh-start、上記実revision、同じclockのaware UTC時刻、同じruntime_epochを渡す。以前の主体の復元が必要なら本fresh-start入口では拒否する。Reducer、execution、Decay policyとprovenanceをそのまま保持する。Decayの別timer・規則をSystemが生成しない。
4. #691のread/load / create_executive_configurationへ同じboundsと正規Direct binding集合を渡す。実RequirementsOwner・initial generation・cleanupをそのまま利用する。
5. AttentionSchedulingPolicy.production()を取得して参照identity/revisionを照合し、ゆら本体が所有するAttentionTurnStoreを構築する。
6. minimumのInput Meaning、Appraisal、Executiveの同じpolicy実体からdescriptorを取得し、§3の接続集合を解決する。各Ownerの接続IDが存在することを照合し、接続clientを構築する。
7. CoreCognitionConfigurationへAppraisalのstate/policy、Executiveのpolicy/RequirementsOwner、Attention、借用registry/routerと明示bindingを設定する。既存compose / deliveryを再利用する。
8. minimumの共通構成処理へ、上記認知構成・同じProvider port・同じ準備済みFoundation / reference / clockを明示注入する。_load_coreが再度Providerを暗黙構築しないよう、ゆら本体の明示引数付き経路と既存既定経路を分ける。minimumの公開既定動作は変えない。
9. 全構成のidentity・generationを再照合後、§5のsnapshotを発行して返す。タスク受付開始は返却後の明示start()のみ。途中構築物・部分provenanceを成功として公開しない。

CoreInputReferenceContextBindingとAppraisal初期化のrevision照合を受付前に行う。取得と結合の間の正規Owner更新を新revisionへ付替えずINITIALIZATION_FAILEDとする。runtimeの以後の現在性は既存Owner / #611 / 最終Fenceに従う。

## 5. typed System provenance

`app/composition/system_cognition_configuration.py`にfrozenな`SystemCompositionSnapshot`を定義し、既存System正本§4の概念に対応する唯一のSystem DTOとする。component/provider/subsystem bindingsは不変typed tupleとする。

| field | 実際の供給元 |
| --- | --- |
| composition_id / composition_revision | 検証済みゆら本体 config |
| config_id / config_revision / activation_id | 同じゆら本体 config |
| runtime_epoch / system_run_id | 同じCoreRunIdentity |
| created_at | 構築完了時の既存RuntimeClock、aware UTC |
| character_definition_revision / character_id | 実際にCoreへ渡す検証済み文書 |
| component_bindings | minimum構成のidentity、#690 / #691の既存provenance、Attentionの実policy ID/revisionと登録identity |
| llm_connection_bindings | 実Role IDと、対応する設定済み接続ID。接続設定・資格情報・SDK object・具体modelは含めない |
| subsystem_bindings | 実際の明示登録だけ。未登録は空tupleで成功を補作しない |
| requirements_generation | #691の実initial_generation.serialと既存serializerの安全な世代識別情報 |

`CoreRunIdentity(runtime_epoch, system_run_id)`の発行AuthorityはSystem起動caller（#360）とする。実行識別子は各起動を区別するための値であり、GitのHEAD、checkout状態、作業ツリー状態を起動条件または実行構成の証拠にしない。

runtime_epochはそのプロセスのSystem lifecycleが発行する非空identityで、同じAppraisal・Core・永続結合へ使う。system_run_idはSystem起動試行の非空identityで、#620が起動を所有する場合は既存Validation runのrun_idとの対応を明示して渡す。Systemは実行中に再発行しない。新プロセス/新試行のidentityと同一runtimeでのresumeを混同しない。これらはSystem由来でありDomain revisionの代替ではない。

snapshotは初期構成の証拠であり、後刻のcurrent stateを保証しない。#620の観測時には既存Ownerのpublic generationと実行結果を別途照合する。Owner instance object・lock・raw token・SDK object・credential・絶対/private pathを公開しない。Providerの具体model文字列や内部source実体をDomainへ流さず、公開証拠には安全な参照identityを保持する。

## 6. 所有と終了

System wrapperは生成した資源の所有台帳を持ち、成功時は同じ台帳を返却bindingへ移す。既存Ownerに新しいclose意味を追加しない。

| 対象 | 所有・終了操作 |
| --- | --- |
| ゆら本体生成Foundation / CoreRuntimeApplication | owned。既存Core.stop()で配送・タスク・lifecycleを回収 |
| AppraisalProductionBinding / InternalStateReducer | owned。非同期資源やclose APIはない。Coreの利用終了後に参照を解放し、架空のcloseを呼ばない |
| ExecutiveProductionBinding | owned。#691のclose()のみ使用し、借用Direct bindingは破棄しない |
| ゆら本体生成AttentionTurnStore | owned。利用終了後に公開finalization_participant.retire() |
| ゆら本体生成LLM connection registry / composition wrapper | owned。利用終了後に逆順close。内部clientは接続Adapterが所有する |
| 注入registry/router/Direct Owner/Character source/shared infrastructure/external client | borrowed。台帳に終了操作を登録しない |

partial construction failureは台帳を逆順にunwindする。正常終了も、最後に構築したCoreの受付・子タスクを既存stop()で回収した後、Provider lease、Attention、Executive、Appraisal、残るowned準備資源の順に解放する。Coreへ所有移管済みのFoundationは二重終了しない。cleanup途中の失敗でも残りのowned解放を続け、失敗分類を保持する。

wrapper.stop()は同じ終了taskを共有しidempotentとする。取消下でも既存bootstrapのcleanup回収方式に従って最後まで待ち、その後取消を再送出する。失敗したstart()も同じ回収経路を通す。停止済みwrapperを再startせず、新しい明示起動で新run identityを使う。同一runtime resumeでfactoryを再実行してstate/generationを初期化しない。

## 7. 失敗とEarly Boot互換

公開例外は`CoreConfigurationError`、codeは次に限定する。診断には必要な安全なOwner codeを保持できるが、内部例外原文・生YAML・path・secretを含めない。

| code | 条件 |
| --- | --- |
| MISSING_SYSTEM_CONFIG | 明示ゆら本体起動でゆら本体設定・参照manifestが取得不能 |
| INVALID_SYSTEM_CONFIG | schema/field/revision/identity/参照/実行identity不整合 |
| APPRAISAL_CONFIGURATION_FAILED | #690の読取・検証・factory失敗 |
| EXECUTIVE_CONFIGURATION_FAILED | #691の読取・factory失敗。既存固定codeを安全なcauseとして保持 |
| PROVIDER_MAPPING_FAILED | deployment/source/mapping/Role設定/availability整合失敗 |
| COGNITION_COMPOSITION_FAILED | CoreCognitionConfiguration・既存composeの結合失敗 |
| ACTIVATION_FAILED | 明示activation・fresh-start前提不成立、start失敗、停止済み再利用 |
| INITIALIZATION_FAILED | 世代変更・最終照合失敗・その他構築/回収失敗 |

実行開始後の既存Owner / Provider typed failureを構成成功に変換しない。CancelledErrorは取消として伝播し、cleanup後も成功や通常失敗へ潰さない。Appraisal / Executiveの正常なfactory結果をSystem独自の方針で再解釈しない。

ゆら本体 config欠落はゆら本体を要求した起動だけの失敗である。別構成CLIがゆら本体ファイルを探索したり、自動的にゆら本体へ切り替わったりしない。ゆら本体失敗後に黙ってminimumとして成功を返さない。別途明示した別構成起動は従来どおり可能である。

## 8. #620への公開と受入境界

返却wrapperのread-only composition_snapshotから、稼働したゆら本体 config、Owner構成、mapping、人物、exact HEAD、runtime/system run identityを一括取得できるようにする。#620はこれを実際に起動した同一System runの観測に束縛する。正常LLM応答・発話・実環境成功をsnapshotの存在だけで主張しない。

実装時は正規factory利用、identity/revision不一致、missing/malformed、未構成と構成不正の区別、Early Boot不変、source更新、部分構築回収、借用Owner保全、取消・繰返し停止・非直列foregroundを検証する。#620の8ケースやPR #689を先行変更せず、#692の採用後に同じ#620系統で受入れを再開する。

## 9. Speech本番構成の明示接続（#702）

### 9.1. 構成Authorityと公開入口

#702 / #360は、既存Speech Ownerの本番policy・公開binding・pipelineを束ねるSystem composition factoryを所有する。#613の配送・Fact還流、#701の非直列準備、#348のgeneration / 提示 / 資源回収、#358のTTS契約を変更しない。factoryはDomainの新しい意味Ownerではなく、試験fixtureを本番値の正本にしない。

`app/composition/speech_production_configuration.py`に`create_production_speech_configuration(...)`を配置する。型付き入力`SpeechProductionInputs`から`SpeechProductionBinding`を生成する。返却bindingは既存`CoreSpeechConfiguration`、凍結した構成由来、構築資源の回収責務を保持する。新しいSpeech意味DTOは作らない。

`build_core(...)`と`compose_core(...)`は`SpeechProductionInputs | None`の任意引数`speech`を受ける。未指定のdefaultは`None`。指定時はSystem factoryを一度呼び、その返却`configuration`を`CoreCognitionConfiguration.speech`へ設定する。自由な`build` callableだけを本番構成証拠として受理する経路は設けない。既存CoreSpeechConfigurationの汎用注入APIは保持する。

### 9.1.1 本番CLI起動root

#729のCLI起動rootは`python -m app`だけを受理する。ゆら本体設定のactivation ID、runごとのruntime epochとsystem run ID、既存Runtime Ownerを明示して`build_core()`を呼ぶ。`PluginRegistryAuthority`、`PreconditionSourceRouter`、Activity binding、fast appraisal ruleは起動rootが新runへ生成又は明示注入する既存Ownerであり、試験fixture又は外部Providerの代替ではない。

CLIは`user.yaml`の`speech: null`で`None`を渡す。この場合、Speech用semantic owner、Memory、TTS、Presentation登録を生成又は要求しない。Speech有効時は起動rootが既存`SpeechSemanticPolicyOwner`、Memory binding、trusted `SpeechDeploymentRegistry`を明示注入して`create_speech_deployment()`を呼ぶ。いずれかがない場合は構成を拒否し、Speechなし、別voice、`TEXT_ONLY`、模擬portへ変換しない。実Providerと実音声の接続は#621が所有する。

factoryへの入力は呼出元が明示供給する。不足をfixture、別voice、既定Provider、空の成功bindingで補わない。Systemは秘密値・環境変数を探索しない。

### 9.2. 入力の供給元

| 入力 | Authorityと照合 |
| --- | --- |
| 構成identity | deploymentが発行する`source_id`、`config_id` / `config_revision`、`binding_id` / `binding_revision`、`binding_generation`を明示要求する。同じidentity/revisionで内容を変更しない |
| Speech意味 | `SpeechSemanticPolicyOwner`と`ProductionSpeechSources`を既存`bind_speech_semantics_policy_v1`で束ねる。同じ返却bindingのcontext builderとExecutive evidenceを使用し、MeaningPolicy V1を複製しない |
| source接続 | 同じゆら本体のFoundation / reference / Activity Ownerを受ける型付きsource構成境界。外部Memory等は既存production publication / 公開bindingを明示供給する。構成側がFact、token、主体identityを補作しない |
| Character | #330の既存policy、CharacterLanguageAuthority、live-state/bounds reader、LLMRolePort。人物文書のidentity/revisionを同じゆら本体の文書と照合する |
| Verifier | #363の既存policy、LLMRolePort、current context reader。必須検証をTTS成功で代替しない |
| Performance | #331の既存projection policyとcurrent context reader。投影規則や表現意味をSystemへ複製しない |
| Runtime | #348のpolicy、admission priority、expiry policy参照、許可output mode、TTS preparation modeを明示要求。Runtime / queue / admissionは同じoperational policyを使用する |
| TTS / output | deploymentが束ねた既存output preparation portとPreparedAudioDiscardPortの対、公開binding identity/revision、availability。正常返却前はproducerが回収責務を持ち、正常返却後は#701の所有権契約に従う |
| Presentation | 既存process Supervisorを構成する型付き提供境界、公開binding identity/revision、availability、既存current revalidation reader。TTS資源と同じ提示契約に対応することを供給側が保証する |
| 通知 | 同じゆら本体 cognition / reference / Activityを使い、#613の既存通知・提示Fact配送を構成する。別Activity Ownerを生成しない |

Owner policyは実際に既存Owner constructorへ渡す不変値を保持し、その値からpolicy identity/revisionを投影する。完成Ownerのprivate属性を辿ってpolicyを推測せず、別に渡したラベルだけで証拠を作らない。公開policyにないrevisionをSystemが捏造しない。policyにidentityがない部分は、供給元のimmutable binding revisionと使用する既存policy型・公開値の対応を構成側で固定する。

Speech用LLMのRole登録と実portは供給元bindingで明示する。既存ゆら本体の3Role manifestへ未登録Roleを黙って追加しない。Roleのinstructions / policy / schemaは既存Owner、具体model/reasoning mappingはdeploymentのAuthorityを維持する。Speech component内のprovider参照は実際に使用するRole登録の公開identity/revisionへ結び付ける。

Speech用Provider入力は#726の`SpeechProviderBindingPublication`だけから得る。このpublicationはSpeech四Roleのexact descriptors、configs、validated `ProviderBindingSnapshot`、availability mode、deployment / binding identityとrevisionを同一snapshotとして保持する。factoryは受領した四集合の完全一致とcurrentnessを検証して既存`CoreProviderLeaseFactory`へ渡す。cognition用manifest、fixture、任意のsource reference、別deploymentのbindingを補作又は流用しない。

`SpeechDeploymentPortFactory`の本番実装は、#720の`TTSProductionConnection`、#711のtrusted `PresentationWorkerRegistry`、#721の`CoreSpeechProductionOwnerConnection`を返す型付き公開resolver、既存`CoreProviderLeaseFactory`を明示入力として保持する。#726から得たProvider登録用Role/config/binding/modeは`CoreProviderLeaseFactory`だけへ渡し、返却する`SpeechProductionPorts.roles`には`SpeechProductionPublication.roles()`のDomain用Roleだけを渡す。LLM lease、TTS lease、Presentation leaseを取得してportsを返した後、#702が同一ゆら本体 cognition / referenceを確定した時だけ、構成ハンドル内でresolverを一度だけ同期的に解決する。固定済みconnectionはreaderと全notificationで再利用し、未結合、二重結合、別graphへの再結合を拒否する。factoryは具体provider、voice、reader、Normalizer、Activity、Attention、clock、trace又はgenerationを補作しない。

返却前の任意の失敗又はcaller cancellationでは、既に取得したleaseを逆順に一度だけ回収する。子leaseの通常失敗又は取消があっても残りの回収を飛ばさず、全cleanup settlement後に元の失敗又は取消を伝播する。回収failureは固定の安全な診断として残すが、元の失敗又は取消を置換しない。返却後のlease releaseは`SpeechProductionBinding`が保持し、反復・並行releaseは同じ回収へ合流する。借用された#721 Owner graph、Provider factory、TTS connection、Presentation registryをcloseしない。

configured時はRole config、model mapping、mapping / Role-config reference、schema、Provider output formatが同じSpeech publicationに属することを確認する。unconfigured時は既存typed unavailableを維持し、架空のconfig / mapping / referenceを生成しない。設定不良、Role不一致、stale、source更新をunconfigured又はSpeechなしへのfallbackに変換してはならない。取得中にpublicationのcurrentnessが失われた場合は、返却前のowned leaseを既存契約どおり回収して構築を拒否する。

具体voice/provider/speaker/style/credentialは本書で決定しない。deploymentが供給する型付きbindingを既存Ownerが検査する。構成不正と未構成を区別し、音声出力を要求するのにbindingがない場合は構築拒否。明示したunavailable bindingは既存typed unavailableを返し、正常音声や別voiceへ変換しない。TEXT_ONLYは既存policyで明示許可された場合だけ使用でき、TTS不在を理由にSystemが切り替えない。

### 9.3. identity・revision・generation

構成identityは本書の`identity()`相当の公開識別子制約、revisionとbinding_generationはboolでない1以上の整数とする。固定の本番IDや環境固有値を同梱値として発明しない。deploymentのsourceは同一bindingの内容を凍結し、変更時にrevisionとbinding_generationを進め、新しいSystem runで再構築する。本境界でhot replacementは行わない。

`binding_generation`はSystem構成の供給世代であり、SpeechRuntimeのcandidate generationやOwnerのpolicy generationではない。Ownerのpolicy identity/revision、publicationのcurrentnessは元Ownerの公開APIで別途照合する。raw generation tokenをsnapshotへ入れない。candidate未生成時に架空のcandidate generationを発行しない。

入力取得時、Coreへの登録時、snapshot発行直前に、同じsource/bindingのidentity/revision/generationと元Ownerのcurrent publicationを照合する。差異があれば新しい値への付替えをせず構築を拒否する。起動後のcandidate currentnessと最終Fenceは既存Runtime / 各Ownerの責務のまま残す。

### 9.4. 実構築順と同一性

1. 既存ゆら本体設定・人物・Foundation / referenceを準備する。Speech指定時のActivityは既存`SPEECH_OBSERVATION_POLICY`を使用して生成し、同じActivityをreferenceとCoreへ渡す。Speech未指定時の既存Activity構成を変更しない。
2. 既存の順序でAppraisal、Executive / Requirements、Attention、cognition用Providerを構築する。
3. Speech inputsを検証し、同じreferenceからsource bindingを得る。System factoryは同じSpeech semantic bindingからExecutive evidenceとcontext builderを取得する。入力identityを凍結し、資源生成を回収台帳へ即時登録する。
4. Speech用Runtime、queue、task registry、discarder、admission、Presentation executor / Supervisorと#701のCoreSpeechPipelineを既存constructorから構成する。cognition確定後に必要なreader/notificationの接続は、返すCoreSpeechConfiguration.buildの一度限りの同期結合で行う。非同期lease取得はその前段で完了させ、同期callback内で非同期cleanupが必要な外部資源を新規取得しない。
5. `CoreCognitionConfiguration.speech`へ同じconfigurationを注入して既存`_compose_core`を呼ぶ。既存`CoreCognitionConfiguration.compose()`が先にExecutiveへ`self.speech.evidence`を渡し、その後一度だけ`self.speech.compose(delivery, reference)`を呼ぶ順序を維持する。Systemから二重composeしない。
6. 登録pipelineのcontextが同じsemantic bindingを使い、Executive evidenceもそのbindingを参照することをfactoryが保持した実参照で検証する。pipeline/runtime/queue/discarder/output producerの資源接続は同じ構成ハンドルから行い、異なるresource Ownerのport対を混ぜない。
7. Core返却と最終identity/currentness検査の成功後にだけSystemCompositionSnapshotを作る。startは既存どおり返却後。登録前snapshotへのSpeech証拠の後付けは禁止する。

buildの二回呼出し、別cognition/reference/runへのbinding再利用は拒否する。既存generic CoreSpeechConfigurationの意味を変更せず、本番factoryの一度限りの構成ハンドルで制御する。

### 9.5. 所有権・終了・部分構築失敗

| 対象 | 所有と回収 |
| --- | --- |
| 注入されたpolicy/source設定、共有Owner、外部client、共有LLM/TTS port | borrowed。Systemがcloseしない |
| factoryが生成するpipeline、Runtime、queue、task registry、executor | owned。Coreへの移管前はSpeechProductionBindingの回収台帳が保持 |
| factoryが取得するPresentation/TTS lease wrapper | owned wrapperだけreleaseする。lease内部の共有clientは供給元の所有契約に従い閉じない |
| candidate準備音声 | #701のproducer/composition/Runtime所有のまま。System台帳で個々のaudioを再回収しない |

稼働中Runtimeや完成pipelineをborrowedとして注入し、Core停止で共有Runtimeを閉じる構成は受理しない。共有してよいのは上表の明示borrowed依存だけとする。leaseはpublic releaseとowned/borrowedの宣言を持ち、close属性の有無から所有を推測しない。

Core返却前はfactory台帳が失敗時の回収を所有する。pipeline生成後はpipeline.close、その後SpeechRuntimeShutdown.closeを必ず試みる回収操作を登録し、最後にowned leaseを逆順releaseする。先のcleanup失敗でも残りを実行し、元の取消/失敗を成功へ読み替えない。

`_compose_core`が正常返却し、Coreに同じSpeech deliveryが登録されていると確認した時点で、pipeline / Runtime回収責務をCoreへ一度だけ移管する。以後は`CoreRuntimeApplication.stop()` → `CoreSpeechDelivery.close()` → #701 pipeline.close → 既存SpeechRuntimeShutdownが回収する。ゆら本体台帳から同じpipeline/shutdownを再呼出ししない。

移管後もlease releaseはSpeechProductionBindingが保持する。ゆら本体台帳はCore.stopを最初に実行し、その後Speechのowned lease、既存cognition Provider / Attention / Executive等を生成順の逆順で回収する。Core.stop失敗時もleaseと残る資源の回収を続ける。Foundationの既存移管は保持する。

同期compose中の例外でも、既に生成したSpeech資源のハンドルを失わず外側の非同期ゆら本体 cleanupへ返す。部分登録からSystem runやsnapshotを公開しない。非同期providerが正常返却する前の取消・失敗ではproviderが未引渡し資源を回収し、Systemは返却済みleaseだけを台帳へ登録する。

ゆら本体の既存共有stop taskを使い、繰返しstop / cancel下でも一度だけ回収する。borrowed Ownerへの終了伝播、raw例外・秘密値の公開、pending taskを残した成功応答は禁止する。

### 9.6. safe System provenance

既存`ComponentBindings`に任意の`SpeechComponentProvenance | None`を追加し、`SystemCompositionSnapshot.component_bindings`の既存tuple内へ格納する。Speechなしは`None`。別System snapshotや架空のsubsystem登録は作らない。

Speech provenanceはfrozenな構成専用値とし、次を実際の入力・構築bindingから投影する。

- source_id、config_id / config_revision、binding_id / binding_revision / binding_generation。
- semantic policyの公開identity/revision、Character / Verifier / Performanceで実使用したpolicy参照と供給元binding revision。
- Runtime operational policyのidentity/revision、許可output modeとTTS preparation mode。
- TTS / Presentation bindingの公開identity/revisionとavailability。Speech LLMの登録Roleとdeployment bindingの安全な参照。
- 同じSystem run / runtime epoch / character identity/revisionとの対応。

raw token、Owner instance、SDK object、credential、内部/絶対path、raw audio、具体voice/provider設定の生値を含めない。自由文の供給元説明をそのまま証拠へ反射しない。公開参照と実際の入力の対応をfactoryで検証し、identityの自己申告だけをもって成功としない。

snapshotは構築時点の証拠である。#621は返却applicationの既存Core.cognition.speechの公開pipeline/runtime境界から実trace・candidate generation・結果を照合できる。初期snapshotへ後刻のcandidate stateを埋めず、準備済み音声を提示済みFactへ変換しない。

### 9.7. 失敗と互換・受入れ

入力の欠落・型/identity/revision不正・矛盾したavailabilityは既存`INVALID_SYSTEM_CONFIG`、Speech構成/登録不成立は`COGNITION_COMPOSITION_FAILED`、構築中currentness喪失・資源回収不成立は`INITIALIZATION_FAILED`へ分類する。Systemの既存安全な例外を使用し、Domain/TTS/Presentationの失敗Authorityを追加しない。運転中のtyped unavailable / rejection / cancellationは元Ownerの意味を維持する。

Speechなしのゆら本体構築は従来と同じOwner/Role集合・lifecycleで成立する。別構成CLI / 入力意味解析だけの起動にSpeech設定探索や必須依存を追加しない。Speechあり構築の失敗後に自動的にSpeechなしへfallbackしない。

factoryのfixture非依存、同じbindingとgeneration、snapshot実値一致、所有資源だけのclose、構築段階ごとの逆順cleanup、再停止・取消、stale拒否、#701の準備並行動作、#613のFact還流、#692/#620のSpeechなし構成を検証する。#621のSystem Speech acceptanceやHumanの実音声確認を本構成の成功だけで完了扱いしない。

## 10. 三層設定からのSpeech供給（#705）

主設定とProfileから第9節の入力を作る供給Authorityは[三層の本番設定](configuration_architecture.md)とする。`create_speech_deployment()`は設定を既存Owner DTOへ変換し、同じrunに固定した`SpeechProductionInputs`を供給する。具体Provider/voiceの補完、試験policyへの置換、run中のhot replacementはしない。第9節のfactoryと所有権移管は再実装せず、既存の`build_core(speech=...)`へ渡す。

## 11. Speech Deployment Ports factoryのSystem境界（#709）

Systemは同じゆら本体 runで検証済みのProvider lease factory / binding publication、#720 TTS connection、#711 Presentation registry、#721 Owner connection、`SpeechDeploymentOwnerConnections`をtrusted構成rootからfactoryへ明示注入する。factoryが返す`SpeechProductionPorts`のfieldは次表の既存Ownerだけから供給する。

| ports field | 供給元と所有 |
| --- | --- |
| publication / roles | 同一deploymentの検証済みpublication / descriptors、borrowed |
| llm | factoryが`CoreProviderLeaseFactory`から取得するSpeech専用lease、ports releaseまでowned |
| semantic / character / verifier live | `SpeechDeploymentOwnerConnections`の同一ゆら本体既存source、borrowed |
| discard | #720 production leaseが返すresources、TTS lease closeと同じOwner |
| presentation | #711 `PresentationWorkerLease`のSupervisor、ports releaseまでowned |
| readers / notification | #721同一Owner connectionと`SpeechDeploymentOwnerConnections`のresolver / reader factoryから構成、borrowed instancesから構成 |
| release | factoryが正常返却時に移管したowned leaseの逆順cleanup |

`SpeechProductionPorts`に独立したoutput fieldはない。outputはreaders factoryが返す`CoreSpeechContextReaders.output`であり、#721 provenanceを#720 synthesisへ接続する。factoryはartifactを所有しない。factoryはpublication、roles、binding/generationを再照合し、partial acquisition、取消、construction validation failureでは返却済みowned leaseを逆順にsettleする。ports.releaseはidempotentに同じcleanupへ合流し、先行cleanup failureでも残るreleaseを続行する。返却後のpipeline/Runtime shutdownとartifact discardは既存#702/#701のOwnerへ残す。
