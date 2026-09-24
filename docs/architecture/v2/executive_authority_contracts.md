# Executive Authority 型付き契約

## 1. 目的

この文書は Issue #328 の正本である。Executive Deliberatorを、ゆらが意識的に「何をするか、何をしないか」を選ぶ唯一のGoal・Action Authorityとして実装する境界を定義する。

Executiveは候補を決定へ確定するが、Goal/Commitment Store、Activity Planner、Character、Speech、Body、Game、Memoryの所有権を奪わない。

## 2. Authority境界

Executiveが所有するもの:

- bounded contextからhigh-level outcomeとintentを選ぶこと
- Goal/Commitmentの状態遷移をtyped intentとして要求すること
- evidence、capability、precondition、revisionを検証して候補を確定すること
- 同一triggerの競合候補から高々1件をatomicに確定すること

Executiveが所有しないもの:

- #366が所有するcurrent Goal/Commitment Stateの直接変更
- #361が所有する複雑Activityのstep計画
- #362/#330が所有する最終台詞とCharacter表現
- TTS parameter、Body joint angle、game frame actionの生成
- execution前の実行済みfact、Memory write、Capabilityの捏造

## 3. 入力契約

`ExecutiveContextSnapshot` は次をfreezeしたbounded snapshotである。

- `trigger_id`、`source_event_ids`
- `source_context_revision`、`goal_revision`、`attention_revision`
- 任意の `StructuredInputMeaning`
- `InternalStateSnapshot`。その独立した`revision`もExecutiveの入力世代に含める
- Goal、Commitment、Memory evidence、Activity、Execution、Turn、Attention、Speech、Body、Environmentのtyped `ExecutiveFactRef`
- `CapabilityDescriptor`
- 判定済み `PreconditionFact`

`ExecutiveFactRef` のpayloadはstrict JSON objectとし、kindを必須にする。生入力本文は含めない。意味解釈は`StructuredInputMeaning`を正本とし、Executiveがraw textを再解釈しない。

参照可能なevidenceはsnapshot内のsource event、fact、capability、precondition IDに限定する。候補が未知の参照を返した場合はfail-closedで拒否する。

### 3.1 共有容量方針の世代

Executiveは独自の容量方針を持たず、`BrainOperationalBoundsPolicy.executive`を必須注入する。snapshot、Provider request、commit済みdecisionには同じ`policy_id / policy_revision`を保持する。

snapshotは型付きselection boundaryで構築する。source eventはtrigger lineageを必ず先に全件保持し、残余だけを`occurred_at desc → event_id asc`で選ぶ。Goal/Commitmentは#366の`GoalContextView`、Memoryは#332のranking resultをそのまま受け取り、Executiveは再順位付けしない。Capabilityはtrusted ownerが渡す`CapabilityRequirement`とdescriptorの`capability_type / operations`が構造的に対応するものをavailabilityに関係なく先に保持し、残余だけを`capability_type → capability_id → revision desc`で選ぶ。availabilityと`allow_degraded`による実行可能性はselectionではなくcommit gateが再検証する。Preconditionはtrusted ownerの`ExecutivePreconditionRequirement`が参照するものを先に保持し、未参照factを必須evidenceの代用にしない。

必須source lineage、fact、capability、preconditionが上限内に収まらない場合は`EXECUTIVE_CONTEXT_TOO_LARGE`として拒否し、first-N、slice、silent truncateを行わない。Provider candidateのintent、Goal transition、Commitment transition、それぞれが所有する参照が上限を超える場合も切り詰めず拒否する。fact payload量はcanonical JSON UTF-8 bytesで測り、診断にはraw payloadを含めない。

Provider await後、commit直前のcurrent policy世代がsnapshot世代と異なる場合、結果はstaleとして拒否する。次requestはcurrent policyによるsnapshotを新規構築する。

## 4. 出力契約

`ExecutiveDecisionCandidate` はLLMまたは決定論的policyが生成する未確定候補である。

- `outcome`: respond / act / wait / ignore / continue_activity / defer / refuse / silence
- `priority`: foreground / normal / background
- `interruptibility`: interruptible / soft_cancel_only / non_interruptible
- high-level `ExecutiveIntent`
- `GoalTransitionIntent`
- `CommitmentTransitionIntent`
- evidence refs、required capability、precondition ID、forbidden claim refs
- 候補が読んだ3 revision

`ExecutiveIntent`は発話・身体・活動・注意の高水準要求、確定計画全体への明示的な実行承認、計画の完了評価を持つ。内容は汎用JSONではなく、`SpeechIntentPayload` / `BodyIntentPayload` / `ActivityIntentPayload` / `AttentionIntentPayload` / `PlanExecutionIntentPayload` / `PlanProgressIntentPayload`の個別の不変な型とする。意味目標・動作目標・対象・制約は空でない文字列の参照とし、制約群の重複を拒否する。確定時に上限付きの判断入力の根拠と照合する。最終台詞、計画手順列、音声合成の値、関節角、フレーム単位の操作、実行済みの事実を格納しない。

Goal transitionはcreate / activate / reprioritize / suspend / resume / complete / abandon / supersede、Commitment transitionはcreate / activate / suspend / resume / release / fulfill / violateを表す。`GoalTransitionPayload`はoperationに応じてsemantic goal、priority、superseding goalだけを、`CommitmentTransitionPayload`はcreate時のsemantic commitmentだけを許可する。いずれもexpected goal revisionを持つ。CREATEのstate IDとsemantic refは新規identityであり、既存Factを要求しない。non-CREATEの対象と、既存Stateを指すpayload参照はboundedな同kind Factにgroundする。#366が後続で再検証・適用するintentである。

## 5. Commit Gate

`ExecutiveFreshnessStamp`はFoundationの`RevisionVector`を置き換えず、Executiveが実際に読んだ`source_context_revision / goal_revision / attention_revision / internal_state_revision`を一組にした責務固有の世代契約である。`source_context_revision`が同じままInternal Stateだけ更新された場合も別世代として扱う。

LLM完了後、`ExecutiveLiveStatePort`はcommit直前のcurrent stateをimmutableな`ExecutiveCommitState`として取得する。これはcurrent `ExecutiveFreshnessStamp`、current `CapabilityDescriptor`、current `PreconditionFact`、信頼済みの決定論的policyまたはupstream typed contractがintentごとに導出した`AuthoritativeIntentRequirements`を持つ。開始時にcallerが取得した値をLLM完了後へ持ち越すこと、LLM candidate自身の申告だけを必須条件の正本にすることを禁止する。live state取得は一貫したsnapshotとして行い、実装側は各current ownerのrevision付きreadまたは同等のserialized read境界を使う。

`ExecutiveDecisionAuthority.commit` は次を短い単一lock区間で検証・確定する。

