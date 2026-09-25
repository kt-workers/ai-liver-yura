# 三層の本番設定とSpeech供給

## 1. 責務と適用範囲（#705 / #360）

変更可能な設定はファイルで管理する。通常編集する主設定、詳細をまとめるProfile、内部管理値を分離する。Systemは既存Ownerの公開DTOと登録を構築するだけで、Domainの意味、instructions、schema、規則選択を所有しない。Brain / Body / Memoryもこの境界へ従うが、既存Owner設定の全移行は要求しない。GUI/Adminは許可された安全な投影だけを表示し、設定やsecretの別Authorityにならない。

## 2. ファイルと優先順位

`resources/config/v2/user.yaml`は`schema: yura.user.v1`と`speech`だけを持つ。`speech: null`は明示的な無効化であり、利用可能な発話成功を意味しない。有効時は`profile`と`deployment`の名前だけを指定する。同じ設定rootの`profiles/speech/<name>.yaml`と`profiles/deployment/<name>.yaml`へ解決する。名前はASCII英数字・アンダースコア・ハイフンに限定し、任意path、環境変数展開、任意module importを許可しない。

優先順位は呼出側が明示した一つのrootと主設定だけである。隠れた環境上書き、複数ファイルの部分merge、別profileへのfallbackは行わない。secretは既存Adapterのenvironment / 登録済み接続境界が所有し、設定にはcredential値や任意のsecret参照名を持たせない。提供先は信頼されたdeployment registryへの選択名で指定する。registryは既存Ownerのclient / portを供給し、設定でPython moduleを選べない。

## 3. Profileの意味

Speech profile（`yura.speech-profile.v1`）は四つの論理Roleのexecution、Runtime運用値、output mode、TTS preparation mode、priority、および採用済みPerformance policy参照をまとめる。executionは#357数値契約、Runtime値は#348の型と制約をそのまま検証する。policy ID / revisionは入力させない。Speech意味規則は#362のproduction Owner、Character定義はロード済みのCharacter Owner、Verifierの判断は#363、Performanceの意味投影は#331を再利用する。

deployment profile（`yura.speech-deployment.v1`）は登録された接続先名、LLMのavailabilityとRoleごとの具体model / reasoning mapping、TTSのavailability / provider / voice / locale、Presentationのavailabilityと登録名を明示する。未構成なら対象の具体値をnullにする。利用可能なのに欠落した構成は失敗とし、別model / voiceを選ばない。具体provider/model/voiceは同梱の推測値で補わない。音声出力の選択には利用可能なTTS構成が必要である。

主設定以外も厳密に未知field、重複key、不正な型、循環参照、未対応schemaを拒否する。読み取りはroot内の通常ファイルに限定し、サイズと階層を制限する。失敗は入力値、path、内部例外を含まない型付きcodeで返す。

## 4. revision、generationと反映

schemaは形式のバージョンであり、内容revisionとは異なる。正規化した設定内容のSHA-256から正の整数revisionを導出し、Profile名からsafe identityを導出する。秘密値は設定に受け入れず、digestの入力にも含めない。既存Ownerが定義済みの意味policy identity/revisionは置換しない。

解決済み構成は不変。publicationは一つのSystem runに束縛し、binding identityにrun identityを含める。新しい供給元のbinding generationは1から始まり、そのrun中には更新しない。candidate generation、Ownerのcurrentness token、lifecycleは設定から指定しない。元ファイルの内容が変わったら古い供給元はstaleとして拒否し、自動再解決・hot replacementしない。変更は新run / restartでのみ適用する。同名profileの内容変更はrevisionを変え、旧publicationへ付け替えない。他Ownerのreload契約には影響しない。

## 5. 本番供給と所有境界

`load_user_configuration()` → 不変のProfile解決結果 → `create_speech_deployment()` → `SpeechProductionInputs` → #702 factory → `build_s2_production_core(speech=...)`を正式経路とする。

