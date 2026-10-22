# 三層の本番設定とSpeech供給

## 1. 責務と適用範囲（#705 / #360）

**現行の起動・配置:** 製品起動は[統合本体](unified_core_architecture.md)の`python -m app`だけを使用する。設定と人物定義の正規ルートは`config/`、構成と外部接続の組立ては`app/bootstrap/`とする。Speechが外部で未構成でもBrain側の意味Ownerを省略してはならない。

変更可能な設定はファイルで管理する。通常編集する主設定、詳細をまとめるProfile、内部管理値を分離する。Systemは既存Ownerの公開DTOと登録を構築するだけで、Domainの意味、instructions、schema、規則選択を所有しない。Brain / Body / Memoryもこの境界へ従うが、既存Owner設定の全移行は要求しない。GUI/Adminは許可された安全な投影だけを表示し、設定やsecretの別Authorityにならない。

### 可変人物定義・関数方針と単一製品構成

[自律人格と統合本体](unified_core_architecture.md)で採用した、人物固有名・性格・言葉遣い・声・身体スタイル等の設定値への分離を全Ownerへ適用する。安定した人格6層はCharacter Definitionを正本とし、現在の内的状態（第7層）をCharacter Profileに保存しない。同じ設定rootで人物とRuntimeのidentity/revisionを明示して照合する。

内部状態の関数種類・パラメータ・半減期・baselineは[時刻別内部状態契約](appraisal_internal_state_contracts.md)と採用済みOwnerのversioned policyが所有し、勝手なデフォルトやファイルに置いた任意Pythonコードでは生成しない。未定義のfacet別規則を補作しない。

現行の設定schema・Profile識別子の人物固有名は、今後の**設定schema版の明示移行対象**である。既存ファイル名とschemaをドキュメントだけで別名へ変更して実装不整合を作らない。新しい中立識別子への移行時はloader・config・Character Definition・provider binding・テストを同一変更で整合させる。

`speech: null`等の外部提示設定の無効化が、統合本体のSpeech意味Owner省略を意味する設計にはしない。製品起動は単一rootの完全構成を要求する。

## 2. ファイルと優先順位

`config/user.yaml`は`schema: yura.user.v1`と`speech`だけを持つ。`speech: null`は明示的な無効化であり、利用可能な発話成功を意味しない。有効時は`profile`と`deployment`の名前だけを指定する。同じ設定rootの`profiles/speech/<name>.yaml`と`profiles/deployment/<name>.yaml`へ解決する。名前はASCII英数字・アンダースコア・ハイフンに限定し、任意path、環境変数展開、任意module importを許可しない。

優先順位は呼出側が明示した一つのrootと主設定だけである。隠れた環境上書き、複数ファイルの部分merge、別profileへのfallbackは行わない。secretは既存Adapterのenvironment / 登録済み接続境界が所有し、設定にはcredential値や任意のsecret参照名を持たせない。提供先は信頼されたdeployment registryへの選択名で指定する。registryは既存Ownerのclient / portを供給し、設定でPython moduleを選べない。

## 3. Profileの意味

Speech profile（`yura.speech-profile.v1`）は四つの論理Roleのexecution、Runtime運用値、output mode、TTS preparation mode、priority、および採用済みPerformance policy参照をまとめる。executionは#357数値契約、Runtime値は#348の型と制約をそのまま検証する。policy ID / revisionは入力させない。Speech意味規則は#362のproduction Owner、Character定義はロード済みのCharacter Owner、Verifierの判断は#363、Performanceの意味投影は#331を再利用する。

deployment profile（`yura.speech-deployment.v1`）は登録された接続先名、LLMのavailabilityとRoleごとの具体model / reasoning mapping、TTSのavailability / provider / voice / locale、Presentationのavailabilityと登録名を明示する。未構成なら対象の具体値をnullにする。利用可能なのに欠落した構成は失敗とし、別model / voiceを選ばない。具体provider/model/voiceは同梱の推測値で補わない。音声出力の選択には利用可能なTTS構成が必要である。

主設定以外も厳密に未知field、重複key、不正な型、循環参照、未対応schemaを拒否する。読み取りはroot内の通常ファイルに限定し、サイズと階層を制限する。失敗は入力値、path、内部例外を含まない型付きcodeで返す。

## 4. revision、generationと反映

schemaは形式のバージョンであり、内容revisionとは異なる。正規化した設定内容のSHA-256から正の整数revisionを導出し、Profile名からsafe identityを導出する。秘密値は設定に受け入れず、digestの入力にも含めない。既存Ownerが定義済みの意味policy identity/revisionは置換しない。

