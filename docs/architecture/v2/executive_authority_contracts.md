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

`ExecutiveIntent` はspeech/body/activity/attentionの高レベル要求だけを持つ。payloadは汎用JSONではなく、`SpeechIntentPayload` / `BodyIntentPayload` / `ActivityIntentPayload` / `AttentionIntentPayload` の個別immutable DTOとする。semantic/motion goal、target、constraintはnon-empty string参照、constraint群はunique tupleとして検証し、commit時にbounded snapshotへgroundする。最終台詞、step列、TTS値、joint角、frame action、実行済みfactを格納しない。

Goal transitionはcreate / activate / reprioritize / suspend / resume / complete / abandon / supersede、Commitment transitionはcreate / activate / suspend / resume / release / fulfill / violateを表す。`GoalTransitionPayload`はoperationに応じてsemantic goal、priority、superseding goalだけを、`CommitmentTransitionPayload`はcreate時のsemantic commitmentだけを許可する。いずれもexpected goal revisionを持ち、対象・spec・payload参照はbounded Goal/Commitment factにgroundする。#366が後続で再検証・適用するintentである。

## 5. Commit Gate

`ExecutiveFreshnessStamp`はFoundationの`RevisionVector`を置き換えず、Executiveが実際に読んだ`source_context_revision / goal_revision / attention_revision / internal_state_revision`を一組にした責務固有の世代契約である。`source_context_revision`が同じままInternal Stateだけ更新された場合も別世代として扱う。

LLM完了後、`ExecutiveLiveStatePort`はcommit直前のcurrent stateをimmutableな`ExecutiveCommitState`として取得する。これはcurrent `ExecutiveFreshnessStamp`、current `CapabilityDescriptor`、current `PreconditionFact`、信頼済みの決定論的policyまたはupstream typed contractがintentごとに導出した`AuthoritativeIntentRequirements`を持つ。開始時にcallerが取得した値をLLM完了後へ持ち越すこと、LLM candidate自身の申告だけを必須条件の正本にすることを禁止する。live state取得は一貫したsnapshotとして行い、実装側は各current ownerのrevision付きreadまたは同等のserialized read境界を使う。

`ExecutiveDecisionAuthority.commit` は次を短い単一lock区間で検証・確定する。

1. request/resultのrole、schema、identity、時系列が一致する。
2. candidateのtrigger、source event、3 revisionがrequest時snapshotと一致する。
3. request時の`ExecutiveFreshnessStamp`とcommit直前に取得したcurrent stampが一致する。
4. evidence、precondition、capability参照がsnapshotにgroundされる。
5. authoritative requirementsがcandidateの申告から欠落しておらず、申告されたrequired capabilityが開始時snapshotに存在し、同じcapability ID・revisionのままcurrent stateでavailableまたは明示許可されたdegradedである。開始時snapshotだけで判定しない。
6. authoritative requirementsがcandidateの申告から欠落しておらず、申告されたrequired preconditionがcurrent stateで判定済みかつ期待値と一致する。開始時snapshotだけで判定しない。
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