供給関数は既存`SpeechSemanticPolicyOwner`、Memory binding、ロード済みCharacter identity/revision、run identity、信頼されたports取得境界を明示入力として受ける。これらのOwnerやlive readerを設定値や試験fixtureから捏造しない。取得境界には解決済みの具体deployment、production Role登録、publicationを渡すため、policyとProvider選択を試験fixtureへ置換する必要がない。

Speech Semanticsは#706のhelperと復元portを必ず再利用する。Character / VerifierもOwnerのproduction instructions/schemaを使用し、任意profileからinstructionsを編集できない。外部I/Oはdeployment registryが所有する。取得成功後のlease wrapperは#702に渡し、構築失敗、取消、shutdownのcleanupを二重実装しない。取得境界内で返却前に失敗した資源は取得側が回収する。

Snapshotは#702のsafe provenanceを利用する。provider/model/voiceの具体値、設定root、secret、SDK objectをSnapshotへ追加せず、safe binding identityとrevisionで使用した構成へ対応付ける。同じpublicationと意味OwnerをExecutive evidenceとcognitionで共有する。

## 6. 同梱Profileの初期運用値

`speech/conservative`は外部提供先を含まない運用Profileである。四Role共通のlogical classはbalanced、reasoningはmedium、timeoutは30秒、attemptsは1、outputは4096 token、temperatureは未指定とする。長い待機や無制限再試行を避け、具体modelの能力制約をAdapterでも照合する。retryは初期0.5秒、倍率2、最大2秒で明示し、attempts=1の間は再試行しない。

Runtimeはqueue 4、同時準備2、background 1、regeneration 1、speculative上限1、overflowはreject_new。少数候補でforegroundの独立進行を可能にする初期値であり、全値は#348の非負/正数・background≤total制約に従う。expiryはbackground 10秒、normal 30秒、foreground 30秒、direct_user 60秒。Presentation timeoutは採用済み5/5/5/60秒、worker回収は0.2/1/1秒をそのままProfileに明記する。

初期outputはtext_only、TTSはafter_semantic_acceptance、priorityはforeground。Performanceは既存yura revision 1を参照する。これらはfixture由来ではなく、外部提示前の確認とbounded resource利用を優先したSystem運用初期値である。変更はProfile変更と新runで行い、Owner意味契約や許容範囲を越える値は受け入れない。

## 7. 公開APIの利用と登録契約

起動側は既存Character documentから構築した`SpeechSemanticPolicyOwner`とMemory binding、`S2RunIdentity`を供給する。Character profileの選択元は既存S2設定の`character_definition.resource_ref`であり、本主設定に第二のCharacter identity/revisionを重複入力させない。#702が同じCharacterを照合する。

`SpeechDeploymentRegistry`は接続名から`SpeechDeploymentPortFactory`へ解決する。取得関数は`SpeechDeploymentRequest`の具体model、reasoning、voice、Presentation bindingをそのまま既存Adapter/Ownerへ渡し、同じpublication/rolesで`SpeechProductionPorts`を返す。別設定による取得は契約違反である。返却した借用LLM portには#706のwire復元を一度だけ適用する。secret取得、TTS client、Presentation worker、live readerの具体供給は既存の登録された接続境界に残す。この設定Workが別の提示・合成実装を生成しない。

LLMの初期対応形式は既存OpenAI Responses Role configであり、接続名はこの型を消費できる登録先を選択する。具体endpoint/modelは固定しない。temperatureを使用する場合、deploymentのRole行に`temperature_range: {minimum, maximum}`を明示する。未指定はnullであり、normalized temperatureが要求された場合は拒否する。`max_output_tokens`も具体提供先の制約が判明していれば明示し、超過を切り詰めない。

主設定が有効な配置例では、`speech: {profile: conservative, deployment: <登録先の設定名>}`を使用する。deploymentは`schema / connection / llm / tts / presentation`を持つ。`llm`は`availability / roles`、Role行は`model / reasoning / max_output_tokens / temperature_range`。`tts`は`availability / provider / voice / locale`、`presentation`は`binding / availability`。availabilityはavailableまたはunavailable。未構成LLMのroles、未構成TTSのprovider/voice/localeはnullとする。deploymentの具体値は運用側が提供し、架空の動作する配置例を同梱しない。
