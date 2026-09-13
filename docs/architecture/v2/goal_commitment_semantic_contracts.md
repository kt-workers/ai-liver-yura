# Goal / Commitmentの意味内容公開契約

Owner: #366 / Work #663。Executive #328がCREATEで意味内容を選択・確定し、GoalCommitmentStoreがexact内容を保存する。#362のSpeech投影値は本契約で決めない。

## 1. 不変な意味仕様

`GoalCommitmentSemanticSpec`はsemantic_ref、semantic_revision、subject_kind、subject_ref、predicate、value、polarity、degreeを持つ#366所有の中立型とする。循環importを避ける共有型配置は`app/domain/goal_commitment_semantics.py`とし、Speech型をimportしない。

- semantic_revisionはV1では整数1のみ。semantic_refとpredicateは空でないsemantic identifier。predicateは有限phrase辞書ではない。
- subject_kindはSELF / REFERENCE。SELFはsubject_ref=None、REFERENCEは今回のbounded contextで参照可能なIDを必須とする。
- valueはstrict JsonValueをdeep immutable化する。polarityはAFFIRM / NEGATE、degreeはNoneまたはboolを除く有限数[0,1]。
- 許可fieldは上記だけ。raw user text、prompt、free-form rationaleのfieldを持たず、それらから仕様を復元しない。value中の文字列を構造だけで自然言語分類することも行わない。
- 同一semantic_ref / semantic_revisionへの異なる内容登録はGoalとCommitmentを跨いで拒否する。失敗したbatchは全体非適用とする。

## 2. CREATEと保存

GoalTransitionPayload.semantic_goal_spec / CommitmentTransitionPayload.semantic_commitment_specをCREATEだけで必須とする。spec.semantic_refは既存の対応するref fieldと一致する。non-CREATEにspecを渡すことは禁止する。全lifecycle操作はspecをexact保持し、意味内容の上書き操作を追加しない。

Executive candidate出力はexecutive.candidate.v2へ更新し、parser / serializer / role exchange / instructionsを同じgenerationへ揃える。inputのexecutive.context.v2は保持する。CREATEのspec検証とREFERENCE参照のbounded membership検査を既存commit検証に含める。既存Goal選択・必要根拠・revision照合のAuthorityは変えない。

GoalState / CommitmentStateは対応するtyped specを必須で保持する。refはidentityであり、specとの不一致を拒否する。Goalのcreated_from_decision_id / motivation_refs、Commitmentのsource_decision_id / source_event_ids、およびCREATEのreason_refsを由来として保持する。

保存codecもexact specを搬送する。semantic materialのない旧snapshotから内容を捏造する復元は禁止する。保存形式を明示更新し、旧形式はtyped incompatibleとして非破壊的に拒否する。既存保存レコードの書換え・削除・自動移行は行わない。

## 3. 公開と現在性

GoalCommitmentStore.goal_semantic_publication(goal_id) / commitment_semantic_publication(commitment_id)は既存Owner lock内でcurrent State、exact specと既存finalization tokenを公開する。不在はNone。第二のAuthority、元Executive snapshot、LLM response、payloadの解釈を必要としない。

公開値はstate_kind / state_id / state_revision、semantic_ref / semantic_revision / spec、modality、certainty、lifecycle status、source_decision_id、reason_refsを持ち、Goalのcreated_from_decision_id / motivation_refs、Commitmentのsource_event_idsも保持する。modalityはGOAL / COMMITMENT、certaintyはCERTAIN。これは「このStateがこの内容を持つ」というOwner事実であり、内容が外部世界で実現したという主張ではない。

source identityはgoal_id / commitment_id、source revisionはcurrent State.revision。semantic revisionと区別する。取得後のlifecycle更新で古いtokenは失効する。consumerは既存Fenceで検査し、古い公開へ新revisionを付けない。既存Owner単位のgeneration無効化規則を維持する。

## 4. 容量と検証

新D10 fieldやshared generationは追加しない。既存Executive candidate/input JSON上限とGoalContext item上限へspecも含め、超過を切捨てない。

CREATE保存、必須/余剰spec拒否、ref一致、subject構造とmembership、strict JSON / polarity / degree / revision、同identityの内容衝突、atomic batch、全lifecycleの内容保持、元snapshotなしのturn跨ぎ公開、provenance、current state revision、並行更新後のstale、candidate v2 / malformed入力、保存復元を試験する。