1. request/resultのrole、schema、identity、時系列が一致する。
2. candidateのtrigger、source event、3 revisionがrequest時snapshotと一致する。
3. request時の`ExecutiveFreshnessStamp`とcommit直前に取得したcurrent stampが一致する。
4. evidence、precondition、capability参照がsnapshotにgroundされる。
5. 第9節で導出した必須能力と候補の申告が完全一致し、開始時に存在した同じ能力識別子・リビジョンの提供先が現在も利用可能、または明示的に許可された縮退状態である。開始時の情報だけで判定しない。
6. 第9節で導出した必須前提条件と候補の申告が完全一致し、開始時と同じ識別子・対象・述語の条件が現在も判定済みで期待値と一致する。同一識別子で別条件へ差し替えることも拒否する。要件の由来と方針世代は第9.6節に従い確定まで検査する。
7. outcomeとintentの組合せが整合する。
8. intent IDが一意で、Goal/Commitment transitionがexpected goal revisionを持つ。
9. 同一triggerが未確定である。

成功時だけtriggerを消費し、immutable `CommittedExecutiveDecision` を返す。検証失敗時は状態を変更しない。同一triggerの競合候補は最初の1件だけ成功し、以後をstale/supersededとして拒否できる。

## 6. Foundationへの投影

確定結果はFoundation `ExecutiveDecision`へ投影する。Authorityはowner=`executive`、scope=`conscious_goal_action`で固定し、intent refsとrevision vectorを保持する。

実行可能なhigh-level intentだけをFoundation `SystemCommand`へ投影できる。commit時に一致を確認したpreconditionはsubject、predicate、expectedを失わずcommandへ投影し、実行境界で再検証できるようにする。Goal/Commitment transitionは#366向けtyped intentであり、Storeを直接変更するcommandにはしない。wait / ignore / defer / silenceは実行済みfactを生成しない。

## 7. LLM Roleと並行性

logical role IDは`executive_deliberation`、input schemaは`executive.context.v2`、output schemaは`executive.candidate.v2`とする。Provider固有型はdomainへ入れない。

各requestは独立invokeされ、Executive全体を覆うglobal async lockや単一queueを持たない。background roleが遅延してもforeground requestはinvoke・live state取得・commit可能である。`ExecutiveDeliberator`はLLM開始前のcurrent値を引数として受け取らず、`await`完了後に`ExecutiveLiveStatePort`を呼ぶ。atomic lockは短い同期commitだけを保護し、awaitや外部callbackを含めない。

## 8. Failureと検証

- schema不正、未知参照、capability欠損、precondition不一致、stale revision、競合commitはfail-closed
- provider失敗から意思・実行factを補作しない
- refusal / defer / wait / silenceは正常な意識的選択として表現する
- Unitでoutcome、Goal/Commitment transition、conflict、capability、precondition、Internal Stateを含むstaleを検証する
- AdjacentでInput Meaning/Appraisal/Foundation投影を検証する
- ConcurrencyでLLM実行中の各revision・capability・precondition変更、slow background中のforeground完了、同一trigger競合を検証する
- Live LLM品質はtyped contract完成後のVerificationで扱う


## 9. 意図別の必須要件を導出する正本（#630）

本節は#328の実行判断の意味所有者に属する、後発の独立Work #630の設計である。必須要件の導出元が未定義だった不足を具体化する。#328と#400の完了済み成果は保持する。別の判断権限や、結合側の判断代行を追加しない。

実装は`ExecutiveRequirementsOwner`が公開する不変な`RequirementsGeneration`を既存の`ExecutiveDeliberator`と`ExecutiveDecisionAuthority`へ接続する。`DerivedIntentRequirements`は既存の`AuthoritativeIntentRequirements`と方針・規則・出典を保持し、候補と現在状態の申告を完全一致で照合する。構成側は信頼済みの方針を明示登録する。未登録を空要件で補わない。#610の横断読取接続は別Workに残す。

### 9.1. 方針・規則・由来

`ExecutiveIntentRequirementsPolicy`を必須要件の導出方針、`ExecutiveIntentRequirementRule`をその方針に属する単一規則の型とする。構成時に信頼済みの実行判断所有者へ登録し、候補や外部入力から登録・変更できない。導出は型付き意図、信頼済み上流記録、現在の導出方針を入力とする決定論的処理であり、LLMを呼ばない。

| 対象 | 必須情報 |
| --- | --- |
| 方針 | `policy_id`、`revision`、不変な規則群 |
| 規則 | `rule_id`、`revision`、所属方針の識別子とリビジョン、対象の`intent_kind`、型付き選択条件、導出方式とその型付き出典指定 |
| 上流の出典 | 所有者の識別子、公開契約の型、記録の識別子・リビジョン、対応する意図の種類と型付き内容、取得した不変な内容 |
| 導出結果 | `intent_id`、必須能力群、必須前提条件群、`policy_id / policy_revision / rule_id / rule_revision`、適用した選択条件、利用した全出典 |

規則識別子は方針内で一意とする。一度削除した規則も所有者の存続中は最後の内容とリビジョンを保持し、再登録で変更履歴の検査を迂回できない。保持する規則識別子数は`max_fact_refs`以下とし、超過は`INVALID_PROJECTION`で拒否する。履歴を暗黙に破棄しない。同じ識別子・リビジョンでの内容変更とリビジョンの退行を拒否する。規則の追加・削除・変更は必ず方針リビジョンも進める。所属不一致や不正な出典指定のある方針は登録しない。導出結果は既存の`AuthoritativeIntentRequirements`に対応する不変な契約であり、出典を失った単なる能力・条件の組を同等の正本として受け入れない。

`BrainOperationalBoundsPolicy`は保持数・容量の方針である。必須要件を決める本方針とは別の識別子・リビジョンを持ち、容量方針の由来で必須要件の由来を代用しない。規則・出典・導出結果も既存の判断入力の容量検査に従い、超過時に一部を削って要件を弱めない。

### 9.2. 単一規則の選択

最初に意図の種類と内容の型の組合せを検証し、次表の型付き選択条件で規則を照合する。選択条件は「その種類全体」または表に示す既存の識別子への完全一致だけとし、正規表現・自由文の解釈・優先順位による先勝ちを持たない。対象・制約参照を含む意図内容の正当性は既存の参照検査を通す。

| 意図の種類 | 内容の型 | 規則が指定できる一致対象 |
| --- | --- | --- |
| `SPEECH` | `SpeechIntentPayload` | 種類全体、または`semantic_goal_ref` |
| `BODY` | `BodyIntentPayload` | 種類全体、または`motion_goal_ref` |
| `ACTIVITY` | `ActivityIntentPayload` | 種類全体、または`activity_type` |
| `ATTENTION` | `AttentionIntentPayload` | 種類全体、または`mode` |
| `PLAN_EXECUTION` | `PlanExecutionIntentPayload` | 種類全体。`scope_ref`は選択後に正規の承認範囲へ解決する |
| `PLAN_PROGRESS` | `PlanProgressIntentPayload` | 種類全体。`context_ref`は選択後に正規の完了評価文脈へ解決する |

