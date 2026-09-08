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

Goal transitionはcreate / activate / reprioritize / suspend / resume / complete / abandon / supersede、Commitment transitionはcreate / activate / suspend / resume / release / fulfill / violateを表す。`GoalTransitionPayload`はoperationに応じてsemantic goal、priority、superseding goalだけを、`CommitmentTransitionPayload`はcreate時のsemantic commitmentだけを許可する。いずれもexpected goal revisionを持ち、対象・spec・payload参照はbounded Goal/Commitment factにgroundする。#366が後続で再検証・適用するintentである。

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

logical role IDは`executive_deliberation`、input schemaは`executive.context.v1`、output schemaは`executive.candidate.v1`とする。Provider固有型はdomainへ入れない。

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

本節と第5節の完全一致検査は設計上の要求であり、実装済みという記録ではない。現行の`AuthoritativeIntentRequirements`には方針・規則の由来がなく、確定処理の包含検査も完全一致検査ではない。これらの型・導出処理・確定検査・単体および隣接試験は、設計採用後の#630実装で対応する。この設計だけで#630を完了せず、#610の実装も開始しない。

### 9.1. 方針・規則・由来

`ExecutiveIntentRequirementsPolicy`を必須要件の導出方針、`ExecutiveIntentRequirementRule`をその方針に属する単一規則の設計上の型名とする。構成時に信頼済みの実行判断所有者へ登録し、候補や外部入力から登録・変更できない。導出は型付き意図、信頼済み上流記録、現在の導出方針を入力とする決定論的処理であり、LLMを呼ばない。

| 対象 | 必須情報 |
| --- | --- |
| 方針 | `policy_id`、`revision`、不変な規則群 |
| 規則 | `rule_id`、`revision`、所属方針の識別子とリビジョン、対象の`intent_kind`、型付き選択条件、導出方式とその型付き出典指定 |
| 上流の出典 | 所有者の識別子、公開契約の型、記録の識別子・リビジョン、対応する意図の種類と型付き内容、取得した不変な内容 |
| 導出結果 | `intent_id`、必須能力群、必須前提条件群、`policy_id / policy_revision / rule_id / rule_revision`、適用した選択条件、利用した全出典 |

規則識別子は方針内で一意とする。同じ識別子・リビジョンでの内容変更とリビジョンの退行を拒否する。規則の追加・削除・変更は必ず方針リビジョンも進める。所属不一致や不正な出典指定のある方針は登録しない。導出結果は既存の`AuthoritativeIntentRequirements`に対応する不変な契約であり、出典を失った単なる能力・条件の組を同等の正本として受け入れない。

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
- **上流要件投影方式**：規則が指定する所有者・公開契約の型・参照項目で上流の型付き要件記録を一意に解決する。参照項目はその意図の型が公開する参照だけとし、`ACTIVITY`では`activity_type`を上流の登録キーにも使える。上流記録が同じ種類・型付き内容の意図に対応することを検査し、そこで確定済みの能力と期待条件を値を変えずに投影する。記録が要件の一部しか所有しない場合は不完全な出典として拒否する。現在の実測値から期待値を生成しない。
- **計画承認範囲投影方式**：第9.5節の確定計画・承認範囲のみを使う。`PLAN_EXECUTION`はこの方式に限定する。

最初の二方式を`SPEECH / BODY / ACTIVITY / ATTENTION`に使用できる。上流契約の型・参照項目がその意図に適合しない規則は登録時に拒否する。参照先が0件・複数件・未登録・取得失敗の場合、明示定数方式へ切り替えない。上流契約が保持する型付き要件以外から操作名・能力・期待条件を推測しない。

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

由来は確定結果にも保持する。同じ規則を読み直したと称する自己申告の由来や、容量方針のリビジョンによる代用を受理しない。失敗時は契機を消費せず、判断・承認を確定しない。

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

### 9.8. 設計採用後に必要な検証

単体・隣接試験では、6種類の意図の型と規則の組合せ、0件・1件・複数件の一致、明示的な空要件の成功と取得失敗の非確定を区別する。要件の省略・追加・操作変更・縮退許可変更・期待値変更・重複・型違いを拒否する。信頼済み出典と同名の候補自己申告を混同しないことも検証する。

計画では範囲不存在・別範囲・内容変更・古いリビジョン・全手順の投影・重複集約と競合拒否、完了評価では実行承認との分離と元文脈の検査を確認する。LLM待機中、上流取得中、取得後から確定までの方針・規則・出典更新で旧判断が確定せず、既存の取消・競合・契機非消費を維持することを検証する。提供先未登録でも不足を捏造しない模擬提供先での検証を含める。

## 計画から活動への公開接続（#334）

計画全体への明示的承認は`plan_execution_approval_contracts.md`の承認対象と型付き意図を使う。#328以外の計画・結合・検証の所有者が承認を代行しない。承認範囲内の手順進行には、各手順のLLM再判断を一律に要求しない。

計画承認の確定時刻はLLM応答完了時刻から独立させる。現在状態取得の待機後に信頼できる時計を読み、確定処理へ明示的に渡す。期限を超えた承認は判断ごと非確定とする。詳細は[計画実行承認契約](plan_execution_approval_contracts.md)第9節に従う。

## 10. 最終世代照合の共通基盤への接続（#632）

第9.6節の世代公開と確定の直列化は、[並行動作設計第20節](concurrency_architecture.md#20-所有者の世代更新と最終確定を直列化する632)の共通参加者・Fenceを使用する。元所有者の更新ロックと同じ境界で取得した正規のトークンを使い、読取値のコピーを実行判断側で再公開して代用しない。方針・規則の世代、計画・進行・活動など利用した全出典と、確定先自身の参加者を取得前に確定する。

Foundationが呼ぶのは既存の実行判断所有者の短い同期確定操作だけである。第7節が禁止する外部コールバック・await・I/Oを確定区間へ追加しない。候補の意味・完全一致・権限・期限・重複・承認生成と判断の同時確定は本所有者の責務を維持する。共通基盤はこれらを代行しない。

参加者不在、世代不一致、取得集合不正、競合中の場合は型付き失敗として返し、旧候補を新世代へ付け替えない。確定後の取消では成功結果と出典証拠を保持する。#632は共通同期契約と必要な機械的参加を所有し、#630は必須要件の意味とその利用を所有する。両Workの実装・採用は設計レビューとは別工程であり、現在の#630はBlockedを維持する。
