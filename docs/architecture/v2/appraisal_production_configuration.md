# Appraisalの本番構成（#690）

状態: 設計finding修正候補。ChatGPTのfinding確認待ち。実装・本流採用・Human検証は未実施。
Owner: #327の構成Work #690。利用側: #692 / #611。

## 1. 正本と監査結果

本書をDeep Appraisal実行方針・fresh-start初期化方式・Decay具体規則・構成保存形式の唯一の値の正本とする。[Appraisal契約](appraisal_internal_state_contracts.md)の意味・Reducer Authority、[減衰数値契約](appraisal_decay_numeric_contracts.md)の式・選択・現在性、[LLM数値契約](llm_execution_numeric_contracts.md)の値域・Provider mappingを変更しない。[最小本体構成](minimum_brain_production_configuration.md)§12のAppraisal側留保を具体化する設計であり、Executive / Requirementsは#691、S2登録は#692に残す。

| 監査対象 | 採用済み境界と本Workの対応 |
| --- | --- |
| app/domain/appraisal/deep.py | ROLE_ID=subjective_appraisal、入力yura.subjective-appraisal.request.v1、出力yura.subjective-appraisal.candidate.v1。descriptorは既存生成関数を使う |
| Role activation / failure | OPTIONAL / SKIP_OPTIONAL。LLMはappraisal_candidateだけを生成し、状態commitや判断を行わない |
| DeepAppraisalPolicy | 既存LLMExecutionPolicyを包む型。production値の供給元が未登録だったため本書で確定する |
| InternalStateSnapshot / Reducer | 空facet集合を許す。state revisionとsource context revisionは独立。Reducerだけが以後の状態をcommitする |
| DecayPolicy / DecayFacetRule | 既存の明示規則・exact選択・missing diagnosticを使う。値の供給だけを追加する |
| app/config/minimum_brain.py / gui_admin.py | 専用YAML→厳密loader→不変構成の既存patternを採用する。minimum YAMLに別Roleを必須追加しない |
| CoreCognitionConfiguration | 外部注入境界は既存。#690はAppraisal部分を供給し、Executive / Attentionや配備全体を生成しない |
| Provider mapping | #692 / #360のSystem・deployment構成から外部注入する。#357はgeneric型・検証・Adapterを所有し、Appraisal固有登録は#690が所有する |

V1のbranch・実装は参照・移植しない。testsのhelperを構成Authorityにしない。

## 2. Deep Appraisalの初期実行方針

| field | 初期値 |
| --- | --- |
| policy_id | yura.appraisal.execution |
| policy_revision | 1 |
| model_class | balanced |
| reasoning_effort | medium |
| timeout_seconds | 15.0 |
| max_attempts | 1 |
| max_output_tokens | 1536 |
| temperature_normalized | null |
| retry_policy.initial_backoff_seconds | 0.25 |
| retry_policy.backoff_multiplier | 2.0 |
| retry_policy.max_backoff_seconds | 1.0 |

これは#690で選定する初期運用値であり、既存試験や実測から導出した値とは主張しない。boundedな主観評価候補にはbalanced / mediumを選び、複数のdimensions・delta・由来を表す出力枠1536と有限待機15秒を割り当てる。非必須評価の再試行で古い候補を蓄積させないため総試行は1回とする。retryの型は省略せず有効な値を登録するが、このリビジョンではretry待機は実行されない。temperatureを人格表現の調整つまみとして追加せず、mappingでパラメータ非送信を明示する。

上限は成功保証・性能SLOではない。長すぎる候補、提供先制約、不正mapping、時間切れは既存の型付き失敗へ閉じる。成功fallback・silent clamp・別モデルへの暗黙切替を設けない。descriptorとrequestは同じ不変policy実体を使用する。実行中に新policyへ付け替えない。遅いDeep評価は既存の認知laneだけで待ち、foregroundや別traceのglobal前提にしない。

値は有限性・bool拒否・総attempt定義・retry式・Provider output上限の全既存検査を通す。具体Provider/model・reasoning mappingとそのrevision/sourceは#692 / #360が供給し、#357の既存検証・拒否を利用する。Appraisalの論理policy値を配備都合で暗黙変更しない。

### 2.1. Appraisal固有のProvider Role契約

#690 / #327はlogical Role、production instructions、strict output schema、provider format name、Role config helperと論理実行Policyを所有する。#357 / #567にRole固有設定の補作を委ねない。