解決済み構成は不変。publicationは一つのSystem runに束縛し、binding identityにrun identityを含める。新しい供給元のbinding generationは1から始まり、そのrun中には更新しない。candidate generation、Ownerのcurrentness token、lifecycleは設定から指定しない。元ファイルの内容が変わったら古い供給元はstaleとして拒否し、自動再解決・hot replacementしない。変更は新run / restartでのみ適用する。同名profileの内容変更はrevisionを変え、旧publicationへ付け替えない。他Ownerのreload契約には影響しない。

## 4.1 統合本体でのSpeech提供先

`python -m app`が読み込む同一構成runの設定として、既存の`load_user_configuration()`による三層Speech設定を固定する。全必須Brain OwnerとSpeechの意味規則は統合本体に属する。外部音声出力が無効または未構成なら、出力提供先の可用性と実提示未実施を正しく表し、Brainの機能を省略しない。

Speech profileが有効なら`CoreRunIdentity`、正規の`SpeechSemanticPolicyOwner`、Memory binding、trusted deployment registryを`create_speech_deployment()`へ明示供給する。登録欠落、stale、binding mismatch、構成不正は型付き構成失敗とし、別Providerや試験fixtureへfallbackしない。

## 5. 本番供給と所有境界

`load_user_configuration()` → 不変のProfile解決結果 → `create_speech_deployment()` → `SpeechProductionInputs` → #702 factory → `build_core(speech=...)`を正式経路とする。

供給関数は既存`SpeechSemanticPolicyOwner`、Memory binding、ロード済みCharacter identity/revision、run identity、信頼されたports取得境界を明示入力として受ける。これらのOwnerやlive readerを設定値や試験fixtureから捏造しない。取得境界には解決済みの具体deployment、production Role登録、publicationを渡すため、policyとProvider選択を試験fixtureへ置換する必要がない。

Speech Semanticsは#706のhelperと復元portを必ず再利用する。Character / VerifierもOwnerのproduction instructions/schemaを使用し、任意profileからinstructionsを編集できない。外部I/Oはdeployment registryが所有する。取得成功後のlease wrapperは#702に渡し、構築失敗、取消、shutdownのcleanupを二重実装しない。取得境界内で返却前に失敗した資源は取得側が回収する。

Snapshotは#702のsafe provenanceを利用する。provider/model/voiceの具体値、設定root、secret、SDK objectをSnapshotへ追加せず、safe binding identityとrevisionで使用した構成へ対応付ける。同じpublicationと意味OwnerをExecutive evidenceとcognitionで共有する。

## 6. 同梱Profileの初期運用値

`speech/conservative`は外部提供先を含まない運用Profileである。四Role共通のlogical classはbalanced、reasoningはmedium、timeoutは30秒、attemptsは1、outputは4096 token、temperatureは未指定とする。長い待機や無制限再試行を避け、具体modelの能力制約をAdapterでも照合する。retryは初期0.5秒、倍率2、最大2秒で明示し、attempts=1の間は再試行しない。

Runtimeはqueue 4、同時準備2、background 1、regeneration 1、speculative上限1、overflowはreject_new。少数候補でforegroundの独立進行を可能にする初期値であり、全値は#348の非負/正数・background≤total制約に従う。expiryはbackground 10秒、normal 30秒、foreground 30秒、direct_user 60秒。Presentation timeoutは採用済み5/5/5/60秒、worker回収は0.2/1/1秒をそのままProfileに明記する。

初期outputはtext_only、TTSはafter_semantic_acceptance、priorityはforeground。Performanceは既存yura revision 1を参照する。これらはfixture由来ではなく、外部提示前の確認とbounded resource利用を優先したSystem運用初期値である。変更はProfile変更と新runで行い、Owner意味契約や許容範囲を越える値は受け入れない。

## 7. 公開APIの利用と登録契約

起動側は既存Character documentから構築した`SpeechSemanticPolicyOwner`とMemory binding、`CoreRunIdentity`を供給する。Character profileの選択元は`config/core.yaml`の`character_definition.resource_ref`であり、本主設定に第二のCharacter identity/revisionを重複入力させない。#702が同じCharacterを照合する。