一致が0件なら規則未登録、複数件なら曖昧な設定として拒否し、ちょうど1件の場合だけ導出する。「種類全体」と個別識別子の規則が同時に一致する場合も拒否する。複数規則の合成や自動的な別規則への切替えは行わない。未知の種類、異なる内容の型、不許可の選択項目は未対応の意図設定として拒否する。

選択入力に候補の`required_capabilities / preconditions`、説明文、最終台詞を使わない。候補の識別子は登録済み規則を参照する入力であり、規則の内容を指定する権限ではない。特定プラグイン・配信・ゲームを選ぶ規則や定型句を本体へ内蔵しない。

### 9.3. 能力・前提条件の導出方式

一つの規則は次のいずれか一つの方式を明示する。暗黙の方式や任意の実行式を許可しない。

- **明示定数方式**：信頼済み規則に保存された`CapabilityRequirement`群と`ExecutivePreconditionRequirement`群をそのまま出力する。各能力の`capability_type / operation / allow_degraded`、各条件の`precondition_id / expected`は規則が所有する。この方式は両方の空の組も明示的に表せる。
- **上流要件投影方式**：規則が指定する所有者・公開契約の型・参照項目で上流の型付き要件記録を一意に解決する。参照項目はその意図の型が公開する参照だけとし、`ACTIVITY`では`activity_type`を上流の登録キーにも使える。ただし#649のbindingを使用するproduction Direct ACTIVITYは第11.1節の`binding_ref`による正規source解決を必須とし、他の参照へのfallbackを行わない。generic上流記録は同じ種類・完全一致する型付き意図内容を検査し、Direct専用sourceは第11.1節のbinding対応fieldと独立したsemantic参照検証を通して、そこで確定済みの能力と期待条件を値を変えずに投影する。記録が要件の一部しか所有しない場合は不完全な出典として拒否する。現在の実測値から期待値を生成しない。
- **計画承認範囲投影方式**：第9.5節の確定計画・承認範囲のみを使う。`PLAN_EXECUTION`はこの方式に限定する。

最初の二方式を`SPEECH / BODY / ACTIVITY / ATTENTION`に使用できる。ただしproduction Direct ACTIVITYは第11.1節の上流要件投影に限定する。上流契約の型・参照項目がその意図に適合しない規則は登録時に拒否する。参照先が0件・複数件・未登録・取得失敗の場合、明示定数方式へ切り替えない。上流契約が保持する型付き要件以外から操作名・能力・期待条件を推測しない。

`PLAN_PROGRESS`には明示定数方式または同じ`context_ref`の完了評価に対応する上流要件投影方式を使える。どちらも第9.5節の文脈検査を必須とする。実行手順の能力を評価の要件へ自動転用しない。

明示定数方式で要件なしと定義した規則、または完全で信頼済みの上流要件記録が要件なしと確定している場合の空の組は正常である。規則識別子・リビジョン・出典を伴う成功結果として返す。方針不在、規則不在、曖昧さ、出典不足、取得失敗、古い世代、導出失敗を空の組へ変換する処理は禁止する。要件が空でも、参照・現在性・期限・重複など既存の確定条件を免除しない。

### 9.4. 候補の申告との完全一致

候補の`ExecutiveIntent.required_capabilities / preconditions`は検査対象であり、要求の正本ではない。導出結果と候補の意図識別子を一対一で対応させ、余分・不足・重複した結果を拒否する。導出元は候補の申告をコピーしない。

能力は`capability_type / operation / allow_degraded`の全項目、前提条件は`precondition_id / expected`の全項目で完全一致を求める。組の並び順は意味を持たず、能力は型と操作、条件は識別子をキーとして比較する。同一キーの重複は候補・規則・上流要件記録で拒否する。型付きJSONの期待値は型と内容を再帰的に比較し、真偽値・数値・文字列・nullを相互変換しない。オブジェクトのキー順は無視し、配列の順序は保持する。

候補による要件の省略と追加をどちらも拒否する。操作の変更、縮退許可の変更、期待値の変更も拒否し、追加の条件が保守的に見える場合でも自動採用しない。完全一致後、既存の#400の境界で能力の現在の提供状態・リビジョンと前提条件の現在の実測値を検査する。導出要件の正しさと現在の充足を別の検査として保持する。

### 9.5. 計画由来の要件と完了評価

`PLAN_EXECUTION`は`scope_ref`が指す正規の`PlanExecutionScope`を、要求時と確定前の両方で解決する。所有者に登録済みの同じ識別子・確定計画・手順・束縛内容・由来リビジョン・期限であることを既存の計画承認検査へ渡す。候補が持ち込んだ同名の範囲や内容の異なる複製を出典にしない。

必須能力は範囲に固定された確定計画の全手順の`required_capabilities`を投影し、前提条件は同じ範囲の全束縛の`preconditions`から識別子と期待値を投影する。各手順と束縛の対応・欠落がないこと、および条件の対象・述語が正規の条件と一致することを検査する。複数手順で同じ能力・条件が現れる場合のみ、全内容が一致した重複をまとめ、由来には全出現箇所を保持する。同じ能力キーで縮退許可が異なる場合や、同じ条件識別子で対象・述語・期待値が異なる場合は、不正な投影として拒否する。どちらかを選択したり、内容を統合したりしない。

計画の`operation_ref / target_ref`は元の手順と束縛の同一性の検査に使い、そこから追加の能力や条件を再推論しない。要求の意味は#361の確定計画が所有する。#630は操作を再選択せず、手順選択・完了条件・再試行・再計画・操作引数を変更しない。操作引数の型付き由来仕様の不足は後続の#361で解消する。この参照境界はその不足を埋める設計ではなく、不足した範囲を仮の空引数で生成する許可でもない。

`PLAN_PROGRESS`は実行承認とは別の完了評価である。`context_ref`から要求時と確定前で一致する正規の`PlanProgressContext`を取得し、要件の出典にもその文脈の識別子・由来リビジョン・不変な内容を含める。規則が要件なしを明示しても、文脈不在・変更や不正な参照は拒否する。`PlanProgressIntentPayload.claims`は既存の完了評価の検査対象であり、要件の正本にしない。#630は完了の意味、実行事実、進捗を判定・更新せず、実行許可も発行しない。

### 9.6. 要求開始から確定までの現在性

