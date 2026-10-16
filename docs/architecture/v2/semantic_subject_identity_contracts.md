# 共通Semantic Subject Identity契約

Owner：#671 / #320 Foundation。関連：#355 / #442 / #672 / #673 / #661。

## Authorityと共有型

`SemanticSubjectKind`は`SELF`と`REFERENCE`だけを持つ。
不変の`SemanticSubjectIdentity(kind, subject_ref)`は明示された型付き主体を表す。
subject_refは既存identifier契約と同じく空・空白のみでない文字列とし、正規化・alias解決はしない。

不変の`RuntimeSubjectIdentity`は`self_subject_ref`、`character_id`、
`character_schema_version`、`character_definition_revision`を保持する。
V1では`self_subject_ref == character_id == ロード済みCharacterDefinitionDocument.character_id`。
schemaは正の整数、definition revisionは非負整数とし、boolを整数として受理しない。
双方は同じロード済みdocumentからそのまま搬送する。Character schemaの対応可否は既存loaderが検証する。

共有型は`app/domain/contracts/semantic_subject.py`に置き、Character Domainをimportしない。
compositionがprimitive値を渡す。Foundationはidentity・kind・canonical SELF ref・provenanceだけを所有し、
Speech命題、Memory事実、Goal意味、人格内容、self-disclosure policyは所有しない。

## production供給と寿命

active Characterの選択は既存`MinimumBrainProductionConfig.character_definition_path`とbootstrapのresource loadingだけをAuthorityとする。
`_load_core`が一度ロードしたdocumentを`MinimumCoreApplication.character_definition`へ保持し、
application構築時に同じdocumentから一度だけ`runtime_subject_identity`を生成する。
このfieldは外部から別identityを注入できず、application同様に不変である。
既存Character projectorへ渡すdocumentもこの同じ公開documentとする。新しいprojection経路は追加しない。
通常・永続化bootstrapの双方が同じapplication構築境界を利用する。

第二のself設定、二重load、mutable global registry、singleton、hot-reload managerを追加しない。
新しいapplicationを構成した場合のみ新documentのidentity/provenanceを持つ。
既存default locator `resources/character_definitions/v2/yura.yaml`は保持するが、pathやfilenameはidentityのAuthorityではない。
現製品の結果は`yura`であっても、algorithmへその文字列をhard-codeしない。

## 検証と失敗

`self_subject()`はexact SELFを返す。`reference_subject(explicit_ref)`は明示REFERENCEを構築して検証する。
`validate(subject)`は型付きidentityを要求し、SELFのrefがcurrent Runtime SELFと違えば拒否する。
REFERENCEのrefがcurrent SELF reserved refと一致する場合も拒否する。
REFERENCEのcanonical性は上流の明示的なtyped解決が保証するものであり、本契約は未知の外部refを登録・推測しない。
callerはkindを確定して渡し、raw stringからkindを選ぶAPIは提供しない。

空・不正identifier、schema/revision provenance、invalid kind、SELF不一致、REFERENCE衝突は`ValueError`でfail-closedとする。
値の補完やkindの書換えはしない。missing/invalid Character Definition時は既存loader/bootstrap failureを保持する。
`yura`、`self`、`agent`、`character`等のfallback identityは生成しない。

`display_name`、`name_reading`、`language.first_person`、self_modelやnarrative_identityの自然文、
filename、path、alias、prefix、regex、substringはAuthorityではない。
alias解決は本Workの範囲外で、上流typed解決がなければ利用不能とする。

## 後続Ownerと検証

#672がMemoryのtyped保存・公開、#673がReflectionのtyped供給、#661がGoal/Commitment/MemoryからSpeechへの投影を所有する。
本Workでこれらを前倒ししない。既存Character schema・content・意味も変更しない。

Domainでは型・identifier・provenance・SELF一致・REFERENCE衝突・不変性を検証する。
production bootstrapでは同じロードdocumentのidentityとprojectorのcharacter_idが一致すること、alternate Characterでも同一codeが機能すること、
非Authorityの人物表記を変えてもidentityが変わらないこと、単一loadと既存startup failureの保持を検証する。

#661をtrunkへ最終採用する前に、一時的なstack専用CI例外を除去する義務を保持する。