| 要素 | 契約 |
| --- | --- |
| role_id | subjective_appraisal |
| input_schema_id | yura.subjective-appraisal.request.v1 |
| output_schema_id | yura.subjective-appraisal.candidate.v1 |
| activation / failure_policy | OPTIONAL / SKIP_OPTIONAL |
| provider_output_format_name | subjective_appraisal_candidate_v1 |
| allowed model classes | FAST / BALANCED / DEEP_REASONING。MULTIMODALの暗黙変換は禁止 |
| 初期要求 | §2のBALANCED / MEDIUM。許可class集合は全classの登録を要求するものではない |

format nameはDomain schema IDと分離し、既存Adapterのsafe-name・Role間非重複検査を通す。schema・instructionsは`app/domain/appraisal/schemas.py`の`appraisal_output_schema()` / `appraisal_instructions()`に配置する設計とする。DomainはProvider非依存のdict / strを返し、OpenAI型をimportしない。

`app/adapters/llm/appraisal.py::appraisal_openai_role_config(model_policies: Mapping[LLMModelClass, OpenAIResponsesModelPolicy]) -> OpenAIResponsesRoleConfig`を予定する。Character Language / Reflectionの「Adapter側helperがDomainのschemaとinstructionsを利用する」依存方向を踏襲する。mapping identity/revision・output上限を失わないよう既存の不変ModelPolicyを明示注入し、helper内で具体モデル名やmapping revisionを新規生成しない。helperは許可classとRole固有identityを検査し、固定したschema・instructions・SKIP_OPTIONALを結び付ける。空mappingは拒否する。

### 2.2. strict output schemaと意味検証