LLM開始前に実行判断所有者から導出方針の不変な世代を取得し、判断要求へ識別子・リビジョンと利用可能な規則・上流参照の由来を固定する。候補の意図がまだない段階で規則を推測して選ばない。候補が返った後、固定した世代と型付き意図から所有者が単一規則を選び、正規の上流記録を使って導出する。要求に存在しなかった上流参照を後付けしない。

既存の#400の現在状態再取得で現在の方針・規則・利用した上流記録・計画範囲または完了評価文脈を読み直す。要求開始時、導出時、現在状態取得後、確定時の世代と出典が一致することを検査する。LLM待機中または現在状態の取得中に方針が更新されていた場合、新方針で旧候補を黙って救済せず、その判断を非確定として返す。

取得後から確定までの変更も取りこぼさない。方針・規則と導出用上流記録の世代公開は、既存`ExecutiveDecisionAuthority`の短い同期確定区間と直列化する。非同期取得は区間の外で完了させ、区間内では既に公開された不変な世代と出典を照合し、成功時だけ既存の判断を確定する。外部読取や待機を区間へ持ち込まず、別の判断所有者やLLM全体を囲む排他を作らない。上流所有者が世代更新の直列化を提供できず、この最終照合を保証できない場合は取得境界の不足として拒否する。単に直前に読んだという時刻だけを保証にしない。

`RequirementSourcePublication`には実際の上流所有者から取得した`AuthorityGenerationToken`を必須とする。要件公開の参加者は順位80、既存の判断確定の参加者は順位70で、確定操作に要件所有者の依存を登録する。通常の`commit()`も共通Fenceを通し、正本から再導出して完全一致を確認した結果の`provenance.sources`だけと、方針のtokenを検査する。登録済みでも今回利用しなかった出典は参加させず、その更新・busyで無関係な判断を拒否しない。共通Fenceの16参加者上限をそのまま使い、要求数から上限を拡張しない。必要な正規依存も含むunique参加者が超過した場合は`INVALID_LOCK_CONFIGURATION`で非確定とする。Fence前は不変値の整合だけを検査し、現在性の照合で待機するLock取得を先行させない。busy時は即時拒否する。全参加者を取得した後の短い同期区間で要件を再照合し、既存の判断確定を行う。外部Fenceからの確定でも同じ照合を省略しない。失敗・no-op公開でも古いtokenを失効させる。拒否された公開の論理内容は採用せず、fresh `capture()`では変更前の正常な方針・規則・出典を現在tokenと同じ排他区間で再取得する。旧snapshotや旧candidateのtokenは差し替えて救済しない。公開JSONには所有者実体、Lock、tokenの内部参照を含めない。

由来は確定結果にも保持する。#610の読取接続が供給する`ExecutiveCommitState.evidence_tokens`は、正本要件で実際に使用する現在の能力・実測前提条件の出典である。通常の確定要求へ追加し、最終operationでも宣言済みtokenとの一致を確認する。`CommittedExecutiveDecision.evidence_tokens`へ同じ由来を保持し、公開JSONではtokenの内部参照を除く。同じ規則を読み直したと称する自己申告の由来や、容量方針のリビジョンによる代用を受理しない。失敗時は契機を消費せず、判断・承認を確定しない。

### 9.7. 所有者間の境界と失敗

| 所有者 | この契約との境界 |
| --- | --- |
| #328配下の#630 | 単純な意図の必須要件の意味、単一規則の選択、決定論的導出、由来付き結果を所有する |
| #361 | 計画の操作・対象・必須能力・必須条件・完了条件・再試行・再計画と、後続で具体化する操作引数の由来仕様を所有する |
| #343 | 能力識別子・種類・対応操作・入力形式・権限の提供契約を所有する。既存`PluginOperationDeclaration.input_schema_ref`等を参照し、#630は提供先固有の形式や権限付与を発明しない |
| #329 | 確定した要求を受け、受付、現在の能力への束縛、利用可否、前提条件の実測値、リビジョン・権限・期限・重複を検査し、不変な`ActivityInvocation`の実行と終端・効果の事実を所有する。必要条件の意味や引数を補作しない |
| #610 | #630の公開所有者へ導出を依頼し、現在の方針と選択済み規則・由来、能力記述、`PreconditionFact`、計画承認範囲・完了評価文脈を読む。自ら規則を選択せず、要件や操作・引数・架空の条件を生成しない |

失敗は少なくとも「方針または規則未登録」「複数規則一致」「未対応の意図設定」「上流要件の取得不能」「方針・規則の古い世代」「不正な型付き投影」「計画範囲の不在」「計画範囲の古い世代」「完了評価文脈の不在または古い世代」「候補申告との不一致」を区別できる型付き結果とする。列挙値の識別子は実装工程で確定してよいが、この意味の区別と非確定の動作を維持する。生例外やメッセージの文字列比較を意味の正本にしない。

どの失敗でも空の要件・空の引数・架空の前提条件で続行せず、命令・承認・完了事実を補作しない。#630の設計と実装の採用、および別Work #361の契約具体化が済むまで#610はBlockedを維持する。

### 9.8. 必要な検証

単体・隣接試験では、6種類の意図の型と規則の組合せ、0件・1件・複数件の一致、明示的な空要件の成功と取得失敗の非確定を区別する。要件の省略・追加・操作変更・縮退許可変更・期待値変更・重複・型違いを拒否する。信頼済み出典と同名の候補自己申告を混同しないことも検証する。

計画では範囲不存在・別範囲・内容変更・古いリビジョン・全手順の投影・重複集約と競合拒否、完了評価では実行承認との分離と元文脈の検査を確認する。LLM待機中、上流取得中、取得後から確定までの方針・規則・出典更新で旧判断が確定せず、既存の取消・競合・契機非消費を維持することを検証する。提供先未登録でも不足を捏造しない模擬提供先での検証を含める。

## 計画から活動への公開接続（#334）

計画全体への明示的承認は`plan_execution_approval_contracts.md`の承認対象と型付き意図を使う。#328以外の計画・結合・検証の所有者が承認を代行しない。承認範囲内の手順進行には、各手順のLLM再判断を一律に要求しない。

計画承認の確定時刻はLLM応答完了時刻から独立させる。現在状態取得後、共通Fenceが全参加者を取得しtokenを検査してからUTC時計を読む。その時刻だけを確定処理へ渡し、callerがFence前に取得した時刻を最終確定時刻として使わない。期限を超えた承認は判断ごと非確定とする。詳細は[計画実行承認契約](plan_execution_approval_contracts.md)第9節に従う。

## 10. 最終世代照合の共通基盤への接続（#632）