`SpeechDeploymentRegistry`は接続名から`SpeechDeploymentPortFactory`へ解決する。取得関数は`SpeechDeploymentRequest`の具体model、reasoning、voice、Presentation bindingをそのまま既存Adapter/Ownerへ渡し、同じpublication/rolesで`SpeechProductionPorts`を返す。別設定による取得は契約違反である。返却した借用LLM portには#706のwire復元を一度だけ適用する。secret取得、TTS client、Presentation worker、live readerの具体供給は既存の登録された接続境界に残す。この設定Workが別の提示・合成実装を生成しない。

LLMの初期対応形式は既存OpenAI Responses Role configであり、接続名はこの型を消費できる登録先を選択する。具体endpoint/modelは固定しない。temperatureを使用する場合、deploymentのRole行に`temperature_range: {minimum, maximum}`を明示する。未指定はnullであり、normalized temperatureが要求された場合は拒否する。`max_output_tokens`も具体提供先の制約が判明していれば明示し、超過を切り詰めない。

主設定が有効な配置例では、`speech: {profile: conservative, deployment: <登録先の設定名>}`を使用する。deploymentは`schema / connection / llm / tts / presentation`を持つ。`llm`は`availability / roles`、Role行は`model / reasoning / max_output_tokens / temperature_range`。`tts`は`availability / provider / voice / locale`、`presentation`は`binding / availability`。availabilityはavailableまたはunavailable。未構成LLMのroles、未構成TTSのprovider/voice/localeはnullとする。deploymentの具体値は運用側が提供し、架空の動作する配置例を同梱しない。

## 8. Speech RoleのProvider binding publication（#726）

Speech deploymentは、次の四Roleだけを一組とする不変の`SpeechProviderBindingPublication`を解決済み設定から一度だけ生成する。

- `speech_semantics`
- `character_language`
- `semantic_verification_blind_inventory`
- `semantic_verification_plan_relation`

このpublicationは`deployment_id / deployment_revision`、resolved configurationの`binding_id / binding_revision`、availability mode、四Roleのexactな`LLMRoleDescriptor`、同順序の`OpenAIResponsesRoleConfig`、model mapping publication、Roleごとの`ProviderBindingSnapshot`を保持する。consumerはRole config、model mapping、source reference、snapshotを別々に再構築・推測しない。Role集合、順序、各Role IDの重複は生成時に照合し、差異はfail-closedとする。

`ProviderBindingSnapshot`は既存`CoreProviderLeaseFactory`の入力型であり、#726はその意味を変えない。Speech publicationを構築する構成層だけが、検証済みRole descriptor、Role config、model mappingからsnapshotへ一度だけ変換する。#709等のconsumerがsnapshotを手作業で生成したり、cognition用`ProviderDeploymentConfig`やそのmanifestを流用したりしてはならない。

### 8.1 source referenceとcurrentness

`mapping_ref`と`role_config_ref`はUser Configurationの入力fieldではない。三層設定を解決した内部publicationが、deployment identity / revision、Role ID、mapping又はRole configの公開identity / revisionに決定論的に束縛した非秘密の`ProviderSourceReference`として発行する。source IDは固定の構成Authority識別子、reference identityは上記の公開識別子の組、reference revisionはresolved configurationのbinding revisionを使用する。credential、endpoint、private path、environment値、SDK objectを含めない。

同じ`binding_id / binding_revision`のpublication内容は不変とする。構築中に主設定、Profile、deployment、Role Owner publicationのいずれかが変化した場合、生成済みのsource referenceやsnapshotを新値へ付け替えずstaleとして拒否する。変更は新しいSystem run / restartでのみ反映する。

### 8.2 configured / unconfigured

configuredでは、各RoleのsnapshotがRole ID、deployment identity / revision、mapping reference、Role-config reference、mapping identity / revision、reasoning mapping、input / output schema ID、Provider output format nameを同一publicationへ束縛する。instructions、schema、failure policyは既存Speech Role Owner helperとの完全一致を検証し、#726はコピー又は変更しない。具体model / reasoning mappingはSpeech deploymentだけが供給し、既存#357の検証を再利用する。

unconfiguredでは四Role descriptor集合とdeployment / binding identityを保持し、configsとmapping / Role-config referenceを空として、各snapshotのavailability modeを`unconfigured`にする。架空のreference、mapping、Role configを生成しない。構成不良やcurrentness喪失をunconfiguredへ変換せず、既存の失敗を返す。正当なunconfigured publicationだけが既存`CoreProviderLeaseFactory`を経由して`UnavailableLLMRolePort`契約へ接続できる。

### 8.3 consumer境界と後続実装