次のJSON Schemaを出力shapeの正本とし、既存Adapterが`strict: true`で送る。全objectの全fieldをrequiredとし、未知fieldを禁止する。nullable参照もfield自体は省略できない。

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["candidate_id", "dimensions", "proposals", "salience", "relevance", "evidence_refs"],
  "properties": {
    "candidate_id": {"type": "string"},
    "dimensions": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["kind", "value", "target_ref"],
        "properties": {
          "kind": {"type": "string", "enum": ["pleasantness", "novelty", "goal_congruence", "controllability", "certainty", "social_meaning"]},
          "value": {"type": "number", "minimum": -1, "maximum": 1},
          "target_ref": {"type": ["string", "null"]}
        }
      }
    },
    "proposals": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["facet_kind", "state_key", "target_ref", "delta", "confidence", "cause_refs"],
        "properties": {
          "facet_kind": {"type": "string", "enum": ["emotion", "desire", "drive", "motivation", "value", "interest", "relationship", "energy", "arousal"]},
          "state_key": {"type": "string"},
          "target_ref": {"type": ["string", "null"]},
          "delta": {"type": "number", "minimum": -1, "maximum": 1},
          "confidence": {"type": "number", "minimum": 0, "maximum": 1},
          "cause_refs": {"type": "array", "items": {"type": "string"}}
        }
      }
    },
    "salience": {"type": "number", "minimum": 0, "maximum": 1},
    "relevance": {"type": "number", "minimum": 0, "maximum": 1},
    "evidence_refs": {"type": "array", "items": {"type": "string"}}
  }
}
```

これは`deep.py::_candidate_from_json()` / `_dimension()` / `_proposal()`のclosed shapeに対応する。JSON arrayは既存LLM DTOの凍結処理を通してparserが要求するtupleになる。識別子、参照の非空・重複、causeの必須性、delta非ゼロ、Interest / Relationshipのtarget必須、bounded input内参照、候補の現在性等の意味検証は既存Domain型・parser・commit経路に残す。Provider schema成功だけではこれらの成功や状態commitを意味しない。source event・context/state revision・時刻・pathを出力fieldへ追加せず、既存の信頼された呼出文脈から付与する。

production instructionsの内容は次を満たす日本語の固定指示とする。

> 入力されたcurrent event、structured meaning、boundedなInternal Stateとcontextだけを評価してください。出力は指定schemaに一致するAppraisalCandidateの候補だけとし、schema外の説明文を返さないでください。current Internal Stateを直接変更せず、Goal・Attention・Actionを選択しないでください。状態facetの絶対値ではなくtyped delta proposalを返してください。evidence_refs・cause_refs・target_refにはbounded inputに存在する参照だけを使用し、参照や因果を捏造しないでください。変化のないfacetにdelta=0のproposalを作らず、Interest・Relationshipには対象参照を付けてください。これらは状態commitの指示ではありません。

instructionsは#327の候補生成責務だけを表す。Providerからの出力を信頼せず、既存Reducerと現在性検証を維持する。

### 2.3. System・deploymentのmapping供給境界

ユーザーが確定した分担に従い、#692 / #360がconcrete model mapping、reasoning mapping、mapping revision/source、Roleごとのmapping供給API、runtime provider registration、`SystemCompositionSnapshot.provider_bindings`を所有する。#620はこれらを実際に使用したSystem Acceptanceを所有する。#690 YAMLにはconcrete model・Provider reasoning文字列・認証・deployment設定を追加しない。

#692のRole別供給APIは、`subjective_appraisal`について`Mapping[LLMModelClass, OpenAIResponsesModelPolicy]`を返し、同じ構成snapshotにmappingのsourceとidentity/revisionを対応付ける契約とする。#692は自ら所有するdeployment sourceからこのAPIで取得したmappingを、§2.1のhelperへそのまま渡す。APIの配置・名前・保存形式・具体モデル選定は#692の設計責務であり、現時点で既存実装済みとは扱わない。#690ではこの型付き消費境界だけを固定し、別の供給registryを作らない。

ModelPolicyの`model`がmodel classからProvider model stringへの対応、`reasoning_by_effort`が論理enumからProvider reasoning stringへの対応を保持する。`mapping_id / mapping_revision / provider_max_output_tokens / temperature_mapping`も同じ不変実体から使用する。#692はsourceの来歴を保持し、System snapshotへ公開する情報は秘密値・private pathを含めない。DomainへProvider固有値を移さない。

missing mappingやBALANCED / MEDIUM未対応を他class・effortへfallbackしない。genericなModelPolicy値検証とrequest時のmapping解決・output上限検証は既存#357へ委ね、helperへ複製しない。既知Provider output上限が1536未満なら既存Adapterが呼出前にPOLICY_VIOLATIONへ閉じることを受入条件とする。値のclamp・§2のpolicy改変は禁止する。構造不正は構成エラー、requestに未対応の組合せは既存型付き失敗として保持し、成功とは扱わない。

API key未構成では既存`create_openai_port_from_environment()`の`UnavailableLLMRolePort`を使用できる。構成済みでは#692が全登録Roleに一致する明示`role_configs`を渡し、その中のAppraisal設定を本helperで構築する。identity不一致・設定不備・mapping不正をUnavailableへfallbackしない。#690のhelperは環境変数を読まず、runtime登録・秘密管理はSystem / deploymentと既存Adapterに残す。

## 3. fresh-startと継続主体の境界

fresh-startは、配備の正規起動判断が「復元対象となる以前のcurrent stateがない」と明示した新しい実行世代に限る。単なるプロセス再起動、保存先の読取失敗、復元契約未実装をfresh-startの根拠にしない。

| initial_state field | 初期値・取得元 |
| --- | --- |
| mode | fresh_empty |
| state_revision | 0 |
| facets | 空tuple。YAMLにfacet数値を持たせない |
| source_context_revision | 起動側が既存の権威ある現在文脈から取得し、factoryへ明示する非負整数 |
| updated_at | 起動側RuntimeClockのtimezone-aware時刻を明示注入。Domain内でwall clockを読まない |

空は「全ての感情が0」でも「neutralな人物」でもなく、因果的に採用されたdynamic facetがまだない状態を表す。架空のcauseやconfidence、joy=0.2等を付与しない。Characterのstatic traitやMemoryの過去記述をfacetへ複写しない。実際のtyped eventの評価候補が既存Reducerを通って必要なfacetを生成する。既存Reducerの新facet処理を変更せず、欠落facetを観測済みの値として外部へ投影しない。

state revision=0は新Reducerの初期世代であり、source context revision=0という主張ではない。構築時点の文脈が取得不能ならfactoryを呼ばずS2初期化を拒否する。起動受付前に同じ文脈Ownerとの整合を#692が確認し、別の文脈へ初期状態の由来を付け替えない。

### 3.1. startup / resume

startup / wake / resumeの意味評価は既存のtyped lifecycle eventとAppraisal候補生成・Reducer検証を通す。fresh空snapshotを作ること自体をAwakening評価成功・Goal・Attention選択とは扱わない。固定Awakening presetを作らない。

すでに有効なReducerを持つ同一実行世代のresumeではそのOwnerを維持し、factoryを再実行してrevisionを0へ戻さない。以前のプロセスからの復元は、既存Persistenceと#327が承認したrehydration境界だけが扱う。#690のfactoryはpersisted snapshotを引数に取らず、保存形式・復元可否・停止時間の信頼性を再定義しない。承認済み復元境界がない配備のresumeは対応不能として拒否し、freshへfallbackしない。

既存Owner検証済みsnapshotでlifecycle / decayを行う場合も、元のfacet.updated_atと絶対時刻差を使い、旧値を新しいcurrent factへ無条件復元しない。本書は全プロセス再起動対応の完成を主張しない。

## 4. Decayの初期production規則

policy_idは`yura.appraisal.decay`、policy_revisionは`1`。以下が規則集合の全件である。enumは既存の値を使う。state_key=nullは当該kind / scopeの全keyに対する明示規則であり、他kind / scopeへのfallbackではない。

| rule_id | facet_kind | state_key | target_scope | neutral_baseline | half_life_seconds | minimum_elapsed_seconds |
| --- | --- | --- | --- | --- | --- | --- |
| emotion.global | emotion | null | global | 0.0 | 300.0 | 1.0 |
| emotion.targeted | emotion | null | targeted | 0.0 | 300.0 | 1.0 |
| arousal.global | arousal | null | global | 0.0 | 120.0 | 1.0 |
| arousal.targeted | arousal | null | targeted | 0.0 | 120.0 | 1.0 |

Emotionの出来事に対する一時的な変化とArousalの活動準備の変化だけを時間経過で漸近させる初期方針とする。5分と2分のhalf-lifeは本Workの初期校正案であり、人格仕様・実測最適値とはしない。baseline=0は既存の符号付き状態尺度の減衰先であり、現在値を即時resetする指示ではない。1秒未満では微小な更新候補を生成しない。式・exact rule優先・現在性検査は既存数値正本のままとし、timer頻度や起動回数を乗数にしない。

| facet family | リビジョン1の扱いと理由 |
| --- | --- |
| Emotion | 上記global / targeted規則あり |
| Arousal | 上記global / targeted規則あり |
| Desire | 意図的に規則なし。持続的な望みの解消を経過時間だけで代作しない |
| Drive | 意図的に規則なし。欲求充足・身体因果を減衰で補作しない |
| Motivation | 意図的に規則なし。目標や根拠の変化を時間だけで置換しない |
| Value | 意図的に規則なし。価値・道徳的評価を自動忘却しない |
| Interest | 意図的に規則なし。target付きの関心を一律の飽きへ変換しない |
| Relationship | 意図的に規則なし。相手との関係を経過時間だけで書き換えない |
| Energy | 意図的に規則なし。休息や消費を時間減衰で捏造しない |

「規則なし」は型付きDECAY_POLICY_RULE_MISSINGを返し、proposalなしで該当facetを維持する。意図的だからという理由でdiagnosticを成功proposalへ書き換えない。Interest / Relationshipのglobal facetは既存型で不正であり、規則なしとして受理する意味ではない。

half-life / baseline / 最小経過時間はHuman校正可能なversioned dataである。校正時はconfig_revisionとdecay policy_revisionを進め、過去の候補を新世代でcommitしない。新規則や対象familyの追加も同じ変更管理を必要とする。Reducer唯一のAuthority・因果・式・missing時非生成は校正対象ではない。

## 5. 保存形式・loader・factory

既存minimum_brain / gui_adminの専用設定patternと比較し、独立YAMLを採用する。Early BootのINPUT_MEANING-only設定へ必須fieldを増やさない。

| 要素 | 正規配置・識別 |
| --- | --- |
| 本番データ | resources/config/v2/appraisal.yaml |
| loader | app/config/appraisal.py の load_appraisal_config(source: str \| bytes) |
| 不変構成DTO | AppraisalProductionConfig |
| fresh factory / binding | app/composition/appraisal_configuration.py |
| Provider非依存schema / instructions | app/domain/appraisal/schemas.py |
| Appraisal Provider Role登録helper | app/adapters/llm/appraisal.py |
| schema_id | yura.appraisal.production-config.v1 |
| config_id / config_revision | yura.appraisal.production / 1 |

YAMLの最上位fieldは`schema_id, config_id, config_revision, execution, initial_state, decay`のみ。executionは§2の既存LLMExecutionPolicyのfield、retry_policyはその既存3field。initial_stateは`mode, state_revision`のみ。decayは既存DecayPolicyの`policy_id, policy_revision, rules`、各ruleは§4の7fieldとする。上記表が初期データの値の正本であり、他文書へ再掲しない。

DTOはschema/config identityとrevision、DeepAppraisalPolicy、初期化方式と初期revision、DecayPolicyをimmutableに保持する。loaderはYAML重複key・未知field・欠落・未知enum・bool数値・非有限数・不正rule・不正schemaを拒否し、既存Domain型の検査も利用する。enumは既存`.value`、nullは明示null。初期schemaではmode=fresh_empty、state_revision=0だけを受け付け、任意snapshot入力は追加しない。

loaderはテストhelper・環境秘密・外部サービスへアクセスしない。ファイル読込は構成側が行い、IO失敗と形式失敗は秘密値や生YAMLを含めない構成エラーとしてS2 activationへ返す。設定missing / invalidを埋めず、factoryを呼ばない。既存Early Bootや無関係laneの全停止へ拡大しない。

factoryは検証済みDTO、fresh-startの明示指定、source_context_revision、initialized_at、呼出側のruntime_epoch識別子を必須で受ける。省略時の固定値・現在時刻・新epoch自動生成は設けない。新InternalStateSnapshotとInternalStateReducerを一度生成し、Appraisal policy・Decay policy・不変の初期化provenanceと共にbindingとして返す。factory内部で候補commitやLLM呼出しをしない。同じruntimeでの再生成は#692の起動所有権で防ぎ、config変更をreset入口にしない。

#692は返された同じReducerとAppraisal policyをCoreCognitionConfigurationへ注入する。Attention / Executive / Requirementsを#690で構築しない。Decay利用側へ同じpolicyを明示渡し、所有者の既存proposal生成・commitを使用する。#690はtimer、独自task、global lock、Decay schedulerを追加しない。規則の供給を自動周期運転の完成へ読み替えない。

policy全体を取得できない減衰要求では既存DECAY_POLICY_UNAVAILABLEとproposalなしを保持する。構成初期化失敗によるS2受付拒否と、稼働中の個別減衰要求のtyped degradationを区別する。

## 6. 世代と公開provenance

初期bindingは次を不変の読取情報として公開する。Domain状態の別Authorityにはしない。

- config_id / config_revision / schema_id
- execution policy_id / policy_revision
- decay policy_id / policy_revision
- initialization_mode=fresh_empty、initial_state_revision=0
- 初期化時のsource_context_revision / initialized_at / runtime_epoch
- source_config_ref=resources/config/v2/appraisal.yaml（リポジトリ相対参照のみ）

stateの以後のrevision・current valueはReducerのsnapshotから読み、初期provenanceをcurrent状態として再利用しない。config_revision、state revision、source context revision、runtime_epochを等置しない。configの実行中差替えはこのリビジョンでは提供せず、再配備時に検証済み構成を新epochへ結び付ける。値変更はconfig revisionと該当policy revisionの双方を更新し、同identity / revisionで異なるデータを配備しない。

#692 / System evidenceは本公開情報に、実際のminimum config、Ownerから生成したrole descriptor、Character定義リビジョン、exact Git HEADと設定内容の来歴を結び付ける。#690でHEADやCharacter値を固定・推測しない。未commit製品変更をcommit済みHEADの証拠と表示しない。秘密値・private path・内部Lockを公開しない。

## 7. 実装時の受入条件と今回の停止点

後続Code工程では、正規YAML→loader→型付きpolicy→既存descriptor / requestへの同一値伝播、fresh空state、文脈revision独立性、runtime provenance、重複・不正値・missing拒否、全facet familyの規則選択・missing診断、half-life・現在性拒否を試験する。resumeをfreshへfallbackしないこと、既存Appraisal・Decay・通常認知への隣接整合、tests import不在とtest.llm.execution不在も確認する。

Code工程ではさらにRole/schema identity、strict schemaとparserのshape一致、format nameの安全性とRole間非重複、SKIP_OPTIONAL、外部注入mappingのidentity/revision保持、BALANCED / MEDIUM、未対応mappingと上限1536未満の呼出前拒否を確認する。認証未構成時のUnavailable、構成済みかつ正しいRole configでのAdapter構築、構成済みかつ不正configのfail-closedを外部I/Oなしで試験する。#692の供給API・runtime登録・provider_bindingsの実装完成や#620のSystem受入完了とは区別する。

今回の変更は設計文書だけである。resource・loader・factory・testは未作成。設計値はレビュー対象の初期運用案であり、既存実測・人格品質の承認済み値ではない。Human VerificationはNOT_RUN / UNRATED。ChatGPTがこの設計HEADのfinding解消を確認し、実装指示を出してから同じ#690 branchで実装を開始する。追加の独立review cycleは要求しない。