第9.6節の世代公開と確定の直列化は、[並行動作設計第20節](concurrency_architecture.md#20-所有者の世代更新と最終確定を直列化する632)の共通参加者・Fenceを使用する。元所有者の更新ロックと同じ境界で取得した正規のトークンを使い、読取値のコピーを実行判断側で再公開して代用しない。方針・規則の世代、計画・進行・活動など利用した全出典と、確定先自身の参加者を取得前に確定する。

Foundationが呼ぶのは既存の実行判断所有者の短い同期確定操作だけである。第7節が禁止する外部コールバック・await・I/Oを確定区間へ追加しない。候補の意味・完全一致・権限・期限・重複・承認生成と判断の同時確定は本所有者の責務を維持する。共通基盤はこれらを代行しない。

参加者不在、世代不一致、取得集合不正、競合中の場合は型付き失敗として返し、旧候補を新世代へ付け替えない。確定後の取消では成功結果と出典証拠を保持する。#632は共通同期契約と必要な機械的参加を所有し、#630は必須要件の意味とその利用を所有する。両Workの実装・採用は設計レビューとは別工程であり、現在の#630はBlockedを維持する。

## 11. 活動bindingの正規参照（#649）

Direct ACTIVITYは`ActivityIntentPayload.binding_ref`で、snapshotに提示された`ActivityExecutionBindingPublication`を明示選択する。未登録・省略・種類・対象・正本能力operationの不一致を拒否する。候補の引数自己申告は受け付けない。

正本requirements集合に、binding descriptorが満たす同じactivity_type / operationのprimary requirementが少なくとも1件必要である。network/access等の追加authoritative requirementを許容し、bindingと同一operationを要求しない。追加要件の存在・revision・availabilityは既存Executive検査、実行時の個別解決は#329へ残す。#649は補助能力のproviderを選ばない。Plannerのstep要件の意味は変更しない。

`ExecutiveRequirementsOwner`による完全一致照合を維持し、選択binding・schema・実値Owner・provider非依存のoperation Ownerと、Requirements・利用したprovenance・evidence・確定先の実際のtokenをFenceへ含める。fact参照数とdistinct participant総数は独立した制約である。同じ正規Ownerの複数factは同じtokenを使用できるが、独立Ownerは統合しない。総数16以下は通常検査を経て確定可能、17以上は既存#632の`INVALID_LOCK_CONFIGURATION`で非確定とする。source数だけの固定上限へ読み替えない。

確定判断は検証済みpublicationを保持し、#612が操作を再選択しない。bindingが0件でも活動以外の判断を妨げない。


### 11.1. Direct ACTIVITYの本番要件source（#695）

状態: #695の設計候補。Code・採用は未実施。第9節の要件意味Authorityを#328 / #630に維持し、第11節のexact bindingへsource identityを接続する。#649 / #651 / #653の既存成果は変更しない。Direct ACTIVITYを未対応化したり、空要件で通したりしない。

#### 正規Ownerと公開型

`app/domain/executive/direct_activity_requirements.py`に`DirectActivityRequirementsOwner`を予定する。これは#328 / #630配下の要件内容の正規所有者であり、Goal / Action選択者ではない。1実体は1個のbinding identityに対する完全な要件宣言を所有する。別bindingの宣言を同じmutable集合へ押し込み、全件を同じtokenで失効させない。構成側はtrustedな型付き宣言と、登録済みの同じ`ActivityBindingAuthority`実体を明示注入する。candidate・Plugin manifest・availabilityから宣言を作らない。

Direct専用の不変型`DirectActivityRequirementRecord`を定義する。fieldは`owner_id / contract_id / record_id / revision / binding_ref / binding_revision / activity_type / target_ref / capabilities / preconditions`とする。owner_idは登録済み要件Ownerのidentity、contract_idは`executive.direct-activity-requirements.v1`、binding_refは正規binding_id、binding_revisionは対応するbindingのrevisionである。target_refはbindingと同じnullable参照型、capabilities / preconditionsは既存の型付き不変tupleとする。識別子・revision・重複・容量は既存検証に従う。record_id / revisionと要件値はtrustedな宣言が明示し、binding側の情報も正規publicationへ照合する。ACTIVITY専用型であるため汎用intent_kind / payloadは持たない。

既存`UpstreamRequirementRecord.payload == intent.payload`の完全一致契約は、既存generic UPSTREAM経路で維持する。Direct専用recordへgeneric recordを変換・流用したり、generic側でconstraint_refsを無視したりしない。Directではbindingが所有するfieldのexact照合とExecutive semantic参照の検証を分離する。

binding identityは#649のoperation・target・Capability identity・arguments・argument provenance側のidentityであり、Requirements semantic variantのidentityにしない。同じbindingでconstraint_refsだけが異なる候補を許し、その差だけで別binding_idを要求しない。target_refはsource・candidate・bindingのexact照合対象とするが、同一binding identityの新revisionでtargetを更新できる#649契約を維持する。target変更だけで新identityを強制しない。

constraint_refsはcandidateのsemantic refsとして第4節のbounded context membership・参照妥当性・現在Executive検証に従う。Direct record/source identityや要件導出のselectorには含めず、sourceが生成・変更・削除しない。本Direct sourceの宣言要件はconstraint_refsに依存しない。第9.2節の規則選択にもconstraintによる要件切替は定義されておらず、今回その意味を発明しない。将来その切替が正本上必要になった場合は#328/#630所有のtyped variant/selectorを明示設計する必要があり、#649 binding_idへ符号化して代用してはならない。これは未定義のvariantを今回暗黙対応することを許す契約ではない。

専用recordと正規publicationの対応を保持する薄い不変型`DirectActivityRequirementSource(record, binding_publication)`を追加し、recordはDirectActivityRequirementRecordに限定する。既存`RequirementSourcePublication.value`の許可variantへこの型を追加し、外側の`source_id / revision / tokens`を再利用する。source_idはrecord_id、revisionはrecord.revisionと一致必須。UpstreamRequirementRecordの既存variant、PlanExecutionScope、PlanProgressContextを置換しない。外側publicationは正規Ownerからだけ取得でき、callerが任意DTOとtokenを組み合わせて発行できないproof境界を設ける。

Ownerの予定APIは`publish(record)`、`capture()`、`close()`とする。constructorでowner identity・binding Owner実体・共有boundsを必須にし、publishは次を検証してから記録を採用する。

- recordのowner / contract / Direct専用型 / binding_refと登録先binding identityが一致する。
- 正規bindingをそのOwnerから取得し、recordのbinding_ref / binding_revision / activity_type / target_refがbindingの値と一致する。constraint_refsはrecordに持たず、candidateに合わせた宣言変更を行わない。
- 明示capabilitiesのうち、capability_type == binding.activity_typeかつoperation == binding.operation_refとなるprimaryがexactly 1件。
- capabilitiesの同一type/operation重複、preconditionsの同一ID重複、型・容量不正を拒否する。allow_degradedを含め、全値を宣言から保持する。
- sourceとbindingのidentity/revision・内容を固定する。同revisionでの内容変更やrevision退行を拒否し、binding更新時も要件Ownerによる新revisionの明示publishを必要とする。captureは旧宣言を新bindingへ自動upgradeしない。

このOwnerは要件内容を実際に保管・更新する正規Ownerであり、他Ownerの値コピーでtokenを代用するshadow Ownerではない。bindingの正規tokenも保持する。bindingからCapabilityRequirementを生成する機能は設けない。source宣言の具体的な本番保存・ロードは#691、Systemの起動登録は#692へ残し、#695はtest fixtureに依存しない公開・登録APIを提供する。

#### primary・auxiliary・preconditions

primary 0件・2件以上は拒否する。auxiliaryはprimaryとは別のtype / operationを許し、primary descriptor自身に全auxiliaryの充足を要求しない。具体auxiliary Providerの選択は既存#329に残す。

allow_degradedと必須条件の期待値は要件Ownerのtrusted宣言が所有する。条件なしは明示された空preconditionsとして公開できるが、Direct ACTIVITYのprimary能力は省略できない。現在のPreconditionFact、binding descriptor、availability、candidateの申告から必要条件を生成しない。期待値と実測値の一致検査は既存#610の正規読取と#328のcommit検証へ残す。

#### request開始前のcaptureと規則選択

`ExecutiveRequirementsOwner`へ、binding_idから正規DirectActivityRequirementsOwner実体への不変route集合を構成時に登録する。routeの重複・owner identity衝突は拒否する。実行中のroute差替えは提供せず、新runtimeの構成で変更する。選択規則は第9.2節の種類／activity_typeによる単一規則選択を維持する。source解決はその後に行う別段階であり、rule selectorへbinding文字列解析を加えない。

Direct ACTIVITYのUPSTREAMには、既存`RequirementSourceSpec`とは区別した不変な出典指定`DirectActivityRequirementSourceSpec(route_id, contract_id, reference_field)`を追加する。reference_fieldはbinding_ref、contract_idは上記固定契約に限定する。規則のsourceは既存指定またはこの指定のいずれか一つとし、新指定をACTIVITY以外へ使用しない。同じactivity_typeの複数bindingを扱う単一規則は登録済みroute_idを指定し、binding_refのexact lookupで実Ownerへ解決する。route集合は要件値・tokenのOwnerではない。既存RequirementSourceSpec.owner_idをroute identityへ読み替えず、DirectActivityRequirementRecord.owner_idは実Ownerのidentityと照合する。generic UpstreamRequirementRecordの照合は変更しない。由来にはroute_idと実Owner identityを区別して保持する。未知routeを新規生成しない。規則登録時にroute存在・contract・参照項目を検査する。

開始snapshotに採用するboundedな`activity_bindings`を先に確定する。同じbinding_idの重複は同値でも拒否する。提示する各bindingに対応する要件Ownerからpublicationを取得し、正規bindingの全内容・revision・tokenと完全一致を確認する。欠落・閉鎖・重複・不一致はrequest開始前に拒否し、bindingや要件を削って通さない。candidateが存在する前に専用recordの全field・正規binding・要件をcaptureする。まだ選択されていないcandidateのconstraint_refsを補作しない。

request用`RequirementsGeneration`にcaptured source群を保持する。共有の`publish(policy, sources)`をrequestごとに呼んで更新してはならない。既存のpolicy世代を指す非公開`base_generation`を持つrequest captureを追加し、既存のpolicy / serial / tokenと非Direct出典を固定したままDirect出典を合成する。base_generationはrequest captureを指せず、登録済み共有世代だけを指す。公開JSONへこの内部参照を出さない。

既存の`_check()`や#610のgeneration同一性照合は、この正規base_generationの現在性を検証できるOwner公開APIへ統一する設計とする。request captureが共有generationと別objectであることだけで拒否せず、逆に任意の同内容コピーを受理しない。Owner発行証拠を持つcaptureだけを認める。従来の非Direct source・policyの更新時の拒否契約は維持する。#610はAPIを呼ぶだけで規則を選ばない。

#### candidate後の導出とcurrent検査

Direct ACTIVITYではbinding_ref省略・null・集合外を拒否する。開始集合からbinding_idがexact一致する1件と、そのbinding用sourceを1件だけ解決する。候補返却後に見つかった新bindingやsourceを追加しない。重複・複数一致を先頭選択しない。

導出時に、正規route / 実Owner / contract、record.binding_ref == intent.payload.binding_ref、record.activity_type == intent.payload.activity_type、record.target_ref == intent.payload.target_ref、record.binding_revision == selected binding.revision、bindingの全内容・operationとprimary exactly 1を再検査する。candidateのconstraint_refsは別途、既存Executiveのbounded参照・現在性検証を必須とし、専用recordに存在しないpayloadとの完全一致を課さない。結果は既存`DerivedIntentRequirements`として、元capabilities / preconditionsを一切補完せず返す。第9.4節のcandidate不足・余剰・型違い・allow_degraded変更の完全一致拒否を維持する。

commit前には選択されたbindingとsourceだけを登録済み実Ownerから再取得する。開始時のidentity / revision / 完全な内容 / 正規tokenと一致を要求する。再取得値は比較用であり、旧captureを新値へ置換しない。使用するsourceとbindingの由来を`RequirementProvenance.sources`および既存の確定判断の要件由来へ残す。

未選択source Bの更新はBのOwner tokenだけを失効させ、共有Requirements policy generationへ再publishしない。開始時A/Bを提示しcandidateがAを選んだ場合、B更新だけではAの判断を失効させない。candidateがBを選んだ場合は旧Bを拒否する。policyそのものや共有の実上流Ownerが更新された場合は、その正規依存の失効を無関係扱いして無視しない。

#### 同期・Fence

要件source Ownerは既存AuthorityFinalizationParticipantを所有し、要件領域のrank 80と独立instance keyを使用する。#632の実装・上限・順序規則は変更しない。publish時は自Ownerのtarget tokenとbindingが保持する全正規Owner tokenで既存Fenceを通し、短い同期区間で明示recordとbindingの組を確定する。capture時は自Ownerとbinding依存の既存read-setを順序どおり取得し、内容とtokenを同時に読む。外部I/O・awaitをLock内へ入れない。

最終Executive Fenceには、既存commit target（rank 70）とRequirements policy token（rank 80）、選択source Ownerのtoken、選択binding Ownerとそのoperation/schema/argumentの正規token、実際に使用する能力・実測前提条件などの既存依存を含める。candidateが未選択のsource tokenを追加しない。実Ownerをdeduplicateしたdistinct participants <= 16を維持し、超過・busy・staleは既存typed失敗で非確定にする。shadow participant、copy owner、token省略、global lockを設けない。current読取後の競合はこの最終Fenceで拒否する。

#### boundsと公開provenance

全て注入した同じ`BrainOperationalBoundsPolicy.executive`で検査する。route数と提示binding数はそれぞれmax_fact_refs以下。request generationのrule数＋非Direct source数＋Direct source数は既存のmax_fact_refs枠に収める。要件のcapabilities＋preconditions、candidate payload内の各参照集合はmax_refs_per_intentで制約する。source publication単体の全公開JSON（record・binding公開・安全な世代情報を含む）はmax_fact_payload_json_bytes以下、全requestはmax_context_json_bytes以下とする。既存binding自身の容量制約も維持する。超過を削除・切捨て・別枠への逃避で回避せず、既存容量失敗に閉じる。数値追加や上限拡張は行わない。

公開JSONは、policy ID/revision、rule ID/revision、source_id/revision、実source Owner/contract identity、route集合identity、Direct recordの全fieldと要件（constraint_refsは含めない）、binding_id/revision/activity_type/operation_refを追跡可能にする。binding_publicationの公開serializerを再利用し、実際の開始値を出す。内部Lock・participant object・raw token参照・base_generation・Owner実体を出さない。安全な世代識別値だけを既存方式でserializeする。

#### 失敗と設計受入表

| 条件 | 必須結果 |
| --- | --- |
| 同じactivity_typeのA / B、異なるoperation | 両方を開始集合に保持し、binding_refに対応する1件だけから導出 |
| binding_ref省略・unknown・重複binding | 非確定。型付き不正参照／publication失敗。first matchなし |
| source 0件・複数件・Owner/contract不一致 | SOURCE_UNAVAILABLEまたはINVALID_PROJECTION。空要件で救済しない |
| primary 0件・複数件、Direct recordのbinding対応field不一致 | INVALID_PROJECTION。publish時と導出時に拒否 |
| primary＋異なるauxiliary、明示preconditions | 全件を保持し、候補と完全一致検査 |
| candidateの不足・余剰・期待値変更 | CANDIDATE_MISMATCH。保守的な追加でも拒否 |
| policy変更 | STALE_POLICY。旧候補の救済なし |
| 選択binding/source変更、current読取後の更新 | STALE_SOURCEまたは既存Fence失敗。旧tokenを差し替えない |
| 未選択かつ独立source更新 | 選択sourceがcurrentなら、それだけを理由に拒否しない |
| distinct participants超過／busy | 既存#632の型付き非確定。16上限維持 |

#### Design finding修正の机上確認

| ケース | 設計上の結果 |
| --- | --- |
| A: 同じbinding A（research / search / web）、候補のconstraint_refsがfact-aとfact-b | 同じcaptured sourceを解決する。各参照は既存Executiveで個別検証し、有効ならconstraint差だけで拒否・別binding化しない |
| B: Aはresearch / search、Bはresearch / query_database | binding_refのexact一致でそれぞれ1件だけ解決し、activity_typeによる先勝ちなし |
| C: 同じbindingのrevision更新（target更新を含む） | 旧source・旧candidateはstale。新bindingと明示的な新source revisionをcaptureした新requestが必要。自動upgradeなし |
| D: sourceとcandidate constraintの関係 | sourceはconstraint_refsを保持・生成・変更せず、candidateも要件宣言のAuthorityにならない |
| E: constraintsによる要件切替 | 現行規則にその意味はないため追加しない。必要性が別途確定した場合の設計責務は#328/#630のtyped selectorであり、binding identityへの転嫁は禁止 |

具体型付きbinding参照失敗の識別子はCode工程で既存enumへ対応付けるが、上記の意味を成功へ変換しない。設計検証はこの表の全行を追跡し、Code工程で正常・失敗・競合・由来serializationを実証する。

#649は操作・Capability identity・argumentsを、#343は提供能力・schema・権限・availabilityを、#329は確定要求の検査実行を、#610は読取を、#612は配送を所有する。本節のsource公開・要件意味・導出はそれらへ移管しない。予定実装範囲はexecutiveのsource Owner / requirements / generation / authority検証と、既存readerの機械的capture接続であり、別Ownerの製品意味変更を前提にしない。


## Speech用の参照選択と意味定義catalog（#661）

Speech Semanticsのproduction入力供給は[speech_semantics_contracts.md 第11節](speech_semantics_contracts.md#11-production入力の供給契約661)を主正本とする。

`ExecutiveFactRef`はExecutiveのbounded context/read modelである。payloadはsnapshot transportであって、下流のsemantic Authorityではない。下流Ownerはfact ID / kind / expected revisionと元Ownerのpublic typed valueを解決し、payloadから発話のsubject / predicate / polarity / certainty / degree / truth ruleを推測しない。

#362がversioned immutableな`CommunicativeActDefinition`群を定義し、bounded `CommunicativeGoalCatalogView`としてExecutive contextへ公開する。これはread-only vocabularyであり、今回の発話行為・Goal・Actionを選ぶAuthorityはExecutiveに留まる。Executiveは定義の意味を生成・変更せず、#362は今回のactを選択しない。

Speechの`semantic_goal_ref`は元typed Factまたはcatalog definitionを参照する。exact membershipから`UPSTREAM_FACT / COMMUNICATIVE_ACT_DEFINITION`を識別し、両集合へのID衝突・unknown・catalog外refは拒否する。自由文字列を生成しただけでは参照を採用しない。ID prefixの解析で種類を推測しない。catalogのdefinition revision / policy generationを要求へfreezeし、commit直前のcurrent値と照合する。

Speech参照の解決記録は既存commitで検証して確定結果に束縛する。元Factは元snapshotのID・kind・revision、catalogはdefinition ID・revision・MeaningPolicy generationを保持する。後続がdecision IDと文字列だけから元参照の種類・世代を補作する契約にはしない。catalog更新中の古い選択を新しい定義へ付け替えず非確定とする。current確認から確定までの既存同期・Fence境界を保持する。

Executiveはtarget / evidence / forbidden claim / constraint参照も選択するが、元Fact値、SpeechSemanticFactのfacet、truth rule、self-disclosure、semantic budgetは決定しない。gratitudeの定義は#362、実際に助けられたという事実は元Owner、今回どのactと根拠を使うかはExecutiveという分離を維持する。既存の能力・事前条件・Goal/Action承認の責務をcatalogへ移さない。


### catalog transportの固定配置とD10（#662 Design finding対応）

`ExecutiveContextSnapshot.communicative_goal_catalog`に#362のimmutable `CommunicativeGoalCatalogView | None`を保持する。generic Factへcatalogを格納しない。非提供は明示nullであり、non-Speechと元typed Factを意味目標にするSpeechは許可するが、definition選択には提供を必須とする。

inputのserialized shapeを変更するため`executive.context.v2`を採用する。candidateは#663のCREATE semantic specを加えた`executive.candidate.v2`とする。Speech参照選択のshapeは維持する。v1 inputへfieldを追加する互換運用は禁止する。

`ExecutiveLiveStatePort`がcommit直前に再取得したcurrent公開を`ExecutiveCommitState.communicative_goal_catalog`へ格納する。使用するdefinitionのID / revision / 内容、MeaningPolicy generation、共有bounds generationを要求開始値と照合し、正規同期境界で確定する。

確定先は`CommittedExecutiveDecision.speech_reference_resolutions: tuple[ExecutiveSpeechReferenceResolution, ...]`に固定する。独立publicationを別途発行しない。Speech intentごとの共通fieldと排他的variant、current取得、non-Speech時の扱いはSpeech正本§11.9を正とする。LLM candidateがresolutionを供給することは禁止する。

catalog専用容量は共有policyの`communicative_catalog`（64件 / definition 4096 bytes / view 524288 bytes）、snapshot全体は`executive.max_context_json_bytes`（8388608 bytes）とする。実Fact枠を流用せず、D10正本§15の全体計測も行う。超過はD10第15節で定義する`ExecutiveContextError(EXECUTIVE_CONTEXT_TOO_LARGE)`へ収束させ、definitionを落とさない。


### 全Speech required参照の確定搬送（#662追加finding対応）

確定結果の`speech_reference_resolutions`へsemantic goal / target / evidence / forbidden claim / constraintを統合する。semantic goal専用fieldは設けない。主正本はSpeech §11.9の`ExecutiveSpeechReferenceResolution`であり、`(intent_id, role, selected_ref)`ごとにexactly oneを保持する。欠落・余剰・重複・非Speech記録は非確定とする。

元Ownerの解決根拠は`ExecutiveContextSnapshot.speech_source_bindings`、commit直前の再取得値は`ExecutiveCommitState.speech_source_bindings`に置く。両方とも`tuple[ExecutiveSpeechSourceBinding, ...]`で、元Owner / public contract kind / identity / revisionと、Factの場合のfact ID / kind / revisionを持つ。Factは開始snapshotのExecutiveFactRefと一致を必要とし、専用制約は明示登録されたOwnerのtyped公開と照合する。全source fieldの現在性を正規commit境界で検証する。

設計中のinput v2はcatalogとこのtyped binding集合をserializeする。candidate v2のSpeech意図は参照を選択するだけで、resolutionを生成しない。COMMUNICATIVE_ACT_DEFINITIONはSEMANTIC_GOALだけ、TYPED_CONSTRAINTはCONSTRAINTだけに許可する。catalog / Fact / constraintのID衝突は拒否する。後続へは同じCommittedExecutiveDecisionだけを渡し、元snapshotへの後日アクセスや別publicationを前提にしない。

## Goal / Commitment CREATEの意味内容（#663）

CREATEは[Goal / Commitment意味内容契約](goal_commitment_semantic_contracts.md)のtyped specを必須とし、Executiveが選択・確定して#366へ渡す。candidateはexecutive.candidate.v2、inputはexecutive.context.v2を用いる。non-CREATEはspecを持たず、既存内容を変更しない。


## #663 CREATE identityと搬送互換性

CREATEのgoal_spec_ref / semantic_goal_ref、commitment_spec_ref / semantic_commitment_refは新しく導入するidentityであり、既存GOAL / COMMITMENT Factへのmembershipを要求しない。対応するspec.semantic_refとの一致は必須。新state IDはcurrent同kind Stateと重複できず、Executiveのbounded同kind Factとの照合に加え、#366 Storeでも最終duplicate検査を行う。

CREATEでもreason_refs、REFERENCE subject_ref、Goalのtarget_ref / commitment_refs / precondition_ids / completion_condition_refs、Commitmentのcounterparty_ref / related_goal_refs / due_condition_refs / release_condition_refsは既存typed/bounded規則に従う。non-CREATEのgoal_ref / commitment_refおよびSUPERSEDEのsuperseding_goal_refは既存の同kind State Factを必須とする。

既存BrainOperationalBoundsPolicy.executive.max_fact_payload_json_bytes（16384）を意味上限の新設ではなくExecutiveへのtransport compatibility boundとして適用する。candidate境界でCREATE spec単体のcanonical JSON UTF-8 bytesを検査する。#366 Storeには既存shared boundsを注入し、batchのlocal copy構築後、snapshotの更新前に完全なGoalState.to_dict() / CommitmentState.to_dict()の同byte数を検査する。超過はbatch全体非適用、State revision不変とし、切捨てやcommit後の保存失敗への転嫁を禁止する。復元時にも同じ上限を検査する。合法Stateの保存不可時には既存のin-memory継続契約を維持する。新D10 field / 数値 / generationは追加しない。


### #661：production Speech source captureの採用済みOwner整合

speech_semantics_contracts.md §11.11–11.14を#362投影の正本とする。ExecutiveSpeechSourceBindingはtransportであり、任意DTO注入を元Owner publicationの代わりにしない。開始snapshot/current commitは実GoalCommitmentStore.goal_semantic_publication / commitment_semantic_publication、MemoryStoreAuthority.read_semantic_assertion_publication、ActivityExecutionAuthority.snapshot_publicationから、同時取得したtyped値とOwner tokenでexact bindingを構成する。current commitで再取得・token照合し、元Owner participantを既存最終fenceへ渡す。staleをlatest revisionへ付替えない。

Executiveは参照選択とtyped resolutionの確定を維持し、Goal/Commitment modalityやMemory時間意味のSpeech投影は所有しない。ATTENTIONはExecutive context/selection用途を維持するが、V1 Speech material sourceとして登録しない。external TYPED_CONSTRAINTもV1登録しない。Fact/catalog/constraint ID collision検査と全required refのexactly one解決は維持する。

MeaningPolicy V1の採用値はFACT_GROUNDED / 1 / 1。GRATITUDEのevidence要件はsources=() / minimum_count=0、COMMITMENTは(COMMITMENT,) / 1。これはcatalog vocabularyの供給でありExecutiveのact選択を#362へ移さない。本reconciliationはdesign-only、capture reader等のproduction修正はpendingである。


## Speech sourceの非同期captureと寿命（#677）

起動時に登録するのはOwner/contract routeであり、具体的source IDではない。既存のExecutive bounded contextへ採用したtyped Factだけを非同期captureへ渡し、実Owner publicationから検証したbindingをspeech_source_bindingsへ保持する。現在の参照選択Authority、bounded selection、D10、candidate schema、commitのexact照合は変更しない。開始時とcurrent commit直前のreaderが同じpublic acquisitionをawaitし、確定resolutionには元Owner identity/revision/tokenを固定する。Memory待機を囲む全体lockや同期DB呼出しを加えない。詳細はspeech_semantics_contracts.md §11.15を正とする。