`SpeechDeploymentRequest`は`SpeechProviderBindingPublication`を一つだけ保持し、#709はそこからexactなRole descriptors、configs、validated snapshots、availability modeを既存`CoreProviderLeaseFactory`へ渡す。factoryのclient ownership、cleanup、releaseの意味は変更しない。

実装の正規配置は、`app/config/layered.py`がresolved configurationの不変情報を供給し、`app/bootstrap/speech_deployment.py`がpublicationを構築してrequestへ接続する。Providerの共通型とlease契約は`app/bootstrap/core_provider.py`を使用し、具体接続の取得と所有権は`app/bootstrap/speech_deployment_factory.py`で扱う。これらを別の起動構成に分岐させない。

### 8.4 本番Speech Deployment Ports Factory（#709）

`SpeechDeploymentRegistry`へ登録する本番factoryは、`SpeechDeploymentRequest`と明示注入された既存Owner接続だけから`SpeechProductionPorts`を返す。設定値から任意のimport、callable、shell command、Provider、voice又はPresentation workerを解決しない。

| 入力 | 正規供給元 | 検証と結合 | 所有権 |
| --- | --- | --- | --- |
| Provider登録用LLM四Role | requestの`SpeechProviderBindingPublication.factory_inputs()` | Provider schemaのexact roles / configs / bindings / modeを既存`CoreProviderLeaseFactory`へそのまま渡す | factoryが返却前と返却後のlease releaseを所有 |
| Domain用LLM四Role | `SpeechProductionPublication.roles()` | `SpeechProductionPorts.roles`と#702の完全比較にはDomain schemaのdescriptorだけを渡す。Provider登録用descriptorをこの境界へ公開しない | #706の既存#705経路で一度だけwire wrapperを適用する |
| TTS | #720 `TTSProductionConnection`とrequestの`TTSVoiceBinding` | binding identity / revisionと同一connectionを既存`acquire()`で照合する | `TTSProductionLease`をfactoryがreleaseする |
| Presentation | #711 `PresentationWorkerRegistry`とpublicationのPresentation binding | trusted registrationだけをexact identity / revisionで取得する | `PresentationWorkerLease`をfactoryがreleaseする |
| reader / notification | #721 `CoreSpeechProductionOwnerConnection`を返す公開resolverと明示reader factory | lease取得後、同じ統合本体のcognition / reference / Activity / Attention / Normalizer graphだけを受理する | borrowed Ownerをcloseしない |

factoryは未構成LLMを既存typed unavailableとして通すが、configured publicationの不正、Role不一致、stale、binding mismatchをunconfigured又はTEXT_ONLYへ変換しない。TEXT_ONLYとAUDIO_WITH_TEXT、Runtime candidate priorityと`TTSSynthesisPriority`、request identityは各既存Ownerの公開契約に従い、factoryが再符号化又は推測しない。

取得はLLM lease、必要なTTS lease、Presentation leaseを非同期で完了して`SpeechProductionPorts`を返す第一段階と、#702が同一統合本体のcognition / referenceを確定して`CoreSpeechConfiguration.build`内でreader / notificationを同期結合する第二段階に分ける。第二段階のresolverは構成ハンドルごとに一度だけ#721 connectionを解決して固定し、readerと全notificationは固定済みconnectionだけを使う。未結合、二重結合、別cognition / reference / runへの再結合は拒否し、同期結合中に非同期資源を新規取得しない。いずれかの取得・検証・取消に失敗した場合、既取得のowned leaseを逆順に全て一度ずつsettleしてから元の失敗又は取消を伝播する。cleanup failureは全回収試行後に固定の安全な診断として残すが、元の失敗又は取消を置換せず、成功又は通常の構成成功へ変換しない。返却後のpipeline / Runtime所有権移管は#702の`SpeechProductionBinding`に委譲し、borrowed Ownerをfactoryが終了しない。

この境界の結合回帰は、`production_speech_deployment_registry`から登録済みの本番factoryを解決し、`create_speech_deployment()`が返す未取得の`inputs`を一度だけ`build_core(speech=...)`へ渡して確認する。configured / unconfiguredの両方で、#726のProvider用Role/config/binding/modeは`CoreProviderLeaseFactory`だけに渡り、`SpeechProductionPorts.roles`と#702の完全比較には`SpeechProductionPublication.roles()`のDomain用Roleだけが渡る。configuredのProvider wireは#706の既存経路で一度だけDomain portへ復元され、unconfiguredは既存のtyped unavailableを維持する。構築中に外部合成・提示を開始せず、返却済み資源は既存の停止・release経路で回収する。
